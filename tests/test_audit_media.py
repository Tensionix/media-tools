"""The media findings of the audit of 15.10.2026, each held by a short synthetic case and checked by the content, not by
the length or the green status:

- F01 a cut of a file whose timeline starts late keeps the frames asked for (frame hashes);
- F07 a lossless archive keeps the bits or refuses: x264 refuses 12 bits, FFV1 keeps them and float sound;
- F11 a cut takes a Source of one file;
- F12 the loudness report of sound in a video measures every track;
- F13 a copy of big-endian PCM goes to a container that holds it;
- F15 a download repeated at once writes nothing and says so;
- F16 x264 keeps the fields of an interlaced source.
"""
from __future__ import annotations

import functools
import hashlib
import http.server
import json
import os
import subprocess
import sys
import threading
from pathlib import Path

import pytest

PROJECT = Path(__file__).resolve().parent.parent
CLI = PROJECT / "system_core" / "cli.py"
FFMPEG = PROJECT / "Tools" / "ffmpeg" / "bin" / "ffmpeg.exe"
FFPROBE = PROJECT / "Tools" / "ffmpeg" / "bin" / "ffprobe.exe"
pytestmark = pytest.mark.skipif(not FFMPEG.is_file(), reason="no FFmpeg of the program in Tools")


def run(*args: str) -> subprocess.CompletedProcess:
    env = dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
    env.pop("AUDION_SOURCE", None)
    env.pop("AUDION_OUTPUT", None)
    return subprocess.run([sys.executable, "-u", str(CLI), *args], capture_output=True, text=True, encoding="utf-8",
                          timeout=300, env=env)


