from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable
import importlib
import json
import os
import queue
import re
import secrets
import subprocess
import threading
import time
import traceback

from .logging_utils import append_log, timestamp
from .manifest import Operation
from .output_decode import decode_process_bytes
from .paths import ProjectPaths
from .path_cache import cached_output_path, cached_source_path
from .preflight import run_preflight


LogCallback = Callable[[str], None]
ProgressCallback = Callable[[float], None]
CancelCallback = Callable[[], bool]


@dataclass
class JobContext:
    paths: ProjectPaths
    operation: Operation
    log_file: Path
    report_dir: Path
    log_callback: LogCallback | None = None
    progress_callback: ProgressCallback | None = None
    cancel_callback: CancelCallback | None = None
    commands: list[dict[str, Any]] = field(default_factory=list)
    # The share the service told last, and the share of one unit of its work once it said how many there are: the
    # runner of a process then moves the share inside the unit at work by FFmpeg's own progress, not by the clock.
    told_share: float = 0.0
    unit_share: float | None = None
    # The targets of this run and the source each was claimed for: two sources never share one file.
    claimed: dict[str, str] = field(default_factory=dict)

    def log(self, message: str) -> None:
        append_log(self.log_file, message)
        if self.log_callback:
            self.log_callback(message)

    def progress(self, value: float) -> None:
        """The share of the operation done, as the service tells it: the base of the unit that comes next."""
        self.told_share = max(0.0, min(1.0, float(value)))
        if self.progress_callback:
            self.progress_callback(self.told_share)

    def units(self, count: int) -> None:
        """How many units of work the operation has - files, or files times targets; the service tells the share
        after each."""
        self.unit_share = 1.0 / count if count > 0 else None

    def progress_inside(self, ratio: float) -> None:
        """How far the unit at work is, 0..1, moved into the share of the operation; the service's word stays the base."""
        if self.unit_share is not None and self.progress_callback:
            self.progress_callback(min(1.0, self.told_share + self.unit_share * max(0.0, min(1.0, float(ratio)))))

    def progress_guess(self, value: float) -> None:
        """A share guessed by the clock while a process runs: told, but no base for the next unit."""
        if self.progress_callback:
            self.progress_callback(max(0.0, min(1.0, float(value))))

    def cancelled(self) -> bool:
        return bool(self.cancel_callback and self.cancel_callback())


@dataclass
class JobResult:
    ok: bool
    message: str
    data: dict[str, Any]


@dataclass(frozen=True)
class ProcessResult:
    exit_code: int
    lines: tuple[str, ...]


def utf8_subprocess_env(extra: dict[str, str] | None = None) -> dict[str, str]:
    env = os.environ.copy()
    env.setdefault("PYTHONUTF8", "1")
    env["PYTHONIOENCODING"] = "utf-8"
    if extra:
        env.update(extra)
    env["PYTHONUNBUFFERED"] = "1"
    env.pop("NO_COLOR", None)
    env["CLICOLOR"] = "1"
    env["CLICOLOR_FORCE"] = "1"
    env["FORCE_COLOR"] = "1"
    env["AUDION_GUI_TERMINAL"] = "1"
    return env


def unbuffer_python_command(command: list[str]) -> list[str]:
    if not command:
        return command
    executable = Path(str(command[0])).stem.lower()
    if not _is_python_executable(executable):
        return command
    args = [str(item) for item in command]
    if "-u" in args[1:3]:
        return args
    return [args[0], "-u", *args[1:]]


def _is_python_executable(executable_stem: str) -> bool:
    return executable_stem.startswith("python")


def _is_python_command(command: list[str]) -> bool:
    return bool(command and _is_python_executable(Path(str(command[0])).stem.lower()))


SPINNER_FRAME_CHARS = set("-\\|/ \t")


def _is_spinner_only_line(line: str) -> bool:
    stripped = line.strip()
    return bool(stripped) and all(char in SPINNER_FRAME_CHARS for char in line)


def decoded_process_lines(raw_line: bytes | str) -> list[str]:
    text = str(raw_line) if isinstance(raw_line, str) else decode_process_bytes(raw_line)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    lines: list[str] = []
    for part in text.split("\n"):
        line = part.rstrip()
        if not line or _is_spinner_only_line(line):
            continue
        lines.append(line)
    return lines


