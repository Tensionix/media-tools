"""The wrappers of Scripts\\ against what they ran before 3.0.0.

Until 3.0.0 a wrapper ran its own executor; from 3.0.0 it is a door to `media_cli.cmd wrapper <name>`, and the
work is the engine's. tests\\former_wrapper_commands.json holds what every one of the 95 wrappers had FFmpeg and
yt-dlp run in a dry run on a set of short clips (tests\\capture_former_wrappers.py). Here every wrapper is run
the new way, in its dry run, on the same clips, and its command lines are held to the record.

A command line is compared by what it does: the input, the kind of file written, the options; a download also by
the formats yt-dlp picks with it from a fixed list of formats, offline (YOUTUBE_INFO). Two writings of one work are
made one before the comparison (normal). What 3.0.0 changes on purpose is read into the record, one rule each with
its reason - REWRITTEN, ACCEPTED, PASSED_OVER, RUN_NOW; anything else is a difference and fails.
"""
from __future__ import annotations

import ctypes
import fnmatch
import functools
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from collections import Counter
from pathlib import Path
from typing import Any

import pytest

PROJECT = Path(__file__).resolve().parent.parent
CLI = PROJECT / "system_core" / "cli.py"
FFMPEG = PROJECT / "Tools" / "ffmpeg" / "bin" / "ffmpeg.exe"
YTDLP = PROJECT / "Tools" / "yt-dlp" / "bin" / "yt-dlp.exe"
RECORD: dict[str, dict[str, Any]] = json.loads((Path(__file__).resolve().parent / "former_wrapper_commands.json").read_text(encoding="utf-8"))


def recorded_root() -> Path:
    """The program the record was taken on: its root stands in the record as <ROOT>, but not where FFmpeg was told it in
    the escaped form of a filter (lut3d=file=E\\:/TOOLS/...). Read from the record itself - a copy of this program in
    another folder compares the same as this one."""
    for entry in RECORD.values():
        for command in entry.get("commands") or []:
            for token in command:
                found = re.search(r"lut3d=file=([A-Za-z])\\\\:(/.+?)/LUTs/", str(token))
                if found:
                    return Path(f"{found.group(1)}:{found.group(2)}".replace("/", "\\"))
    return PROJECT.parent / f"{PROJECT.name} NiceGUI"


REFERENCE = recorded_root()

spec = importlib.util.spec_from_file_location("capture_former_wrappers", Path(__file__).resolve().parent / "capture_former_wrappers.py")
capture = importlib.util.module_from_spec(spec)
spec.loader.exec_module(capture)

# Options that say how a command runs, not what it makes; overwriting is the form's choice (the window's
# default: do not overwrite - the wrappers overwrote).
QUIET = {"-hide_banner", "-stats", "-nostats", "-nostdin", "-y", "-n"}
QUIET_WITH_VALUE = {"-loglevel", "-progress"}
# FFmpeg copies the metadata and the chapters of its first input without being told.
DEFAULTS = {("-map_metadata", "0"), ("-map_chapters", "0")}
# One option, two spellings.
ALIASES = {"-a": "--batch-file"}
# Changed on purpose in 3.0.0 (the owner, 15.10.2026: "Source -> Transcoded на input -> output"): Download leaves the
# root for output, and the list of links lies in the Source. Read into the record before it is compared.
CHANGED = [
    ("<ROOT>\\Download\\urls.txt", "<SRC>\\urls.txt"),
    ("<ROOT>\\Download", "<OUT>\\Download"),
]

