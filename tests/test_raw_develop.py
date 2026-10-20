"""ProRes RAW developed on the video card (system_core\\services\\raw_develop.py): the ranges of a clip, where cineraw
seeks, the encoder a development takes, the commands of cineraw and FFmpeg, and when the operations that decode the
picture take ProRes RAW instead of refusing it.

The development itself needs a ProRes RAW clip and a video card with Vulkan 1.4: MEMORY.md says how it was checked
(209 frames of a Sony A7S III / Atomos Ninja V sample, the same to the bit in 2, 4, 8 and 12 ranges). Here the rules are
held; a run of the console command on a header of ProRes RAW with no picture in it shows the reason of the failure.
"""
from __future__ import annotations

import json
import os
import struct
import subprocess
import sys
from fractions import Fraction
from pathlib import Path

import pytest

from system_core.core import camera_raw
from system_core.services import raw_develop as rd

PROJECT = Path(__file__).resolve().parent.parent
CLI = PROJECT / "system_core" / "cli.py"
RATE = Fraction(24000, 1001)


def clip(frames: int = 209, width: int = 4264) -> rd.Clip:
    return rd.Clip(frames=frames, rate=RATE, width=width, height=2408, timecode="00:00:10:00", duration=frames / float(RATE))


@pytest.mark.parametrize("frames, count", [(209, 8), (209, 2), (5, 8), (1, 4), (240, 12)])
def test_the_ranges_cover_the_clip_once_and_the_last_runs_to_its_end(frames: int, count: int) -> None:
    parts = rd.ranges(frames, count)
    assert len(parts) == min(frames, count)
    assert parts[-1][1] is None
    covered = [size for _start, size in parts[:-1]]
    starts = [start for start, _size in parts]
    assert starts[0] == 0
    assert all(starts[i] + covered[i] == starts[i + 1] for i in range(len(covered)))
    assert max(covered, default=0) - min(covered, default=0) <= 1
    assert frames - starts[-1] >= 1


def test_cineraw_seeks_a_quarter_of_a_frame_early() -> None:
    # cineraw starts at the first frame not before the time asked: a quarter late lost a frame at every join (208 of 209).
    for frame in (1, 17, 26, 182):
        asked = float(rd.start_seconds(frame, RATE))
        assert float(Fraction(frame - 1) / RATE) < asked < float(Fraction(frame) / RATE)


def test_h264_of_nvenc_is_not_asked_wider_than_it_takes() -> None:
    assert rd.encoder_for("h264", "nvenc", clip(width=4264))[0] == "cpu"
    assert "4096" in rd.encoder_for("h264", "nvenc", clip(width=4264))[1]
    assert rd.encoder_for("h264", "nvenc", clip(width=3840)) == ("nvenc", "")
    assert rd.encoder_for("h265", "nvenc", clip(width=4264)) == ("nvenc", "")
    assert rd.encoder_for("prores4444", "nvenc", clip()) == ("cpu", "")


def test_the_pieces_at_once_follow_the_cores_and_the_sessions_of_nvenc() -> None:
    assert rd.workers(clip(), "12") == 8                       # a clip of 8.7 s: no more ranges than its seconds
    assert rd.workers(clip(frames=2400), "12") == 12
    assert rd.workers(clip(frames=2400), "12", "nvenc") == 8   # a GeForce gives eight sessions of NVENC
    assert 1 <= rd.workers(clip(frames=2400), "auto") <= 8
    assert rd.workers(clip(frames=10), "auto") == 1


def test_a_range_reads_frames_from_a_pipe_and_writes_bt709() -> None:
    command = rd.piece_command("ffmpeg.exe", clip(), "prores4444", "cpu", Path("piece00.mov"))
    assert command[command.index("-f") + 1] == "pfm_pipe" and command[command.index("-i") + 1] == "-"
    assert command[command.index("-framerate") + 1] == "24000/1001"
    chain = command[command.index("-vf") + 1]
    assert "out_color_matrix=bt709" in chain and "format=yuv444p10le" in chain
    assert "color_primaries=bt709:color_trc=bt709:colorspace=bt709" in chain
    assert command[command.index("-profile:v") + 1] == "4" and "-an" in command
    hevc = rd.piece_command("ffmpeg.exe", clip(), "h265", "nvenc", Path("piece00.mp4"))
    assert "hevc_nvenc" in hevc and "format=p010le" in hevc[hevc.index("-vf") + 1]


def test_cineraw_is_asked_for_its_range_into_pipes() -> None:
    first = rd.cineraw_command(PROJECT, Path("A001.mov"), clip(), 0, 26, r"\\.\pipe\audion-raw-1-00-%05d.pfm")
    assert "--start" not in first and first[first.index("--frames") + 1] == "26"
    assert first[first.index("--encode") + 1] == "sdr" and first[first.index("--space") + 1] == "bt709"
    assert first[first.index("-o") + 1].endswith("%05d.pfm") and first[-1] == "A001.mov"
    last = rd.cineraw_command(PROJECT, Path("A001.mov"), clip(), 182, None, "x-%05d.pfm")
    assert "--frames" not in last and last[last.index("--start") + 1] == rd.start_seconds(182, RATE)


