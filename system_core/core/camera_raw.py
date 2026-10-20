"""Camera RAW the program does not develop, how a file of it is known, and the line that says what opens it. ProRes RAW
the program develops after all once cineraw is installed (develops, services\\raw_develop.py) - on a video card.

FFmpeg develops none of it. ProRes RAW it reads as the signal of the sensor: no white balance, no colour matrix of the
camera are applied (they ride with every frame from 9.0 on, and no filter of FFmpeg takes them), and before 9.0 the tones
are distorted too - a run that decodes the picture gave a flat green frame; a trim, a remux and the sound copy the
stream as it is and take it. ARRIRAW, Sony RAW / X-OCN, RED R3D, Nikon N-RAW, Blackmagic RAW and Canon Cinema RAW it does
not read at all: the video of an ARRIRAW MXF does not even copy into MOV, MKV or MXF ("dimensions not set").

The kinds, why, and the programs with their download pages are data: config\\camera_raw.yaml. A file is known

  - ProRes RAW - by the codec the 'stsd' of its MOV header names: 'aprn', 'aprh';
  - ARRIRAW in MXF - by the label of its picture, 04.01.02.01.02.01.01 (02 - HDE), read from the header of the ALEXA 35
    sample and named so by MediaInfo (File_Mxf.cpp);
  - Sony RAW / X-OCN in MXF - by a label of the picture in Sony's own range (0E.06; MediaInfo names 0E.06.04.01.02.04.02
    "Sony RAW SQ") when FFmpeg does not know the codec: its XAVC and XDCAM carry public labels;
  - the others - by the kind of their files (.ari, .arx, .r3d, .nev, .braw, .crm, .rmf), which no operation takes.

A few reads of the header, the picture is not touched.
"""
from __future__ import annotations

import os
import struct
import subprocess
import sys
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable

import yaml

TABLE = Path(__file__).resolve().parents[2] / "config" / "camera_raw.yaml"
RAW_CODECS = {b"aprn": "ProRes RAW", b"aprh": "ProRes RAW HQ"}
# The services that decode the picture refuse every camera RAW; the ones that copy the stream refuse what FFmpeg
# does not read.
PICTURE_SERVICES = frozenset({"encode_targets", "fps_convert", "run_color_grade"})
COPY_SERVICES = frozenset({"remux_media", "trim_media"})
_MOVS = frozenset({".mov", ".mp4", ".m4v"})
# The most of a header read: the moov of an hour of 4K is a few megabytes, the header metadata of an MXF less.
_HEADER_MOST = 64 << 20
_MXF_HEADER_MOST = 8 << 20
_ARRIRAW = {0x01: "ARRIRAW", 0x02: "ARRIRAW HDE"}


@dataclass(frozen=True)
class Raw:
    kind: str     # the kind of config\camera_raw.yaml
    name: str     # as the file says it: "ProRes RAW HQ", "ARRIRAW HDE"
    read: bool    # FFmpeg reads the stream: a trim, a remux and the sound take it


@lru_cache(maxsize=1)
def table() -> dict[str, Any]:
    with open(TABLE, encoding="utf-8") as file:
        data = yaml.safe_load(file) or {}
    return {"programs": dict(data.get("programs") or {}), "kinds": dict(data.get("kinds") or {})}


def raw_files() -> dict[str, str]:
    """The kinds of files of camera RAW no operation takes, each with its kind: ".braw" -> "braw"."""
    return {str(suffix).lower(): kind for kind, entry in table()["kinds"].items() for suffix in entry.get("files") or []}


def _name(kind: str) -> str:
    return str(table()["kinds"].get(kind, {}).get("name") or kind)


def hint(raw: Raw) -> str:
    """Why FFmpeg does not develop it and what opens it - the pages of config\\camera_raw.yaml."""
    entry = table()["kinds"].get(raw.kind, {})
    programs = table()["programs"]
    named = [f"{programs[key]['name']} ({programs[key]['page']})" for key in entry.get("open") or [] if key in programs]
    why = str(entry.get("why") or "FFmpeg does not decode it")
    line = f"{why}; open it in {' or '.join(named)} and render ProRes 4444 or DNxHR 444 for the program"
    if raw.kind == "prores_raw":
        line += "; on a machine with NVIDIA RTX the program develops it itself - SERVICE: Install ProRes RAW development"
    return line + (" - a trim, a remux and the sound take it as it is" if raw.read else "")


def refuses(service: str, raw: Raw) -> bool:
    return service in PICTURE_SERVICES or (service in COPY_SERVICES and not raw.read)


# cineraw of libcraw (SERVICE - Install ProRes RAW development, install\Install-Cineraw.ps1).
CINERAW = Path("Tools") / "cineraw"


def develops(root: Path, service: str, raw: Raw) -> bool:
    """A ProRes RAW an operation that decodes the picture takes after all: cineraw is installed and develops it on the
    video card first, into a ProRes 4444 master the operation reads (services\\raw_develop.py). AUDION_CINERAW=off - a run
    that refuses it as without cineraw (the tests of the refusal on a machine that has it)."""
    if os.environ.get("AUDION_CINERAW", "").strip().lower() in {"0", "off", "no"}:
        return False
    folder = Path(root) / CINERAW
    return (raw.kind == "prores_raw" and service in PICTURE_SERVICES and (folder / "cineraw.exe").is_file()
            and (folder / "libcraw.dll").is_file())


