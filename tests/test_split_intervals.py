"""Equal-duration splits and the Copy preset through the same entry point as the window."""
from __future__ import annotations

import json
import subprocess
import sys
from fractions import Fraction
from pathlib import Path

import pytest

from system_core.core.manifest import load_manifest
from system_core.core.operation_model import Form, find_node, wrong_choices
from system_core.core.trim_contract import parse_split_interval, plan_audio_trim, plan_split, split_interval_points
from system_core.services.media_service import _trim_part_suffix, _trim_split_points

PROJECT = Path(__file__).resolve().parents[1]
FFMPEG = PROJECT / "Tools/ffmpeg/bin/ffmpeg.exe"
FFPROBE = PROJECT / "Tools/ffmpeg/bin/ffprobe.exe"


@pytest.mark.parametrize("value, seconds", [
    (89, 5340), ("89", 5340), ("89,5", 5370), ("89.5", 5370),
    ("01:29:00:000", 5340), ("01:29:00,125", 5340.125),
    ("01:29:00.125", 5340.125), ("01:29:00", 5340), ("00:00:00:001", 0.001),
])
def test_part_length_accepts_minutes_or_wall_clock(value, seconds):
    assert parse_split_interval(value) == seconds


@pytest.mark.parametrize("value", ["", None, 0, -1, True, False, "nan", "inf", "01:89:00:000", "01:29:60:000", "01:29:00:1000"])
def test_invalid_part_lengths_are_refused(value):
    with pytest.raises(ValueError):
        parse_split_interval(value)


def test_89_minutes_generates_the_points_from_zero_and_ignores_old_manual_points():
    expected = [5340, 10680, 16020, 21360]
    assert split_interval_points("89", 22733.534) == expected
    assert _trim_split_points({"trim_split_mode": "duration", "trim_split_duration": "01:29:00:000",
                               "trim_points": [1, 2], "trim_start": "9"}, duration=22733.534) == expected


def test_exact_multiple_has_no_empty_tail_and_shorter_file_is_one_part():
    assert split_interval_points("00:00:03:000", 9) == [3, 6]
    for duration in (2, 3):
        video = plan_split(points=[1], duration=duration, rate=Fraction(25), keyframes=[0, 1], split_interval="00:00:03:000")
        audio = plan_audio_trim(pattern="split", start=1, end=2, duration=duration, sample_rate=48000,
                                split_interval="00:00:03:000")
        assert len(video.parts) == len(audio.pieces) == 1
        assert video.parts[0].start == audio.pieces[0].start == 0
        assert video.parts[0].end is audio.pieces[0].end is None


def test_automatic_splits_do_not_inherit_the_limit_of_30_manual_fields():
    split = plan_split(points=[], duration=40, rate=Fraction(25), keyframes=range(40), split_interval="00:00:01:000")
    assert len(split.parts) == 40
    assert sum(part.seconds for part in split.parts) == 40
    assert _trim_part_suffix(3, 120) == "part003"
    with pytest.raises(ValueError, match="longer part length"):
        split_interval_points("00:00:00:001", 11)


def test_audio_points_use_the_sample_grid_without_accumulating_drift():
    split = plan_audio_trim(pattern="split", start="", end="", duration=1, sample_rate=48000,
                            split_interval="00:00:00:100")
    assert [piece.start for piece in split.pieces] == list(range(0, 48000, 4800))
    assert split.total == 48000


def test_split_form_switches_fields_and_keeps_manual_points(tmp_path):
    manifest = load_manifest(PROJECT / "config/tool_manifest.yaml")
    form = Form(find_node(manifest, "trim_run"), tmp_path).open()
    form.click("trim_action", "trim_action", "split")
    form.click("split_point", "trim", [0, "00:00:03,000"])
    form.click("choose", "trim_split_mode", "duration")
    shown = {field["id"] for field in form.shown_fields()}
    assert "trim_split_duration" in shown and "trim_rows" not in shown
    assert not form.trim_can_add()
    for value in ("89", "01:29:00:000"):
        form.click("type", "trim_split_duration", value)
        assert form.refusal() == ""
    form.click("type", "trim_split_duration", "0")
    assert "positive" in form.refusal("en") and "положительную" in form.refusal("ru")
    form.click("choose", "trim_split_mode", "points")
    assert form.split_points() == ["00:00:03,000"]
    assert form.refusal() == ""
    assert "trim_rows" in {field["id"] for field in form.shown_fields()}