def hidden_subprocess_startupinfo() -> subprocess.STARTUPINFO | None:
    if os.name != "nt" or not hasattr(subprocess, "STARTUPINFO"):
        return None
    startupinfo = subprocess.STARTUPINFO()
    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startupinfo.wShowWindow = 0
    return startupinfo


def hidden_subprocess_creationflags() -> int:
    if os.name == "nt" and hasattr(subprocess, "CREATE_NO_WINDOW"):
        return int(subprocess.CREATE_NO_WINDOW)
    return 0


def hidden_subprocess_kwargs() -> dict[str, Any]:
    return {
        "startupinfo": hidden_subprocess_startupinfo(),
        "creationflags": hidden_subprocess_creationflags(),
    }


def format_command(command: list[str]) -> str:
    return " ".join(f'"{item}"' if " " in item else item for item in command)


def _format_seconds(seconds: float | None) -> str:
    if seconds is None or seconds < 0:
        return "--:--"
    whole = int(seconds)
    hours = whole // 3600
    minutes = (whole % 3600) // 60
    secs = whole % 60
    if hours:
        return f"{hours:d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def _parse_ffmpeg_out_time(value: str) -> float | None:
    text = str(value or "").strip()
    if not text or text == "N/A":
        return None
    if ":" not in text:
        try:
            raw = float(text)
        except ValueError:
            return None
        return raw / 1_000_000.0 if raw > 10_000 else raw
    parts = text.split(":")
    if len(parts) != 3:
        return None
    try:
        hours = int(parts[0])
        minutes = int(parts[1])
        seconds = float(parts[2])
    except ValueError:
        return None
    return hours * 3600 + minutes * 60 + seconds


# FFmpeg's own line of its work, as it prints it every half second: "frame=  250 fps= 98 q=28.0 size=    1024KiB
# time=00:00:10.00 bitrate= 838.9kbits/s speed=3.93x"; of a sound file "size= ... time= ..."; the last one "Lsize=".
FFMPEG_STATS = re.compile(r"^(?:frame=\s*\d+\s+fps=|L?size=\s*\S+\s+time=)")


def _ffmpeg_progress_command(command: list[str], enabled: bool) -> list[str]:
    """The run reads how far FFmpeg is (-progress pipe:1) and FFmpeg keeps its own line of its work (-stats): the line is
    said beside the bar of the run (the owner, 15.10.2026: the native line of FFmpeg beside the bar)."""
    if not enabled or not command:
        return command
    executable = Path(str(command[0])).name.lower()
    if "ffmpeg" not in executable or any(str(item).lower() == "-progress" for item in command):
        return command
    tail = [item for item in command[1:] if str(item).lower() not in {"-stats", "-nostats"}]
    return [command[0], "-progress", "pipe:1", "-stats", *tail]


def _ffmpeg_progress_bar(label: str, current: float, total: float, speed: str) -> str:
    ratio = max(0.0, min(1.0, current / max(total, 0.001)))
    width = 24
    filled = int(round(ratio * width))
    bar = "#" * filled + "-" * (width - filled)
    percent = int(round(ratio * 100))
    clean_label = label.strip() or "ffmpeg"
    suffix = f" speed={speed}" if speed else ""
    return f"[PROGRESS] {clean_label} [{bar}] {percent:3d}% {_format_seconds(current)}/{_format_seconds(total)}{suffix}"