def ffmpeg_reads(ffprobe: str) -> Callable[[Path], bool]:
    """Whether FFmpeg knows the codec of the video of a file: what ffprobe names it."""
    creation = getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0

    def reads(path: Path) -> bool:
        try:
            done = subprocess.run([ffprobe, "-v", "quiet", "-select_streams", "v:0", "-show_entries", "stream=codec_name",
                                   "-of", "default=nw=1:nk=1", str(path)], capture_output=True, timeout=60, creationflags=creation)
        except (OSError, subprocess.SubprocessError):
            return False
        codec = (done.stdout or b"").decode("utf-8", errors="replace").strip().lower()
        return codec not in {"", "unknown", "none"}

    return reads


def raw_of(path: Path, reads: Callable[[Path], bool] | None = None) -> Raw | None:
    """The camera RAW a file is; None for any other. `reads` - whether FFmpeg knows its codec (ffmpeg_reads): it settles
    a label of Sony's own range; without it the label alone does."""
    path = Path(path)
    suffix = path.suffix.lower()
    if suffix in raw_files():
        kind = raw_files()[suffix]
        return Raw(kind, _name(kind), False)
    if suffix in _MOVS:
        name = _mov_codec(path)
        return Raw("prores_raw", name, True) if name else None
    if suffix == ".mxf":
        found = _mxf_picture(path)
        if found is None:
            return None
        kind, name = found
        if kind == "sony_raw" and reads is not None and reads(path):
            return None
        return Raw(kind, name, False)
    return None


def camera_raw(path: Path) -> str:
    """The name of the camera RAW a file is ("ProRes RAW HQ", "ARRIRAW"); "" for any other."""
    raw = raw_of(path)
    return raw.name if raw else ""


def stray_raw(source: Path) -> dict[str, list[Path]]:
    """The files of camera RAW in the Source that no operation takes, by kind."""
    source = Path(source)
    kinds = raw_files()
    found: dict[str, list[Path]] = {}
    if source.is_file():
        candidates = [source]
    elif source.is_dir():
        candidates = sorted(path for path in source.rglob("*") if path.suffix.lower() in kinds and path.is_file())
    else:
        candidates = []
    for path in candidates:
        if path.suffix.lower() in kinds:
            found.setdefault(kinds[path.suffix.lower()], []).append(path)
    return found


def _mov_codec(path: Path) -> str:
    """The top boxes of a MOV walked by their sizes to its header ('moov'), the codec of every track read where 'stsd'
    names it."""
    try:
        with open(path, "rb") as file:
            size = os.fstat(file.fileno()).st_size
            at = 0
            while at + 8 <= size:
                file.seek(at)
                head = file.read(16)
                if len(head) < 8:
                    return ""
                length, kind = struct.unpack(">I4s", head[:8])
                if length == 1 and len(head) == 16:
                    length = struct.unpack(">Q", head[8:16])[0]
                elif length == 0:
                    length = size - at
                if length < 8:
                    return ""
                if kind == b"moov":
                    file.seek(at)
                    header = file.read(min(length, _HEADER_MOST))
                    # stsd: size, 'stsd', version and flags, the number of entries; then an entry: its size, its codec.
                    found = header.find(b"stsd")
                    while found >= 0:
                        codec = header[found + 16:found + 20]
                        if codec in RAW_CODECS:
                            return RAW_CODECS[codec]
                        found = header.find(b"stsd", found + 4)
                    return ""
                at += length
    except OSError:
        return ""
    return ""


def _mxf_picture(path: Path) -> tuple[str, str] | None:
    """The camera RAW the header of an MXF names in its descriptors: the Picture Essence Coding (local tag 3201) and the
    Essence Container (3004) of each local set. The KLVs are walked by their lengths: only the local sets are read."""
    try:
        with open(path, "rb") as file:
            at = 0
            while at < _MXF_HEADER_MOST:
                file.seek(at)
                head = file.read(25)
                if len(head) < 17 or head[:4] != b"\x06\x0e\x2b\x34":
                    return None
                key, first = head[:16], head[16]
                if first < 0x80:
                    length, body = first, at + 17
                else:
                    count = first & 0x7F
                    if count > 8 or len(head) < 17 + count:
                        return None
                    length, body = int.from_bytes(head[17:17 + count], "big"), at + 17 + count
                # The header ends where the essence begins: a body partition or an element of the picture or sound.
                if (key[4] == 0x02 and key[5] == 0x05 and key[13] == 0x03) or (key[4] == 0x01 and key[5] == 0x02):
                    return None
                # A local set (06 0E 2B 34 02 53): two-byte tags, two-byte lengths.
                if key[4] == 0x02 and key[5] == 0x53 and length < 1 << 20:
                    file.seek(body)
                    found = _raw_in_set(file.read(length))
                    if found:
                        return found
                at = body + length
    except OSError:
        return None
    return None


def _raw_in_set(value: bytes) -> tuple[str, str] | None:
    i = 0
    while i + 4 <= len(value):
        tag, size = struct.unpack(">HH", value[i:i + 4])
        label = value[i + 4:i + 4 + size]
        if tag == 0x3201 and len(label) == 16:
            if label[8:14] == b"\x04\x01\x02\x01\x02\x01" and label[14] in _ARRIRAW:
                return "arriraw", _ARRIRAW[label[14]]
            if label[8:10] == b"\x0e\x06":
                return "sony_raw", _name("sony_raw")
        if tag == 0x3004 and len(label) == 16 and label[8:10] == b"\x0e\x06":
            return "sony_raw", _name("sony_raw")
        i += 4 + size
    return None