# --- one work, two writings ------------------------------------------------------------------------------------
# A sound taken out alone (-vn): its first stream named by place (0:a:0?) or by index (0:1) is one stream once the
# file is read, and a file without sound is passed over (PASSED_OVER); nothing else is mapped, so -sn and -dn say
# nothing and -c copy is -c:a copy.
SOUND_MAP = re.compile(r"0:a:0\??|0:\d+")
# loudnorm: print_format only writes the measure into the log; -2.0 and -2 are one number.
LOG_ONLY = re.compile(r":print_format=summary")
WHOLE_NUMBER = re.compile(r"\b(I|TP|LRA)=(-?\d+)\.0\b")
# yt-dlp: --sub-langs says nothing without a subtitle to write; -N (fragments at once) nothing without a download; the
# old executor put Tools\ffmpeg\bin first on PATH, the engine names it with --ffmpeg-location.
SUBTITLE_WRITERS = {("--write-subs",), ("--write-auto-subs",), ("--embed-subs",)}
FFMPEG_LOCATION = ("--ffmpeg-location", "<ROOT>\\Tools\\ffmpeg\\bin")
# What picks a format is compared by what yt-dlp picks with it (-x too: it makes the default bestaudio/best).
PICKERS = {"-f", "--format", "-S", "--format-sort"}

# --- changed on purpose in 3.0.0 ----------------------------------------------------------------------------------
# A unit of the record as the engine writes it now: (the wrappers, the unit then, the units now, why).
REWRITTEN = [
    ("audio-*", r"-af aresample=(\d+):resampler=soxr:cutoff=0\.95:precision=28:dither_method=triangular(,aresample=async=1:first_pts=0)?",
     [r"-af aresample=resampler=soxr:precision=33:osr=\1\2"],
     "one resampler for the window and the wrappers: SoX at its highest precision (33, not 28), with its own cutoff (0.91, "
     "not 0.95 - the band up to 20 kHz at 44.1 kHz), without a dither on the way to 24 bits"),
    ("audio-to-flac-*", r"-ar (\d+)", [r"-af aresample=resampler=soxr:precision=33:osr=\1"],
     "the same resampler for FLAC: SoX, where the wrapper left FFmpeg's own"),
    ("audio-lufs-14", r"-af loudnorm=I=-14:TP=-1:LRA=11", ["-af loudnorm=I=-14:TP=-1.5:LRA=11"],
     "one ceiling for -14 LUFS in the window and the wrappers: -1.5 dBTP, not -1"),
    ("ff-remux-*", r"-map 0:v:0", ["-map 0:v?"], "the window's PACKAGE: every video stream, and a file without one is no error"),
    ("ff-remux-mp4-to-mkv*", r"-map 0", ["-map 0:v?", "-map 0:a?", "-sn", "-dn"],
     "MKV takes neither the mov_text subtitles of an MP4 nor its data streams: the old line stopped on a clip with "
     "subtitles - 'Subtitle codec mov_text is not supported'"),
    ("ff-extract-subs", r"-map 0:s\?", ["-map 0:s"], "the file is read first and one without subtitles passed over: the map needs no '?'"),
]
# Units the record gains or loses: (the wrappers, lost, added, why).
ACCEPTED = [
    ("yt-batch-*", [], ["-o %(uploader)s/%(upload_date>%Y-%m-%d)s - %(title).180B [%(id)s].%(ext)s"],
     "a list of links names its files as one link does - by the channel and the date - where the old batch took the name of yt-dlp"),
    ("yt-subs-only", [], ["--write-auto-subs", "--sub-format srt/best"],
     "the window's SUBTITLES: the automatic ones too, for a language without subtitles of its own; SRT where the site has it"),
]
# Units every command of yt-dlp gains: (the unit, why).
EVERY_YTDLP = [
    ("--ignore-config", "the personal yt-dlp.conf of the user (%APPDATA%\\yt-dlp\\config) no longer changes a download of the "
     "program in silence - Media Downloader 5.6.6 passes it to every download"),
]
# Units a command of yt-dlp for one link gains - not a playlist, not the links of a file: (the unit, why).
ONE_LINK_YTDLP = [
    ("--no-playlist", "one link is one video: a link to a video in a playlist (watch?v=...&list=...) no longer brings the "
     "playlist along - Media Downloader 5.6.6 passes it unless asked otherwise"),
]
# Files the old executor ran and the engine passes over: (the wrappers, the files, why).
PASSED_OVER = [
    ("audio-*", ["hdr_hevc10_pq.mkv"], "a file without sound; the old line stopped on it - 'Output file does not contain any stream'"),
    ("audio-extract-audio-copy", ["song.*"], "EXTRACT takes the sound out of a video; the old line copied a sound file beside itself"),
    ("ff-extract-audio", ["song.*"], "EXTRACT takes the sound out of a video; the old line copied a sound file beside itself"),
    ("ff-extract-subs", ["clip_51_pcm.mov", "clip_h264_aac.mkv", "clip_h264_aac.mp4", "clip_mpeg2_pcm.mxf", "clip_prores_pcm.mov",
                         "hdr_hevc10_pq.mkv"],
     "a file without subtitles; the old line wrote its picture and sound into the .mks instead"),
]
# Files the engine runs and the old executor passed over: (the wrappers, the files, why).
RUN_NOW = [
    ("audio-resample-to-*", ["*"], "every file gets its sound at the rate asked; the old executor passed over a file already at it "
                                   "('already 48000 Hz')"),
]
# Exit codes other than 0: (the code, why).
EXITS = {
    "ff-trim-middle": (1, "the clip has no keyframe after the piece to cut out, so nothing is cut (the old executor passed it over "
                          "the same way): the engine says so with exit 1, where the old one ended with 0"),
}
# One selftest behind both wrappers, of every tool of the program, where each looked at its own: what the old one ran is
# run, and more.
SELFTESTS = {"ff-selftest", "yt-selftest"}
# A wrapper of a rate reads the rate of each file from the file; the old executor took it from the wrapper's name. The
# clips run at 25 fps (tests\capture_former_wrappers.py): every such wrapper does on them what ff-25to23976-<mode> did.
RATE = re.compile(r"ff-\d+to23976-(varispeed|conform)")