def _json_safe(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _write_batch_report(
    context: JobContext,
    *,
    started_at: str,
    finished_at: str,
    duration_seconds: float,
    ok: bool,
    message: str,
    preflight: dict[str, Any],
    result_data: dict[str, Any] | None = None,
    error_traceback: str = "",
) -> dict[str, str]:
    report_json = context.report_dir / "batch_report.json"
    report_md = context.report_dir / "batch_report.md"
    source_path = cached_source_path(context.paths.root)
    output_path = cached_output_path(context.paths.root)
    payload: dict[str, Any] = {
        "operation": {
            "id": context.operation.id,
            "title": context.operation.title,
            "title_ru": context.operation.title_ru,
            "service": context.operation.service,
            "kind": context.operation.kind,
        },
        "status": "OK" if ok else "FAIL",
        "message": message,
        "started_at": started_at,
        "finished_at": finished_at,
        "duration_seconds": round(duration_seconds, 3),
        "source": str(source_path),
        "output": str(output_path),
        "log_file": str(context.log_file),
        "report_dir": str(context.report_dir),
        "parameters": _json_safe(context.operation.parameters),
        "preflight": _json_safe(preflight),
        "result": _json_safe(result_data or {}),
        "commands": _json_safe(context.commands),
    }
    if error_traceback:
        payload["traceback"] = error_traceback

    report_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    preflight_checks = preflight.get("checks", []) if isinstance(preflight, dict) else []
    lines = [
        "# Audion Operation Report",
        "",
        f"- Operation: `{context.operation.id}`",
        f"- Status: `{payload['status']}`",
        f"- Message: {message}",
        f"- Started: {started_at}",
        f"- Finished: {finished_at}",
        f"- Duration: {duration_seconds:.1f}s",
        f"- Source: `{source_path}`",
        f"- OUT: `{output_path}`",
        f"- Log: `{context.log_file}`",
        "",
        "## Preflight",
        "",
    ]
    if preflight_checks:
        lines.extend(f"- [{item.get('level', '?')}] {item.get('subject', '')}: {item.get('detail', '')}" for item in preflight_checks if isinstance(item, dict))
    else:
        lines.append("- No preflight checks recorded.")
    lines.extend(["", "## Result", "", "```json", json.dumps(_json_safe(result_data or {}), ensure_ascii=False, indent=2), "```", "", "## Commands", ""])
    if context.commands:
        for index, command in enumerate(context.commands, start=1):
            display = str(command.get("display") or "")
            exit_code = command.get("exit_code")
            duration = command.get("duration_seconds")
            lines.extend(
                [
                    f"### Command {index}",
                    "",
                    f"- Exit: `{exit_code}`",
                    f"- Duration: `{duration}`s",
                    "",
                    "```bat",
                    display,
                    "```",
                    "",
                ]
            )
    else:
        lines.append("- No child process commands were run.")
    if error_traceback:
        lines.extend(["", "## Traceback", "", "```text", error_traceback.rstrip(), "```", ""])
    report_md.write_text("\n".join(lines), encoding="utf-8", newline="\n")
    return {"batch_report_json": str(report_json), "batch_report_md": str(report_md), "report_dir": str(context.report_dir), "log_file": str(context.log_file)}


class OperationCancelled(RuntimeError):
    """STOP was pressed: the child process was ended. Not a failure of the program - the run says one line, no trace."""


class PreflightRefused(RuntimeError):
    """The preflight found the run cannot begin - no file of its kind in the Source, no FFmpeg, a Target that cannot be
    written. Its [PREFLIGHT] lines say why: the run is refused in one line, no trace."""


# Muxers that read a number pattern ("%03d") in the name of their output: a sequence of pictures, of segments.
PATTERN_MUXERS = {"image2", "segment", "stream_segment", "ssegment", "hls", "dash"}
PICTURE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".dpx", ".exr", ".webp", ".tga", ".jxl"}
NUMBER_PATTERN = re.compile(r"%0?\d*d")


def _is_ffmpeg(command: list[str]) -> bool:
    return bool(command) and "ffmpeg" in Path(str(command[0])).name.lower()


def _writes_a_pattern(command: list[str], output: str) -> bool:
    """The output names many files by a number: a muxer of sequences, or pictures, and a "%d" in the name itself. A "%"
    anywhere else - "take%percent.mp4", "50% grey" - is a letter of an ordinary name."""
    if not NUMBER_PATTERN.search(Path(output).name):
        return False
    muxers = {str(command[index + 1]).lower() for index, item in enumerate(command[:-1]) if item == "-f"}
    return bool(muxers & PATTERN_MUXERS) or Path(output).suffix.lower() in PICTURE_EXTENSIONS


def _output_of(command: list[str], working_dir: Path) -> Path | None:
    """The one file an FFmpeg command writes, from the working folder; None - a pipe, a device, a pattern, nothing."""
    if not _is_ffmpeg(command):
        return None
    last = str(command[-1])
    if (not last or last.startswith("-") or last.lower() in {"nul", "-", os.devnull.lower()} or "://" in last
            or last.lower().startswith("pipe:") or _writes_a_pattern(command, last)):
        return None
    return Path(last) if Path(last).is_absolute() else Path(working_dir) / last


def _same_place(first: Path, second: Path) -> bool:
    """One file under two names: the same path, a junction or a symbolic link to it, a hard link."""
    try:
        if first.exists() and second.exists():
            return os.path.samefile(first, second)
    except OSError:
        pass
    return os.path.normcase(os.path.realpath(first)) == os.path.normcase(os.path.realpath(second))


