"""The findings of the audit of 15.10.2026 that lose files or misreport a run, each held by a case:

- F03 --result never replaces a source, and a file that only looks like its draft stays;
- F04 cleanup_project.cmd refuses a folder that is a link and never walks through one;
- F08 a file that failed makes the run a failure, not a green done;
- F09 a run stopped before its first file is a stop, exit code 130;
- F10 two sources of one stem write two files;
- F14 STOP ends a child that says nothing.

The runs make their own short media with the FFmpeg of the program and are skipped where there is none.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

from system_core.core import jobs

PROJECT = Path(__file__).resolve().parent.parent
CLI = PROJECT / "system_core" / "cli.py"
FFMPEG = PROJECT / "Tools" / "ffmpeg" / "bin" / "ffmpeg.exe"
needs_ffmpeg = pytest.mark.skipif(not FFMPEG.is_file(), reason="no FFmpeg of the program in Tools")


def run(*args: str) -> subprocess.CompletedProcess:
    env = dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
    env.pop("AUDION_SOURCE", None)
    env.pop("AUDION_OUTPUT", None)
    return subprocess.run([sys.executable, "-u", str(CLI), *args], capture_output=True, text=True, encoding="utf-8",
                          timeout=300, env=env)


def make(path: Path, *inputs: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run([str(FFMPEG), "-hide_banner", "-loglevel", "error", *inputs, str(path)], check=True, timeout=120)
    return path


def clip(path: Path) -> Path:
    return make(path, "-f", "lavfi", "-i", "testsrc2=size=320x180:rate=25:duration=1", "-f", "lavfi", "-i",
                "sine=frequency=440:duration=1", "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", "-shortest")


def told(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


@needs_ffmpeg
def test_result_never_replaces_a_source(tmp_path: Path) -> None:
    source = clip(tmp_path / "in" / "source.mp4")
    before = source.read_bytes()
    folder = source.parent
    for given, result in ((source, source), (folder, source), (folder, folder / "outcome.json"),
                          (source, tmp_path / "out" / "outcome.txt")):
        done = run("run", "--operation", "probe_source", "--source", str(given), "--result", str(result))
        assert done.returncode == 2, (given, result, done.stdout[-1500:])
    assert source.read_bytes() == before and sorted(path.name for path in folder.iterdir()) == ["source.mp4"]


@needs_ffmpeg
def test_a_file_that_only_looks_like_the_draft_of_the_result_stays(tmp_path: Path) -> None:
    source = clip(tmp_path / "in" / "clip.mp4")
    stranger = tmp_path / "outcome.json.tmp"
    stranger.write_text("someone's", encoding="utf-8")
    done = run("run", "--operation", "probe_source", "--source", str(source), "--result", str(tmp_path / "outcome.json"))
    assert done.returncode == 0 and told(tmp_path / "outcome.json")["outcome"] == "done"
    assert stranger.read_text(encoding="utf-8") == "someone's"
    assert sorted(path.name for path in tmp_path.iterdir()) == ["in", "outcome.json", "outcome.json.tmp"]


@needs_ffmpeg
def test_two_sources_of_one_stem_write_two_files(tmp_path: Path) -> None:
    make(tmp_path / "in" / "take.flac", "-f", "lavfi", "-i", "sine=frequency=880:duration=1")
    make(tmp_path / "in" / "take.wav", "-f", "lavfi", "-i", "sine=frequency=440:duration=1")
    call = ["run", "--operation", "audio_run", "--set", "audio_workflow=audio_files", "--set", "audio_profile=m4a384",
            "--source", str(tmp_path / "in"), "--target", str(tmp_path / "out"), "--set", "overwrite=false"]
    done = run(*call, "--result", str(tmp_path / "first.json"))
    assert done.returncode == 0 and told(tmp_path / "first.json")["data"]["processed"] == 2
    written = sorted(path.name for path in (tmp_path / "out").rglob("*.m4a"))
    assert written == ["take.m4a", "take_wav.m4a"], written
    again = run(*call, "--result", str(tmp_path / "again.json"))
    data = told(tmp_path / "again.json")["data"]
    assert again.returncode == 0 and data["processed"] == 0 and data["skipped"] == 2


@needs_ffmpeg
def test_a_file_that_failed_is_a_failure(tmp_path: Path) -> None:
    clip(tmp_path / "in" / "clip.mov")
    call = ["run", "--operation", "remux_run", "--set", "remux_stream_mode=video_audio", "--set", "remux_target_format=mkv",
            "--source", str(tmp_path / "in"), "--target", str(tmp_path / "out")]
    assert run(*call).returncode == 0
    written = next((tmp_path / "out").rglob("clip.mkv"))
    written.unlink()
    written.mkdir()
    done = run(*call, "--set", "overwrite=true", "--result", str(tmp_path / "told.json"))
    result = told(tmp_path / "told.json")
    assert done.returncode == 1 and result["outcome"] == "failed" and result["data"]["failed"] == 1


@needs_ffmpeg
@pytest.mark.parametrize("operation", ["storage_run", "audio_run", "remux_run", "fps_run", "grading_run"])
def test_a_stop_before_the_first_file_is_a_stop(operation: str, tmp_path: Path) -> None:
    clip(tmp_path / "in" / "clip.mov")
    stop = tmp_path / "stop.flag"
    stop.write_text("", encoding="utf-8")
    extra = ["--set", "grading_profile=hdr_hable_x264"] if operation == "grading_run" else []
    done = run("run", "--operation", operation, *extra, "--source", str(tmp_path / "in"), "--target", str(tmp_path / "out"),
               "--cancel-file", str(stop), "--result", str(tmp_path / "told.json"))
    result = told(tmp_path / "told.json")
    assert done.returncode == 130 and result["outcome"] == "stopped", done.stdout[-1500:]
    assert not any((tmp_path / "out").rglob("*.*")) if (tmp_path / "out").exists() else True


class QuietContext:
    def __init__(self, root: Path, stop_after: float) -> None:
        self.paths = type("Paths", (), {"root": root})()
        self.commands: list[dict] = []
        self.stop_at = time.monotonic() + stop_after

    def log(self, text: str) -> None:
        pass

    def progress(self, value: float) -> None:
        pass

    def cancelled(self) -> bool:
        return time.monotonic() >= self.stop_at


def test_stop_ends_a_child_that_says_nothing(tmp_path: Path) -> None:
    started = time.monotonic()
    with pytest.raises(jobs.OperationCancelled):
        jobs.run_process(QuietContext(tmp_path, 0.3), [sys.executable, "-c", "import time; time.sleep(30)"])
    assert time.monotonic() - started < 10


@pytest.mark.skipif(os.name != "nt", reason="cleanup_project.cmd is a Windows script")
def test_cleanup_refuses_a_folder_that_is_a_link(tmp_path: Path) -> None:
    mini, outside, outside_too = tmp_path / "mini", tmp_path / "outside", tmp_path / "outside_too"
    for folder in (mini / "system_core", mini / "config", mini / "output", outside / "originals", outside_too / "deep"):
        folder.mkdir(parents=True)
    (mini / "system_core" / "cli.py").write_text("# marker", encoding="utf-8")
    (mini / "config" / "tool_manifest.yaml").write_text("tool: {}", encoding="utf-8")
    (outside / "top.txt").write_text("owner", encoding="utf-8")
    (outside / "originals" / "owner.txt").write_text("owner", encoding="utf-8")
    (outside_too / "deep" / "keep.txt").write_text("owner", encoding="utf-8")
    (mini / "output" / "result.mp4").write_text("a result", encoding="utf-8")
    shutil.copy2(PROJECT / "cleanup_project.cmd", mini / "cleanup_project.cmd")
    subprocess.run(["cmd", "/c", "mklink", "/J", str(mini / "input"), str(outside)], check=True, capture_output=True)
    subprocess.run(["cmd", "/c", "mklink", "/J", str(mini / "output" / "linked"), str(outside_too)], check=True,
                   capture_output=True)
    try:
        done = subprocess.run(["cmd", "/d", "/c", str(mini / "cleanup_project.cmd"), "/Y"], capture_output=True, text=True,
                              env=dict(os.environ, AUDION_NO_PAUSE="1"), timeout=120)
        assert done.returncode != 0 and "is a link to another place" in done.stdout
        assert (outside / "top.txt").is_file() and (outside / "originals" / "owner.txt").is_file()
        assert (outside_too / "deep" / "keep.txt").is_file()
        assert not (mini / "output" / "linked").exists() and not (mini / "output" / "result.mp4").exists()
    finally:
        for link in (mini / "input", mini / "output" / "linked"):
            if os.path.lexists(link):
                os.rmdir(link)
