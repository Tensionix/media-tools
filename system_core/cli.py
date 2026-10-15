"""The console command of Audion Media Tools.

A button of the window and the command line run the same thing: an operation of the manifest, by the same
runner (`execute_operation`), with the same rules of its form (`core\\operation_model.py`). Until 3.0.0 an
operation could be run "as the window runs it" only from the window.

  python system_core/cli.py describe
  python system_core/cli.py run --operation storage_run --set storage_profile=x264_crf14
  python system_core/cli.py run --operation trim_run --set trim_file=clip.mov --set trim_start=00:00:05,000
  python system_core/cli.py run --operation remux_run --source D:\\Footage --target D:\\Out --dry-run
  python system_core/cli.py version

The output of `run`: a plain line is a line of the operation's journal; a line that starts with `::media::`
is a service line and carries JSON - `started`, `progress` (the share of the work done, 0..1), `activity`
(the one live line under the journal), `finished`. Service lines go to a caller that reads the output by a pipe
(the window, a script); a person at a console does not get them. The outcome goes to the file of `--result` as well.

The engine tells how far a file is with a line `[PROGRESS] name [####----] 42% 00:01:12/00:02:50 speed=3.4x`, with
FFmpeg's own line `frame= ... speed=` under it, and how far the operation is with its share of files done; yt-dlp - with
its `[download]` lines. A caller that
asked for it (`--live`: the window does) gets `activity` instead of those lines and `progress` for the share;
a console gets every line as before. A caller that reads the output by a pipe gets the text without colour
codes, or with them when it asks (`--colours`).

Outcomes and exit codes: `done` 0; `failed` 1; `stopped` 130; a wrong call - 2, and nothing is run. A form
that may not be run as it stands (no tick in a row that needs one, a field the operation has not, a value
that is none of its choices) is a wrong call; so is `--dry-run` of an operation that cannot only say its commands.
A run its preflight refuses (no file of its kind in the Source) is `refused`, exit 2: its [PREFLIGHT] lines say why.

Paths: a relative `--source` or `--target` is counted from the project folder, as the window shows them; a
relative `--params`, `--result` or `--cancel-file` - from the folder of the caller.

Stopping: the caller creates the file of `--cancel-file`; the operation ends its engine and stops.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import secrets
import sys
import time
from dataclasses import replace
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from system_core.core import operation_model as model  # noqa: E402
from system_core.core import program_map, window_layout  # noqa: E402
from system_core.core.program_map import as_text, load_wrappers, wrapper_runs  # noqa: E402
from system_core.core.jobs import FFMPEG_STATS, execute_operation  # noqa: E402
from system_core.core.manifest import load_manifest  # noqa: E402
from system_core.core.path_cache import ONLY_FORMATS_ENV, OUTPUT_ENV, SOURCE_ENV  # noqa: E402
from system_core.core.paths import ensure_project_dirs, get_project_paths  # noqa: E402

CONTROL = "::media::"
EXIT_OK, EXIT_FAILED, EXIT_USAGE, EXIT_STOPPED = 0, 1, 2, 130
ANSI = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]")

# Nobody reads the output any more - the caller closed its end of the pipe. The operation goes on without it:
# its own journal file is written all the same.
_nobody_listens = False


def strip_ansi(text: str) -> str:
    return ANSI.sub("", text)


def say(line: str) -> None:
    global _nobody_listens
    if _nobody_listens:
        return
    try:
        print(line, flush=True)
    except (OSError, ValueError):
        _nobody_listens = True


def control(payload: dict[str, Any]) -> None:
    # A service line is for the window and the callers that read the output through a pipe. A person at a console - a
    # wrapper of Scripts\ started from a launcher - reads the lines of the run, not "::media::{...}".
    if sys.stdout.isatty():
        return
    say(CONTROL + json.dumps(payload, ensure_ascii=False, default=str))


def usage_error(message: str) -> int:
    try:
        print("[ERR] " + message, file=sys.stderr, flush=True)
    except (OSError, ValueError):
        pass
    return EXIT_USAGE


# --- how far the engine is -------------------------------------------------------------------

# "[PROGRESS] clip.mov [##########--------------]  42% 00:01:12/00:02:50 speed=3.4x" - core\jobs.py, every 5 % or 5 s.
FFMPEG = re.compile(r"^\[PROGRESS\]\s+(?P<name>.*?)\s+\[[#-]+\]\s+(?P<share>\d{1,3})%\s+(?P<done>[\d:-]+)/(?P<all>[\d:-]+)(?:\s+speed=\s*(?P<speed>\S+))?\s*$")
# "[download]  42.3% of ~ 123.45MiB at    3.21MiB/s ETA 00:12 (frag 3/40)" - yt-dlp.
YTDLP = re.compile(r"^\[download\]\s+(?P<share>\d{1,3}(?:\.\d+)?)%\s+of\s+~?\s*(?P<size>\S+)(?:\s+at\s+(?P<rate>\S+))?(?:\s+ETA\s+(?P<eta>\S+))?")
# yt-dlp tidying up after a merge or a conversion: "Deleting original file x.f137.mp4 (pass -k to keep)". The window folds
# it, as Media Downloader 5.6.6 does; the journal of the operation in logs\ keeps it.
HOUSEKEEPING = re.compile(r"^Deleting original file .+ \(pass -k to keep\)$")


def seconds_of(clock: str) -> float | None:
    parts = clock.split(":")
    try:
        numbers = [float(part) for part in parts]
    except ValueError:
        return None
    total = 0.0
    for number in numbers:
        total = total * 60 + number
    return total


def clock(seconds: float) -> str:
    whole = max(0, int(round(seconds)))
    hours, rest = divmod(whole, 3600)
    return f"{hours}:{rest // 60:02d}:{rest % 60:02d}" if hours else f"{rest // 60:02d}:{rest % 60:02d}"


class Progress:
    """The share of an operation done, told by its service, and the live line, told by FFmpeg and yt-dlp."""

    def __init__(self, live: bool) -> None:
        self.live, self.told = live, -1.0
        self.said, self.when = "", 0.0
        # The share of the last bar of FFmpeg: its own line beside a bar short of 100 % is the live line's business.
        self.bar = 100

    def share(self, value: float) -> None:
        """The share done, told once and never taken back."""
        value = round(max(0.0, min(1.0, float(value))), 4)
        if value > self.told:
            self.told = value
            control({"progress": value})

    def activity(self, text: str, last: bool = False) -> None:
        """The live line, said at most ten times a second."""
        now = time.monotonic()
        if text == self.said or (not last and now - self.when < 0.1):
            return
        self.said, self.when = text, now
        control({"activity": text})

    def line(self, text: str) -> bool:
        """A line of the journal read for what it says of the work done; True - it was a line of progress, told as such."""
        if not self.live:
            return False
        plain = strip_ansi(text).strip()
        if HOUSEKEEPING.match(plain):
            return True
        if FFMPEG_STATS.match(plain):
            # FFmpeg's own line: the window has the bar as its live line; the final line of a file goes to the journal.
            return self.bar < 100
        found = FFMPEG.match(plain)
        if found:
            self.bar = int(found["share"])
            measures = [f"{found['share']}%", f"{found['done']} / {found['all']}"]
            speed = (found["speed"] or "").strip()
            if speed and speed not in {"N/A", "0x"}:
                measures.append(speed)
                factor = re.match(r"^(\d+(?:\.\d+)?)x$", speed)
                done, total = seconds_of(found["done"]), seconds_of(found["all"])
                if factor and float(factor[1]) > 0 and done is not None and total and total > done:
                    measures.append("ETA " + clock((total - done) / float(factor[1])))
            self.activity(f"{found['name']} · " + " · ".join(measures), found["share"] == "100")
            return True
        found = YTDLP.match(plain)
        if found:
            measures = [f"{found['share']}%", found["size"]]
            if found["rate"] and "Unknown" not in found["rate"]:
                measures.append(found["rate"])
            if found["eta"] and "Unknown" not in found["eta"]:
                measures.append("ETA " + found["eta"])
            self.activity("yt-dlp · " + " · ".join(measures), found["share"].startswith("100"))
            return True
        return False


# --- the project -----------------------------------------------------------------------------


def project(root: str | None):
    paths = get_project_paths(Path(root).resolve() if root else ROOT)
    manifest = paths.config / "tool_manifest.yaml"
    if not manifest.is_file():
        raise ValueError(f"not a project folder, no manifest: {manifest}")
    try:
        return paths, load_manifest(manifest)
    except Exception as error:  # noqa: BLE001 - whatever the manifest stumbles over, nothing was run
        raise ValueError(f"the manifest does not read: {manifest}: {error}") from error


def project_version(paths) -> str:
    try:
        return str(json.loads((paths.config / "version.json").read_text(encoding="utf-8")).get("version", ""))
    except (OSError, ValueError):
        return ""


def language_of(args: argparse.Namespace, paths) -> str:
    """The language named by the caller; without it - the one chosen in the window, English when none was."""
    if getattr(args, "language", ""):
        return model.safe_language(args.language)
    try:
        chosen = json.loads((paths.config / "window_settings.json").read_text(encoding="utf-8-sig")).get("Lang", "")
    except (OSError, ValueError, AttributeError):  # settings that do not read are no reason to refuse a run
        chosen = ""
    return model.safe_language(str(chosen))


def command_describe(args: argparse.Namespace) -> int:
    paths, manifest = project(args.root)
    payload = model.describe(manifest)
    payload["version"] = project_version(paths)
    payload["language"] = language_of(args, paths)
    # Where every operation stands in the window: the sections of the ribbon and the modes of each.
    payload["layout"] = window_layout.for_window(window_layout.load(paths.config), manifest)
    payload["paths"] = {"root": str(paths.root), "input": str(paths.input), "output": str(paths.output),
                        "logs": str(paths.logs), "report": str(paths.report), "config": str(paths.config)}
    # The operations that download: the window names what they fetch (command plan) before it runs them.
    from system_core.services.media_service import INSTALLER_SCRIPTS

    payload["plans"] = list(INSTALLER_SCRIPTS)
    say(json.dumps(payload, ensure_ascii=False, default=str))
    return EXIT_OK


def command_map(args: argparse.Namespace) -> int:
    """The map of the program from its data: sections, operations, fields, choices, presets, wrappers, texts in both
    languages and what has none (core\\program_map.py). To a file with --out, else as one line of JSON."""
    paths, manifest = project(args.root)
    told = program_map.build(paths, manifest, version=project_version(paths), environment=WRAPPER_ENVIRONMENT)
    if getattr(args, "docs", False):
        from system_core.core import program_docs

        written = program_docs.write(told, paths.root)
        for path in written:
            say(f"[DOCS] {path.relative_to(paths.root)}")
        say(f"[DOCS] {len(written)} written, the others are as the map makes them")
        if not args.out:
            return EXIT_OK
    if args.out:
        trouble = write_result(own_file(args.out), told)
        if trouble:
            return usage_error(f"the map could not be written to {args.out}: {trouble}")
        say(f"[MAP] {own_file(args.out)}: {len(told['operations'])} operations, {len(told['wrappers'])} wrappers, "
            f"{len(told['missing'])} texts missing")
        return EXIT_OK
    say(json.dumps(told, ensure_ascii=False, default=str))
    return EXIT_OK


def command_form(args: argparse.Namespace) -> int:
    """The forms of the window, held while it is open (core\\form_pages.py): a JSON request a line on the input, a JSON
    answer a line on the output, until the input closes."""
    from system_core.core import form_pages

    paths, manifest = project(args.root)
    os.chdir(paths.root)
    answers = sys.stdout
    # Whatever the engine prints while a form is drawn goes to the errors: the output carries the answers alone.
    sys.stdout = sys.stderr
    try:
        sys.stdin.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass

    def write(text: str) -> None:
        answers.write(text)
        answers.flush()

    form_pages.serve(form_pages.Pages(paths.root, manifest, language_of(args, paths)), sys.stdin.readline, write)
    return EXIT_OK


def command_version(args: argparse.Namespace) -> int:
    paths, _manifest = project(args.root)
    say(project_version(paths))
    return EXIT_OK


def command_plan(args: argparse.Namespace) -> int:
    """What an installer of SERVICE would download - its files, their source and size - asked of its script with nothing
    fetched (media_service.installer_plan), as one line of JSON."""
    from system_core.services.media_service import INSTALLER_SCRIPTS, installer_plan

    paths, _manifest = project(args.root)
    if args.operation not in INSTALLER_SCRIPTS:
        return usage_error(f"{args.operation!r} is no installer; installers: {', '.join(INSTALLER_SCRIPTS)}")
    say(json.dumps(installer_plan(paths.root, args.operation), ensure_ascii=False))
    return EXIT_OK


def command_components(args: argparse.Namespace) -> int:
    """The versions of the components and the GPU drivers, and which component has a newer release (core\\components.py),
    as one line of JSON."""
    from system_core.core import components

    paths, _manifest = project(args.root)
    say(json.dumps(components.report(paths.root, latest=args.latest, refresh=args.refresh), ensure_ascii=False))
    return EXIT_OK


def read_values(args: argparse.Namespace, node) -> dict[str, Any]:
    """The values of the fields: the file of `--params`, over it every `--set name=value`."""
    values: dict[str, Any] = {}
    if args.params:
        loaded = json.loads(Path(args.params).read_text(encoding="utf-8-sig"))
        if not isinstance(loaded, dict):
            raise ValueError("--params: a JSON object \"field name: value\" is expected")
        values.update(loaded)
    fields = {model.field_id(field): field for field in node.fields if model.field_id(field)}
    for item in args.set or []:
        name, separator, text = item.partition("=")
        name = name.strip()
        if not separator or not name:
            raise ValueError(f"--set: name=value is expected, got {item!r}")
        if name not in fields:
            raise ValueError(f"--set: the operation has no field {name!r}")
        if model.is_route_field(fields[name]):
            raise ValueError(f"--set {name}: the folders are named with --source and --target")
        try:
            values[name] = model.coerce(fields[name], text)
        except ValueError as error:
            raise ValueError(f"--set {name}: {error}") from error
    return values


def write_result(path: str, payload: dict[str, Any]) -> str:
    """The outcome into its file, whole or not at all; the reason when it could not be written. The draft is a name of
    its own, made only where no file is: a file that only looks like a draft is never touched."""
    if not path:
        return ""
    target = Path(path)
    draft: Path | None = None
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        text = json.dumps(payload, ensure_ascii=False, indent=1, default=str)
        while draft is None:
            candidate = target.with_name(f"{target.name}.{os.getpid()}-{secrets.token_hex(3)}.tmp")
            try:
                with candidate.open("x", encoding="utf-8") as stream:
                    stream.write(text)
                draft = candidate
            except FileExistsError:
                continue
        draft.replace(target)
        return ""
    except OSError as error:
        if draft is not None:
            draft.unlink(missing_ok=True)
        return str(error)


def result_refusal(result: str, source: Path, params: str, paths) -> str:
    """Why the outcome may not go where --result names it; "" - it may. It is a .json file: a source, a file inside the
    Source, the --params file and the settings of the program are never written over by it."""
    if not result:
        return ""
    target = Path(result)
    if target.suffix.lower() != ".json":
        return f"--result names a .json file, and {target.name} is not one"
    if target.is_dir():
        return f"--result names a folder: {target}"
    def same(first: Path, second: Path) -> bool:
        try:
            if first.exists() and second.exists():
                return os.path.samefile(first, second)
        except OSError:
            pass
        return os.path.normcase(os.path.realpath(first)) == os.path.normcase(os.path.realpath(second))
    def inside(path: Path, folder: Path) -> bool:
        try:
            Path(os.path.realpath(path)).relative_to(Path(os.path.realpath(folder)))
            return True
        except ValueError:
            return False
    # The window's own session folder, ._runtime inside the program, is not a file of the Source - even when the Source is
    # a folder that holds the program.
    own = inside(target, paths.root) and "._runtime" in Path(os.path.realpath(target)).parts
    if same(target, source) or (source.is_dir() and inside(target, source) and not own):
        return f"--result would be written into the Source: {target}"
    if params and same(target, Path(params)):
        return "--result and --params name one file"
    if inside(target, paths.config):
        return f"--result would be written over a file of the program's settings: {target}"
    return ""


def expand_percent(text: str) -> str:
    """`%NAME%` of the environment and nothing else: a folder may be called `$TEMP`."""
    return re.sub(r"%([^%\\/:*?\"<>|]+)%", lambda found: os.environ.get(found.group(1), found.group(0)), text)


def workbench_path(text: str, fallback: Path, root: Path) -> Path:
    """Source or Target as named by the caller; a relative one is counted from the project folder."""
    if not text:
        return fallback
    cleaned = text.strip().strip('"').strip()
    if '"' in cleaned:
        # `"E:\My Files\" --target D:\Out` reaches a program as one argument with a quote inside: the
        # backslash before the closing quote glued the next key to the path.
        raise ValueError(f"a quotation mark inside a path - was the path quoted with a backslash at its end? {text!r}")
    path = Path(expand_percent(cleaned)).expanduser()
    return path if path.is_absolute() else root / path


def own_file(text: str) -> str:
    """A file of the caller - the values, the outcome, the stop signal - as a full path, counted from where it called."""
    return str(Path(text).expanduser().resolve()) if text else ""


# Operations without the field of a dry run that still take --dry-run: an installer says the script it would run and runs none
# (media_service._run_installer); a check and the source info change nothing - their run is their own preview. Any other
# operation would run for real: the encoder tests write config\hardware_capabilities_cache.json, the preset matrix encodes for
# an hour.
DRY_RUN_TOO = {"install_7zip", "install_ffmpeg", "install_ytdlp", "install_mpv", "selftest", "inventory", "profile_doctor",
               "probe_source", "source_info"}


def command_run(args: argparse.Namespace) -> int:
    paths, manifest = project(args.root)
    node = model.find_node(manifest, args.operation)
    if node is None:
        return usage_error(f"the manifest has no operation {args.operation!r}")
    if node.kind == "dangerous":
        # It deletes for good. The window clears the working folders itself, through the Recycle Bin.
        return usage_error(f"{args.operation!r} deletes for good and is not run from here")
    language = language_of(args, paths)
    # Before the command moves to the project folder: these three are counted from the caller's.
    args.params, args.result, args.cancel_file = own_file(args.params), own_file(args.result), own_file(args.cancel_file)
    try:
        given = read_values(args, node)
        source = workbench_path(args.source, paths.input, paths.root).resolve()
        target = workbench_path(args.target, paths.output, paths.root).resolve()
    except (OSError, ValueError) as error:
        return usage_error(str(error))
    refusal = result_refusal(args.result, source, args.params, paths)
    if refusal:
        return usage_error(refusal)
    unknown = model.unknown_values(node, given)
    if unknown:
        return usage_error("the operation has no fields: " + ", ".join(unknown))
    # The services read the Source and the Target of the process (core\path_cache.py): this run's, not the window's.
    os.environ[SOURCE_ENV], os.environ[OUTPUT_ENV] = str(source), str(target)
    # The kinds of file this run takes, when the caller narrows them (media_service._media_files).
    only = ",".join(part.strip().lower().lstrip(".") for part in str(getattr(args, "only", "") or "").split(",") if part.strip())
    if only:
        os.environ[ONLY_FORMATS_ENV] = only
    else:
        os.environ.pop(ONLY_FORMATS_ENV, None)
    wrong = model.wrong_choices(node, given, paths.root, language)
    if wrong:
        return usage_error("; ".join(wrong))
    form = model.Form(node, paths.root, source, target).open().fill(given)
    refused = form.refusal(language)
    if refused:
        return usage_error(refused)
    parameters = form.parameters()
    if getattr(args, "pass_over_empty", False):
        from system_core.core.preflight import source_files

        if source_files(str(getattr(node, "service", "") or ""), parameters, source) == []:
            # One of several runs of a wrapper, and the Source holds none of its files: another run takes them.
            say(f"[SKIP] {node.id}: no file of its kind in {source}")
            args.passed_over = True
            return EXIT_OK
    if args.dry_run:
        # What the window's command preview did: the engine says what it would run and runs nothing. Only a service with the
        # field of it reads it: any other would run for real.
        own = {"dry_run", "youtube_dry_run"} & {model.field_id(field) for field in model.form_fields(node)}
        if node.id not in DRY_RUN_TOO and not own:
            return usage_error(f"{args.operation!r} cannot say its commands without running them: it has no dry run")
        # The field of the operation's own, and no other: a field the operation has not would stand in its parameters.
        parameters.update({name: True for name in own or {"dry_run"}})

    ensure_project_dirs(paths)
    # Where the services have always been run from: the program folder.
    os.chdir(paths.root)
    cancel_file = Path(args.cancel_file) if args.cancel_file else None
    progress = Progress(bool(args.live))
    colours = bool(args.colours)

    def tell(line: str) -> None:
        text = str(line)
        if progress.line(text):
            return
        say(text if colours or sys.stdout.isatty() else strip_ansi(text))

    for key, wanted, became in form.changed(given):
        tell(f"[NOTE] {key}: {wanted!r} became {became!r} - the form changes it so, as the window did")

    operation = node.to_operation(parameters) if hasattr(node, "to_operation") else replace(node, parameters=parameters)
    control({"started": {"operation": operation.id, "source": str(source), "target": str(target)}})
    began = time.monotonic()
    run_paths = replace(paths, input=source, output=target)
    result = execute_operation(run_paths, operation, tell, progress.share,
                               (lambda: cancel_file.exists()) if cancel_file is not None else None)
    # A service ends its engine when asked to stop and reports the run as failed: with the signal there and no
    # success, that is a stop. A success is a success whatever lies there.
    stopped = bool(not result.ok and (result.data.get("cancelled") is True
                                      or (cancel_file is not None and cancel_file.exists())))
    # A run the preflight refused began nothing: a refusal, as a wrong call is - the window says "refused before it began".
    refused = bool(not result.ok and not stopped and result.data.get("preflight_refused") is True)
    outcome = "stopped" if stopped else "done" if result.ok else "refused" if refused else "failed"
    seconds = round(time.monotonic() - began, 1)
    trouble = write_result(args.result, {"operation": operation.id, "outcome": outcome, "ok": result.ok,
                                         "message": result.message, "data": result.data, "parameters": parameters,
                                         "source": str(source), "target": str(target), "seconds": seconds})
    if trouble:
        say(f"[WARN] The outcome could not be written to {args.result}: {trouble}")
    control({"finished": {"outcome": outcome, "message": result.message, "seconds": seconds}})
    return EXIT_STOPPED if stopped else EXIT_OK if result.ok else EXIT_USAGE if refused else EXIT_FAILED


# --- the wrappers of Scripts\ ----------------------------------------------------------------------------------------

# What the wrappers have always read from the environment, by the field of the operation it goes to. A name goes in
# only where the operation has that field. SOURCE, OUT and the other short names are the ones Scripts\Common set.
WRAPPER_ENVIRONMENT = {
    "crf": ("AUDION_CRF", "CRF"),
    "cq": ("AUDION_CQ", "AUDION_QP", "CQ", "QP"),
    "encode_backend": ("AUDION_ENCODE_BACKEND", "AUDION_BACKEND", "ENCODE_BACKEND"),
    "decode_backend": ("AUDION_DECODE_BACKEND", "DECODE_BACKEND"),
    "cpu_encoder_preset": ("AUDION_CPU_ENCODER_PRESET", "AUDION_ENCODER_PRESET", "ENCODER_PRESET", "PRESET"),
    "nvenc_preset": ("AUDION_NVENC_PRESET",),
    "qsv_encoder_preset": ("AUDION_QSV_ENCODER_PRESET",),
    "amf_quality": ("AUDION_AMF_QUALITY",),
    "av1_preset": ("AUDION_AV1_PRESET", "AV1_PRESET"),
    "pix_fmt": ("AUDION_PIX_FMT", "PIX_FMT"),
    "encode_tuning": ("AUDION_ENCODE_TUNING", "ENCODE_TUNING"),
    "target_codecs": ("AUDION_TARGET_CODECS", "TARGET_CODECS"),
    "input_formats": ("AUDION_INPUT_FORMATS", "INPUT_FORMATS"),
    "audio_bitrate": ("AUDION_AUDIO_BITRATE", "AUDIO_BITRATE"),
    "audio_mode": ("AUDION_AUDIO_MODE", "AUDIO_MODE"),
    "audio_copy_container": ("AUDION_AUDIO_COPY_CONTAINER", "AUDIO_COPY_CONTAINER"),
    "audio_sample_rate": ("AUDION_AUDIO_SAMPLE_RATE", "AUDIO_SAMPLE_RATE"),
    "mp3_lame_preset": ("AUDION_MP3_LAME_PRESET", "MP3_LAME_PRESET"),
    "overwrite": ("AUDION_OVERWRITE", "OVERWRITE"),
    "limit_first_file": ("AUDION_LIMIT_FIRST_FILE", "AUDION_FIRST_FILE", "FIRST_FILE"),
    "lut_file": ("AUDION_LUT_FILE", "LUT_FILE", "ACTIVE_LUT"),
    "pre_gamma": ("AUDION_PRE_GAMMA", "PRE_GAMMA"),
    "fps_output_profile": ("AUDION_FPS_OUTPUT_PROFILE", "OUT_MODE"),
    "fps_audio_pcm_depth": ("AUDION_FPS_AUDIO_PCM_DEPTH",),
    "fps_audio_oversample": ("AUDION_FPS_AUDIO_OVERSAMPLE",),
    "trim_file": ("AUDION_TRIM_FILE", "TRIM_FILE"),
    "trim_start": ("AUDION_TRIM_START", "TRIM_START"),
    "trim_end": ("AUDION_TRIM_END", "TRIM_END"),
    "trim_container": ("AUDION_TRIM_CONTAINER",),
    "trim_audio": ("AUDION_TRIM_AUDIO",),
    "trim_audio_channel": ("AUDION_TRIM_AUDIO_CHANNEL",),
    "trim_timecode": ("AUDION_TRIM_TIMECODE",),
    "trim_faststart": ("AUDION_TRIM_FASTSTART",),
    "trim_data": ("AUDION_TRIM_DATA",),
    "trim_subtitles": ("AUDION_TRIM_SUBTITLES",),
    "youtube_url": ("AUDION_YOUTUBE_URL", "YOUTUBE_URL", "URL"),
    "batch_file": ("AUDION_URLS_FILE", "URLS_FILE", "LIST"),
}
SOURCE_NAMES = ("AUDION_SOURCE", "AUDION_SRC", "SOURCE", "SRC")
TARGET_NAMES = ("AUDION_OUTPUT", "AUDION_OUT", "AUDION_DESTINATION", "OUT")
DRY_NAMES = ("AUDION_DRY_RUN", "DRY_RUN")


def first_env(*names: str) -> str:
    for name in names:
        value = os.environ.get(name, "").strip()
        if value:
            return value
    return ""


def wrapper_values(run: dict[str, Any], fields: set[str]) -> dict[str, Any]:
    """The values of one run of a wrapper: its `set`, over them the environment for the fields the operation has,
    over everything its `fixed`."""
    values = dict(run.get("set") or {})
    for field, names in WRAPPER_ENVIRONMENT.items():
        given = first_env(*names)
        if given and field in fields:
            values[field] = given
    values.update(run.get("fixed") or {})
    return values


def command_wrapper(args: argparse.Namespace) -> int:
    """A wrapper of Scripts\\: its operations from config\\wrappers.yaml, its values over them from the environment."""
    paths, manifest = project(args.root)
    wrappers = load_wrappers(paths.config)
    # Windows does not tell ff-grade-lut-only-proresLT.cmd from ...proreslt.cmd, and %~n0 is the name as it was typed.
    entry = wrappers.get(args.name) or next((value for key, value in wrappers.items() if key.lower() == args.name.lower()), None)
    if entry is None:
        return usage_error(f"no wrapper {args.name!r} in config\\wrappers.yaml")
    rest = list(args.arguments or [])
    dry = "--dry-run" in rest or bool(first_env(*DRY_NAMES).lower() in {"1", "true", "yes", "on"})
    rest = [item for item in rest if item != "--dry-run"]
    worst = EXIT_OK
    runs = wrapper_runs(entry)
    ran = False
    for index, run in enumerate(runs):
        node = model.find_node(manifest, str(run.get("op")))
        if node is None:
            return usage_error(f"{args.name}: the manifest has no operation {run.get('op')!r}")
        fields = {model.field_id(field) for field in model.form_fields(node)}
        values = wrapper_values(run, fields)
        takes = str(entry.get("takes") or "")
        if takes == "sections" and rest:
            values["youtube_sections"], rest_urls = rest[0], rest[1:]
        else:
            rest_urls = rest if takes == "urls" else []
        if rest_urls:
            values["youtube_url"] = rest_urls[0]
            if len(rest_urls) > 1:
                # Several links: a list of them, as input\urls.txt is one.
                listed = Path(os.environ.get("TEMP", str(paths.workspace))) / f"audion-wrapper-urls-{os.getpid()}.txt"
                listed.write_text("\n".join(rest_urls) + "\n", encoding="utf-8")
                values.update({"youtube_source_mode": "batch", "batch_file": str(listed)})
        elif "youtube_url" in fields and not values.get("youtube_url") and values.get("youtube_source_mode") != "batch":
            # No link given: the links of the list, as the wrapper of a list does.
            values["youtube_source_mode"] = "batch"
        run_args = argparse.Namespace(
            root=args.root, operation=node.id, source=first_env(*SOURCE_NAMES), target=first_env(*TARGET_NAMES),
            set=[f"{key}={as_text(value)}" for key, value in values.items() if key in fields],
            params="", result="", cancel_file="", dry_run=dry, live=bool(args.live), colours=bool(args.colours),
            only=as_text(run.get("only") or []), language=getattr(args, "language", ""),
            # Several runs take a kind of file each (the sound of videos, then sound files): a run whose files the
            # Source has none of is passed over - but not the last when nothing ran, it says why nothing did.
            pass_over_empty=len(runs) > 1 and (index < len(runs) - 1 or ran))
        code = command_run(run_args)
        ran = ran or not getattr(run_args, "passed_over", False)
        if code != EXIT_OK and worst == EXIT_OK:
            worst = code
    return worst


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="media_cli", description="Audion Media Tools: the console command.")
    parser.add_argument("--root", default="", help="The project folder; this one when not named.")
    parser.add_argument("--language", default="", help="en or ru; the language of the window when not named")
    commands = parser.add_subparsers(dest="command", required=True)

    describe = commands.add_parser("describe", help="The operations, their fields and the layout of the window as one line of JSON")
    describe.add_argument("--language", default=argparse.SUPPRESS)
    describe.set_defaults(func=command_describe)

    run = commands.add_parser("run", help="Run an operation of the manifest")
    run.add_argument("--operation", required=True)
    run.add_argument("--source", default="", help="A folder or one file; `input` of the program when not named")
    run.add_argument("--target", default="", help="A folder; `output` of the program when not named")
    run.add_argument("--set", action="append", default=[], metavar="NAME=VALUE")
    run.add_argument("--params", default="", help="A JSON file \"field name: value\"")
    run.add_argument("--result", default="", help="A file the outcome is written to")
    run.add_argument("--cancel-file", default="", help="A file whose appearance stops the operation")
    run.add_argument("--dry-run", action="store_true", help="Say the commands the operation would run, run none")
    run.add_argument("--only", default="", help="The kinds of file to take, e.g. mkv or mov,mxf; all the operation knows when not named")
    run.add_argument("--language", default=argparse.SUPPRESS)
    run.add_argument("--live", action="store_true", help="Tell the progress of the engine as service lines, not as its lines")
    run.add_argument("--colours", action="store_true", help="Leave the colour codes in the lines")
    run.set_defaults(func=command_run)

    wrapper = commands.add_parser("wrapper", help="Run a wrapper of Scripts\\ by its name (config\\wrappers.yaml)")
    wrapper.add_argument("name")
    wrapper.add_argument("arguments", nargs=argparse.REMAINDER, help="Links of yt-dlp, a section; --dry-run")
    wrapper.add_argument("--live", action="store_true", help=argparse.SUPPRESS)
    wrapper.add_argument("--colours", action="store_true", help=argparse.SUPPRESS)
    wrapper.add_argument("--language", default=argparse.SUPPRESS)
    wrapper.set_defaults(func=command_wrapper)

    form = commands.add_parser("form", help="The forms of the window: a JSON request a line in, a JSON answer a line out")
    form.add_argument("--language", default=argparse.SUPPRESS)
    form.set_defaults(func=command_form)

    program = commands.add_parser("map", help="The map of the program from its data, the texts in both languages and what has none")
    program.add_argument("--out", default="", help="A JSON file to write it to; one line on the output when not named")
    program.add_argument("--docs", action="store_true",
                         help="Write the reference part of the documents from the map: Docs\\OPERATIONS_*.md, Docs\\SCRIPTS_*.md and the "
                              "tables between <!-- map:NAME --> and <!-- /map --> of SKILL.md, the agent guides and the CLI guides")
    program.set_defaults(func=command_map)

    commands.add_parser("version", help="The version number").set_defaults(func=command_version)

    parts = commands.add_parser("components", help="The versions of yt-dlp, deno, mpv, FFmpeg, 7-Zip and the GPU drivers, and the newest releases")
    parts.add_argument("--latest", action="store_true", help="Ask GitHub for the newest releases when the remembered ones are a day old")
    parts.add_argument("--refresh", action="store_true", help="Ask GitHub now")
    parts.set_defaults(func=command_components)

    plan = commands.add_parser("plan", help="What an installer of SERVICE would download: the files, their source and size")
    plan.add_argument("--operation", required=True, help="install_7zip, install_ffmpeg, install_ytdlp or install_mpv")
    plan.set_defaults(func=command_plan)
    return parser


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass
    try:
        args = build_parser().parse_args(argv)
    except SystemExit as stop:
        return EXIT_OK if stop.code in (0, None) else EXIT_USAGE
    try:
        return args.func(args)
    except ValueError as error:
        return usage_error(str(error))


if __name__ == "__main__":
    raise SystemExit(main())