def _output_over_input(command: list[str], working_dir: Path) -> Path | None:
    """The output of an FFmpeg command when it is one of its inputs: FFmpeg itself refuses that, but it would not see it
    through a draft or a link - and the source would be written over."""
    output = _output_of(command, working_dir)
    if output is None:
        return None
    for index, item in enumerate(command[:-1]):
        if item != "-i":
            continue
        given = Path(str(command[index + 1]))
        source = given if given.is_absolute() else Path(working_dir) / given
        if source.is_file() and _same_place(source, output):
            return output
    return None


def _writing_output(command: list[str], working_dir: Path) -> tuple[list[str], Path | None, Path | None]:
    """An FFmpeg command writes its file under a name of its own first - "name.writing-<run>.ext", the extension kept
    for the muxer - and the file takes its own name only whole (as Audion Image Tools writes): STOP, a failure or a
    window that fell leave no half-written file where a finished one is looked for. The draft is a name no file has: a
    file that only looks like a draft is not this run's and is never touched, and two runs into one Target never share
    one. Not for a pattern of many files, a pipe or a device; nor for a file already there that FFmpeg is not told to
    overwrite (-y) - it refuses or asks about that itself, as it always did. The command, the file it is for and its
    name while it is written, both from the working folder; None, None - the command stays as it is."""
    final = _output_of(command, working_dir)
    if final is None or not final.suffix or (final.exists() and "-y" not in command):
        return command, None, None
    while True:
        writing = final.with_name(f"{final.stem}.writing-{os.getpid()}-{secrets.token_hex(3)}{final.suffix}")
        if not writing.exists():
            break
    return [*command[:-1], str(writing)], final, writing


def run_process(
    context: JobContext,
    command: list[str],
    *,
    cwd: Path | None = None,
    extra_env: dict[str, str] | None = None,
    check: bool = True,
    progress_seconds: float = 600.0,
    ffmpeg_progress: bool = False,
    progress_total_seconds: float | None = None,
    progress_label: str = "",
) -> ProcessResult:
    """Run a child process hidden, stream stdout/stderr into the GUI log."""
    if not command:
        raise ValueError("Command is empty.")

    command = unbuffer_python_command(command)
    progress_total = float(progress_total_seconds or 0.0)
    ffmpeg_progress = bool(ffmpeg_progress and progress_total > 0)
    command = _ffmpeg_progress_command(command, ffmpeg_progress)
    working_dir = cwd or context.paths.root
    over = _output_over_input(command, Path(working_dir))
    if over is not None:
        context.log(f"[ERR] {over} is a source of this command: it is not written over.")
        raise RuntimeError(f"Refused: the result would be written over its own source, {over.name}.")
    command, final_output, writing_output = _writing_output(command, Path(working_dir))
    try:
        result = _run_process(context, command, working_dir, extra_env, check, progress_seconds, ffmpeg_progress,
                              progress_total, progress_label)
    except BaseException:
        if writing_output is not None:
            writing_output.unlink(missing_ok=True)
        raise
    if writing_output is not None and final_output is not None:
        if result.exit_code == 0 and writing_output.exists():
            try:
                os.replace(writing_output, final_output)
            except OSError as exc:
                # A folder or a locked file in the place of the result: the write failed, as when FFmpeg could not
                # open the file itself - a failed command, not an error of the program.
                writing_output.unlink(missing_ok=True)
                context.log(f"[ERR] {final_output} could not take its place: {exc}")
                if check:
                    raise RuntimeError(f"Command failed: {final_output.name} could not be written.") from exc
                return ProcessResult(exit_code=1, lines=result.lines)
        else:
            writing_output.unlink(missing_ok=True)
    return result


