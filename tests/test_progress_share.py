"""The share of an operation done: by the service's word between its units of work, by FFmpeg's own progress inside the
unit at work - not by the clock, which kept a one-file encode near 8 % from its start to its end. And `--dry-run` sets
only the dry-run field the operation has.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from system_core.core.jobs import JobContext

PROJECT = Path(__file__).resolve().parent.parent
CLI = PROJECT / "system_core" / "cli.py"
FFMPEG = PROJECT / "Tools" / "ffmpeg" / "bin" / "ffmpeg.exe"
CONTROL = "::media::"


def context_telling(told: list[float]) -> JobContext:
    return JobContext(paths=None, operation=None, log_file=Path(os.devnull), report_dir=Path(os.devnull),  # type: ignore[arg-type]
                      progress_callback=told.append)


def test_inside_a_unit_the_share_follows_ffmpeg() -> None:
    told: list[float] = []
    context = context_telling(told)
    context.units(4)
    context.progress(0.25)
    context.progress_inside(0.5)
    context.progress_inside(1.0)
    assert told == [0.25, 0.375, 0.5]


def test_without_units_nothing_is_said_inside() -> None:
    told: list[float] = []
    context = context_telling(told)
    context.progress_inside(0.5)
    context.progress_guess(0.3)
    context.progress_inside(0.9)
    assert told == [0.3]
    assert context.told_share == 0.0, "a guess of the clock is no base for the next unit"


def run(*args: str) -> subprocess.CompletedProcess:
    env = dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
    env.pop("AUDION_SOURCE", None)
    env.pop("AUDION_OUTPUT", None)
    return subprocess.run([sys.executable, "-u", str(CLI), *args], capture_output=True, text=True, encoding="utf-8",
                          timeout=300, env=env)


def test_a_one_file_encode_moves_the_share_while_it_runs(tmp_path: Path) -> None:
    if not FFMPEG.is_file():
        pytest.skip("no FFmpeg of the program in Tools")
    source = tmp_path / "in"
    source.mkdir()
    subprocess.run([str(FFMPEG), "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc2=size=640x360:rate=25:duration=20",
                    "-c:v", "libx264", "-preset", "ultrafast", str(source / "clip.mp4")], check=True, timeout=120)
    done = run("run", "--operation", "storage_run", "--set", "storage_profile=x264_crf14", "--set", "cpu_encoder_preset=veryslow",
               "--source", str(source), "--target", str(tmp_path / "out"))
    assert done.returncode == 0, done.stdout[-3000:]
    shares = [json.loads(line[len(CONTROL):])["progress"] for line in done.stdout.splitlines()
              if line.startswith(CONTROL) and '"progress"' in line]
    assert shares == sorted(shares), "the share went back"
    inside = [share for share in shares if 0.1 < share < 0.95]
    assert inside, f"the share did not move inside the file: {shares}"


@pytest.mark.parametrize(("operation", "own", "other"), [("editing_run", "dry_run", "youtube_dry_run"),
                                                         ("youtube_run", "youtube_dry_run", "dry_run")])
def test_a_dry_run_sets_only_its_own_field(operation: str, own: str, other: str, tmp_path: Path) -> None:
    extra = ["--set", "youtube_url=https://example.com/v"] if operation == "youtube_run" else []
    source = tmp_path / "in"
    source.mkdir()
    (source / "clip.mov").write_bytes(b"")
    done = run("run", "--operation", operation, *extra, "--dry-run", "--source", str(source), "--target", str(tmp_path / "out"),
               "--result", str(tmp_path / "told.json"))
    parameters = json.loads((tmp_path / "told.json").read_text(encoding="utf-8"))["parameters"]
    assert parameters.get(own) is True, done.stdout[-2000:]
    assert other not in parameters
