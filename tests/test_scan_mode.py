"""The scan of an interlaced source (field `scan_mode` of EDITING, STORAGE, DELIVERY and COLOR): Keep fields keeps them and
their order, Progressive makes a whole frame of each frame by bwdif, Progressive x2 a frame of each field with the rate
doubled; the folder of the settings tells a progressive result apart, and a progressive source is not touched.
The runs make their own short clips with the FFmpeg of the program and are skipped where there is none.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

PROJECT = Path(__file__).resolve().parent.parent
CLI = PROJECT / "system_core" / "cli.py"
FFMPEG = PROJECT / "Tools" / "ffmpeg" / "bin" / "ffmpeg.exe"
FFPROBE = PROJECT / "Tools" / "ffmpeg" / "bin" / "ffprobe.exe"
pytestmark = pytest.mark.skipif(not FFMPEG.is_file(), reason="no FFmpeg of the program in Tools")


def clip(path: Path, interlaced: bool) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = ["-flags", "+ildct+ilme", "-field_order", "tt"] if interlaced else []
    subprocess.run([str(FFMPEG), "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i",
                    "testsrc2=size=320x180:rate=25:duration=1", "-c:v", "libx264", *fields, str(path)], check=True, timeout=120)
    return path


def encode(source: Path, target: Path, mode: str) -> tuple[str, str, int]:
    env = dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
    env.pop("AUDION_SOURCE", None)
    env.pop("AUDION_OUTPUT", None)
    chosen = ["--set", f"scan_mode={mode}"] if mode else []
    done = subprocess.run([sys.executable, "-u", str(CLI), "run", "--operation", "storage_run", "--set", "cpu_encoder_preset=fast",
                           *chosen, "--source", str(source), "--target", str(target)],
                          capture_output=True, text=True, encoding="utf-8", timeout=300, env=env)
    assert done.returncode == 0, done.stdout[-2000:]
    written = next(target.rglob("*.mp4"))
    told = subprocess.run([str(FFPROBE), "-v", "error", "-select_streams", "v:0", "-count_frames", "-show_entries",
                           "stream=field_order,nb_read_frames", "-of", "csv=p=0", str(written)],
                          capture_output=True, text=True).stdout.strip().split(",")
    return written.parent.name, told[0], int(told[1])


@pytest.mark.parametrize(("mode", "folder", "order", "frames"), [
    ("keep", "x264_crf14_fast", "tt", 25),
    ("progressive", "x264_crf14_fast_progressive", "progressive", 25),
    ("double", "x264_crf14_fast_progressive_2x", "progressive", 50),
])
def test_an_interlaced_source_in_each_mode(mode: str, folder: str, order: str, frames: int, tmp_path: Path) -> None:
    clip(tmp_path / "in" / "field.mp4", interlaced=True)
    assert encode(tmp_path / "in", tmp_path / "out", mode) == (folder, order, frames)


def test_progressive_twice_the_rate_by_default(tmp_path: Path) -> None:
    clip(tmp_path / "in" / "field.mp4", interlaced=True)
    assert encode(tmp_path / "in", tmp_path / "out", "") == ("x264_crf14_fast_progressive_2x", "progressive", 50)


def test_a_progressive_source_is_not_touched(tmp_path: Path) -> None:
    clip(tmp_path / "in" / "frame.mp4", interlaced=False)
    assert encode(tmp_path / "in", tmp_path / "out", "double") == ("x264_crf14_fast", "progressive", 25)
