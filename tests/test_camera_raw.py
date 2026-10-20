"""Camera RAW in the Source: the program develops none of it, and says so in one line with what opens it.

ProRes RAW FFmpeg reads as the signal of the sensor - without the white balance and the colour matrix of the camera (8.0.1
with distorted tones too): an encode came out flat and green; the services that decode the picture refuse it, a remux
and a trim copy it. ARRIRAW, Sony RAW / X-OCN, RED R3D, Nikon N-RAW, Blackmagic RAW and Canon Cinema RAW FFmpeg does not
read at all: the copy services refuse them too, and their own files, which no operation takes, are said. A Source of it
alone is refused by the preflight; among other videos each such file fails by itself and the rest are made.

The headers are made here: a MOV box by box, as Atomos lays it out - 'ftyp', 'wide', a large 'mdat', then 'moov' (the
sample of a Sony A7S III through a Ninja V gave "aprh" in its 'stsd'); an MXF KLV by KLV - the partition pack, a fill,
the descriptor with the label of its picture (the ALEXA 35 sample gave 04.01.02.01.02.01.01). The pages of the programs
are in config\\camera_raw.yaml; tests\\probe_raw_pages.py asks them, on the network, apart from this test.
"""
from __future__ import annotations

import json
import os
import struct
import subprocess
import sys
from pathlib import Path

import pytest

from system_core.core import camera_raw as raw_module
from system_core.core.camera_raw import camera_raw, raw_of, stray_raw

PROJECT = Path(__file__).resolve().parent.parent
CLI = PROJECT / "system_core" / "cli.py"
FFMPEG = PROJECT / "Tools" / "ffmpeg" / "bin" / "ffmpeg.exe"
STORAGE = ["--operation", "storage_run", "--set", "storage_profile=x264_crf14", "--set", "cpu_encoder_preset=fast"]
REMUX = ["--operation", "remux_run", "--set", "remux_stream_mode=video_audio", "--set", "remux_target_format=mkv"]
ARRIRAW = bytes.fromhex("060e2b340401010d0401020102010103")
ARRIRAW_HDE = bytes.fromhex("060e2b340401010d0401020102010203")
SONY_RAW_SQ = bytes.fromhex("060e2b340401010e0e06040102040200")
PRORES_HQ = bytes.fromhex("060e2b340401010d0401020203060300")


def box(kind: bytes, body: bytes) -> bytes:
    return struct.pack(">I4s", 8 + len(body), kind) + body


def mov(codec: bytes, mdat: int = 4096, large: bool = False) -> bytes:
    """A MOV of one video track of the codec named: its picture is zeros, its header says the codec where 'stsd' does."""
    entry = box(codec, b"\0" * 70)
    stsd = box(b"stsd", b"\0\0\0\0" + struct.pack(">I", 1) + entry)
    trak = box(b"trak", box(b"mdia", box(b"minf", box(b"stbl", stsd))))
    moov = box(b"moov", box(b"mvhd", b"\0" * 100) + trak)
    picture = b"\0" * mdat
    data = struct.pack(">I4sQ", 1, b"mdat", 16 + len(picture)) + picture if large else box(b"mdat", picture)
    return box(b"ftyp", b"qt  \0\0\0\0qt  ") + box(b"wide", b"") + data + moov


def klv(key: str, value: bytes, long_length: bool = False) -> bytes:
    length = (b"\x83" + len(value).to_bytes(3, "big")) if long_length or len(value) > 127 else bytes([len(value)])
    return bytes.fromhex(key) + length + value


def mxf(picture_coding: bytes) -> bytes:
    """An MXF header: the partition pack, a fill, a Generic Picture Essence Descriptor naming the coding of its picture,
    then an element of the picture - zeros."""
    descriptor = struct.pack(">HH", 0x3201, 16) + picture_coding + struct.pack(">HH", 0x3203, 4) + (4608).to_bytes(4, "big")
    return (klv("060e2b34020501010d01020101020400", b"\0" * 88, long_length=True)
            + klv("060e2b34010101020301021001000000", b"\0" * 300)
            + klv("060e2b34025301010d01010101012700", descriptor, long_length=True)
            + klv("060e2b34010201010d01030115010501", b"\0" * 4096, long_length=True))


@pytest.mark.parametrize("codec, said", [(b"aprh", "ProRes RAW HQ"), (b"aprn", "ProRes RAW"), (b"apch", ""), (b"avc1", "")])
def test_the_codec_of_a_mov_is_read_from_its_header(codec: bytes, said: str, tmp_path: Path) -> None:
    for large in (False, True):
        clip = tmp_path / f"clip_{codec.decode()}_{large}.mov"
        clip.write_bytes(mov(codec, large=large))
        assert camera_raw(clip) == said