@pytest.mark.parametrize("workflow", ["extract", "in_video", "audio_files"])
def test_copy_form_parameters_pass_the_console_choice_check(tmp_path, workflow):
    manifest = load_manifest(PROJECT / "config/tool_manifest.yaml")
    node = find_node(manifest, "audio_run")
    form = Form(node, tmp_path).open().fill({"audio_profile": "copy_auto", "audio_workflow": workflow})
    assert form.parameters()["audio_resampler"] == "auto"
    assert wrong_choices(node, form.parameters(), tmp_path) == []


def run(command):
    done = subprocess.run(command, capture_output=True, timeout=120)
    assert done.returncode == 0, (done.stdout + done.stderr).decode("utf-8", errors="replace")[-6000:]
    return done.stdout


def cli(source, target, result, operation, values, tmp_path):
    parameters = tmp_path / f"{result.stem}-params.json"
    parameters.write_text(json.dumps(values), encoding="utf-8")
    output = run([sys.executable, "-X", "utf8", "-B", str(PROJECT / "system_core/cli.py"), "run", "--operation", operation,
                  "--source", str(source), "--target", str(target), "--params", str(parameters), "--result", str(result)])
    payload = json.loads(result.read_text(encoding="utf-8"))
    assert payload["outcome"] == "done"
    return payload, output.decode("utf-8")


def packets(path, stream):
    data = run([str(FFPROBE), "-v", "error", "-select_streams", stream, "-show_packets", "-show_data_hash", "sha256",
                "-show_entries", "packet=data_hash", "-of", "csv=p=0", str(path)])
    return data.splitlines()


@pytest.mark.skipif(not FFMPEG.is_file(), reason="FFmpeg is not installed under Tools")
@pytest.mark.parametrize("kind", ["video", "audio"])
@pytest.mark.parametrize("length, count", [(7.5, 3), (3, 1), (2, 1)])
def test_equal_parts_run_through_cli_preserve_content_and_copy_extraction(tmp_path, kind, length, count):
    source = tmp_path / ("take.mp4" if kind == "video" else "take.wav")
    sound = ["-f", "lavfi", "-i", f"sine=frequency=731:sample_rate=48000:duration={length}"]
    if kind == "video":
        run([str(FFMPEG), "-v", "error", "-f", "lavfi", "-i", f"testsrc2=size=160x90:rate=25:duration={length}",
             *sound, "-c:v", "libx264", "-preset", "ultrafast", "-g", "25", "-sc_threshold", "0", "-c:a", "aac", str(source)])
    else:
        run([str(FFMPEG), "-v", "error", *sound, "-c:a", "pcm_s24le", str(source)])
    target = tmp_path / "out"
    done, _output = cli(source, target, tmp_path / "split.json", "trim_run",
                        {"trim_action": "split", "trim_split_mode": "duration", "trim_split_duration": "00:00:03:000",
                         "trim_points": [1, 2]}, tmp_path)
    assert done["data"]["processed"] == count
    parts = sorted(target.rglob(f"take_part*{source.suffix}"))
    assert [part.stem for part in parts] == [f"take_part{index}" for index in range(1, count + 1)]
    if kind == "video":
        assert [packet for part in parts for packet in packets(part, "v:0")] == packets(source, "v:0")
        manifest = load_manifest(PROJECT / "config/tool_manifest.yaml")
        values = Form(find_node(manifest, "audio_run"), PROJECT).open().parameters()
        done, commands = cli(parts[0].parent, tmp_path / "audio", tmp_path / "extract.json", "audio_run", values, tmp_path)
        assert done["data"]["processed"] == count
        extracted = sorted((tmp_path / "audio").rglob("*.m4a"))
        assert len(extracted) == count
        for part, audio in zip(parts, extracted):
            assert packets(audio, "a:0") == packets(part, "a:0")
        assert "-c:a copy" in commands and "aresample" not in commands
    else:
        def samples(path):
            return run([str(FFMPEG), "-v", "error", "-i", str(path), "-f", "s24le", "-c:a", "pcm_s24le", "-"])
        assert b"".join(samples(part) for part in parts) == samples(source)
