"""A file of FFmpeg takes its name only whole (core\\jobs.py: _writing_output, run_process).

STOP in the middle of an encode left a half-written file in the Target (WINDOW_INVENTORY, 11). An FFmpeg command now writes
"name.writing-<run>.ext" - a name no file has - and the file takes its own name when FFmpeg ends well; a stop or a failure
leaves neither, and a file that only looks like a draft is not touched. A file FFmpeg is not told to overwrite, a pattern of
many files and a pipe keep the command as it is; a "%" that is no number pattern does not. A command whose output is one
of its inputs is refused before FFmpeg starts.
"""
from __future__ import annotations

import os
import re
from pathlib import Path

import pytest

from system_core.core import jobs

PROJECT = Path(__file__).resolve().parent.parent
FFMPEG = PROJECT / "Tools" / "ffmpeg" / "bin" / "ffmpeg.exe"
needs_ffmpeg = pytest.mark.skipif(not FFMPEG.is_file(), reason="FFmpeg of the program is not installed")
DRAFT = re.compile(r"^.+\.writing-\d+-[0-9a-f]{6}\.mp4$")


class Context:
    """What run_process asks of a job: its log, its progress, whether STOP was pressed."""

    def __init__(self, root: Path, stop_when_written: bool = False) -> None:
        self.paths = type("Paths", (), {"root": root})()
        self.commands: list[dict] = []
        self.said: list[str] = []
        self.root = root
        self.stop_when_written = stop_when_written
        self.seen_writing = False

    def log(self, text: str) -> None:
        self.said.append(text)

    def progress(self, value: float) -> None:
        pass

    def cancelled(self) -> bool:
        """STOP, pressed once FFmpeg has written a part of the file - a half-written file is on the disk."""
        if not self.stop_when_written:
            return False
        self.seen_writing = self.seen_writing or any(DRAFT.match(path.name) and path.stat().st_size > 0
                                                     for path in self.root.iterdir())
        return self.seen_writing


def encode(output: Path, seconds: int, *more: str) -> list[str]:
    return [str(FFMPEG), "-hide_banner", "-nostdin", *more, "-f", "lavfi", "-i", f"testsrc2=size=640x360:rate=25:duration={seconds}",
            "-c:v", "libx264", "-preset", "veryslow", str(output)]


def test_what_keeps_its_command(tmp_path: Path) -> None:
    there = tmp_path / "there.mp4"
    there.write_bytes(b"x")
    segments = [str(FFMPEG), "-f", "lavfi", "-i", "testsrc2=duration=1", "-f", "segment", str(tmp_path / "part%03d.mp4")]
    for command in (encode(there, 1, "-n"), encode(there, 1), segments,
                    [str(FFMPEG), "-i", "a.wav", "-f", "null", "-"], ["yt-dlp", "-o", str(tmp_path / "x.mp4")]):
        assert jobs._writing_output(command, tmp_path)[1:] == (None, None), command
    told, final, writing = jobs._writing_output(encode(there, 1, "-y"), tmp_path)
    assert final == there and writing.parent == tmp_path and DRAFT.match(writing.name) and told[-1] == str(writing)
    # A "%" that is no number pattern names an ordinary file: it is written through a draft too.
    for name in ("take%percent.mp4", "50% grey.mp4", "x%y.mkv"):
        assert jobs._writing_output(encode(tmp_path / name, 1), tmp_path)[1] == tmp_path / name, name
    assert jobs._writing_output(encode(tmp_path / "frame%04d.png", 1), tmp_path)[1:] == (None, None)


@needs_ffmpeg
def test_a_whole_file_takes_its_name(tmp_path: Path) -> None:
    output = tmp_path / "clip.mp4"
    result = jobs.run_process(Context(tmp_path), encode(output, 1, "-n"))
    assert result.exit_code == 0 and output.stat().st_size > 0
    assert sorted(path.name for path in tmp_path.iterdir()) == ["clip.mp4"]