def test_only_a_mov_is_looked_into_and_a_broken_one_is_no_raw(tmp_path: Path) -> None:
    other = tmp_path / "clip.mkv"
    other.write_bytes(mov(b"aprh"))
    broken = tmp_path / "broken.mov"
    broken.write_bytes(b"\0\0\0\x04moov")
    assert camera_raw(other) == "" and camera_raw(broken) == "" and camera_raw(tmp_path / "none.mov") == ""


@pytest.mark.parametrize("coding, kind, said", [
    (ARRIRAW, "arriraw", "ARRIRAW"), (ARRIRAW_HDE, "arriraw", "ARRIRAW HDE"),
    (SONY_RAW_SQ, "sony_raw", "Sony RAW / X-OCN"), (PRORES_HQ, None, ""),
])
def test_the_picture_of_an_mxf_is_read_from_the_label_of_its_descriptor(coding: bytes, kind: str | None, said: str,
                                                                        tmp_path: Path) -> None:
    clip = tmp_path / "A001.mxf"
    clip.write_bytes(mxf(coding))
    found = raw_of(clip)
    assert (found.kind if found else None) == kind and camera_raw(clip) == said
    assert not found or not found.read


def test_a_sony_label_ffmpeg_decodes_is_no_raw(tmp_path: Path) -> None:
    # Sony's own range of labels names its RAW; FFmpeg knowing the codec settles it otherwise.
    clip = tmp_path / "A001.mxf"
    clip.write_bytes(mxf(SONY_RAW_SQ))
    assert raw_of(clip, lambda path: True) is None
    assert raw_of(clip, lambda path: False).kind == "sony_raw"


@pytest.mark.parametrize("name, kind", [("A001.braw", "braw"), ("A001.R3D", "r3d"), ("DSC_0001.NEV", "nraw"),
                                        ("A001C001.crm", "canon_raw"), ("A001.0000001.ari", "arriraw"), ("B001.arx", "arriraw")])
def test_the_files_of_their_own_kind_are_known_by_it(name: str, kind: str, tmp_path: Path) -> None:
    clip = tmp_path / name
    clip.write_bytes(b"\0" * 64)
    assert raw_of(clip).kind == kind
    assert stray_raw(tmp_path) == {kind: [clip]}


def test_every_kind_names_programs_with_their_pages_and_the_readme_holds_them() -> None:
    table = raw_module.table()
    readmes = [(PROJECT / "Docs" / name).read_text(encoding="utf-8") for name in ("README_RU.md", "README_EN.md")]
    for kind, entry in table["kinds"].items():
        assert entry["name"] and entry["open"], kind
        for program in entry["open"]:
            assert program in table["programs"], (kind, program)
    for program in table["programs"].values():
        assert program["page"].startswith("https://"), program
        assert all(program["page"] in readme for readme in readmes), program["page"]


@pytest.mark.skipif(not FFMPEG.is_file(), reason="no FFmpeg of the program in Tools")
def test_an_mxf_ffmpeg_writes_is_no_raw(tmp_path: Path) -> None:
    for codec, name in (("mpeg2video", "mpeg2.mxf"), ("prores_ks", "prores.mxf"), ("dnxhd", "dnxhr.mxf")):
        extra = ["-profile:v", "dnxhr_sq"] if codec == "dnxhd" else []
        subprocess.run([str(FFMPEG), "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc2=size=1280x720:rate=25:duration=0.2",
                        "-c:v", codec, *extra, "-pix_fmt", "yuv422p", str(tmp_path / name)], check=True, timeout=120)
        assert raw_of(tmp_path / name) is None, name


def run(*args: str, timeout: float = 300) -> subprocess.CompletedProcess:
    # The refusal as without cineraw: on a machine that has it, ProRes RAW would be developed (tests\test_raw_develop.py).
    env = dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8", AUDION_CINERAW="off")
    env.pop("AUDION_SOURCE", None)
    env.pop("AUDION_OUTPUT", None)
    return subprocess.run([sys.executable, "-u", str(CLI), *args], capture_output=True, text=True, encoding="utf-8",
                          errors="replace", timeout=timeout, env=env)


def told(tmp_path: Path) -> dict:
    return json.loads((tmp_path / "told.json").read_text(encoding="utf-8"))


def clip(folder: Path, name: str) -> None:
    subprocess.run([str(FFMPEG), "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc2=size=320x180:rate=25:duration=1",
                    "-c:v", "libx264", "-preset", "ultrafast", str(folder / name)], check=True, timeout=120)


def test_a_source_of_prores_raw_alone_is_refused_with_the_reason(tmp_path: Path) -> None:
    source = tmp_path / "in"
    source.mkdir()
    (source / "A001.mov").write_bytes(mov(b"aprh"))
    done = run("run", *STORAGE, "--source", str(source), "--target", str(tmp_path / "out"), "--result", str(tmp_path / "told.json"))
    assert told(tmp_path)["outcome"] == "refused", done.stdout[-3000:]
    assert "camera RAW: the program does not develop A001.mov (ProRes RAW HQ)" in done.stdout
    assert "DaVinci Resolve (https://" in done.stdout and "Final Cut Pro (https://" in done.stdout
    assert "Traceback" not in done.stdout + done.stderr


