from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable
import importlib
import json
import locale
import os
import subprocess
import time
import traceback
import unicodedata

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

    def log(self, message: str) -> None:
        append_log(self.log_file, message)
        if self.log_callback:
            self.log_callback(message)

    def progress(self, value: float) -> None:
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


def _windows_codepage(name: str) -> str | None:
    if os.name != "nt":
        return None
    try:
        import ctypes

        getter = getattr(ctypes.windll.kernel32, name)
        codepage = int(getter())
    except Exception:
        return None
    return f"cp{codepage}" if codepage > 0 else None


def _looks_utf16_le(data: bytes) -> bool:
    if len(data) < 4:
        return False
    odd = data[1::2]
    return bool(odd) and odd.count(0) / len(odd) >= 0.35


def _looks_utf16_be(data: bytes) -> bool:
    if len(data) < 4:
        return False
    even = data[0::2]
    return bool(even) and even.count(0) / len(even) >= 0.35


def _decode_candidates(data: bytes) -> list[str]:
    candidates: list[str] = []

    def add(encoding: str | None) -> None:
        if not encoding:
            return
        normalized = encoding.lower().replace("_", "-")
        if normalized not in candidates:
            candidates.append(normalized)

    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        add("utf-16")
    elif _looks_utf16_le(data):
        add("utf-16-le")
    elif _looks_utf16_be(data):
        add("utf-16-be")

    add("utf-8")
    add(_windows_codepage("GetOEMCP"))
    add("cp866")
    add(locale.getpreferredencoding(False))
    add("mbcs")
    add(_windows_codepage("GetACP"))
    add("cp1251")
    return candidates


_MOJIBAKE_MARKERS = (
    "\ufffd",
    "����",
    "㤠",
    "䠩",
    "Рћ",
    "Р°",
    "Рµ",
    "Рё",
    "Ð",
    "Ñ",
)

_RARE_CYRILLIC = set("ЃѓЄЅѕІЇЈЉЊЋЌЎЏҐґєіїјљњћќўџ")


def _decode_score(text: str) -> int:
    score = 0
    for marker in _MOJIBAKE_MARKERS:
        score += text.count(marker) * 120
    for char in text:
        codepoint = ord(char)
        if char in "\r\n\t":
            continue
        if char == "\x00":
            score += 200
            continue
        category = unicodedata.category(char)
        if category.startswith("C"):
            score += 80
        if char in _RARE_CYRILLIC:
            score += 12
        if char in {"\xa0", "¤", "©", "®", "�"}:
            score += 20
        if 0x2E80 <= codepoint <= 0x9FFF or 0xAC00 <= codepoint <= 0xD7AF:
            score += 40
    return score


def decode_subprocess_line(data: bytes) -> str:
    """Decode non-Python subprocess output without committing to lossy UTF-8 first."""
    return decode_process_bytes(data)


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


def _ffmpeg_progress_command(command: list[str], enabled: bool) -> list[str]:
    if not enabled or not command:
        return command
    executable = Path(str(command[0])).name.lower()
    if "ffmpeg" not in executable or any(str(item).lower() == "-progress" for item in command):
        return command
    tail = [item for item in command[1:] if str(item).lower() != "-stats"]
    return [command[0], "-progress", "pipe:1", "-nostats", *tail]


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
        now = time.monotonic()
        should_log = status == "end" or ratio >= last_bar_ratio + 0.05 or now - last_bar_time >= 5.0
        if should_log:
            bar_line = _ffmpeg_progress_bar(progress_label, current, progress_total, ffmpeg_progress_state.get("speed", ""))
            lines.append(bar_line)
            context.log(bar_line)
            last_bar_time = now
            last_bar_ratio = ratio
        return True

    assert process.stdout is not None
    for raw_line in process.stdout:
        if context.cancelled():
            context.log("[CANCEL] Terminating child process...")
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
            raise RuntimeError("Operation cancelled by user.")

        output_lines = decoded_process_lines(raw_line) if isinstance(raw_line, bytes) else [str(raw_line).rstrip("\r\n")]
        for line in output_lines:
            if not line or consume_ffmpeg_progress(line):
                continue
            lines.append(line)
            context.log(line)

        now = time.monotonic()
        if now - last_progress >= 0.5:
            elapsed = max(0.0, now - start)
            context.progress(min(0.95, 0.08 + elapsed / max(1.0, float(progress_seconds))))
            last_progress = now

    exit_code = process.wait()
    command_record["exit_code"] = exit_code
    command_record["duration_seconds"] = round(time.monotonic() - process_started, 3)
    command_record["line_count"] = len(lines)
    context.log(f"[EXIT] {exit_code}")
    if check and exit_code != 0:
        raise RuntimeError(f"Command failed with exit code {exit_code}.")
    return ProcessResult(exit_code=exit_code, lines=tuple(lines))


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
            raise RuntimeError("Preflight failed. See operation log and batch report.")
        result = _load_callable(operation.service)(context)
        context.progress(1.0)
        context.log(f"Finished operation: {operation.id}")

        finished_at = timestamp()
        duration = time.monotonic() - started
        if isinstance(result, dict):
            data = dict(result)
            reported_ok = bool(data.get("ok", True))
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
        error_text = traceback.format_exc()
        context.log(error_text)
        finished_at = timestamp()
        duration = time.monotonic() - started
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
        return JobResult(False, message, report_files)
