r"""Record what the 95 wrappers of Scripts\ had FFmpeg and yt-dlp run, before they go over to the console command.

Until 3.0.0 a wrapper ran its own executor, Scripts\Common\script_runner.py, which built its command lines itself.
From 3.0.0 a wrapper is a door to `media_cli.cmd run`: one engine for the window, the console and the wrappers. The
owner agreed "если это стабильно" - so before the executor goes, every wrapper is run by it here in its dry run,
on a set of short clips this script makes with FFmpeg, and every command line it would run is written down.
tests\test_wrappers.py holds the new wrappers to this record: the same work, and every difference named.

    "<reference>\runtime\python.exe" tests\capture_former_wrappers.py <reference>

The executor that runs is the reference's - the program as it was, 2.6.1 - not the working copy's, which 3.0.0
already changes. A dry run runs nothing; the reference is not written to. The record:
tests\former_wrapper_commands.json. It is taken once and is not written anew.
"""
from __future__ import annotations

import ctypes
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
RECORD = Path(__file__).resolve().parent / "former_wrapper_commands.json"
URL = "https://example.com/watch?v=sample"

PICTURE = "testsrc2=size=640x360:rate=25:duration=2"
TONE = "sine=f=440:d=2:sample_rate=48000"
# The clips: one of each kind a wrapper looks for, small enough that a dry run probes them in a moment.
CLIPS = {
    "clip_h264_aac.mp4": ["-f", "lavfi", "-i", PICTURE, "-f", "lavfi", "-i", TONE, "-ac", "2", "-c:v", "libx264", "-preset", "ultrafast",
                          "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest"],
    "clip_h264_aac.mkv": ["-f", "lavfi", "-i", PICTURE, "-f", "lavfi", "-i", TONE, "-ac", "2", "-c:v", "libx264", "-preset", "ultrafast",
                          "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest"],
    "clip_prores_pcm.mov": ["-f", "lavfi", "-i", PICTURE, "-f", "lavfi", "-i", TONE, "-ac", "2", "-c:v", "prores_ks", "-profile:v", "0",
                            "-c:a", "pcm_s24le", "-shortest"],
    "clip_51_pcm.mov": ["-f", "lavfi", "-i", PICTURE, "-f", "lavfi", "-i", TONE, "-ac", "6", "-c:v", "libx264", "-preset", "ultrafast",
                        "-pix_fmt", "yuv420p", "-c:a", "pcm_s24le", "-shortest"],
    "clip_mpeg2_pcm.mxf": ["-f", "lavfi", "-i", PICTURE, "-f", "lavfi", "-i", TONE, "-c:v", "mpeg2video", "-pix_fmt", "yuv422p",
                           "-c:a", "pcm_s24le", "-shortest"],
    "clip_subs.mp4": ["-f", "lavfi", "-i", PICTURE, "-f", "lavfi", "-i", TONE, "-i", "{srt}", "-map", "0:v", "-map", "1:a", "-map", "2:s",
                      "-ac", "2", "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac", "-c:s", "mov_text",
                      "-shortest"],
    "hdr_hevc10_pq.mkv": ["-f", "lavfi", "-i", PICTURE, "-vf", "format=yuv420p10le", "-c:v", "libx265", "-preset", "ultrafast",
                          "-x265-params", "colorprim=bt2020:transfer=smpte2084:colormatrix=bt2020nc", "-color_primaries", "bt2020",
                          "-color_trc", "smpte2084", "-colorspace", "bt2020nc"],
    "song.wav": ["-f", "lavfi", "-i", TONE, "-ac", "2", "-c:a", "pcm_s24le"],
    "song.flac": ["-f", "lavfi", "-i", "sine=f=440:d=2:sample_rate=44100", "-ac", "2", "-c:a", "flac"],
}
# What a wrapper takes on its command line, and what it reads from the environment, for its dry run.
ARGUMENTS = {"yt-clip-sections": ["*00:00:01-00:00:02", URL]}
ENVIRONMENT = {"ff-trim-": {"AUDION_TRIM_START": "00:00:00,500", "AUDION_TRIM_END": "00:00:01,500",
                            "AUDION_TRIM_FILE": "clip_h264_aac.mp4"}}