def test_prores_raw_among_other_videos_is_said_and_failed_by_itself(tmp_path: Path) -> None:
    if not FFMPEG.is_file():
        pytest.skip("no FFmpeg of the program in Tools")
    source = tmp_path / "in"
    source.mkdir()
    (source / "A001.mov").write_bytes(mov(b"aprn"))
    clip(source, "B001.mov")
    target = tmp_path / "out"
    done = run("run", *STORAGE, "--source", str(source), "--target", str(target), "--result", str(tmp_path / "told.json"))
    result = told(tmp_path)
    assert result["outcome"] == "failed", done.stdout[-3000:]
    assert result["data"]["failed"] == 1 and result["data"]["processed"] == 1, result["data"]
    assert "camera RAW: the program does not develop A001.mov (ProRes RAW)" in done.stdout
    assert "[FAIL] A001.mov: ProRes RAW is not developed by the program" in done.stdout
    assert [path.name for path in target.rglob("*.mp4") if "B001" in path.name], "the other video was not made"


def test_a_remux_of_prores_raw_is_not_stopped_by_it(tmp_path: Path) -> None:
    source = tmp_path / "in"
    source.mkdir()
    (source / "A001.mov").write_bytes(mov(b"aprh"))
    done = run("run", *REMUX, "--source", str(source), "--target", str(tmp_path / "out"), "--result", str(tmp_path / "told.json"))
    assert "camera RAW" not in done.stdout and "is not developed" not in done.stdout, done.stdout[-3000:]


def test_a_remux_of_arriraw_is_refused_with_what_opens_it(tmp_path: Path) -> None:
    source = tmp_path / "in"
    source.mkdir()
    (source / "A001.mxf").write_bytes(mxf(ARRIRAW))
    done = run("run", "--operation", "remux_run", "--set", "remux_stream_mode=video_audio", "--set", "remux_target_format=mov",
               "--source", str(source), "--target", str(tmp_path / "out"), "--result", str(tmp_path / "told.json"))
    assert told(tmp_path)["outcome"] == "refused", done.stdout[-3000:]
    assert "camera RAW: the program does not read A001.mxf (ARRIRAW): FFmpeg does not decode it" in done.stdout
    assert "ARRI Reference Tool (https://" in done.stdout


def test_a_trim_of_arriraw_fails_it_in_one_line(tmp_path: Path) -> None:
    source = tmp_path / "in"
    source.mkdir()
    (source / "A001.mxf").write_bytes(mxf(ARRIRAW_HDE))
    done = run("run", "--operation", "trim_run", "--set", "trim_action=keep", "--set", "trim_start=1", "--set", "trim_end=2",
               "--source", str(source), "--target", str(tmp_path / "out"), "--result", str(tmp_path / "told.json"))
    assert told(tmp_path)["outcome"] == "failed", done.stdout[-3000:]
    assert "[FAIL] A001.mxf: ARRIRAW HDE is not read by the program" in done.stdout
    assert "Traceback" not in done.stdout + done.stderr and not (tmp_path / "out").exists() or not any((tmp_path / "out").rglob("*.*"))


def test_files_no_operation_takes_are_said_and_the_rest_is_made(tmp_path: Path) -> None:
    if not FFMPEG.is_file():
        pytest.skip("no FFmpeg of the program in Tools")
    source = tmp_path / "in"
    source.mkdir()
    (source / "A001.braw").write_bytes(b"\0" * 64)
    clip(source, "B001.mov")
    target = tmp_path / "out"
    done = run("run", *STORAGE, "--source", str(source), "--target", str(target), "--result", str(tmp_path / "told.json"))
    assert told(tmp_path)["outcome"] == "done", done.stdout[-3000:]
    assert "[WARN] camera RAW: 1 file(s) of Blackmagic RAW are not taken (A001.braw)" in done.stdout
    assert "Blackmagic RAW Player (https://" in done.stdout
    assert [path.name for path in target.rglob("*.mp4") if "B001" in path.name]


def test_a_source_of_files_no_operation_takes_is_refused_with_them(tmp_path: Path) -> None:
    source = tmp_path / "in"
    source.mkdir()
    (source / "A001.R3D").write_bytes(b"\0" * 64)
    (source / "A002.R3D").write_bytes(b"\0" * 64)
    done = run("run", *STORAGE, "--source", str(source), "--target", str(tmp_path / "out"), "--result", str(tmp_path / "told.json"))
    assert told(tmp_path)["outcome"] == "refused", done.stdout[-3000:]
    assert "[ERROR] camera RAW: 2 file(s) of RED R3D are not taken (A001.R3D, A002.R3D)" in done.stdout
    assert "REDCINE-X PRO (https://" in done.stdout
