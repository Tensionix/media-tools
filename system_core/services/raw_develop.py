"""ProRes RAW developed on the video card: cineraw of libcraw (Tools\\cineraw, install\\Install-Cineraw.ps1) and FFmpeg.

cineraw decodes a ProRes RAW clip with FFmpeg and develops every frame on a Vulkan device as it was shot - the white
balance and the colour matrix of the camera - into BT.709 with the SDR roll-off of its highlights. The software decode
of ProRes RAW takes one core and 130 ms a frame, the card 3 ms (RTX 5070, MEMORY.md), so a clip is cut into ranges
and a cineraw runs for each, side by side.

No frame touches the disk. cineraw opens every frame by its name, and the name is a pipe of Windows this module made:
cineraw writes the frame (PFM, float RGB, 121 MB at 4.2K) into it and waits until it is read, the frame goes on into the
FFmpeg of its range (pfm_pipe on stdin), and the pipe of the next frame stands before cineraw asks for it. A range is a
piece in the workspace; the pieces are joined by the concat demuxer and the sound and the timecode of the source put
back: ProRes 4444 or DNxHR 444 for editing, H.264 or H.265 for viewing, BT.709 said in the file.

Two users: the operation RAW of ENCODE (develop_raw) and the operations that decode the picture of a source - ENCODE,
FRAME RATE, COLOUR - which take a ProRes RAW once it is developed into a ProRes 4444 master in the workspace
(develop_master); the run removes the masters when its service ends (release_masters, core\\jobs.py).
"""
from __future__ import annotations

import json
import math
import os
import shutil
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from fractions import Fraction
from pathlib import Path
from typing import Any

from system_core.core.camera_raw import raw_of
from system_core.core.jobs import JobContext, _ffmpeg_progress_bar, run_process
from system_core.core.path_cache import cached_output_path, cached_source_path

CINERAW_DIR = Path("Tools") / "cineraw"
# A Vulkan device in software: it develops, an hour for a minute of 24p (lavapipe on Iris Xe, MEMORY.md).
SOFTWARE_DEVICES = ("llvmpipe", "lavapipe", "swiftshader", "microsoft basic render")
PIPE_ROOT = "\\\\.\\pipe\\"
# BT.709 said twice: the matrix of the conversion from RGB, and the tags of every frame the encoder writes into the file.
BT709 = ("scale=out_color_matrix=bt709:out_range=tv:flags=accurate_rnd+full_chroma_int,format={pix_fmt},"
         "setparams=color_primaries=bt709:color_trc=bt709:colorspace=bt709:range=tv")

# What a development is written into: the codec of every range, the pixel format, the container, the sound.
TARGETS: dict[str, dict[str, Any]] = {
    "prores4444": {"label": "ProRes 4444", "folder": "prores4444", "ext": "mov", "pix_fmt": "yuv444p10le",
                   "video": ["-c:v", "prores_ks", "-profile:v", "4", "-vendor", "apl0"], "audio": ["-c:a", "copy"]},
    "dnxhr444": {"label": "DNxHR 444", "folder": "dnxhr444", "ext": "mov", "pix_fmt": "yuv444p10le",
                 "video": ["-c:v", "dnxhd", "-profile:v", "dnxhr_444"], "audio": ["-c:a", "copy"]},
    "h264": {"label": "H.264", "folder": "h264", "ext": "mp4", "pix_fmt": "yuv420p",
             "video": ["-c:v", "libx264", "-preset", "medium", "-crf", "16"], "audio": ["-c:a", "aac", "-b:a", "320k"],
             "nvenc": ["-c:v", "h264_nvenc", "-preset", "p6", "-tune", "hq", "-cq:v", "16", "-b:v", "0"]},
    "h265": {"label": "H.265 10-bit", "folder": "h265", "ext": "mp4", "pix_fmt": "yuv420p10le",
             "video": ["-c:v", "libx265", "-preset", "medium", "-x265-params", "crf=16:log-level=error", "-tag:v", "hvc1"],
             "audio": ["-c:a", "aac", "-b:a", "320k"],
             "nvenc": ["-c:v", "hevc_nvenc", "-preset", "p6", "-tune", "hq", "-cq:v", "16", "-b:v", "0", "-tag:v", "hvc1"],
             "nvenc_pix_fmt": "p010le"},
}
MASTER_TARGET = "prores4444"
_MASTERS: dict[str, Path] = {}
_MASTERS_LOCK = threading.Lock()