def argv_of(line: str) -> list[str]:
    """A command line as Windows splits it - the way list2cmdline joined it."""
    count = ctypes.c_int()
    split = ctypes.windll.shell32.CommandLineToArgvW
    split.restype = ctypes.POINTER(ctypes.c_wchar_p)
    pointer = split(line, ctypes.byref(count))
    try:
        return [pointer[index] for index in range(count.value)]
    finally:
        ctypes.windll.kernel32.LocalFree(pointer)


def make_clips(folder: Path, ffmpeg: Path) -> None:
    srt = folder.parent / "subs.srt"
    srt.write_text("1\n00:00:00,000 --> 00:00:01,000\nF/2.8, ISO 100\n\n2\n00:00:01,000 --> 00:00:02,000\nF/2.8, ISO 200\n", encoding="utf-8")
    for name, arguments in CLIPS.items():
        filled = [str(srt) if item == "{srt}" else item for item in arguments]
        subprocess.run([str(ffmpeg), "-hide_banner", "-loglevel", "error", "-y", *filled, str(folder / name)], check=True, timeout=120)
    (folder / "urls.txt").write_text(URL + "\n", encoding="utf-8")


def placeholders(value: str, stand: Path, root: Path) -> str:
    for path, mark in ((stand / "input", "<SRC>"), (stand / "output", "<OUT>"), (root, "<ROOT>")):
        value = value.replace(str(path), mark)
    return value


def main() -> int:
    import yaml

    reference = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else PROJECT.parent / f"{PROJECT.name} NiceGUI"
    runner = reference / "Scripts" / "Common" / "script_runner.py"
    ffmpeg = reference / "Tools" / "ffmpeg" / "bin" / "ffmpeg.exe"
    names = list(yaml.safe_load((reference / "config" / "script_profiles.yaml").read_text(encoding="utf-8"))["profiles"])
    wrappers = sorted(path.stem for path in (reference / "Scripts").glob("*.cmd"))
    assert sorted(names) == wrappers, "every wrapper has its profile"
    stand = Path(tempfile.mkdtemp(prefix="wrappers-record-"))
    record: dict[str, dict] = {}
    try:
        (stand / "input").mkdir()
        make_clips(stand / "input", ffmpeg)
        for name in wrappers:
            out = stand / "output"
            shutil.rmtree(out, ignore_errors=True)
            out.mkdir()
            env = dict(os.environ, AUDION_SOURCE=str(stand / "input"), AUDION_OUTPUT=str(out), AUDION_DRY_RUN="1",
                       PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
            for prefix, extra in ENVIRONMENT.items():
                if name.startswith(prefix):
                    env.update(extra)
            arguments = ARGUMENTS.get(name, [URL] if name.startswith("yt-") else [])
            done = subprocess.run([sys.executable, str(runner), name, *arguments], capture_output=True, text=True,
                                  encoding="utf-8", errors="replace", env=env, cwd=str(reference), timeout=300)
            lines = done.stdout.splitlines()
            commands = [[placeholders(item, stand, reference) for item in argv_of(line[len("[CMD] "):])] for line in lines if line.startswith("[CMD] ")]
            said = [placeholders(line, stand, reference) for line in lines if not line.startswith("[CMD] ")]
            record[name] = {"exit": done.returncode, "commands": commands, "said": said[:40],
                            "errors": placeholders(done.stderr.strip(), stand, reference)[-600:]}
            print(f"{name:34} exit {done.returncode}  {len(commands)} command(s)")
    finally:
        shutil.rmtree(stand, ignore_errors=True)
    RECORD.write_text(json.dumps(record, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"{len(record)} wrappers -> {RECORD}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