def _run_process(
    context: JobContext,
    command: list[str],
    working_dir: Path,
    extra_env: dict[str, str] | None,
    check: bool,
    progress_seconds: float,
    ffmpeg_progress: bool,
    progress_total: float,
    progress_label: str,
) -> ProcessResult:
    context.log(f"[CWD] {working_dir}")
    display_command = format_command(command)
    context.log(f"[CMD] {display_command}")
    command_record: dict[str, Any] = {
        "cwd": str(working_dir),
        "command": [str(item) for item in command],
        "display": display_command,
        "started_at": timestamp(),
        "exit_code": None,
        "duration_seconds": None,
        "line_count": 0,
    }
    context.commands.append(command_record)
    process_started = time.monotonic()

    python_text_stream = _is_python_command(command)
    popen_kwargs: dict[str, Any] = {
        "cwd": str(working_dir),
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.PIPE,
        "stderr": subprocess.STDOUT,
        "env": utf8_subprocess_env(extra_env),
        **hidden_subprocess_kwargs(),
    }
    if python_text_stream:
        popen_kwargs.update({"text": True, "encoding": "utf-8", "errors": "replace"})
    else:
        popen_kwargs.update({"text": False})

    process = subprocess.Popen(command, **popen_kwargs)

    lines: list[str] = []
    start = time.monotonic()
    last_progress = start
    ffmpeg_progress_state: dict[str, str] = {}
    last_bar_time = 0.0
    last_bar_ratio = -1.0
    # FFmpeg's own line: the last one it printed, and the last one said. It comes every half second and is said beside
    # the bar, not every time; the final one at the end of the file.
    native = {"last": "", "said": ""}
    # A context of a test or of another caller may know only progress(): the share by the clock, as before.
    inside = getattr(context, "progress_inside", None)
    guess = getattr(context, "progress_guess", context.progress)

    def say_native() -> None:
        if native["last"] and native["last"] != native["said"]:
            lines.append(native["last"])
            context.log(native["last"])
            native["said"] = native["last"]

    def consume_ffmpeg_progress(line: str) -> bool:
        nonlocal last_bar_time, last_bar_ratio
        if not ffmpeg_progress or "=" not in line:
            return False
        key, value = line.split("=", 1)
        key = key.strip()
        if not (key in {"frame", "fps", "bitrate", "total_size", "out_time_us", "out_time_ms", "out_time", "dup_frames", "drop_frames", "speed", "progress"} or key.startswith("stream_")):
            return False
        ffmpeg_progress_state[key] = value.strip()
        if key != "progress":
            return True

        current = (
            _parse_ffmpeg_out_time(ffmpeg_progress_state.get("out_time", ""))
            or _parse_ffmpeg_out_time(ffmpeg_progress_state.get("out_time_us", ""))
            or _parse_ffmpeg_out_time(ffmpeg_progress_state.get("out_time_ms", ""))
            or 0.0
        )
        status = value.strip().lower()
        if status == "end":
            current = max(current, progress_total)
        ratio = max(0.0, min(1.0, current / max(progress_total, 0.001)))
        if inside is not None:
            inside(ratio)
        now = time.monotonic()
        should_log = status == "end" or ratio >= last_bar_ratio + 0.05 or now - last_bar_time >= 5.0
        if should_log:
            bar_line = _ffmpeg_progress_bar(progress_label, current, progress_total, ffmpeg_progress_state.get("speed", ""))
            lines.append(bar_line)
            context.log(bar_line)
            # The bar of the end has FFmpeg's final line under it, said once FFmpeg is done (below).
            if status != "end":
                say_native()
            last_bar_time = now
            last_bar_ratio = ratio
        return True

    assert process.stdout is not None
    # The output is read by a thread of its own, and the run looks at STOP every fifth of a second: a child that says
    # nothing - a long pass of FFmpeg without progress, a quiet helper - is stopped as soon as one that talks.
    feed: queue.Queue = queue.Queue()

    def read_output() -> None:
        try:
            for raw in process.stdout:
                feed.put(raw)
        finally:
            feed.put(None)

    reader = threading.Thread(target=read_output, name="process-output", daemon=True)
    reader.start()
    while True:
        try:
            raw_line = feed.get(timeout=0.2)
        except queue.Empty:
            raw_line = b""
        if context.cancelled():
            context.log("[CANCEL] Terminating child process...")
            _end_process_tree(process)
            raise OperationCancelled("Operation cancelled by user.")
        if raw_line is None:
            break
        if raw_line in (b"", ""):
            output_lines: list[str] = []
        else:
            output_lines = decoded_process_lines(raw_line) if isinstance(raw_line, bytes) else [str(raw_line).rstrip("\r\n")]
        for line in output_lines:
            if not line:
                continue
            # Before the keys of -progress: "frame=  250 fps=..." would read as the key frame.
            if ffmpeg_progress and FFMPEG_STATS.match(line):
                native["last"] = line.strip()
                continue
            if consume_ffmpeg_progress(line):
                continue
            lines.append(line)
            context.log(line)

        now = time.monotonic()
        # The clock guesses only for an operation that did not say its units: with them, the share moves by the
        # service's word between units and by FFmpeg's progress inside one.
        if now - last_progress >= 0.5 and getattr(context, "unit_share", None) is None:
            elapsed = max(0.0, now - start)
            guess(min(0.95, 0.08 + elapsed / max(1.0, float(progress_seconds))))
            last_progress = now

    exit_code = process.wait()
    reader.join(timeout=5)
    # FFmpeg's final line ("Lsize=") comes after its last progress, or it was not said with a bar yet.
    say_native()
    command_record["exit_code"] = exit_code
    command_record["duration_seconds"] = round(time.monotonic() - process_started, 3)
    command_record["line_count"] = len(lines)
    context.log(f"[EXIT] {exit_code}")
    if check and exit_code != 0:
        raise RuntimeError(f"Command failed with exit code {exit_code}.")
    return ProcessResult(exit_code=exit_code, lines=tuple(lines))