def _video(fid: str, ext: str, vcodec: str, width: int, height: int, tbr: int) -> dict[str, Any]:
    return {"format_id": fid, "ext": ext, "vcodec": vcodec, "acodec": "none", "width": width, "height": height, "fps": 30, "tbr": tbr,
            "vbr": tbr, "protocol": "https", "url": f"https://example.com/{fid}", "filesize": tbr * 75_000, "dynamic_range": "SDR"}


def _sound(fid: str, ext: str, acodec: str, abr: int, asr: int) -> dict[str, Any]:
    return {"format_id": fid, "ext": ext, "vcodec": "none", "acodec": acodec, "abr": abr, "tbr": abr, "asr": asr, "audio_channels": 2,
            "protocol": "https", "url": f"https://example.com/{fid}", "filesize": abr * 75_000}


# The formats of a YouTube video as yt-dlp lists them: H.264, VP9 and AV1 from 144p to 2160p, AAC and Opus.
YOUTUBE_INFO = {
    "id": "sample0000a", "title": "Sample", "uploader": "Someone", "upload_date": "20260101", "duration": 600, "_type": "video",
    "webpage_url": "https://www.youtube.com/watch?v=sample0000a", "extractor": "youtube", "extractor_key": "Youtube",
    "formats": [
        {"format_id": "18", "ext": "mp4", "vcodec": "avc1.42001E", "acodec": "mp4a.40.2", "width": 640, "height": 360, "fps": 30, "tbr": 500,
         "asr": 44100, "audio_channels": 2, "protocol": "https", "url": "https://example.com/18", "filesize": 40_000_000},
        _video("160", "mp4", "avc1.4d400c", 256, 144, 100), _video("135", "mp4", "avc1.4d401f", 854, 480, 1100),
        _video("136", "mp4", "avc1.4d401f", 1280, 720, 2300), _video("137", "mp4", "avc1.640028", 1920, 1080, 4400),
        _video("244", "webm", "vp9", 854, 480, 750), _video("247", "webm", "vp9", 1280, 720, 1500),
        _video("248", "webm", "vp9", 1920, 1080, 2700), _video("313", "webm", "vp9", 3840, 2160, 17000),
        _video("397", "mp4", "av01.0.04M.08", 854, 480, 600), _video("398", "mp4", "av01.0.05M.08", 1280, 720, 1100),
        _video("399", "mp4", "av01.0.08M.08", 1920, 1080, 2100), _video("401", "mp4", "av01.0.12M.08", 3840, 2160, 12000),
        _sound("139", "m4a", "mp4a.40.5", 49, 22050), _sound("140", "m4a", "mp4a.40.2", 129, 44100),
        _sound("250", "webm", "opus", 70, 48000), _sound("251", "webm", "opus", 135, 48000),
    ],
}


