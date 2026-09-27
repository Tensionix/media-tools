"""Whole trim runs on real files, through the same executor the panel uses.

Each case here was a defect found by the 2.6.0 audit and reproduced on real
FFmpeg before it was fixed:

- a take with subtitles did not trim at all into MP4 - "Error selecting an
  encoder" - because the subtitle stream was mapped without a codec;
- then, with the packets copied, the lines came out wrong at every boundary:
  a line across OUT vanished, and the "Cut it out" join made one line a
  microsecond long and moved the next a second early (re-audit, TRIM-5). The
  tests read the lines back - text, start and end - not merely the track;
- a failed, refused or cancelled run was reported as done, with a green status;
- a cancel before a piece had started removed an older result under its name,
  with Overwrite off.

FFmpeg is a payload under `Tools\\`, absent from a fresh clone; without it these
tests are skipped rather than failed.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from system_core.core.jobs import execute_operation, hidden_subprocess_kwargs
from system_core.core.manifest import Operation
from system_core.core.trim_contract import parse_srt
from system_core.core.paths import ensure_project_dirs, get_project_paths

PROJECT = Path(__file__).resolve().parents[1]
FFMPEG_BIN = PROJECT / "Tools" / "ffmpeg" / "bin"
FFMPEG = FFMPEG_BIN / "ffmpeg.exe"
FFPROBE = FFMPEG_BIN / "ffprobe.exe"

pytestmark = pytest.mark.skipif(not FFMPEG.exists(), reason="FFmpeg is not installed under Tools")

# Three lines: one inside the head, one inside the piece "Cut it out" removes,
# and one running across the OUT of "Keep it" - the case the re-audit caught.
CAPTIONS = (
    "1\n00:00:00,500 --> 00:00:01,500\nBEFORE\n\n"
    "2\n00:00:02,500 --> 00:00:03,500\nINSIDE\n\n"
    "3\n00:00:05,000 --> 00:00:07,500\nAFTER\n"
)


def run(command: list[str]) -> bytes:
    completed = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, **hidden_subprocess_kwargs())
    assert completed.returncode == 0, completed.stderr.decode("utf-8", errors="replace")
    return completed.stdout


def streams(path: Path) -> list[str]:
    data = json.loads(run([str(FFPROBE), "-v", "error", "-show_entries", "stream=codec_type,codec_name", "-of", "json", str(path)]))
    return [f"{item['codec_type']}:{item.get('codec_name', '')}" for item in data["streams"]]


@pytest.fixture(scope="module")
def fixtures(tmp_path_factory) -> Path:
    folder = tmp_path_factory.mktemp("trim_fixtures")
    (folder / "captions.srt").write_text(CAPTIONS, encoding="utf-8")
    picture = ["-f", "lavfi", "-i", "testsrc2=size=160x90:rate=25:duration=8"]
    sound = ["-f", "lavfi", "-i", "sine=frequency=800:sample_rate=48000:duration=8"]
    common = ["-map", "0:v", "-map", "1:a", "-map", "2:s", "-c:v", "libx264", "-preset", "ultrafast", "-g", "25", "-sc_threshold", "0"]
    run([str(FFMPEG), "-v", "error", "-y", *picture, *sound, "-i", str(folder / "captions.srt"), *common,
         "-c:a", "aac", "-c:s", "mov_text", str(folder / "take.mp4")])
    run([str(FFMPEG), "-v", "error", "-y", *picture, *sound, "-i", str(folder / "captions.srt"), *common,
         "-c:a", "aac", "-c:s", "srt", str(folder / "take.mkv")])
    run([str(FFMPEG), "-v", "error", "-y", "-i", str(folder / "take.mp4"), "-map", "0:v", "-map", "0:a", "-c", "copy",
         str(folder / "plain.mp4")])
    return folder


def trim(tmp_path: Path, fixtures: Path, name: str, monkeypatch, *, cancel=None, prepare=None, **params):
    monkeypatch.setenv("PATH", str(FFMPEG_BIN) + os.pathsep + os.environ.get("PATH", ""))
    paths = get_project_paths(tmp_path)
    ensure_project_dirs(paths)
    shutil.copy2(fixtures / name, paths.input / name)
    if prepare:
        prepare(paths)
    operation = Operation(
        "trim_run", "Trim", "", "system_core.services.media_service:trim_media",
        parameters={"trim_file": name, "overwrite": True, **params},
    )
    result = execute_operation(paths, operation, cancel_callback=cancel)
    return paths, result


def lines(path: Path) -> list[tuple[float, float, str]]:
    """The lines a player shows, read back out of the result - text and time, not merely a track."""
    text = run([str(FFMPEG), "-v", "error", "-i", str(path), "-map", "0:s:0", "-c:s", "srt", "-f", "srt", "-"])
    return [(cue.start, cue.end, cue.text) for cue in parse_srt(text.decode("utf-8", errors="replace"))]


def assert_lines(path: Path, expected: list[tuple[float, float, str]]) -> None:
    got = lines(path)
    assert [text for _start, _end, text in got] == [text for _start, _end, text in expected], got
    for (start, end, _text), (want_start, want_end, _want) in zip(got, expected):
        assert start == pytest.approx(want_start, abs=0.03) and end == pytest.approx(want_end, abs=0.03), got


def test_a_kept_piece_keeps_the_part_of_a_line_across_out(tmp_path, fixtures, monkeypatch) -> None:
    """Re-audit, scenario B: AFTER at 5.0-7.5 s vanished from a piece kept to 7 s."""
    paths, result = trim(tmp_path, fixtures, "take.mp4", monkeypatch, trim_action="keep", trim_start="0", trim_end="7")
    assert result.ok, result.message
    target = paths.output / "Trim" / "take.mp4"
    assert "subtitle:mov_text" in streams(target)
    assert_lines(target, [(0.5, 1.5, "BEFORE"), (2.5, 3.5, "INSIDE"), (5.0, 7.0, "AFTER")])


def test_lines_follow_the_keyframe_the_piece_starts_on(tmp_path, fixtures, monkeypatch) -> None:
    """IN at 1.2 s lands on the keyframe at 1.0 s: the picture starts there, and so do the lines."""
    paths, result = trim(tmp_path, fixtures, "take.mp4", monkeypatch, trim_action="keep", trim_start="1.2", trim_end="7")
    assert result.ok, result.message
    assert_lines(paths.output / "Trim" / "take.mp4", [(0.0, 0.5, "BEFORE"), (1.5, 2.5, "INSIDE"), (4.0, 6.0, "AFTER")])


def test_cutting_a_piece_out_lays_the_lines_onto_the_join(tmp_path, fixtures, monkeypatch) -> None:
    """Re-audit, scenario A: BEFORE came out a microsecond long, AFTER a second early."""
    paths, result = trim(tmp_path, fixtures, "take.mp4", monkeypatch, trim_action="cut", trim_start="2", trim_end="4")
    assert result.ok, result.message
    # INSIDE went with the removed piece; AFTER moved two seconds earlier with the tail.
    assert_lines(paths.output / "Trim" / "take.mp4", [(0.5, 1.5, "BEFORE"), (3.0, 5.5, "AFTER")])


def test_split_parts_share_the_line_across_the_joint(tmp_path, fixtures, monkeypatch) -> None:
    paths, result = trim(tmp_path, fixtures, "take.mp4", monkeypatch, trim_action="split", trim_points=["3"])
    assert result.ok, result.message
    assert_lines(paths.output / "Trim" / "take_part1.mp4", [(0.5, 1.5, "BEFORE"), (2.5, 3.0, "INSIDE")])
    assert_lines(paths.output / "Trim" / "take_part2.mp4", [(0.0, 0.5, "INSIDE"), (2.0, 4.5, "AFTER")])


def test_srt_from_matroska_is_rewritten_for_mp4(tmp_path, fixtures, monkeypatch) -> None:
    """MP4 refuses SubRip as it is; the words go over as mov_text, on time."""
    paths, result = trim(
        tmp_path, fixtures, "take.mkv", monkeypatch, trim_action="keep", trim_start="0", trim_end="7", trim_container="mp4"
    )
    assert result.ok, result.message
    target = paths.output / "Trim" / "take.mp4"
    assert "subtitle:mov_text" in streams(target)
    assert_lines(target, [(0.5, 1.5, "BEFORE"), (2.5, 3.5, "INSIDE"), (5.0, 7.0, "AFTER")])


def test_the_rebuilt_lines_do_not_outlive_the_run(tmp_path, fixtures, monkeypatch) -> None:
    paths, result = trim(tmp_path, fixtures, "take.mp4", monkeypatch, trim_action="cut", trim_start="2", trim_end="4")
    assert result.ok, result.message
    assert not (paths.workspace / "trim_subtitles").exists()


def test_refused_points_are_not_reported_as_done(tmp_path, fixtures, monkeypatch) -> None:
    _paths, result = trim(tmp_path, fixtures, "plain.mp4", monkeypatch, trim_action="keep", trim_start="6", trim_end="2")
    assert not result.ok
    assert result.data["refused"] == 1


def test_a_failed_write_is_not_reported_as_done(tmp_path, fixtures, monkeypatch) -> None:
    """A folder in place of the result makes the real FFmpeg fail; nothing is mocked."""

    def block(paths) -> None:
        (paths.output / "Trim" / "plain.mp4").mkdir(parents=True)

    _paths, result = trim(tmp_path, fixtures, "plain.mp4", monkeypatch, prepare=block, trim_action="keep", trim_end="3")
    assert not result.ok
    assert result.data["failed"] == 1


def test_a_cancel_before_a_piece_starts_leaves_an_older_file_alone(tmp_path, fixtures, monkeypatch) -> None:
    """The older file is a half-written MP4 - exactly what the cleanup removes - and Overwrite is off."""
    older: dict[str, int] = {}

    def half_written(paths) -> None:
        target = paths.output / "Trim" / "plain.mp4"
        target.parent.mkdir(parents=True, exist_ok=True)
        payload = (fixtures / "plain.mp4").read_bytes()
        target.write_bytes(payload[: len(payload) // 2])
        older["size"] = target.stat().st_size

    paths, result = trim(
        tmp_path, fixtures, "plain.mp4", monkeypatch,
        cancel=lambda: True, prepare=half_written, trim_action="keep", trim_end="3", overwrite=False,
    )
    assert not result.ok
    assert result.data["cancelled"] is True
    target = paths.output / "Trim" / "plain.mp4"
    assert target.exists() and target.stat().st_size == older["size"]


def test_a_kept_result_with_overwrite_off_is_not_an_error(tmp_path, fixtures, monkeypatch) -> None:
    """Keeping what is there is what Overwrite off asks for: skipped, and still a success."""

    def existing(paths) -> None:
        target = paths.output / "Trim" / "plain.mp4"
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(fixtures / "plain.mp4", target)

    _paths, result = trim(
        tmp_path, fixtures, "plain.mp4", monkeypatch, prepare=existing, trim_action="keep", trim_end="3", overwrite=False
    )
    assert result.ok, result.message
    assert result.data["skipped"] == 1 and result.data["processed"] == 0