def _end_process_tree(process: subprocess.Popen) -> None:
    """Stop a child and what it started itself - yt-dlp runs FFmpeg - and wait for the end, five seconds at most."""
    if process.poll() is None:
        if os.name == "nt":
            subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL, **hidden_subprocess_kwargs())
        else:
            process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def resolve_project_path(context: JobContext, raw_path: str) -> Path:
    path_text = raw_path.strip().strip('"')
    if not path_text:
        raise RuntimeError("Path field is empty.")
    path = Path(os.path.expandvars(path_text)).expanduser()
    if not path.is_absolute():
        path = context.paths.root / path
    return path


def run_cmd_script(
    context: JobContext,
    script: str,
    args: list[str] | None = None,
    *,
    check: bool = True,
    extra_env: dict[str, str] | None = None,
) -> ProcessResult:
    script_path = resolve_project_path(context, script)
    if not script_path.exists():
        raise RuntimeError(f"Script was not found: {script_path}")
    command = ["cmd.exe", "/d", "/c", "call", str(script_path), *(args or [])]
    return run_process(context, command, cwd=context.paths.root, check=check, extra_env=extra_env)


# A Target of more folders than this - a whole drive - is not walked: the time would be the run's, not the cleanup's.
FOLDER_WALK_LIMIT = 20000


def _folders_under(roots: list[Path]) -> set[Path] | None:
    """Every folder under the Target and the workspace, before a run; None when there are too many to walk."""
    found: set[Path] = set()
    for root in roots:
        stack = [Path(root)]
        while stack:
            folder = stack.pop()
            try:
                with os.scandir(folder) as entries:
                    for entry in entries:
                        if entry.is_dir(follow_symlinks=False):
                            found.add(Path(entry.path))
                            stack.append(Path(entry.path))
            except OSError:
                continue
            if len(found) > FOLDER_WALK_LIMIT:
                return None
    return found


def _prune_new_empty_folders(roots: list[Path], before: set[Path] | None) -> None:
    """The folders a run made and left empty go: a command only said (dry run), the stage of a trim whose pieces were
    joined and taken away, a download that wrote nothing. A folder that was there before the run stays, empty or not."""
    if before is None:
        return
    after = _folders_under(roots)
    if after is None:
        return
    for folder in sorted(after - before, key=lambda path: len(path.parts), reverse=True):
        try:
            folder.rmdir()  # only an empty one goes
        except OSError:
            pass


def _load_callable(service: str) -> Callable[[JobContext], Any]:
    module_name, function_name = service.split(":", 1)
    module = importlib.import_module(module_name)
    return getattr(module, function_name)


def _run_stamp() -> str:
    return datetime.now().strftime("%Y-%m-%d %H-%M-%S-%f")[:-3]