def make(path: Path, *arguments: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run([str(FFMPEG), "-hide_banner", "-loglevel", "error", "-y", *arguments, str(path)], check=True, timeout=120)
    return path


def frames(path: Path, *extra: str) -> list[str]:
    out = subprocess.run([str(FFMPEG), "-v", "error", "-i", str(path), "-map", "0:v:0", *extra, "-f", "framemd5", "-"],
                         capture_output=True, text=True, check=True).stdout
    return [line.rsplit(",", 1)[-1].strip() for line in out.splitlines() if line and not line.startswith("#")]


def probe(path: Path, entries: str, select: str = "v:0") -> str:
    return subprocess.run([str(FFPROBE), "-v", "error", "-select_streams", select, "-show_entries", entries, "-of", "csv=p=0",
                           str(path)], capture_output=True, text=True).stdout.strip()


def told(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.mark.parametrize(("name", "extra"), [("offset.mp4", ["-output_ts_offset", "10"]), ("stream.ts", [])])
def test_a_late_timeline_is_cut_where_asked(name: str, extra: list[str], tmp_path: Path) -> None:
    source = make(tmp_path / "in" / name, "-f", "lavfi", "-i", "testsrc2=size=320x180:rate=25:duration=6", "-f", "lavfi", "-i",
                  "sine=duration=6", "-c:v", "libx264", "-g", "25", "-keyint_min", "25", "-sc_threshold", "0", "-bf", "0",
                  "-c:a", "aac", *extra)
    done = run("run", "--operation", "trim_run", "--set", f"trim_file={name}", "--set", "trim_action=keep",
               "--set", "trim_start=2", "--set", "trim_end=4", "--source", str(tmp_path / "in"),
               "--target", str(tmp_path / "out"), "--result", str(tmp_path / "told.json"))
    assert done.returncode == 0, done.stdout[-2000:]
    piece = frames(next((tmp_path / "out").rglob(f"{source.stem}*.*")))
    whole = frames(source)
    assert piece and whole.index(piece[0]) == 50 and whole.index(piece[-1]) == 99


def test_a_lossless_archive_keeps_the_bits_or_refuses(tmp_path: Path) -> None:
    master = make(tmp_path / "in" / "master.mov", "-f", "lavfi", "-i", "testsrc2=size=320x180:rate=25:duration=1", "-f", "lavfi",
                  "-i", "sine=frequency=440:sample_rate=48000:duration=1", "-c:v", "prores_ks", "-profile:v", "4",
                  "-pix_fmt", "yuv444p12le", "-c:a", "pcm_f32le", "-shortest")
    refused = run("run", "--operation", "archive_run", "--set", "archive_profile=x264_lossless_mkv", "--source",
                  str(tmp_path / "in"), "--target", str(tmp_path / "x264"), "--result", str(tmp_path / "x264.json"))
    assert refused.returncode == 1 and told(tmp_path / "x264.json")["data"]["refused"] == 1
    assert "FFV1 keeps it" in refused.stdout and not any((tmp_path / "x264").rglob("*.mkv"))
    kept = run("run", "--operation", "archive_run", "--set", "archive_profile=ffv1_mkv", "--source", str(tmp_path / "in"),
               "--target", str(tmp_path / "ffv1"))
    assert kept.returncode == 0, kept.stdout[-2000:]
    archive = next((tmp_path / "ffv1").rglob("*.mkv"))
    assert frames(archive, "-pix_fmt", "yuv444p12le") == frames(master, "-pix_fmt", "yuv444p12le")

    def samples(path: Path) -> str:
        raw = subprocess.run([str(FFMPEG), "-v", "error", "-i", str(path), "-map", "0:a", "-f", "f32le", "-"],
                             capture_output=True, check=True).stdout
        return hashlib.sha256(raw).hexdigest()

    assert samples(archive) == samples(master)


def test_a_cut_takes_a_source_of_one_file(tmp_path: Path) -> None:
    take = make(tmp_path / "in" / "take.mp4", "-f", "lavfi", "-i", "testsrc2=size=320x180:rate=25:duration=4", "-c:v", "libx264",
                "-g", "25")
    done = run("run", "--operation", "trim_run", "--set", "trim_file=take.mp4", "--set", "trim_action=keep",
               "--set", "trim_start=1", "--set", "trim_end=2", "--source", str(take), "--target", str(tmp_path / "out"),
               "--result", str(tmp_path / "told.json"))
    assert done.returncode == 0 and told(tmp_path / "told.json")["data"]["processed"] == 1, done.stdout[-2000:]


def test_the_loudness_report_measures_every_track(tmp_path: Path) -> None:
    make(tmp_path / "in" / "two.mkv", "-f", "lavfi", "-i", "testsrc2=size=160x90:rate=25:duration=3",
         "-f", "lavfi", "-i", "sine=frequency=440:duration=3", "-f", "lavfi", "-i", "sine=frequency=880:duration=3",
         "-filter_complex", "[2:a]volume=-20dB[quiet]", "-map", "0:v", "-map", "1:a", "-map", "[quiet]", "-c:v", "libx264",
         "-c:a", "flac")
    done = run("run", "--operation", "audio_run", "--set", "audio_workflow=in_video", "--set", "audio_profile=lufs_report",
               "--set", "audio_stream_mode=all", "--source", str(tmp_path / "in"), "--target", str(tmp_path / "out"),
               "--result", str(tmp_path / "told.json"))
    assert done.returncode == 0, done.stdout[-2000:]
    rows = [row for row in told(tmp_path / "told.json")["data"]["audio_items"] if row["mode"] == "in_video_lufs_report"]
    loudness = [json.loads(row["lufs"])["input_i"] for row in rows]
    assert len(loudness) == 2 and abs(float(loudness[0]) - float(loudness[1])) > 15, loudness


def test_a_copy_of_big_endian_pcm_goes_where_it_is_held(tmp_path: Path) -> None:
    make(tmp_path / "in" / "camera.mov", "-f", "lavfi", "-i", "testsrc2=size=160x90:rate=25:duration=1", "-f", "lavfi",
         "-i", "sine=duration=1", "-c:v", "libx264", "-c:a", "pcm_s16be", "-shortest")
    done = run("run", "--operation", "audio_run", "--set", "audio_workflow=extract", "--set", "audio_profile=copy_auto",
               "--source", str(tmp_path / "in"), "--target", str(tmp_path / "out"))
    assert done.returncode == 0, done.stdout[-2000:]
    written = [path for path in (tmp_path / "out").rglob("*.*")]
    assert [path.suffix for path in written] == [".mka"] and probe(written[0], "stream=codec_name", "a:0") == "pcm_s16be"


def test_a_download_repeated_writes_nothing(tmp_path: Path) -> None:
    served = make(tmp_path / "served" / "clip.mp4", "-f", "lavfi", "-i", "testsrc2=size=160x90:rate=25:duration=1",
                  "-c:v", "libx264").parent
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(
        type("Quiet", (http.server.SimpleHTTPRequestHandler,), {"log_message": lambda *args: None}), directory=str(served)))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        link = f"http://127.0.0.1:{server.server_address[1]}/clip.mp4"
        counts = []
        for name in ("first", "second"):
            run("run", "--operation", "youtube_run", "--set", f"youtube_url={link}", "--set", "cookies_source=none",
                "--target", str(tmp_path / "out"), "--result", str(tmp_path / f"{name}.json"))
            data = told(tmp_path / f"{name}.json")["data"]
            counts.append((data["processed"], len(data["downloaded"]), len(data["existing"])))
    finally:
        server.shutdown()
    assert counts == [(1, 1, 0), (0, 0, 1)], counts


def test_x264_keeps_the_fields_of_an_interlaced_source(tmp_path: Path) -> None:
    make(tmp_path / "in" / "field.mp4", "-f", "lavfi", "-i", "testsrc2=size=320x180:rate=25:duration=1", "-c:v", "libx264",
         "-flags", "+ildct+ilme", "-field_order", "tt")
    done = run("run", "--operation", "storage_run", "--set", "cpu_encoder_preset=fast", "--set", "scan_mode=keep",
               "--source", str(tmp_path / "in"), "--target", str(tmp_path / "out"))
    assert done.returncode == 0, done.stdout[-2000:]
    assert probe(next((tmp_path / "out").rglob("*.mp4")), "stream=field_order") == "tt"