def forms(path: Path) -> list[str]:
    """A path as a command line carries it: as it is, with forward slashes, and escaped for a filter of FFmpeg."""
    forward = str(path).replace("\\", "/")
    return [str(path), forward, forward.replace(":", "\\\\:", 1)]


def placeholders(token: str, marks: list[tuple[Path, str]]) -> str:
    for path, mark in marks:
        for form in forms(path):
            token = token.replace(form, mark)
    return token


def swap(token: str) -> str:
    for old, new in CHANGED:
        token = token.replace(old, new)
    return token


def argv_of(line: str) -> list[str]:
    count = ctypes.c_int()
    split = ctypes.windll.shell32.CommandLineToArgvW
    split.restype = ctypes.POINTER(ctypes.c_wchar_p)
    pointer = split(line, ctypes.byref(count))
    try:
        return [pointer[index] for index in range(count.value)]
    finally:
        ctypes.windll.kernel32.LocalFree(pointer)


def units(tokens: list[str]) -> list[tuple[str, ...]]:
    """Options as units: a flag with what follows it up to the next flag."""
    told: list[tuple[str, ...]] = []
    for token in tokens:
        if token.startswith("-") and len(token) > 1 and not token[1].isdigit():
            told.append((token,))
        elif told:
            told[-1] = (*told[-1], token)
        else:
            told.append((token,))
    return told


def unit_of(text: str) -> tuple[str, ...]:
    return tuple(text.split(" ", 1))


@functools.lru_cache(maxsize=1)
def youtube_info() -> Path:
    path = Path(tempfile.mkdtemp(prefix="audion-formats-")) / "formats.info.json"
    path.write_text(json.dumps(YOUTUBE_INFO), encoding="utf-8")
    return path


@functools.lru_cache(maxsize=None)
def picks(arguments: tuple[str, ...]) -> str:
    """The formats yt-dlp picks with these arguments from YOUTUBE_INFO - offline, nothing is downloaded."""
    done = subprocess.run([str(YTDLP), "--ignore-config", "--load-info-json", str(youtube_info()), "--ffmpeg-location", str(FFMPEG.parent),
                           *arguments, "-O", "%(format_id)s"], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120)
    return done.stdout.strip() or "error: " + done.stderr.strip()[-200:]


def _ffmpeg_options(kept: list[str]) -> Counter:
    options = Counter(unit for unit in units(kept) if unit not in DEFAULTS)
    for unit, count in list(options.items()):
        if len(unit) == 2 and "loudnorm=" in unit[1]:
            del options[unit]
            options[(unit[0], WHOLE_NUMBER.sub(r"\1=\2", LOG_ONLY.sub("", unit[1])))] += count
    if ("-vn",) in options:
        for unit, count in list(options.items()):
            if unit in {("-sn",), ("-dn",)}:
                del options[unit]
            elif unit[0] == "-map" and len(unit) == 2 and SOUND_MAP.fullmatch(unit[1]):
                del options[unit]
                options[("-map", "<the first sound>")] += count
            elif unit == ("-c", "copy"):
                del options[unit]
                options[("-c:a", "copy")] += count
    return options