@needs_ffmpeg
def test_stop_leaves_no_half_written_file(tmp_path: Path) -> None:
    output = tmp_path / "long.mp4"
    context = Context(tmp_path, stop_when_written=True)
    # FFmpeg says its progress every 0.1 s: the run is asked about STOP that often.
    with pytest.raises(jobs.OperationCancelled):
        jobs.run_process(context, encode(output, 120, "-n", "-stats_period", "0.1"))
    assert context.seen_writing, "FFmpeg was stopped before it had written anything: the test proves nothing"
    assert list(tmp_path.iterdir()) == []
    assert any(line.startswith("[CANCEL]") for line in context.said)


@needs_ffmpeg
def test_a_folder_in_the_place_of_the_file_is_a_failed_command(tmp_path: Path) -> None:
    """FFmpeg writes the whole file beside it; the name it cannot take is a failed run, as when FFmpeg could not write."""
    output = tmp_path / "clip.mp4"
    output.mkdir()
    context = Context(tmp_path)
    with pytest.raises(RuntimeError, match="could not be written"):
        jobs.run_process(context, encode(output, 1, "-y"))
    assert sorted(path.name for path in tmp_path.iterdir()) == ["clip.mp4"] and output.is_dir()
    assert jobs.run_process(context, encode(output, 1, "-y"), check=False).exit_code == 1


@needs_ffmpeg
def test_a_failure_leaves_no_half_written_file(tmp_path: Path) -> None:
    output = tmp_path / "broken.mp4"
    command = [str(FFMPEG), "-hide_banner", "-nostdin", "-n", "-i", str(tmp_path / "missing.mov"), str(output)]
    with pytest.raises(RuntimeError, match="exit code"):
        jobs.run_process(Context(tmp_path), command)
    assert list(tmp_path.iterdir()) == []


@needs_ffmpeg
def test_a_file_that_only_looks_like_a_draft_stays(tmp_path: Path) -> None:
    """Audit F05: clip.writing.mp4 lying in the Target is someone's file, not this run's draft."""
    stranger = tmp_path / "clip.writing.mp4"
    stranger.write_bytes(b"someone's file")
    result = jobs.run_process(Context(tmp_path), encode(tmp_path / "clip.mp4", 1, "-n"))
    assert result.exit_code == 0 and stranger.read_bytes() == b"someone's file"
    assert sorted(path.name for path in tmp_path.iterdir()) == ["clip.mp4", "clip.writing.mp4"]


@needs_ffmpeg
def test_stop_of_a_name_with_percent_leaves_nothing(tmp_path: Path) -> None:
    """Audit F06: a "%" in an ordinary name switched the draft off, and STOP left a headless MP4 under the final name."""
    context = Context(tmp_path, stop_when_written=True)
    with pytest.raises(jobs.OperationCancelled):
        jobs.run_process(context, encode(tmp_path / "take%percent.mp4", 120, "-n", "-stats_period", "0.1"))
    assert context.seen_writing and list(tmp_path.iterdir()) == []


@needs_ffmpeg
@pytest.mark.parametrize("alias", ["same", "hardlink"])
def test_an_output_over_its_input_is_refused(alias: str, tmp_path: Path) -> None:
    """Audit F02: the result named as the source - by its path or by a hard link - is refused before FFmpeg starts."""
    source = tmp_path / "clip.mp4"
    assert jobs.run_process(Context(tmp_path), encode(source, 1)).exit_code == 0
    before = source.read_bytes()
    output = source
    if alias == "hardlink":
        output = tmp_path / "other.mp4"
        os.link(source, output)
    command = [str(FFMPEG), "-hide_banner", "-nostdin", "-y", "-i", str(source), "-c:v", "libx264", str(output)]
    with pytest.raises(RuntimeError, match="its own source"):
        jobs.run_process(Context(tmp_path), command)
    assert source.read_bytes() == before