def cineraw(root: Path) -> Path:
    return Path(root) / CINERAW_DIR / "cineraw.exe"


def ready(root: Path) -> bool:
    """cineraw and its library are in Tools\\cineraw (SERVICE - Install ProRes RAW development)."""
    folder = Path(root) / CINERAW_DIR
    return sys.platform == "win32" and (folder / "cineraw.exe").is_file() and (folder / "libcraw.dll").is_file()


def version(root: Path) -> str:
    """"libcraw-0d44e6d" as Install-Cineraw.ps1 wrote it; "" when it is not installed."""
    try:
        told = json.loads((Path(root) / CINERAW_DIR / "cineraw-source.json").read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return "built" if ready(root) else ""
    return str(told.get("version") or "")


@dataclass
class Clip:
    frames: int
    rate: Fraction
    width: int
    height: int
    timecode: str
    duration: float


@dataclass
class _Range:
    index: int
    start: int
    count: int | None              # None - to the end of the clip
    piece: Path
    done: int = 0
    error: str = ""
    ended: bool = False            # cineraw has exited
    released: bool = False         # a waiting pipe was let go by the run, not by cineraw
    process: subprocess.Popen | None = None
    encoder: subprocess.Popen | None = None
    waiting: dict[int, Any] = field(default_factory=dict)
    thread: threading.Thread | None = None


def _creation() -> int:
    return getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0


def _tool_env(root: Path) -> dict[str, str]:
    """cineraw finds its DLLs beside it; nothing of a PATH of the machine is put before them."""
    environment = dict(os.environ)
    environment["PATH"] = str(Path(root) / CINERAW_DIR) + os.pathsep + environment.get("PATH", "")
    return environment


def probe_clip(root: Path, source: Path) -> Clip:
    from system_core.services.media_service import _ffprobe, _parse_fps

    done = subprocess.run([_ffprobe(Path(root)), "-v", "error", "-select_streams", "v:0", "-show_entries",
                           "stream=width,height,r_frame_rate,avg_frame_rate,duration:stream_tags=timecode:format=duration:format_tags=timecode",
                           "-of", "json", str(source)], capture_output=True, timeout=60, creationflags=_creation())
    data = json.loads((done.stdout or b"{}").decode("utf-8", errors="replace") or "{}")
    stream = (data.get("streams") or [{}])[0]
    rate = _parse_fps(str(stream.get("r_frame_rate") or stream.get("avg_frame_rate") or ""))
    duration = float(stream.get("duration") or (data.get("format") or {}).get("duration") or 0.0)
    timecode = str((stream.get("tags") or {}).get("timecode") or ((data.get("format") or {}).get("tags") or {}).get("timecode") or "")
    # The frames the edit list of the MOV shows, not the packets it holds: 8.714 s of 23.976 - 209, not 210.
    frames = max(1, int(round(duration * rate)))
    return Clip(frames, rate, int(stream.get("width") or 0), int(stream.get("height") or 0), timecode, duration)


def probe_device(root: Path, source: Path) -> tuple[str, str]:
    """The Vulkan device cineraw develops the clip on, and "" - or "" and why it would not: one frame developed and
    nothing written."""
    try:
        done = subprocess.run([str(cineraw(root)), "-v", "--frames", "1", str(source)], capture_output=True, timeout=180,
                              env=_tool_env(root), creationflags=_creation())
    except (OSError, subprocess.SubprocessError) as error:
        return "", f"cineraw did not run: {error}"
    said = ((done.stdout or b"") + b"\n" + (done.stderr or b"")).decode("utf-8", errors="replace")
    device = ""
    for line in said.splitlines():
        if line.startswith("craw: using "):
            device = line.split('"')[1] if line.count('"') >= 2 else line[len("craw: using "):].strip()
    last = [line.strip() for line in said.splitlines() if line.strip() and not line.startswith("warning: no camera recognized")]
    why = last[-1] if last else f"exit {done.returncode}"
    if not device and any("vulkan" in line.lower() or "device" in line.lower() for line in last):
        return "", f"cineraw found no video card it develops on: {why}"
    if done.returncode != 0 or not device:
        return "", f"cineraw did not develop the clip: {why}"
    if any(name in device.lower() for name in SOFTWARE_DEVICES):
        return "", (f"the only Vulkan device is {device}, a renderer in software: a minute of 24p would take about an hour. "
                    "cineraw needs a video card with Vulkan 1.4 that reads storage images without a format (NVIDIA RTX)")
    return device, ""


def workers(clip: Clip, asked: Any = "auto", encoder: str = "cpu") -> int:
    """How many cineraw run side by side: one core each for the decode of ProRes RAW, their FFmpeg the rest; never more
    ranges than a second of frames each would allow. A cineraw takes 0.8 s a frame of 4.2K (decode 130 ms, the frame
    off the card 355 ms, the SDR curve 320 ms); RTX 5070 and Ryzen 9 5900X, ProRes 4444: 2 - 2.2 fps, 4 - 3.8, 8 - 5.2,
    12 - 5.0 - auto is half the cores, eight at most. NVENC takes eight sessions of a GeForce at most."""
    try:
        count = int(asked)
    except (TypeError, ValueError):
        count = max(1, min(8, (os.cpu_count() or 4) // 2))
    if encoder == "nvenc":
        count = min(count, 8)
    seconds = max(1, int(clip.frames / max(1.0, float(clip.rate))))
    return max(1, min(count, 16, seconds))


# The widest picture H.264 of NVENC takes; HEVC of NVENC takes 8192.
NVENC_H264_WIDTH = 4096


def encoder_for(target: str, asked: str, clip: Clip) -> tuple[str, str]:
    """The encoder a development takes, and why it is not the one asked ("" when it is)."""
    if asked != "nvenc" or "nvenc" not in TARGETS[target]:
        return "cpu", ""
    if target == "h264" and clip.width > NVENC_H264_WIDTH:
        return "cpu", f"H.264 of NVENC takes {NVENC_H264_WIDTH} pixels across at most, the clip is {clip.width}: x264 on the processor"
    return "nvenc", ""


def ranges(frames: int, count: int) -> list[tuple[int, int | None]]:
    """The clip in `count` ranges as even as they come: (first frame, frames); the last runs to the end of the clip -
    the edit list of a MOV may end a frame before its packets do."""
    count = max(1, min(count, frames))
    base, extra = divmod(frames, count)
    out: list[tuple[int, int | None]] = []
    start = 0
    for index in range(count):
        size = base + (1 if index < extra else 0)
        out.append((start, None if index == count - 1 else size))
        start += size
    return out


def start_seconds(frame: int, rate: Fraction) -> str:
    """Where cineraw seeks for a frame. It starts at the first frame whose time is not before the one asked; asked a
    quarter of a frame early, rounding never lands on the frame after (a quarter late lost the first frame of every
    range but the first - 208 of 209, 20.10.2026)."""
    return f"{float((Fraction(frame) - Fraction(1, 4)) / rate):.6f}"


def encoder_args(target: str, encoder: str) -> tuple[list[str], str]:
    spec = TARGETS[target]
    if encoder == "nvenc" and "nvenc" in spec:
        return list(spec["nvenc"]), str(spec.get("nvenc_pix_fmt") or spec["pix_fmt"])
    return list(spec["video"]), str(spec["pix_fmt"])


def piece_command(ffmpeg: str, clip: Clip, target: str, encoder: str, piece: Path) -> list[str]:
    video, pix_fmt = encoder_args(target, encoder)
    rate = f"{clip.rate.numerator}/{clip.rate.denominator}"
    return [ffmpeg, "-hide_banner", "-loglevel", "error", "-nostats", "-y", "-f", "pfm_pipe", "-framerate", rate, "-i", "-",
            "-vf", BT709.format(pix_fmt=pix_fmt), *video, "-an", str(piece)]


def cineraw_command(root: Path, source: Path, clip: Clip, start: int, count: int | None, pattern: str) -> list[str]:
    command = [str(cineraw(root)), "--encode", "sdr", "--space", "bt709"]
    if start > 0:
        command += ["--start", start_seconds(start, clip.rate)]
    if count is not None:
        command += ["--frames", str(count)]
    return [*command, "-o", pattern, str(source)]


def join_command(ffmpeg: str, listing: Path, source: Path, target: str, clip: Clip, output: Path) -> list[str]:
    spec = TARGETS[target]
    command = [ffmpeg, "-hide_banner", "-stats", "-y", "-nostdin", "-f", "concat", "-safe", "0", "-i", str(listing),
               "-i", str(source), "-map", "0:v:0", "-map", "1:a?", "-c:v", "copy", *spec["audio"], "-map_metadata", "1"]
    if clip.timecode:
        command += ["-timecode", clip.timecode]
    return [*command, "-movflags", "+faststart", str(output)]


# --- the pipes of Windows: a frame of cineraw read without the disk ---------------------------------------------------

def _make_pipe(name: str):
    import _winapi

    # A byte pipe, inbound, one client; 4 MB of buffer - a frame is written in rows of 50 KB.
    return _winapi.CreateNamedPipe(name, _winapi.PIPE_ACCESS_INBOUND, _winapi.PIPE_WAIT, 1, 0, 4 << 20, 0, _winapi.NULL)


def _release_pipe(name: str) -> None:
    """A run that stops lets a pipe that waits for cineraw go: it connects to it itself and leaves at once."""
    import _winapi

    try:
        handle = _winapi.CreateFile(name, _winapi.GENERIC_WRITE, 0, _winapi.NULL, _winapi.OPEN_EXISTING, 0, _winapi.NULL)
        _winapi.CloseHandle(handle)
    except OSError:
        pass


def _close(handle: Any) -> None:
    import _winapi

    try:
        _winapi.CloseHandle(handle)
    except OSError:
        pass


def _relay(part: _Range, prefix: str, stop: threading.Event) -> None:
    """Frame by frame: the pipe of the next one stands before cineraw asks for it, the current one goes into the FFmpeg
    of the range as it is read."""
    import _winapi

    def name(k: int) -> str:
        return f"{prefix}-{k:05d}.pfm"

    try:
        k = 0
        if k not in part.waiting:
            part.waiting[k] = _make_pipe(name(k))
        while True:
            last = part.count is not None and k + 1 >= part.count
            if not last:
                part.waiting[k + 1] = _make_pipe(name(k + 1))
            handle = part.waiting[k]
            try:
                _winapi.ConnectNamedPipe(handle, False)
            except OSError as error:
                if error.winerror != 535:      # ERROR_PIPE_CONNECTED: cineraw came first - it is connected
                    raise
            got = 0
            while True:
                try:
                    data, _err = _winapi.ReadFile(handle, 4 << 20, False)
                except OSError as error:
                    if error.winerror == 109:  # ERROR_BROKEN_PIPE: cineraw closed the frame
                        break
                    raise
                if not data:
                    break
                got += len(data)
                part.encoder.stdin.write(data)
            _close(part.waiting.pop(k))
            if got == 0:
                # A pipe let go by the run (cineraw ended, or the run stops): no frame came.
                break
            part.done += 1
            k += 1
            if stop.is_set() or last:
                break
    except Exception as error:  # noqa: BLE001 - the range fails, the run says why
        if not part.error:
            part.error = f"{type(error).__name__}: {error}"
    finally:
        for handle in list(part.waiting.values()):
            _close(handle)
        part.waiting.clear()
        try:
            part.encoder.stdin.close()
        except (OSError, ValueError, AttributeError):
            pass


def _let_go(part: _Range, prefix: str) -> None:
    """The pipes of a range that still wait are let go: cineraw ended before them (the last range runs to the end)."""
    part.released = True
    for k in list(part.waiting.keys()):
        _release_pipe(f"{prefix}-{k:05d}.pfm")


def _stop_range(part: _Range, prefix: str) -> None:
    for process in (part.process, part.encoder):
        if process is not None and process.poll() is None:
            try:
                process.kill()
            except OSError:
                pass
    _let_go(part, prefix)


def develop(context: JobContext, source: Path, output: Path, *, target: str = MASTER_TARGET, encoder: str = "cpu",
            asked_workers: Any = "auto", label: str = "", clip: Clip | None = None) -> dict[str, Any]:
    """Develops one ProRes RAW into `output`. Returns what was done; raises RuntimeError with why it was not."""
    from system_core.services.media_service import _ffmpeg

    root = context.paths.root
    clip = clip or probe_clip(root, source)
    encoder, why = encoder_for(target, encoder, clip)
    if why:
        context.log(f"[NOTE] {label or source.name}: {why}")
    count = workers(clip, asked_workers, encoder)
    stages = context.paths.workspace / "raw_develop"
    # What a run before this one could not remove in time (a stopped run whose cineraw came down slowly) goes now.
    for old in stages.glob("*") if stages.is_dir() else []:
        if not old.name.startswith(f"{os.getpid()}-"):
            shutil.rmtree(old, ignore_errors=True)
    stage = stages / f"{os.getpid()}-{int(time.time() * 1000)}"
    stage.mkdir(parents=True, exist_ok=True)
    ext = TARGETS[target]["ext"]
    parts = [_Range(index, start, size, stage / f"piece{index:02d}.{ext}") for index, (start, size) in enumerate(ranges(clip.frames, count))]
    prefix = f"{PIPE_ROOT}audion-raw-{os.getpid()}-{stage.name}"
    stop = threading.Event()
    ffmpeg = _ffmpeg(root)
    label = label or source.name
    started = time.perf_counter()
    logs: list[Any] = []
    try:
        for part in parts:
            logs.append(open(stage / f"piece{part.index:02d}.ffmpeg.log", "wb"))
            part.encoder = subprocess.Popen(piece_command(ffmpeg, clip, target, encoder, part.piece), stdin=subprocess.PIPE,
                                            stdout=subprocess.DEVNULL, stderr=logs[-1], creationflags=_creation())
            # The pipe of the first frame stands before cineraw starts; the relay makes every next one ahead of it.
            part.waiting[0] = _make_pipe(f"{prefix}-{part.index:02d}-00000.pfm")
            part.thread = threading.Thread(target=_relay, args=(part, f"{prefix}-{part.index:02d}", stop), daemon=True)
            part.thread.start()
            logs.append(open(stage / f"piece{part.index:02d}.cineraw.log", "wb"))
            part.process = subprocess.Popen(cineraw_command(root, source, clip, part.start, part.count, f"{prefix}-{part.index:02d}-%05d.pfm"),
                                            stdout=logs[-1], stderr=subprocess.STDOUT, env=_tool_env(root), creationflags=_creation())
        context.log(f"[RAW] {label}: {clip.width}x{clip.height}, {clip.frames} frames at {float(clip.rate):.3f} - "
                    f"{len(parts)} ranges side by side, {TARGETS[target]['label']}")
        shown = 0.0
        while any(part.thread.is_alive() for part in parts):
            time.sleep(0.25)
            for part in parts:
                if not part.ended and part.process.poll() is not None:
                    part.ended = True
                    if part.process.returncode != 0 and not part.error:
                        part.error = f"cineraw exit {part.process.returncode}: {_tail(stage / f'piece{part.index:02d}.cineraw.log')}"
                    # A pipe still waits only when cineraw ended before it: let it go, the FFmpeg of the range finishes.
                    _let_go(part, f"{prefix}-{part.index:02d}")
                if part.encoder.poll() not in (None, 0) and not part.error:
                    part.error = f"FFmpeg exit {part.encoder.returncode}: {_tail(stage / f'piece{part.index:02d}.ffmpeg.log')}"
            failed = next((part for part in parts if part.error), None)
            if failed is not None or context.cancelled():
                stop.set()
                for part in parts:
                    _stop_range(part, f"{prefix}-{part.index:02d}")
                for part in parts:
                    part.thread.join(timeout=10)
                if failed is not None:
                    raise RuntimeError(f"range {failed.index + 1} of {len(parts)}: {failed.error}")
                raise _Stopped()
            done = sum(part.done for part in parts)
            now = time.perf_counter()
            if now - shown >= 1.0:
                shown = now
                rate = done / max(0.001, now - started)
                context.progress_inside(0.95 * done / clip.frames)
                context.log(_ffmpeg_progress_bar(f"{label} RAW", done / float(clip.rate), clip.frames / float(clip.rate), f"{rate:.1f} fps"))
        for part in parts:
            if part.encoder.wait(timeout=600) != 0:
                raise RuntimeError(f"range {part.index + 1}: FFmpeg exit {part.encoder.returncode}: "
                                   f"{_tail(stage / f'piece{part.index:02d}.ffmpeg.log')}")
            if part.process.wait(timeout=60) != 0:
                raise RuntimeError(f"range {part.index + 1}: cineraw exit {part.process.returncode}: "
                                   f"{_tail(stage / f'piece{part.index:02d}.cineraw.log')}")
            if part.error:
                raise RuntimeError(f"range {part.index + 1}: {part.error}")
            if part.count is not None and part.done != part.count:
                # A range in the middle short of its frames would leave a hole at its join.
                raise RuntimeError(f"range {part.index + 1}: cineraw gave {part.done} of {part.count} frames")
        developed = sum(part.done for part in parts)
        seconds = time.perf_counter() - started
        context.log(f"[RAW] {label}: {developed} frames developed in {seconds:.1f} s ({developed / max(seconds, 0.001):.1f} fps)")
        listing = stage / "pieces.txt"
        listing.write_text("".join(f"file '{part.piece.as_posix()}'\n" for part in parts if part.done), encoding="utf-8")
        run_process(context, join_command(ffmpeg, listing, source, target, clip, output), check=True, progress_seconds=600)
        context.progress_inside(1.0)
        return {"frames": developed, "seconds": round(seconds, 1), "ranges": len(parts), "target": target}
    finally:
        stop.set()
        for part in parts:
            _stop_range(part, f"{prefix}-{part.index:02d}")
            if part.thread is not None:
                part.thread.join(timeout=10)
            for process in (part.encoder, part.process):
                if process is not None:
                    try:
                        process.wait(timeout=30)
                    except subprocess.TimeoutExpired:
                        pass
        for handle in logs:
            handle.close()
        _remove(stage)


class _Stopped(Exception):
    """The run was stopped by the person while a clip developed."""


def _remove(folder: Path, seconds: float = 30.0) -> None:
    """The stage of a development, removed. A cineraw ended by the run is reported ended before Windows lets its files
    go - a Vulkan process takes a moment to come down: the removal is tried again for a few seconds."""
    deadline = time.monotonic() + seconds
    while True:
        shutil.rmtree(folder, ignore_errors=True)
        if not folder.exists() or time.monotonic() >= deadline:
            break
        time.sleep(0.25)
    try:
        folder.parent.rmdir()      # workspace\raw_develop, when no other development stands in it
    except OSError:
        pass


def _tail(path: Path) -> str:
    try:
        lines = [line.strip() for line in path.read_text(encoding="utf-8", errors="replace").splitlines() if line.strip()]
    except OSError:
        return ""
    lines = [line for line in lines if not line.startswith("warning: no camera recognized")]
    return lines[-1] if lines else ""


# --- the operation RAW of ENCODE -------------------------------------------------------------------------------------

def develop_raw(context: JobContext) -> dict[str, object]:
    from system_core.services.media_service import (_as_bool, _claim_target, _kept_in_place, _media_files,
                                                    _operation_output_folder, _output_path, _source_display_name)

    params = dict(context.operation.parameters)
    root = context.paths.root
    source_dir = cached_source_path(root)
    output_dir = cached_output_path(root)
    target = str(params.get("raw_target") or MASTER_TARGET)
    if target not in TARGETS:
        context.log(f"[ERROR] No such development: {target}")
        return {"files": 0, "failed": 1}
    encoder = "nvenc" if str(params.get("raw_encoder") or "cpu") == "nvenc" and "nvenc" in TARGETS[target] else "cpu"
    if not ready(root):
        context.log("[ERROR] cineraw is not installed: SERVICE - Install ProRes RAW development.")
        return {"files": 0, "failed": 1}
    files = []
    for path in _media_files(source_dir, {"mov", "mp4", "m4v"}):
        raw = raw_of(path)
        if raw and raw.kind == "prores_raw":
            files.append(path)
        else:
            context.log(f"[SKIP] {_source_display_name(path, source_dir)}: not ProRes RAW")
    if _as_bool(params.get("limit_first_file"), False):
        files = files[:1]
    if not files:
        context.log(f"No ProRes RAW in {source_dir}")
        return {"files": 0}
    overwrite = _as_bool(params.get("overwrite"), True)
    dry_run = _as_bool(params.get("dry_run"), False)
    processed = failed = skipped = 0
    device = ""
    context.units(len(files))
    for index, source in enumerate(files, start=1):
        label = _source_display_name(source, source_dir)
        if context.cancelled():
            context.log("RAW development cancelled by user.")
            return {"cancelled": True, "processed": processed}
        output = _output_path(source, output_dir, TARGETS[target]["folder"], TARGETS[target]["ext"], source_root=source_dir,
                              operation=_operation_output_folder(context, "RAW"))
        output = _claim_target(context, source, output)
        if _kept_in_place(context, output, overwrite):
            skipped += 1
            context.progress(index / len(files))
            continue
        clip = probe_clip(root, source)
        if dry_run:
            context.log(f"[DRY RUN] {label}: {clip.frames} frames, {workers(clip, params.get('raw_workers'))} ranges -> {output}")
            processed += 1
            continue
        if not device:
            device, why = probe_device(root, source)
            if not device:
                context.log(f"[FAIL] {label}: {why}")
                return {"files": len(files), "failed": len(files), "processed": 0}
            context.log(f"[RAW] cineraw {version(root)} on {device}")
        context.log(f"[{index}/{len(files)}] {label} -> {TARGETS[target]['label']}")
        try:
            develop(context, source, output, target=target, encoder=encoder, asked_workers=params.get("raw_workers"),
                    label=label, clip=clip)
        except _Stopped:
            context.log("RAW development cancelled by user.")
            return {"cancelled": True, "processed": processed}
        except RuntimeError as error:
            failed += 1
            context.log(f"[FAIL] {label}: {error}")
            context.progress(index / len(files))
            continue
        processed += 1
        context.progress(index / len(files))
    return {"processed": processed, "failed": failed, "skipped": skipped, "files": len(files), "target": target,
            "encoder": encoder, "device": device, "dry_run": dry_run}


# --- a ProRes RAW for the operations that decode the picture ---------------------------------------------------------

def develop_master(context: JobContext, source: Path, label: str = "") -> Path:
    """The ProRes RAW `source` developed into a ProRes 4444 master in the workspace, for a service that decodes the
    picture; the stem of the source is kept, so the result is named as the source. Raises RuntimeError."""
    root = context.paths.root
    device, why = probe_device(root, source)
    if not device:
        raise RuntimeError(why)
    folder = context.paths.workspace / "raw_master" / f"{os.getpid()}-{int(time.time() * 1000)}"
    folder.mkdir(parents=True, exist_ok=True)
    master = folder / f"{source.stem}.mov"
    context.log(f"[RAW] {label or source.name}: developed first on {device} into a ProRes 4444 master, then taken")
    try:
        develop(context, source, master, target=MASTER_TARGET, label=label or source.name)
    except _Stopped:
        raise RuntimeError("stopped by the user") from None
    with _MASTERS_LOCK:
        _MASTERS[str(master.resolve())] = source
    return master


def original_of(path: Path) -> Path:
    """The ProRes RAW a master was developed from; the path itself for any other."""
    with _MASTERS_LOCK:
        return _MASTERS.get(str(Path(path).resolve()), Path(path))


def release_masters(workspace: Path) -> None:
    """The masters of this run, removed when its service ends."""
    with _MASTERS_LOCK:
        masters = list(_MASTERS)
        _MASTERS.clear()
    for master in masters:
        shutil.rmtree(Path(master).parent, ignore_errors=True)
    shutil.rmtree(Path(workspace) / "raw_master", ignore_errors=True)