def _ytdlp_options(tokens: list[str], links: tuple[str, ...]) -> Counter:
    told = units([ALIASES.get(token, token) for token in tokens if not token.startswith("http")])
    writes_subtitles = any(unit in SUBTITLE_WRITERS for unit in told)
    downloads = ("--skip-download",) not in told
    kept: list[tuple[str, ...]] = []
    picking: list[str] = []
    for unit in told:
        if unit == FFMPEG_LOCATION or (unit[0] == "--sub-langs" and not writes_subtitles) or (unit[0] == "-N" and not downloads):
            continue
        if unit[0] in PICKERS or unit == ("-x",):
            picking.extend(unit)
            if unit[0] in PICKERS and YTDLP.is_file():
                continue
        kept.append(unit)
    if YTDLP.is_file() and (links or any(unit[0] == "--batch-file" for unit in told)):
        kept.append(("<picks>", picks(tuple(picking))))
    return Counter(kept)


def normal(command: list[str]) -> dict[str, Any]:
    """A command line as what it does: the program, the inputs, the kind of file written, the options."""
    program = Path(command[0]).name.lower()
    tokens = list(command[1:])
    if "ffmpeg" in program and tokens and not tokens[-1].startswith("-"):
        output = tokens.pop()
        kept: list[str] = []
        inputs: list[str] = []
        index = 0
        while index < len(tokens):
            token = tokens[index]
            if token in QUIET:
                index += 1
                continue
            if token in QUIET_WITH_VALUE:
                index += 2
                continue
            if token == "-i":
                inputs.append(Path(tokens[index + 1]).name)
                index += 2
                continue
            kept.append(token)
            index += 1
        return {"program": "ffmpeg", "inputs": tuple(inputs), "writes": Path(output).suffix.lower(), "options": _ffmpeg_options(kept)}
    if "yt-dlp" in program:
        links = tuple(token for token in tokens if token.startswith("http"))
        return {"program": "yt-dlp", "inputs": links, "writes": "", "options": _ytdlp_options(tokens, links)}
    if program == "cmd.exe":
        # cmd /c script and cmd /c call script start a script alike.
        tokens = [token for token in tokens if token.lower() != "call"]
    name = "ffmpeg" if "ffmpeg" in program else program
    return {"program": name, "inputs": (), "writes": "", "options": Counter(units(tokens))}


def as_now(name: str, command: dict[str, Any]) -> dict[str, Any]:
    """A command of the record with what 3.0.0 changes on purpose read into it."""
    options = Counter()
    for unit, count in command["options"].items():
        text = " ".join(unit)
        for wrappers, then, now, _why in REWRITTEN:
            if fnmatch.fnmatchcase(name, wrappers) and re.fullmatch(then, text):
                for item in now:
                    options[unit_of(re.fullmatch(then, text).expand(item))] += count
                break
        else:
            options[unit] += count
    for wrappers, lost, added, _why in ACCEPTED:
        if fnmatch.fnmatchcase(name, wrappers):
            options -= Counter(unit_of(text) for text in lost)
            options += Counter(unit_of(text) for text in added)
    if command["program"] == "yt-dlp":
        options += Counter(unit_of(text) for text, _why in EVERY_YTDLP)
        if not fnmatch.fnmatchcase(name, "yt-playlist-*") and not any(unit[0] == "--batch-file" for unit in options):
            options += Counter(unit_of(text) for text, _why in ONE_LINK_YTDLP)
    return {**command, "options": options}


def _named(rules: list[tuple[str, list[str], str]], name: str, inputs: tuple[str, ...]) -> bool:
    return any(fnmatch.fnmatchcase(name, wrappers) and any(fnmatch.fnmatchcase(item, pattern) for item in inputs for pattern in files)
               for wrappers, files, _why in rules)