def test_the_pieces_are_joined_with_the_sound_and_the_timecode_of_the_source() -> None:
    command = rd.join_command("ffmpeg.exe", Path("pieces.txt"), Path("A001.mov"), "h264", clip(), Path("A001.mp4"))
    assert command[command.index("-f") + 1] == "concat" and "-safe" in command
    assert command[command.index("-c:v") + 1] == "copy" and command[command.index("-c:a") + 1] == "aac"
    assert "1:a?" in command and command[command.index("-timecode") + 1] == "00:00:10:00"
    prores = rd.join_command("ffmpeg.exe", Path("pieces.txt"), Path("A001.mov"), "prores4444", clip(), Path("A001.mov"))
    assert prores[prores.index("-c:a") + 1] == "copy"


def test_every_development_is_a_choice_of_the_form() -> None:
    import yaml

    manifest = yaml.safe_load((PROJECT / "config" / "tool_manifest.yaml").read_text(encoding="utf-8"))
    node = next(op for group in manifest.values() if isinstance(group, list) for op in group
                if isinstance(op, dict) and op.get("id") == "raw")
    field = next(item for item in node["fields"] if isinstance(item, dict) and item.get("id") == "raw_target")
    assert {option["value"] for option in field["options"]} == set(rd.TARGETS)


def test_the_operations_that_decode_the_picture_take_prores_raw_once_cineraw_is_there(tmp_path: Path, monkeypatch) -> None:
    prores = camera_raw.Raw("prores_raw", "ProRes RAW HQ", True)
    arriraw = camera_raw.Raw("arriraw", "ARRIRAW", False)
    assert not camera_raw.develops(tmp_path, "encode_targets", prores)
    folder = tmp_path / "Tools" / "cineraw"
    folder.mkdir(parents=True)
    (folder / "cineraw.exe").write_bytes(b"")
    (folder / "libcraw.dll").write_bytes(b"")
    for service in ("encode_targets", "fps_convert", "run_color_grade"):
        assert camera_raw.develops(tmp_path, service, prores), service
    assert not camera_raw.develops(tmp_path, "trim_media", prores)      # a trim copies it as it is
    assert not camera_raw.develops(tmp_path, "encode_targets", arriraw)
    monkeypatch.setenv("AUDION_CINERAW", "off")
    assert not camera_raw.develops(tmp_path, "encode_targets", prores)


def test_a_master_stands_for_its_source() -> None:
    master = PROJECT / "workspace" / "raw_master" / "1-1" / "A001.mov"
    source = PROJECT / "input" / "day1" / "A001.mov"
    with rd._MASTERS_LOCK:
        rd._MASTERS[str(master.resolve())] = source
    try:
        assert rd.original_of(master) == source
        assert rd.original_of(source) == source
    finally:
        with rd._MASTERS_LOCK:
            rd._MASTERS.clear()


def box(kind: bytes, body: bytes) -> bytes:
    return struct.pack(">I4s", 8 + len(body), kind) + body


def mov(codec: bytes) -> bytes:
    """A MOV of ProRes RAW whose picture is zeros, laid out as tests\\test_camera_raw.py lays it: the 'stsd' names it."""
    stsd = box(b"stsd", b"\0\0\0\0" + struct.pack(">I", 1) + box(codec, b"\0" * 70))
    trak = box(b"trak", box(b"mdia", box(b"minf", box(b"stbl", stsd))))
    moov = box(b"moov", box(b"mvhd", b"\0" * 100) + trak)
    return box(b"ftyp", b"qt  \0\0\0\0qt  ") + box(b"wide", b"") + box(b"mdat", b"\0" * 4096) + moov


@pytest.mark.skipif(not rd.ready(PROJECT), reason="cineraw is not installed: SERVICE - Install ProRes RAW development")
def test_a_prores_raw_cineraw_cannot_read_fails_by_itself_with_the_reason(tmp_path: Path) -> None:
    source = tmp_path / "in"
    source.mkdir()
    (source / "A001.mov").write_bytes(mov(b"aprh"))
    env = dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
    env.pop("AUDION_CINERAW", None)
    done = subprocess.run([sys.executable, "-u", str(CLI), "run", "--operation", "storage_run", "--set", "storage_profile=x264_crf14",
                           "--source", str(source), "--target", str(tmp_path / "out"), "--result", str(tmp_path / "told.json")],
                          capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=300, env=env)
    told = json.loads((tmp_path / "told.json").read_text(encoding="utf-8"))
    assert "ProRes RAW is developed first on the video card by cineraw: A001.mov" in done.stdout, done.stdout[-3000:]
    assert "[FAIL] A001.mov: ProRes RAW HQ was not developed - cineraw" in done.stdout, done.stdout[-3000:]
    assert told["outcome"] == "failed" and "Traceback" not in done.stdout + done.stderr