def execute_operation(
    paths: ProjectPaths,
    operation: Operation,
    log_callback: LogCallback | None = None,
    progress_callback: ProgressCallback | None = None,
    cancel_callback: CancelCallback | None = None,
) -> JobResult:
    run_stamp = _run_stamp()
    log_file = paths.logs / f"{run_stamp}_{operation.id}.log"
    report_dir = paths.report / f"{run_stamp}_{operation.id}"
    report_dir.mkdir(parents=True, exist_ok=True)
    context = JobContext(paths, operation, log_file, report_dir, log_callback, progress_callback, cancel_callback)
    started_at = timestamp()
    started = time.monotonic()
    preflight: dict[str, Any] = {}

    try:
        context.log(f"Starting operation: {operation.id}")
        if operation.parameters:
            context.log(f"Parameters: {json.dumps(operation.parameters, ensure_ascii=False, sort_keys=True)}")
        context.progress(0.0)
        preflight = run_preflight(context)
        if not bool(preflight.get("ok", True)):
            raise PreflightRefused("Preflight failed: the [PREFLIGHT] lines above say why.")
        folders_before = _folders_under([paths.output, paths.workspace])
        try:
            result = _load_callable(operation.service)(context)
        finally:
            # The ProRes RAW masters a service read (services\raw_develop.py) are gone with its run.
            from system_core.services.raw_develop import release_masters

            release_masters(paths.workspace)
            _prune_new_empty_folders([paths.output, paths.workspace], folders_before)
        # One rule for every service, whatever it leaves out: a run it says was cancelled is a stop, a file that failed
        # is a failure. A service returning `cancelled` and no `ok` read as done with a green status and exit code 0.
        data = dict(result) if isinstance(result, dict) else None
        cancelled = bool(data and data.get("cancelled")) or context.cancelled()
        failed = data.get("failed") if data else 0
        failed = int(failed) if isinstance(failed, (int, float)) and not isinstance(failed, bool) else 0
        if cancelled:
            context.log("[STOPPED] Operation stopped by the user.")
        else:
            context.progress(1.0)
            context.log(f"Finished operation: {operation.id}")

        finished_at = timestamp()
        duration = time.monotonic() - started
        if data is not None:
            if cancelled:
                data["cancelled"] = True
            reported_ok = bool(data.get("ok", True)) and failed == 0 and not cancelled
            if cancelled:
                result_message = "Operation stopped by the user."
            elif failed:
                result_message = f"Operation finished with {failed} failed file(s)."
            elif not reported_ok and isinstance(data.get("refused"), int) and data["refused"]:
                result_message = f"Operation refused {data['refused']} file(s): the journal says why."
            else:
                result_message = "Operation finished." if reported_ok else "Operation reported failure."
            report_files = _write_batch_report(
                context,
                started_at=started_at,
                finished_at=finished_at,
                duration_seconds=duration,
                ok=reported_ok,
                message=result_message,
                preflight=preflight,
                result_data=data,
            )
            context.log(f"Batch report: {report_files['batch_report_md']}")
            data.update(report_files)
            return JobResult(reported_ok, result_message, data)
        message = str(result or "Operation finished.")
        report_files = _write_batch_report(
            context,
            started_at=started_at,
            finished_at=finished_at,
            duration_seconds=duration,
            ok=True,
            message=message,
            preflight=preflight,
            result_data={},
        )
        context.log(f"Batch report: {report_files['batch_report_md']}")
        return JobResult(True, message, report_files)

    except Exception as exc:
        finished_at = timestamp()
        duration = time.monotonic() - started
        if isinstance(exc, OperationCancelled) or context.cancelled():
            # STOP is no failure of the program: one line, the trace stays out of the journal and the report.
            error_text = ""
            message = "Operation stopped by the user."
            context.log(f"[STOPPED] {message}")
        elif isinstance(exc, PreflightRefused):
            error_text = ""
            message = str(exc)
            context.log(f"[REFUSED] {message}")
        else:
            error_text = traceback.format_exc()
            context.log(error_text)
            message = f"{exc.__class__.__name__}: {exc}"
        report_files: dict[str, str] = {}
        try:
            report_files = _write_batch_report(
                context,
                started_at=started_at,
                finished_at=finished_at,
                duration_seconds=duration,
                ok=False,
                message=message,
                preflight=preflight,
                result_data={},
                error_traceback=error_text,
            )
            context.log(f"Batch report: {report_files['batch_report_md']}")
        except Exception as report_exc:
            context.log(f"Could not write batch report: {report_exc.__class__.__name__}: {report_exc}")
        if isinstance(exc, PreflightRefused):
            # A name of its own: "refused" of a trim is the number of pieces it could not cut.
            return JobResult(False, message, {**report_files, "preflight_refused": True})
        return JobResult(False, message, report_files)