def engine_commands(stdout: str) -> list[list[str]]:
    """The command lines the engine would have run: the lines after its "[DRY RUN]" and those of the selftest."""
    found: list[list[str]] = []
    lines = stdout.splitlines()
    for index, line in enumerate(lines):
        text = line.strip()
        if text.startswith("[DRY RUN]") and index + 1 < len(lines):
            found.append(argv_of(lines[index + 1].strip()))
        elif text.startswith("[CMD]") and any(word in text for word in ("-version", "--version", "-filters")):
            found.append(argv_of(text[len("[CMD] "):]))
    return found


@pytest.fixture(scope="module")
def stand(tmp_path_factory: pytest.TempPathFactory) -> Path:
    if not FFMPEG.is_file():
        pytest.skip("no FFmpeg of the program in Tools")
    root = tmp_path_factory.mktemp("wrappers")
    (root / "input").mkdir()
    capture.make_clips(root / "input", FFMPEG)
    return root


def wrapper_env(name: str, stand: Path) -> dict[str, str]:
    # The wrappers read AUDION_*: none of the machine's, but the folders of the journals and reports of the tests.
    env = {key: value for key, value in os.environ.items() if not key.startswith("AUDION_") or key in {"AUDION_LOGS", "AUDION_REPORT"}}
    env.update(AUDION_SOURCE=str(stand / "input"), AUDION_OUTPUT=str(stand / "output"), PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
    for prefix, extra in capture.ENVIRONMENT.items():
        if name.startswith(prefix):
            env.update(extra)
    return env


def run_wrapper(name: str, stand: Path, arguments: list[str] | None = None) -> subprocess.CompletedProcess:
    if arguments is None:
        arguments = capture.ARGUMENTS.get(name, [capture.URL] if name.startswith("yt-") else [])
    return subprocess.run([sys.executable, "-u", str(CLI), "wrapper", name, *arguments, "--dry-run"], capture_output=True,
                          text=True, encoding="utf-8", errors="replace", env=wrapper_env(name, stand), cwd=str(PROJECT), timeout=600)


def record_of(name: str) -> dict[str, Any]:
    rate = RATE.fullmatch(name)
    return RECORD[f"ff-25to23976-{rate.group(1)}"] if rate else RECORD[name]


def differences(name: str, stand: Path) -> list[str]:
    done = run_wrapper(name, stand)
    then, now = [(REFERENCE, "<ROOT>")], [(stand / "input", "<SRC>"), (stand / "output", "<OUT>"), (PROJECT, "<ROOT>")]
    old = [as_now(name, normal([swap(placeholders(token, then)) for token in command])) for command in record_of(name)["commands"]]
    new = [normal([placeholders(token, now) for token in command]) for command in engine_commands(done.stdout)]
    said: list[str] = []
    if done.returncode != EXITS.get(name, (0, ""))[0]:
        said.append(f"exit {done.returncode}: {done.stderr.strip()[-300:]}")
    if name in SELFTESTS:
        return said + [f"not checked now: {program}" for program in sorted({c["program"] for c in old} - {c["program"] for c in new})]
    by_input_new: dict[tuple[str, ...], list[dict[str, Any]]] = {}
    for command in new:
        by_input_new.setdefault(command["inputs"], []).append(command)
    for command in old:
        twins = by_input_new.get(command["inputs"], [])
        if not twins:
            if not _named(PASSED_OVER, name, command["inputs"]):
                said.append(f"not run now: {command['program']} {' '.join(command['inputs'])}")
            continue
        twin = twins.pop(0)
        if twin["writes"] != command["writes"]:
            said.append(f"{' '.join(command['inputs'])}: writes {twin['writes']} instead of {command['writes']}")
        lost = command["options"] - twin["options"]
        added = twin["options"] - command["options"]
        if lost or added:
            said.append(f"{' '.join(command['inputs'])}: lost {sorted(' '.join(unit) for unit in lost)}"
                        f" added {sorted(' '.join(unit) for unit in added)}")
    for leftover in by_input_new.values():
        for command in leftover:
            if not _named(RUN_NOW, name, command["inputs"]):
                said.append(f"run now, not before: {command['program']} {' '.join(command['inputs'])}")
    return said


# Every wrapper, the updater of yt-dlp too: in a dry run it says what it would run and downloads nothing.
WRAPPERS = sorted(RECORD)


def test_the_record_is_whole() -> None:
    assert len(RECORD) == 95
    wrappers = sorted(path.stem for path in (PROJECT / "Scripts").glob("*.cmd"))
    assert wrappers == sorted(RECORD)


def test_every_rule_names_its_reason() -> None:
    for rule in [*REWRITTEN, *ACCEPTED, *EVERY_YTDLP, *ONE_LINK_YTDLP, *PASSED_OVER, *RUN_NOW, *EXITS.values()]:
        assert len(rule[-1]) > 20, rule


def test_the_door_of_a_wrapper_is_the_console_command(stand: Path) -> None:
    """Scripts\\<name>.cmd -> Common\\run-profile.cmd -> media_cli.cmd wrapper: the commands the console command gives,
    and a link with & in it reaches yt-dlp whole."""
    link = "https://example.com/watch?v=a&list=b"
    for name, arguments in (("audio-to-flac", []), ("yt-best-mp4", [link])):
        quoted = " ".join(f'"{item}"' for item in [*arguments, "--dry-run"])
        door = subprocess.run(f'cmd.exe /d /s /c ""{PROJECT / "Scripts" / (name + ".cmd")}" {quoted}"', capture_output=True, text=True,
                              encoding="utf-8", errors="replace", env=wrapper_env(name, stand), timeout=600)
        direct = run_wrapper(name, stand, arguments)
        assert (door.returncode, direct.returncode) == (0, 0), door.stdout[-600:] + door.stderr[-300:]
        assert engine_commands(door.stdout) == engine_commands(direct.stdout) != []
        if arguments:
            assert link in engine_commands(door.stdout)[0]


def test_a_run_without_files_of_its_kind_is_passed_over(tmp_path: Path, stand: Path) -> None:
    """A wrapper of two runs - the sound of videos, then sound files - takes a folder of one kind: the other run is
    passed over. On a folder of neither the last run is refused before it began - its [PREFLIGHT] lines say why - and the
    exit is 2."""
    for kind, names, code in (("sound", ["song.wav"], 0), ("videos", ["clip_h264_aac.mp4"], 0), ("nothing", [], 2)):
        folder = tmp_path / kind / "input"
        folder.mkdir(parents=True)
        for name in names:
            shutil.copy2(stand / "input" / name, folder / name)
        env = {**wrapper_env("audio-to-flac", stand), "AUDION_SOURCE": str(folder), "AUDION_OUTPUT": str(folder.parent / "output")}
        done = subprocess.run([sys.executable, "-u", str(CLI), "wrapper", "audio-to-flac", "--dry-run"], capture_output=True, text=True,
                              encoding="utf-8", errors="replace", env=env, cwd=str(PROJECT), timeout=600)
        assert done.returncode == code, done.stdout[-800:]
        assert done.stdout.count("[SKIP] audio_run: no file of its kind") == 1, kind
        assert len(engine_commands(done.stdout)) == len(names), kind


def test_a_wrapper_is_found_whatever_the_case_of_its_name(stand: Path) -> None:
    """Windows does not tell proresLT.cmd from proreslt.cmd, and the catalog of the launchers writes it in small letters."""
    small, given = run_wrapper("ff-grade-lut-only-proreslt", stand), run_wrapper("ff-grade-lut-only-proresLT", stand)
    assert small.returncode == given.returncode == 0
    assert engine_commands(small.stdout) == engine_commands(given.stdout) != []


@pytest.mark.parametrize("name", WRAPPERS)
def test_a_wrapper_runs_what_it_ran(name: str, stand: Path) -> None:
    found = differences(name, stand)
    assert not found, "\n".join(found)
