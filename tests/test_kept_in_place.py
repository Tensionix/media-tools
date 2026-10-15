"""A second run into the same Target with Overwrite off writes nothing and says so: the file already there is passed by
before FFmpeg is asked, counted in `skipped`, not in `processed`, and stays as it was. FFmpeg itself answers `-n` on it
with "already exists. Exiting." and exit code 0 - a run that wrote nothing read as done.

And Profile Doctor knows the wrappers of the cut (kind: trim).

The runs make their own short clip with the FFmpeg of the program and are skipped where there is none.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from system_core.services import media_service

PROJECT = Path(__file__).resolve().parent.parent
CLI = PROJECT / "system_core" / "cli.py"
FFMPEG = PROJECT / "Tools" / "ffmpeg" / "bin" / "ffmpeg.exe"
SAID = "already exists and Overwrite is off"

# Every operation that hands FFmpeg `-n`, with values that make it write one file of the clip.
RUNS = {
    "storage": ["--operation", "storage_run", "--set", "storage_profile=x264_crf14", "--set", "cpu_encoder_preset=fast"],
    "package": ["--operation", "remux_run", "--set", "remux_stream_mode=video_audio", "--set", "remux_target_format=mov"],
    "subtitles": ["--operation", "subtitles_extract"],
    "sound_out": ["--operation", "audio_run", "--set", "audio_profile=wav_24_48"],
    "sound_in_video": ["--operation", "audio_run", "--set", "audio_profile=video_aac384_48_soxr"],
    "frame_rate": ["--operation", "fps_run", "--set", "fps_mode=conform", "--set", "fps_target=24000/1001"],
    "colour": ["--operation", "grading_run", "--set", "grading_profile=hdr_hable_x264"],
}


def run(*args: str, timeout: float = 300) -> subprocess.CompletedProcess:
    env = dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
    env.pop("AUDION_SOURCE", None)
    env.pop("AUDION_OUTPUT", None)
    return subprocess.run([sys.executable, "-u", str(CLI), *args], capture_output=True, text=True, encoding="utf-8",
                          timeout=timeout, env=env)


@pytest.fixture(scope="module")
def clip(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A two-second MKV with a picture, a sound and a subtitle stream - every operation above finds its work in it."""
    if not FFMPEG.is_file():
        pytest.skip("no FFmpeg of the program in Tools")
    folder = tmp_path_factory.mktemp("kept") / "in"
    folder.mkdir()
    srt = folder.parent / "line.srt"
    srt.write_text("1\n00:00:00,200 --> 00:00:01,500\nA line\n", encoding="utf-8")
    subprocess.run([str(FFMPEG), "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc2=size=320x180:rate=25:duration=2",
                    "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=2", "-i", str(srt),
                    "-map", "0:v", "-map", "1:a", "-map", "2:s", "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac",
                    "-c:s", "srt", "-shortest", str(folder / "clip.mkv")], check=True, timeout=120)
    return folder


def files_of(folder: Path) -> dict[str, tuple[int, int]]:
    return {str(path.relative_to(folder)): (path.stat().st_size, path.stat().st_mtime_ns)
            for path in folder.rglob("*") if path.is_file()}


@pytest.mark.parametrize("name", sorted(RUNS))
def test_a_second_run_passes_by_what_is_there(name: str, clip: Path, tmp_path: Path) -> None:
    target = tmp_path / "out"
    call = [*RUNS[name], "--source", str(clip), "--target", str(target), "--set", "overwrite=false"]

    first = run("run", *call, "--result", str(tmp_path / "first.json"))
    told = json.loads((tmp_path / "first.json").read_text(encoding="utf-8"))
    assert first.returncode == 0, first.stdout[-3000:]
    assert told["data"]["processed"] >= 1 and told["data"].get("skipped", 0) == 0, told["data"]
    written = files_of(target)
    assert written, "the first run wrote nothing"

    second = run("run", *call, "--result", str(tmp_path / "second.json"))
    told = json.loads((tmp_path / "second.json").read_text(encoding="utf-8"))
    assert second.returncode == 0, second.stdout[-3000:]
    assert told["outcome"] == "done"
    assert told["data"]["processed"] == 0, told["data"]
    assert told["data"]["skipped"] >= 1, told["data"]
    assert SAID in second.stdout
    assert "already exists. Exiting." not in second.stdout, "FFmpeg was asked anyway"
    assert files_of(target) == written, "a file of the first run was touched"


def test_overwrite_on_writes_again(clip: Path, tmp_path: Path) -> None:
    target = tmp_path / "out"
    call = [*RUNS["package"], "--source", str(clip), "--target", str(target)]
    assert run("run", *call, "--set", "overwrite=false").returncode == 0
    again = run("run", *call, "--set", "overwrite=true", "--result", str(tmp_path / "again.json"))
    told = json.loads((tmp_path / "again.json").read_text(encoding="utf-8"))
    assert again.returncode == 0 and told["data"]["processed"] == 1 and told["data"].get("skipped", 0) == 0
    assert SAID not in again.stdout


def test_profile_doctor_knows_the_wrappers_of_the_cut() -> None:
    for pattern in sorted(media_service.TRIM_WRAPPER_PATTERNS):
        assert media_service._validate_script_profile(f"ff-trim-{pattern}", {"kind": "trim", "pattern": pattern}) == []
    told = media_service._validate_script_profile("ff-trim-odd", {"kind": "trim", "pattern": "sideways"})
    assert [item["level"] for item in told] == ["ERROR"]
    told = media_service._validate_script_profile("ff-trim-bare", {"kind": "trim"})
    assert [item["level"] for item in told] == ["ERROR"]


def test_profile_doctor_finds_no_error_in_the_program(tmp_path: Path) -> None:
    done = run("run", "--operation", "profile_doctor", "--result", str(tmp_path / "doctor.json"))
    assert done.returncode == 0, done.stdout[-3000:]
    assert "[ERROR]" not in done.stdout, [line for line in done.stdout.splitlines() if "[ERROR]" in line]
