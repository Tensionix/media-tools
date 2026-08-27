from __future__ import annotations

import array
import warnings

try:  # Removed in Python 3.13; the peak scan falls back to pure Python without it.
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        import audioop as _audioop
except ImportError:  # pragma: no cover - depends on the interpreter version
    _audioop = None
import math
import threading
import time
from pathlib import Path
from typing import Any, Callable
from fractions import Fraction
import base64
import hashlib
import importlib
import json
import os
import platform
import re
import shutil
import subprocess

from system_core.core.ansi_terminal import ansi_status
from system_core.core.audio_contract import (
    mp3_encoder_args,
    mp3_preset_label,
    normalize_mp3_preset,
    normalize_sample_rate,
    resample_filter_args,
    soxr_resample_filter,
)
from system_core.core.encoder_backends import (
    AMF_QUALITY_PRESETS,
    CPU_ENCODER_PRESETS,
    NVENC_PRESETS,
    QSV_ENCODER_PRESETS,
    decode_args as _backend_decode_args,
    decode_backend_from_params as _decode_backend,
    decode_label as _backend_decode_label,
    encode_backend_from_params as _encode_backend,
    can_keep_frames_on_gpu,
    decode_output_format_args,
    hardware_pix_fmt,
    normalize_amf_quality,
    normalize_cpu_preset,
    normalize_nvenc_preset,
    normalize_qsv_preset,
    target_for_backend as _target_for_backend,
)
from system_core.core.ffmpeg_escape import ffmpeg_filter_number, ffmpeg_filter_path
from system_core.core.fps_contract import (
    build_fps_command as _build_fps_command,
    fps_audio_filter as _fps_audio_filter,
    fps_audio_output_rate as _fps_audio_output_rate,
    fps_audio_target_rate as _fps_audio_target_rate,
    fps_oversample_factor as _fps_oversample_factor,
    fps_pcm_audio_args as _fps_pcm_audio_args,
)
from system_core.core.jobs import JobContext, hidden_subprocess_kwargs, run_cmd_script, run_process, utf8_subprocess_env
from system_core.core.logging_utils import timestamp
from system_core.core.manifest import CommandNode, load_manifest
from system_core.core.path_cache import cached_output_path, cached_source_path
from system_core.core.script_profiles import load_script_profiles, script_profile
from system_core.core.trim_contract import (
    audio_channel_complaint,
    audio_channel_filter,
    audio_reencode_args,
    build_trim_command,
    format_offset,
    format_seconds,
    frames_to_seconds,
    is_variable_rate,
    keyframe_probe_command,
    nearest_keyframe,
    extra_stream_plan,
    parse_keyframe_times,
    plan_gap,
    parse_rate,
    parse_seconds,
    plan_cut,
    rate_label,
    seconds_to_frames,
    shift_timecode,
    timecode_is_drop_frame,
    zero_timecode,
)
from system_core.core.video_contract import scale_filter


VIDEO_CONTAINER_EXTENSIONS = {
    "mp4",
    "m4v",
    "mov",
    "mkv",
    "mxf",
    "avi",
    "webm",
    "mpg",
    "mpeg",
    "mts",
    "m2ts",
    "ts",
    "3gp",
}

PURE_AUDIO_EXTENSIONS = {
    "wav",
    "w64",
    "flac",
    "m4a",
    "m4b",
    "aac",
    "mp3",
    "opus",
    "oga",
    "ogg",
    "aif",
    "aiff",
    "caf",
    "au",
    "snd",
    "ac3",
    "eac3",
    "dts",
    "mka",
    "ape",
    "wv",
    "tak",
    "tta",
    "mpc",
    "mpc8",
    "amr",
    "awb",
    "spx",
    "dsf",
    "dff",
}

MEDIA_EXTENSIONS = VIDEO_CONTAINER_EXTENSIONS | PURE_AUDIO_EXTENSIONS

# FFmpeg output that means "this machine has no such hardware", not "the project is broken".
# Hardware smoke tests and the preset matrix must classify these as MISS.
HARDWARE_UNAVAILABLE_MARKERS = (
    "cannot load nvcuda.dll",
    "nvcuda.dll",
    "no capable devices found",
    "no cuda capable devices found",
    "amfrt64.dll failed",
    "amfrt64.dll",
    "amf failed",
    "failed to create hardware device context",
    "failed to create  hardware device context",
    "error initializing an internal mfx session",
    "error creating a mfx session",
    "current codec type is unsupported",
    "no device available",
    "device creation failed",
    "unsupported device",
    "no hardware device available",
)


def _as_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, tuple):
        return [str(item).strip() for item in value if str(item).strip()]
    if value is None or value == "":
        return []
    return [str(value).strip()]


def _as_bool(value: Any, default: bool = False) -> bool:
    if value is None or value == "":
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on", "да"}


def _as_int(value: Any, default: int) -> int:
    try:
        return int(float(str(value).strip()))
    except (TypeError, ValueError):
        return default


def _as_float(value: Any, default: float) -> float:
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return default


def _tool_env(root: Path) -> dict[str, str]:
    paths = [
        root / "Tools" / "ffmpeg" / "bin",
        root / "Tools" / "yt-dlp" / "bin",
        root / "Tools" / "deno",
        root / "Tools" / "deno" / "bin",
        root / "Tools" / "7zip" / "bin",
        root / "Tools" / "fzf" / "bin",
    ]
    existing = [str(path) for path in paths if path.exists()]
    return {"PATH": os.pathsep.join([*existing, os.environ.get("PATH", "")])}


def _resolve_tool(root: Path, candidates: list[Path], fallback: str) -> str:
    for candidate in candidates:
        if candidate.exists():
            return str(candidate)
    resolved = shutil.which(fallback)
    return resolved or fallback


def _ffmpeg(root: Path) -> str:
    return _resolve_tool(root, [root / "Tools" / "ffmpeg" / "bin" / "ffmpeg.exe"], "ffmpeg")


def _ffprobe(root: Path) -> str:
    return _resolve_tool(root, [root / "Tools" / "ffmpeg" / "bin" / "ffprobe.exe"], "ffprobe")


def _yt_dlp(root: Path) -> str:
    return _resolve_tool(
        root,
        [root / "Tools" / "yt-dlp" / "bin" / "yt-dlp.exe"],
        "yt-dlp",
    )


def _deno(root: Path) -> str | None:
    for candidate in [root / "Tools" / "deno" / "deno.exe", root / "Tools" / "deno" / "bin" / "deno.exe"]:
        if candidate.exists():
            return str(candidate)
    return shutil.which("deno", path=_tool_env(root)["PATH"])


def _normalize_extensions(values: list[str]) -> set[str]:
    if not values:
        values = ["mp4", "mov", "mkv", "mxf"]
    result: set[str] = set()
    for value in values:
        clean = value.strip().lower().lstrip(".")
        if clean:
            result.add(clean)
    return result


def _media_files(source: Path, extensions: set[str]) -> list[Path]:
    if not source.exists():
        return []
    if source.is_file():
        return [source] if source.suffix.lower().lstrip(".") in extensions else []
    return sorted(
        path
        for path in source.rglob("*")
        if path.is_file() and path.suffix.lower().lstrip(".") in extensions
    )


def _safe_suffix(value: str) -> str:
    return "".join(char if char.isalnum() or char in {"-", "_"} else "_" for char in value).strip("_")


def _source_relative_parent(source: Path, source_root: Path | None) -> Path:
    if source_root is None:
        return Path()
    try:
        return source.resolve().parent.relative_to(source_root.resolve())
    except (OSError, ValueError):
        return Path()


def _source_display_name(source: Path, source_root: Path | None = None) -> str:
    if source_root is not None:
        try:
            return source.resolve().relative_to(source_root.resolve()).as_posix()
        except (OSError, ValueError):
            pass
    return source.name


def _output_path(source: Path, output_dir: Path, suffix: str, extension: str, *, source_root: Path | None = None, operation: str = "") -> Path:
    clean_operation = _safe_suffix(operation)
    clean_suffix = _safe_suffix(suffix)
    target_dir = output_dir
    if clean_operation:
        target_dir = target_dir / clean_operation
    if clean_suffix:
        target_dir = target_dir / clean_suffix
    target_dir = target_dir / _source_relative_parent(source, source_root)
    target_dir.mkdir(parents=True, exist_ok=True)
    name = f"{source.stem}.{extension.lstrip('.')}"
    return target_dir / name


OPERATION_OUTPUT_FOLDERS = {
    "archive_run": "Archive",
    "editing_run": "Editing",
    "storage_run": "Storage",
    "delivery_run": "Delivery",
    "audio_run": "Audio",
    "remux_run": "Remux",
    "fps_run": "FPS",
    "grading_run": "Color",
}


def _operation_output_folder(context: JobContext, fallback: str = "") -> str:
    return OPERATION_OUTPUT_FOLDERS.get(context.operation.id, fallback)


def _target_family_output_folder(family: str) -> str:
    return {
        "archive": "Archive",
        "editing": "Editing",
        "storage": "Storage",
        "delivery": "Delivery",
    }.get(str(family).strip().lower(), "Encode")


def _cpu_encoder_preset(params: dict[str, Any], default: str = "medium") -> str:
    return normalize_cpu_preset(params.get("cpu_encoder_preset") or params.get("encoder_preset") or default, default)


def _nvenc_preset(params: dict[str, Any], default: str = "p6") -> str:
    return normalize_nvenc_preset(params.get("nvenc_preset") or params.get("encoder_preset") or default, default)


def _qsv_encoder_preset(params: dict[str, Any], default: str = "medium") -> str:
    return normalize_qsv_preset(params.get("qsv_encoder_preset") or params.get("encoder_preset") or default, default)


def _amf_quality(params: dict[str, Any], default: str = "quality") -> str:
    return normalize_amf_quality(params.get("amf_quality") or params.get("encoder_preset") or default, default)


def _source_bit_depth(root: Path, source: Path | None) -> int:
    """Bit depth of the first video stream, used to pick a download format."""
    if source is None:
        return 8
    try:
        video = _stream(_probe_media_json(root, source), "video")
    except Exception:
        return 8
    for key in ("bits_per_raw_sample", "bits_per_sample"):
        try:
            depth = int(video.get(key) or 0)
        except (TypeError, ValueError):
            depth = 0
        if depth > 0:
            return depth
    pix_fmt = str(video.get("pix_fmt") or "")
    return 10 if any(token in pix_fmt for token in ("10", "12", "16")) else 8


def _decode_args(
    params: dict[str, Any],
    context: JobContext,
    *,
    has_video_filters: bool = False,
    source: Path | None = None,
) -> list[str]:
    backend = _decode_backend(params)
    args = _backend_decode_args(backend)
    if backend == "dav1d":
        context.log("AV1 decode: libdav1d")
    elif args:
        context.log(f"Hardware decode: {_backend_decode_label(backend)}")
    else:
        context.log("Hardware decode: CPU/auto")
    output_format = decode_output_format_args(
        backend,
        _encode_backend(params),
        pix_fmt=params.get("pix_fmt", "auto"),
        has_video_filters=has_video_filters,
        source_bit_depth=_source_bit_depth(context.paths.root, source),
    )
    if output_format:
        on_gpu = can_keep_frames_on_gpu(
            backend,
            _encode_backend(params),
            pix_fmt=params.get("pix_fmt", "auto"),
            has_video_filters=has_video_filters,
        )
        where = "stay in GPU memory between decode and encode" if on_gpu else "are downloaded for filtering/encoding"
        context.log(f"Decode frames {where} as {output_format[1]}")
    return [*args, *output_format]


def _mp3_lame_preset(params: dict[str, Any]) -> str:
    return normalize_mp3_preset(params.get("mp3_lame_preset", "v0"))


def _audio_bitrate(params: dict[str, Any], default: str = "384k") -> str:
    value = str(params.get("audio_bitrate", default)).strip().lower()
    if value in {"192", "256", "320", "384"}:
        value = f"{value}k"
    if value not in {"192k", "256k", "320k", "384k"}:
        return default
    return value


def _opus_bitrate(params: dict[str, Any]) -> str:
    bitrate = _audio_bitrate(params)
    try:
        kbps = int(str(bitrate).removesuffix("k"))
    except ValueError:
        return "256k"
    return f"{min(kbps, 256)}k"


def _audio_args(mode: str, bitrate: str = "384k", mp3_preset: str = "v0") -> list[str]:
    if mode == "none":
        return ["-an"]
    if mode in {"source", "native", "original"}:
        return ["-c:a", "copy"]
    if mode == "copy":
        return ["-c:a", "copy"]
    if mode == "mp3":
        # The LAME preset scale is the same one the Audio page offers, so MP3
        # cannot mean two different things depending on which page asked for it.
        return mp3_encoder_args(mp3_preset, bitrate)
    if mode == "flac":
        # Level 8 everywhere: the audio workflow, the CLI runner and this video
        # path must not encode the same FLAC differently.
        return ["-c:a", "flac", "-compression_level", "8"]
    if mode == "pcm_s24":
        return ["-c:a", "pcm_s24le"]
    if mode == "pcm_s16":
        return ["-c:a", "pcm_s16le"]
    if mode == "pcm_f32":
        return ["-c:a", "pcm_f32le"]
    return ["-c:a", "aac", "-b:a", bitrate]


def _container_audio_mode(extension: str, mode: str) -> str:
    container = str(extension or "").strip().lower()
    audio_mode = str(mode or "source").strip().lower()
    if container == "mxf" and audio_mode not in {"pcm_s16", "pcm_s24", "none"}:
        raise RuntimeError("MXF editing output requires PCM 16-bit, PCM 24-bit, or no audio.")
    # The MOV muxer answers "flac only supported in MP4"; without this the run
    # reaches FFmpeg and dies on an invalid header.
    if container == "mov" and audio_mode == "flac":
        raise RuntimeError("MOV output cannot hold FLAC audio. Choose MP4 or MKV for FLAC, or PCM for MOV.")
    return audio_mode


def _audio_sample_rate(params: dict[str, Any]) -> str:
    return normalize_sample_rate(params.get("audio_sample_rate", "48000"))


def _encode_audio_filter_args(params: dict[str, Any], audio_mode: str) -> list[str]:
    if "audio_sample_rate" not in params:
        return []
    return resample_filter_args(params.get("audio_sample_rate"), audio_mode)


def _audio_resampler(params: dict[str, Any]) -> str:
    value = str(params.get("audio_resampler", "soxr")).strip().lower()
    if value in {"sox", "soxr", "libsoxr", "swr", "ffmpeg", "auto", ""}:
        return "soxr"
    return "soxr"


def _audio_bit_depth(params: dict[str, Any]) -> str:
    value = str(params.get("audio_bit_depth", "24")).strip().lower()
    if value in {"source", "native", "original", "auto", ""}:
        return "source"
    if value in {"16", "16bit", "s16"}:
        return "16"
    if value in {"32f", "float", "f32", "32float"}:
        return "32f"
    return "24"


def _audio_lufs_target(params: dict[str, Any]) -> str:
    value = str(params.get("audio_lufs", "off")).strip().lower()
    if value in {"", "off", "none", "no", "false"}:
        return "off"
    if value not in {"-14", "-16", "-23"}:
        return "off"
    return value


def _audio_lufs_mode(params: dict[str, Any]) -> str:
    mode = str(params.get("audio_lufs_mode", "")).strip().lower()
    if mode in {"report", "report_only", "analyze"}:
        return "report"
    if mode in {"one_pass", "one-pass", "1pass"}:
        return "one_pass"
    if mode in {"two_pass", "two-pass", "2pass"}:
        return "two_pass"
    if _audio_lufs_target(params) != "off" and not mode:
        return "one_pass"
    return "off"


def _audio_lufs_true_peak(target: str) -> str:
    return "-2" if target == "-23" else "-1.5"


def _audio_lufs_filter(params: dict[str, Any], measured: dict[str, Any] | None = None) -> tuple[str, str]:
    value = _audio_lufs_target(params)
    if value == "off":
        return "", ""
    true_peak = _audio_lufs_true_peak(value)
    suffix = f"lufs{value.replace('-', '')}"
    if measured:
        parts = [
            f"I={value}",
            f"TP={true_peak}",
            "LRA=11",
            f"measured_I={measured.get('input_i')}",
            f"measured_TP={measured.get('input_tp')}",
            f"measured_LRA={measured.get('input_lra')}",
            f"measured_thresh={measured.get('input_thresh')}",
            f"offset={measured.get('target_offset')}",
            "linear=true",
            "print_format=summary",
        ]
        return "loudnorm=" + ":".join(str(item) for item in parts), f"{suffix}_2pass"
    return f"loudnorm=I={value}:TP={true_peak}:LRA=11", suffix


def _audio_filter_args(params: dict[str, Any], lufs_override: str = "", *, include_lufs: bool = True) -> tuple[list[str], list[str]]:
    channel_mode = str(params.get("audio_channel_mode", "")).strip().lower()
    if _as_bool(params.get("downmix_stereo"), False) and not channel_mode:
        channel_mode = "stereo"
    channel_mode = channel_mode or "keep"
    matrix = _as_bool(params.get("matrix_51"), False) and channel_mode == "stereo"
    downmix = matrix or channel_mode in {"stereo", "mono", "dual_mono"}
    filters: list[str] = []
    suffixes: list[str] = []
    sample_rate = _audio_sample_rate(params)

    if matrix:
        filters.append("aresample=matrix_encoding=dplii")
        suffixes.append("dplii")

    if sample_rate != "source":
        filters.append(soxr_resample_filter(sample_rate))
        suffixes.append("soxr")

    if include_lufs:
        if lufs_override:
            filters.append(lufs_override)
            suffixes.append("lufs2pass")
        elif _audio_lufs_mode(params) == "one_pass":
            lufs_filter, lufs_suffix = _audio_lufs_filter(params)
            if lufs_filter:
                filters.append(lufs_filter)
                suffixes.append(lufs_suffix)

    args: list[str] = []
    if channel_mode == "dual_mono":
        filters.append("pan=stereo|c0=0.5*c0+0.5*c1|c1=0.5*c0+0.5*c1")
        suffixes.append("dualmono")
    if filters:
        args.extend(["-af", ",".join(filters)])
    if downmix:
        if channel_mode == "mono":
            args.extend(["-ac", "1"])
            suffixes.append("mono")
        elif channel_mode != "dual_mono":
            args.extend(["-ac", "2"])
            if "stereo" not in suffixes:
                suffixes.append("stereo")
    return args, suffixes


def _audio_stream_channels(row: dict[str, Any] | None) -> int:
    if not row:
        return 0
    try:
        return int(float(str(row.get("channels", "")).strip()))
    except (TypeError, ValueError):
        pass
    layout = str(row.get("channel_layout") or "").strip().lower()
    if layout in {"mono", "1.0"}:
        return 1
    if layout in {"stereo", "2.0"}:
        return 2
    match = re.search(r"(\d+)\.(\d+)", layout)
    if match:
        return int(match.group(1)) + int(match.group(2))
    return 0


def _audio_copy_container(params: dict[str, Any]) -> str:
    value = str(params.get("audio_copy_container", "auto") or "auto").strip().lower()
    aliases = {
        "source": "auto",
        "codec": "elementary",
        "raw": "elementary",
        "native": "elementary",
        "matroska": "mka",
    }
    value = aliases.get(value, value)
    return value if value in {"auto", "elementary", "m4a", "mka"} else "auto"


def _audio_copy_extension(params: dict[str, Any], row: dict[str, Any] | None) -> str:
    codec = str((row or {}).get("codec") or "").strip().lower()
    channels = _audio_stream_channels(row)
    policy = _audio_copy_container(params)

    if policy == "mka":
        return "mka"
    if policy == "m4a":
        return "m4a" if codec in {"aac", "alac"} else "mka"

    elementary_by_codec = {
        "aac": "aac",
        "aac_latm": "mka",
        "ac3": "ac3",
        "eac3": "eac3",
        "dts": "dts",
        "truehd": "thd",
        "mlp": "mlp",
        "mp3": "mp3",
        "flac": "flac",
        "opus": "opus",
        "vorbis": "ogg",
        "alac": "m4a",
    }
    if policy == "elementary":
        return elementary_by_codec.get(codec, "mka")

    if codec == "aac":
        return "mka" if channels > 2 else "m4a"
    if codec == "aac_latm":
        return "mka"
    if codec == "alac":
        return "m4a"
    if codec in {"ac3", "eac3", "dts", "truehd", "mlp", "mp3", "flac", "opus", "vorbis"}:
        return elementary_by_codec[codec]
    if codec.startswith("pcm_"):
        return "wav"
    if codec.startswith("dsd_"):
        return "mka"
    return "mka"


def _audio_builder_args(
    params: dict[str, Any],
    lufs_override: str = "",
    *,
    include_lufs: bool = True,
    audio_only: bool = True,
    stream_row: dict[str, Any] | None = None,
) -> tuple[list[str], str, str]:
    audio_format = str(params.get("audio_format", "wav")).strip().lower() or "wav"
    bitrate = _audio_bitrate(params)
    sample_rate = _audio_sample_rate(params)
    bit_depth = _audio_bit_depth(params)

    base_args = ["-map_metadata", "0"]
    if audio_only:
        base_args = ["-vn", "-sn", "-dn", *base_args]
    if audio_format == "copy":
        return [*base_args, "-c:a", "copy"], _audio_copy_extension(params, stream_row), "audio_copy"

    filter_args, suffixes = _audio_filter_args(params, lufs_override, include_lufs=include_lufs)
    suffix_rate = "native" if sample_rate == "source" else f"{int(sample_rate) // 1000}k"

    if audio_format == "flac":
        depth_args: list[str] = []
        if bit_depth == "16":
            depth_args = ["-sample_fmt", "s16"]
        elif bit_depth == "24":
            depth_args = ["-sample_fmt", "s32", "-bits_per_raw_sample", "24"]
        depth_label = "native" if bit_depth == "source" else bit_depth
        return (
            [*base_args, *filter_args, "-c:a", "flac", "-compression_level", "8", *depth_args],
            "flac",
            "_".join(["flac", depth_label, suffix_rate, *suffixes]),
        )

    if audio_format == "m4a":
        return (
            [*base_args, *filter_args, "-c:a", "aac", "-b:a", bitrate],
            "m4a",
            "_".join(["m4a", bitrate, suffix_rate, *suffixes]),
        )

    if audio_format == "alac":
        return (
            [*base_args, *filter_args, "-c:a", "alac"],
            "m4a",
            "_".join(["alac", suffix_rate, *suffixes]),
        )

    if audio_format == "mp3":
        lame_preset = _mp3_lame_preset(params)
        return (
            [*base_args, *filter_args, *mp3_encoder_args(lame_preset, bitrate)],
            "mp3",
            "_".join(["mp3", mp3_preset_label(lame_preset, bitrate), suffix_rate, *suffixes]),
        )

    if audio_format == "opus":
        bitrate = _opus_bitrate(params)
        return (
            [*base_args, *filter_args, "-c:a", "libopus", "-b:a", bitrate],
            "opus",
            "_".join(["opus", bitrate, suffix_rate, *suffixes]),
        )

    if bit_depth == "16":
        codec = "pcm_s16le"
    elif bit_depth == "32f":
        codec = "pcm_f32le"
    else:
        codec = "pcm_s24le"
    depth_label = "native" if bit_depth == "source" else bit_depth
    return (
        [*base_args, *filter_args, "-c:a", codec],
        "wav",
        "_".join(["wav", depth_label, suffix_rate, *suffixes]),
    )


def _x264_tune(tuning: list[str]) -> list[str]:
    for tune in ["grain", "film", "animation", "fastdecode", "zerolatency"]:
        if tune in tuning:
            return ["-tune", tune]
    return []


def _x265_tune(tuning: list[str]) -> list[str]:
    for tune in ["grain", "fastdecode", "zerolatency"]:
        if tune in tuning:
            return ["-tune", tune]
    return []


def _scale_filter(params: dict[str, Any]) -> str:
    return scale_filter(params.get("output_resolution") or params.get("scale_height") or "source")


def _scale_args(params: dict[str, Any]) -> list[str]:
    scale = _scale_filter(params)
    if not scale:
        return []
    return ["-vf", scale]


def _hardware_pix_fmt_args(encoder: str, pix_fmt: str) -> list[str]:
    native = hardware_pix_fmt(encoder, pix_fmt)
    return ["-pix_fmt", native] if native else []


def _target_video_args(target: str, params: dict[str, Any]) -> tuple[list[str], str, str, str]:
    target = _target_for_backend(target, _encode_backend(params))
    cpu_preset = _cpu_encoder_preset(params)
    nvenc_preset = _nvenc_preset(params)
    qsv_preset = _qsv_encoder_preset(params)
    amf_quality = _amf_quality(params)
    tuning = _as_list(params.get("encode_tuning"))
    # Defaults match the encode pages in config/tool_manifest.yaml and the
    # defaults block of config/script_profiles.yaml. They only apply when a
    # caller omits the value, because every encode page sends both.
    crf = _as_float(params.get("crf"), 14.0)
    cq = _as_int(params.get("cq"), 14)
    pix_fmt = str(params.get("pix_fmt", "yuv420p")).strip()
    container = str(params.get("output_container", "mp4")).strip() or "mp4"

    if target == "ffv1":
        return (
            ["-c:v", "ffv1", "-level", "3", "-coder", "1", "-context", "1", "-g", "1", "-slicecrc", "1"],
            "mkv",
            "ffv1_archive",
            "archive",
        )
    if target == "x264_lossless":
        args = ["-c:v", "libx264", "-preset", cpu_preset, "-crf", "0", *_x264_tune(tuning)]
        if pix_fmt and pix_fmt != "auto":
            args.extend(["-pix_fmt", pix_fmt])
        return args, "mkv", f"x264_lossless_{cpu_preset}", "archive"
    if target.startswith("prores_"):
        profile_map = {"prores_proxy": "0", "prores_lt": "1", "prores_422": "2", "prores_hq": "3"}
        label_map = {"prores_proxy": "prores_proxy", "prores_lt": "prores_lt", "prores_422": "prores422", "prores_hq": "prores_hq"}
        return ["-c:v", "prores_ks", "-profile:v", profile_map.get(target, "2"), "-pix_fmt", "yuv422p10le"], container if container in {"mov", "mxf"} else "mov", label_map.get(target, "prores"), "editing"
    if target.startswith("dnxhr_"):
        profile = "dnxhr_hqx" if target == "dnxhr_hqx" else "dnxhr_hq"
        pixel_format = "yuv422p10le" if profile == "dnxhr_hqx" else "yuv422p"
        return ["-c:v", "dnxhd", "-profile:v", profile, "-pix_fmt", pixel_format], container if container in {"mov", "mxf"} else "mov", profile, "editing"
    if target == "svt_av1":
        av1_preset = str(params.get("av1_preset", params.get("encoder_preset", "6"))).strip() or "6"
        av1_pix_fmt = "yuv420p10le" if pix_fmt in {"auto", "yuv420p"} else pix_fmt
        return ["-c:v", "libsvtav1", "-preset", av1_preset, "-crf", f"{crf:g}", "-pix_fmt", av1_pix_fmt], container if container in {"mp4", "mkv"} else "mkv", f"svtav1_crf{crf:g}", "delivery"
    if target == "av1_nvenc":
        args = ["-c:v", "av1_nvenc", "-preset", nvenc_preset, "-tune", "hq", "-cq:v", str(cq), "-b:v", "0"]
        return [*args, *_hardware_pix_fmt_args("av1_nvenc", pix_fmt)], container if container in {"mp4", "mkv"} else "mkv", f"av1_nvenc_{nvenc_preset}_cq{cq}", "delivery"
    if target == "av1_qsv":
        args = ["-c:v", "av1_qsv", "-preset", qsv_preset, "-global_quality", str(cq)]
        return [*args, *_hardware_pix_fmt_args("av1_qsv", pix_fmt)], container if container in {"mp4", "mkv"} else "mkv", f"av1_qsv_{qsv_preset}_gq{cq}", "delivery"
    if target == "av1_amf":
        args = ["-c:v", "av1_amf", "-quality", amf_quality, "-rc", "cqp", "-qp_i", str(cq), "-qp_p", str(cq)]
        return [*args, *_hardware_pix_fmt_args("av1_amf", pix_fmt)], container if container in {"mp4", "mkv"} else "mkv", f"av1_amf_{amf_quality}_qp{cq}", "delivery"
    if target in {"h264_nvenc", "hevc_nvenc"}:
        encoder = "hevc_nvenc" if target == "hevc_nvenc" else "h264_nvenc"
        args = ["-c:v", encoder, "-preset", nvenc_preset, "-tune", "hq", "-cq:v", str(cq), "-b:v", "0"]
        return [*args, *_hardware_pix_fmt_args(encoder, pix_fmt)], container, f"{encoder}_{nvenc_preset}_cq{cq}", "delivery"
    if target in {"h264_qsv", "hevc_qsv"}:
        encoder = "hevc_qsv" if target == "hevc_qsv" else "h264_qsv"
        args = ["-c:v", encoder, "-preset", qsv_preset, "-global_quality", str(cq)]
        return [*args, *_hardware_pix_fmt_args(encoder, pix_fmt)], container, f"{encoder}_{qsv_preset}_gq{cq}", "delivery"
    if target in {"h264_amf", "hevc_amf"}:
        encoder = "hevc_amf" if target == "hevc_amf" else "h264_amf"
        args = ["-c:v", encoder, "-quality", amf_quality, "-rc", "cqp", "-qp_i", str(cq), "-qp_p", str(cq)]
        if encoder == "h264_amf":
            args.extend(["-qp_b", str(cq)])
        return [*args, *_hardware_pix_fmt_args(encoder, pix_fmt)], container, f"{encoder}_{amf_quality}_qp{cq}", "delivery"
    if target == "hevc_x265":
        args = ["-c:v", "libx265", "-preset", cpu_preset, "-x265-params", f"crf={crf:g}", *_x265_tune(tuning)]
        if pix_fmt and pix_fmt != "auto":
            args.extend(["-pix_fmt", pix_fmt])
        return args, container, f"hevc_crf{crf:g}_{cpu_preset}", "delivery"

    args = ["-c:v", "libx264", "-preset", cpu_preset, "-crf", f"{crf:g}", *_x264_tune(tuning)]
    if pix_fmt and pix_fmt != "auto":
        args.extend(["-pix_fmt", pix_fmt])
    return args, container, f"x264_crf{crf:g}_{cpu_preset}", "delivery"


def inventory(context: JobContext) -> dict[str, object]:
    source_path = cached_source_path(context.paths.root)
    output_path = cached_output_path(context.paths.root)
    rows: list[dict[str, object]] = []
    for label, folder in [
        ("Source", source_path),
        ("Transcoded", output_path),
        ("Download", context.paths.root / "Download"),
        ("LUTs", context.paths.root / "LUTs"),
    ]:
        if folder.is_file():
            files = [folder]
        else:
            files = [path for path in folder.rglob("*") if path.is_file()] if folder.exists() else []
        rows.append({"folder": label, "path": str(folder), "files": len(files)})
        context.log(f"{label}: {len(files)} file(s) - {folder}")
    context.progress(1.0)
    return {"folders": rows}


def selftest(context: JobContext) -> dict[str, object]:
    root = context.paths.root
    results: dict[str, str] = {}
    commands = [
        ("ffmpeg", [_ffmpeg(root), "-version"]),
        ("ffprobe", [_ffprobe(root), "-version"]),
        ("yt-dlp", [_yt_dlp(root), "--version"]),
    ]
    deno = _deno(root)
    if deno:
        commands.append(("deno", [deno, "--version"]))
    else:
        context.log("Checking deno...")
        results["deno"] = "missing"
    for label, command in commands:
        context.log(f"Checking {label}...")
        result = run_process(context, command, extra_env=_tool_env(root), check=False, progress_seconds=30)
        first_line = result.lines[0] if result.lines else f"exit {result.exit_code}"
        results[label] = first_line
    context.progress(1.0)
    return results


def _run_installer(context: JobContext, script_name: str, label: str) -> dict[str, object]:
    script = Path("install") / script_name
    context.log(f"Installing/updating {label}...")
    result = run_cmd_script(context, str(script), ["/NOPAUSE"], check=True, extra_env=_tool_env(context.paths.root))
    context.progress(1.0)
    return {"script": str(script), "lines": len(result.lines)}


def install_portable_7zip(context: JobContext) -> dict[str, object]:
    return _run_installer(context, "Install-Portable-7Zip.cmd", "portable 7-Zip")


def install_portable_ffmpeg(context: JobContext) -> dict[str, object]:
    context.log("FFmpeg is a GPL/reviewed external tool payload; install stays explicit.")
    return _run_installer(context, "Install-Portable-FFmpeg-Gyan.cmd", "portable FFmpeg Gyan Stable")


def install_portable_ytdlp(context: JobContext) -> dict[str, object]:
    return _run_installer(context, "Install-Portable-yt-dlp.cmd", "portable yt-dlp")


def _profile_id(script_name: str) -> str:
    return Path(str(script_name).strip().strip('"')).stem.lower()


def _walk_nodes(nodes: list[CommandNode] | tuple[CommandNode, ...]) -> list[CommandNode]:
    result: list[CommandNode] = []
    for node in nodes:
        result.append(node)
        result.extend(_walk_nodes(node.children))
    return result


def _walk_raw(value: Any) -> list[Any]:
    result = [value]
    if isinstance(value, dict):
        for child in value.values():
            result.extend(_walk_raw(child))
    elif isinstance(value, list):
        for child in value:
            result.extend(_walk_raw(child))
    return result


def _raw_script_presets(raw: dict[str, Any]) -> set[str]:
    presets: set[str] = set()
    for item in _walk_raw(raw):
        if isinstance(item, dict):
            value = item.get("script_preset")
            if isinstance(value, str) and value.strip():
                presets.add(_profile_id(str(value)))
    return presets


def _profile_doctor_status(level: str, subject: str, detail: str) -> dict[str, str]:
    return {"level": level, "subject": subject, "detail": detail}


def _validate_script_profile(profile_id: str, profile: dict[str, Any]) -> list[dict[str, str]]:
    kind = str(profile.get("kind", "")).strip().lower()
    issues: list[dict[str, str]] = []
    allowed = {"audio", "color", "editing", "encode", "ff_selftest", "fps", "remux", "subtitles", "youtube"}
    if kind not in allowed:
        return [_profile_doctor_status("ERROR", profile_id, f"Unsupported or missing kind: {kind or '<empty>'}")]

    required_by_kind = {
        "audio": ["action"],
        "color": ["color_filter", "targets"],
        "editing": ["target", "extension"],
        "encode": ["target"],
        "fps": ["source_fps", "target_fps", "mode"],
        "remux": ["source", "target"],
        "youtube": [],
    }
    for key in required_by_kind.get(kind, []):
        value = profile.get(key)
        if key not in profile or value is None or value == "" or value == []:
            issues.append(_profile_doctor_status("ERROR", profile_id, f"Missing required key: {key}"))

    if kind == "youtube" and not profile.get("args") and profile.get("mode") not in {"selftest", "update"}:
        issues.append(_profile_doctor_status("WARN", profile_id, "YouTube profile has no args and no special mode."))
    if kind == "audio" and profile.get("action") == "m4a":
        bitrate = str(profile.get("audio_bitrate", "")).strip()
        suffix = str(profile.get("suffix", "")).strip()
        if bitrate and bitrate not in suffix:
            issues.append(_profile_doctor_status("WARN", profile_id, f"M4A suffix does not include bitrate {bitrate}: {suffix}"))
    return issues


def _preset_crf_warnings(raw: dict[str, Any]) -> list[dict[str, str]]:
    warnings: list[dict[str, str]] = []
    for item in _walk_raw(raw):
        if not isinstance(item, dict) or "presets" not in item:
            continue
        presets = item.get("presets")
        if not isinstance(presets, list):
            continue
        for preset in presets:
            if not isinstance(preset, dict):
                continue
            preset_id = str(preset.get("id", ""))
            values = preset.get("values", {})
            if not isinstance(values, dict):
                continue
            match = re.search(r"crf(\d+)", preset_id.lower())
            if match and "crf" in values and str(values.get("crf")) != match.group(1):
                warnings.append(_profile_doctor_status("WARN", preset_id, f"Preset id says CRF {match.group(1)}, value is CRF {values.get('crf')}."))
    return warnings


def profile_doctor(context: JobContext) -> dict[str, object]:
    root = context.paths.root
    issues: list[dict[str, str]] = []
    manifest_path = root / "config" / "tool_manifest.yaml"
    scripts_dir = root / "Scripts"

    context.log("\x1b[1;36mProfile Doctor\x1b[0m")
    context.log(f"Manifest: {manifest_path}")
    context.log(f"Script catalog: {root / 'config' / 'script_profiles.yaml'}")
    context.log("")

    try:
        manifest = load_manifest(manifest_path)
        context.log(f"{ansi_status('OK')} tool_manifest.yaml parsed")
    except Exception as exc:
        issue = _profile_doctor_status("ERROR", "tool_manifest.yaml", f"{exc.__class__.__name__}: {exc}")
        issues.append(issue)
        context.log(f"{ansi_status('ERROR')} {issue['subject']}: {issue['detail']}")
        return {"ok": False, "issues": issues}

    all_operations = [*manifest.operations, *manifest.maintenance_operations]
    all_nodes = _walk_nodes(manifest.operation_groups)
    leaf_nodes = [node for node in all_nodes if not node.children]
    for op_id, service in [(op.id, op.service) for op in all_operations] + [(node.id, node.service) for node in leaf_nodes]:
        if ":" not in service:
            issues.append(_profile_doctor_status("ERROR", op_id, f"Bad service syntax: {service}"))
            continue
        module_name, function_name = service.split(":", 1)
        try:
            module = importlib.import_module(module_name)
            function = getattr(module, function_name)
            if not callable(function):
                issues.append(_profile_doctor_status("ERROR", op_id, f"Service is not callable: {service}"))
        except Exception as exc:
            issues.append(_profile_doctor_status("ERROR", op_id, f"Service import failed: {service} ({exc.__class__.__name__})"))

    script_files = sorted(path for path in scripts_dir.glob("*.cmd") if path.is_file())
    script_ids = {_profile_id(path.name) for path in script_files}
    catalog = load_script_profiles(root)
    profiles = catalog.get("profiles", {})
    profile_ids = set(profiles.keys()) if isinstance(profiles, dict) else set()
    referenced_script_presets = _raw_script_presets(manifest.raw)

    missing_profiles = sorted(script_ids - profile_ids)
    orphan_profiles = sorted(profile_ids - script_ids)
    missing_scripts = sorted(referenced_script_presets - script_ids)
    missing_catalog_refs = sorted(referenced_script_presets - profile_ids)

    for item in missing_profiles:
        issues.append(_profile_doctor_status("ERROR", item, "Script wrapper exists but config/script_profiles.yaml has no profile."))
    for item in orphan_profiles:
        issues.append(_profile_doctor_status("WARN", item, "Profile exists but no Scripts/*.cmd wrapper uses it."))
    for item in missing_scripts:
        issues.append(_profile_doctor_status("ERROR", item, "tool_manifest.yaml references a script_preset without a Scripts/*.cmd wrapper."))
    for item in missing_catalog_refs:
        issues.append(_profile_doctor_status("ERROR", item, "tool_manifest.yaml references a script_preset missing from config/script_profiles.yaml."))

    if isinstance(profiles, dict):
        for profile_id_value, profile in profiles.items():
            if isinstance(profile, dict):
                issues.extend(_validate_script_profile(str(profile_id_value), profile))
            else:
                issues.append(_profile_doctor_status("ERROR", str(profile_id_value), "Profile entry is not a mapping."))

    issues.extend(_preset_crf_warnings(manifest.raw))

    errors = [issue for issue in issues if issue["level"] == "ERROR"]
    warnings = [issue for issue in issues if issue["level"] == "WARN"]
    context.log(f"Operations: {len(all_operations)} top-level/maintenance, {len(leaf_nodes)} leaf command(s)")
    context.log(f"Script wrappers: {len(script_ids)}")
    context.log(f"Script profiles: {len(profile_ids)}")
    context.log(f"Manifest script_preset references: {len(referenced_script_presets)}")
    context.log("")

    if not issues:
        context.log(f"{ansi_status('OK')} Profile Doctor found no issues.")
    else:
        for issue in issues:
            context.log(f"{ansi_status(issue['level'])} {issue['subject']}: {issue['detail']}")

    report_path = context.report_dir / "profile_doctor.json"
    report_path.write_text(json.dumps({"errors": errors, "warnings": warnings, "issues": issues}, ensure_ascii=False, indent=2), encoding="utf-8")
    context.log("")
    context.log(f"Report: {report_path}")
    context.progress(1.0)
    return {"ok": not errors, "errors": len(errors), "warnings": len(warnings), "report": str(report_path)}


def _capture_tool(root: Path, command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=str(root),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=utf8_subprocess_env(_tool_env(root)),
        **hidden_subprocess_kwargs(),
    )


def _tool_listing(root: Path, kind: str) -> str:
    result = _capture_tool(root, [_ffmpeg(root), "-hide_banner", f"-{kind}"])
    return result.stdout or ""


def _has_tool_item(listing: str, item: str) -> bool:
    return item.lower() in listing.lower()


def _hardware_status(label: str, status: str, detail: str, command: list[str] | None = None) -> dict[str, object]:
    row: dict[str, object] = {"label": label, "status": status, "detail": detail}
    if command:
        row["command"] = command
    return row


def _write_hardware_cache(
    root: Path,
    statuses: list[dict[str, object]],
    *,
    ok_count: int,
    fail_count: int,
    miss_count: int,
    skip_count: int,
    report_path: Path,
) -> Path:
    cache_path = root / "config" / "hardware_capabilities_cache.json"
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "updated_at": timestamp(),
        "machine": platform.node(),
        "statuses": statuses,
        "summary": {
            "ok": ok_count,
            "fail": fail_count,
            "miss": miss_count,
            "skip": skip_count,
        },
        "report": str(report_path),
    }
    cache_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return cache_path


HARDWARE_DECODE_SMOKES = (
    ("CUDA decode", "cuda", ["-hwaccel", "cuda"]),
    ("QuickSync decode", "qsv", ["-hwaccel", "qsv"]),
    ("AMD/D3D11VA decode", "d3d11va", ["-hwaccel", "d3d11va"]),
)

DAV1D_SMOKE_LABEL = "dav1d AV1 decode"


def hardware_smoke_tests(ffmpeg: str, input_path: Path, report_dir: Path) -> list[tuple[str, str, list[str]]]:
    """Encoder smoke commands as (cache label, FFmpeg encoder, command).

    The labels are the contract preflight uses to look results up in
    `config\\hardware_capabilities_cache.json`, so they must stay in sync with
    `HARDWARE_ENCODERS` in `system_core\\core\\preflight.py`.
    """
    head = [ffmpeg, "-hide_banner", "-loglevel", "error", "-stats", "-y"]
    read = ["-i", str(input_path)]
    return [
        ("CPU libx264", "libx264", [*head, *read, "-c:v", "libx264", "-preset", "ultrafast", "-crf", "28", "-an", str(report_dir / "cpu_libx264.mp4")]),
        ("SVT-AV1", "libsvtav1", [*head, *read, "-c:v", "libsvtav1", "-preset", "12", "-crf", "40", "-an", str(report_dir / "svt_av1.mkv")]),
        ("QSV H.264 encode", "h264_qsv", [*head, *read, "-c:v", "h264_qsv", "-preset", "medium", "-global_quality", "20", "-an", str(report_dir / "qsv_h264.mp4")]),
        ("QSV HEVC encode", "hevc_qsv", [*head, *read, "-c:v", "hevc_qsv", "-preset", "medium", "-global_quality", "20", "-an", str(report_dir / "qsv_hevc.mp4")]),
        ("QSV AV1 encode", "av1_qsv", [*head, *read, "-c:v", "av1_qsv", "-preset", "medium", "-global_quality", "30", "-an", str(report_dir / "qsv_av1.mp4")]),
        ("QuickSync decode + encode", "h264_qsv", [*head, "-hwaccel", "qsv", *read, "-c:v", "h264_qsv", "-preset", "medium", "-global_quality", "20", "-an", str(report_dir / "qsv_decode_h264.mp4")]),
        ("NVENC H.264 encode", "h264_nvenc", [*head, *read, "-c:v", "h264_nvenc", "-preset", "p5", "-tune", "hq", "-cq:v", "20", "-b:v", "0", "-an", str(report_dir / "nvenc_h264.mp4")]),
        ("NVENC HEVC encode", "hevc_nvenc", [*head, *read, "-c:v", "hevc_nvenc", "-preset", "p5", "-tune", "hq", "-cq:v", "20", "-b:v", "0", "-an", str(report_dir / "nvenc_hevc.mp4")]),
        ("NVENC AV1 encode", "av1_nvenc", [*head, *read, "-c:v", "av1_nvenc", "-preset", "p5", "-tune", "hq", "-cq:v", "30", "-b:v", "0", "-an", str(report_dir / "nvenc_av1.mp4")]),
        ("AMF H.264 encode", "h264_amf", [*head, *read, "-c:v", "h264_amf", "-quality", "speed", "-rc", "cqp", "-qp_i", "22", "-qp_p", "22", "-qp_b", "22", "-an", str(report_dir / "amf_h264.mp4")]),
        ("AMF HEVC encode", "hevc_amf", [*head, *read, "-c:v", "hevc_amf", "-quality", "speed", "-rc", "cqp", "-qp_i", "22", "-qp_p", "22", "-an", str(report_dir / "amf_hevc.mp4")]),
        ("AMF AV1 encode", "av1_amf", [*head, *read, "-c:v", "av1_amf", "-quality", "speed", "-rc", "cqp", "-qp_i", "60", "-qp_p", "60", "-an", str(report_dir / "amf_av1.mp4")]),
    ]


def hardware_smoke_labels() -> tuple[str, ...]:
    """Every label Hardware Capabilities can write into the machine-local cache."""
    encoder_labels = [label for label, _encoder, _command in hardware_smoke_tests("ffmpeg", Path("input.mp4"), Path("report"))]
    decode_labels = [label for label, _hwaccel, _flags in HARDWARE_DECODE_SMOKES]
    return (*encoder_labels, *decode_labels, DAV1D_SMOKE_LABEL)


def _run_hardware_smoke(context: JobContext, label: str, command: list[str]) -> dict[str, object]:
    context.log(f"[SMOKE] {label}")
    result = run_process(context, command, extra_env=_tool_env(context.paths.root), check=False, progress_seconds=20)
    if result.exit_code == 0:
        return _hardware_status(label, "OK", "Smoke encode/decode completed.", command)
    text = "\n".join(result.lines)
    lowered = text.lower()
    unavailable_markers = HARDWARE_UNAVAILABLE_MARKERS
    status = "MISS" if any(marker in lowered for marker in unavailable_markers) else "FAIL"
    if status == "MISS":
        detail = next(
            (
                line
                for line in result.lines
                if line.strip() and any(marker in line.lower() for marker in unavailable_markers)
            ),
            "",
        )
    else:
        detail = ""
    if not detail:
        detail = next((line for line in reversed(result.lines) if line.strip() and not line.lstrip().startswith("frame=")), f"exit {result.exit_code}")
    return _hardware_status(label, status, detail[:240], command)


def hardware_capabilities(context: JobContext) -> dict[str, object]:
    root = context.paths.root
    ffmpeg = _ffmpeg(root)
    report_dir = context.report_dir / "hardware_smoke"
    report_dir.mkdir(parents=True, exist_ok=True)
    input_path = report_dir / "hardware_input.mp4"
    statuses: list[dict[str, object]] = []

    context.log("Hardware Capabilities")
    encoders = _tool_listing(root, "encoders")
    decoders = _tool_listing(root, "decoders")

    input_command = [
        ffmpeg,
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-f",
        "lavfi",
        "-i",
        "testsrc2=size=640x360:rate=30:duration=1",
        "-f",
        "lavfi",
        "-i",
        "sine=frequency=1000:duration=1",
        "-c:v",
        "libx264",
        "-preset",
        "ultrafast",
        "-crf",
        "30",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-b:a",
        "96k",
        str(input_path),
    ]
    context.log("Creating hardware smoke input...")
    input_result = run_process(context, input_command, extra_env=_tool_env(root), check=False, progress_seconds=20)
    if input_result.exit_code != 0:
        statuses.append(_hardware_status("smoke input", "FAIL", "Could not create test input."))
        return {"statuses": statuses, "ok": False}

    tests = hardware_smoke_tests(ffmpeg, input_path, report_dir)

    for label, encoder, command in tests:
        if not _has_tool_item(encoders, encoder):
            statuses.append(_hardware_status(label, "MISS", f"Encoder not listed by FFmpeg: {encoder}"))
            context.log(f"[MISS] {label}: encoder not listed ({encoder})")
            continue
        statuses.append(_run_hardware_smoke(context, label, command))

    hwaccels = _tool_listing(root, "hwaccels")
    for label, hwaccel, decode_flags in HARDWARE_DECODE_SMOKES:
        if not _has_tool_item(hwaccels, hwaccel):
            statuses.append(_hardware_status(label, "MISS", f"Hardware acceleration not listed by FFmpeg: {hwaccel}"))
            context.log(f"[MISS] {label}: hwaccel not listed ({hwaccel})")
            continue
        statuses.append(
            _run_hardware_smoke(
                context,
                label,
                [ffmpeg, "-hide_banner", "-loglevel", "error", "-stats", *decode_flags, "-i", str(input_path), "-f", "null", "NUL"],
            )
        )

    av1_output = report_dir / "svt_av1.mkv"
    if _has_tool_item(decoders, "libdav1d"):
        if av1_output.exists():
            statuses.append(
                _run_hardware_smoke(
                    context,
                    DAV1D_SMOKE_LABEL,
                    [ffmpeg, "-hide_banner", "-loglevel", "error", "-stats", "-c:v", "libdav1d", "-i", str(av1_output), "-f", "null", "NUL"],
                )
            )
        else:
            statuses.append(_hardware_status(DAV1D_SMOKE_LABEL, "SKIP", "libdav1d is listed, but no AV1 smoke file was produced."))
            context.log("[SKIP] dav1d AV1 decode: no AV1 smoke file")
    else:
        statuses.append(_hardware_status(DAV1D_SMOKE_LABEL, "MISS", "Decoder not listed by FFmpeg: libdav1d"))
        context.log("[MISS] dav1d AV1 decode: libdav1d not listed")

    ok_count = sum(1 for item in statuses if item["status"] == "OK")
    fail_count = sum(1 for item in statuses if item["status"] == "FAIL")
    miss_count = sum(1 for item in statuses if item["status"] == "MISS")
    skip_count = sum(1 for item in statuses if item["status"] == "SKIP")
    context.log("")
    for item in statuses:
        context.log(f"[{item['status']}] {item['label']}: {item['detail']}")
    report_path = context.report_dir / "hardware_capabilities.json"
    report_path.write_text(json.dumps({"statuses": statuses}, ensure_ascii=False, indent=2), encoding="utf-8")
    cache_path = _write_hardware_cache(
        root,
        statuses,
        ok_count=ok_count,
        fail_count=fail_count,
        miss_count=miss_count,
        skip_count=skip_count,
        report_path=report_path,
    )
    context.log("")
    context.log(f"Summary: OK={ok_count}, FAIL={fail_count}, MISS={miss_count}, SKIP={skip_count}")
    context.log(f"Report: {report_path}")
    context.log(f"Hardware cache: {cache_path}")
    context.progress(1.0)
    return {"ok": fail_count == 0, "ok_count": ok_count, "fail_count": fail_count, "miss_count": miss_count, "skip_count": skip_count, "report": str(report_path), "cache": str(cache_path)}


def _matrix_status(category: str, result: Any, *, missing_is_miss: bool = False) -> tuple[str, str]:
    if getattr(result, "exit_code", 1) == 0:
        return "OK", "completed"
    lines = tuple(getattr(result, "lines", ()) or ())
    text = "\n".join(lines)
    lowered = text.lower()
    unavailable_markers = HARDWARE_UNAVAILABLE_MARKERS
    missing_markers = ["unknown encoder", "encoder not found", "unknown decoder", "decoder not found", "not found for input stream"]
    matched = [marker for marker in unavailable_markers if marker in lowered]
    if missing_is_miss:
        matched.extend(marker for marker in missing_markers if marker in lowered)
    status = "MISS" if matched else "FAIL"
    detail = ""
    if matched:
        # Report why the hardware is unavailable, not FFmpeg's closing line about
        # an empty output file.
        detail = next((line.strip() for line in lines if line.strip() and any(marker in line.lower() for marker in matched)), "")
    if not detail:
        detail = next((line.strip() for line in reversed(lines) if line.strip() and not line.lstrip().startswith("frame=")), f"exit {getattr(result, 'exit_code', '?')}")
    return status, detail[:260]


def _matrix_row(category: str, preset: str, status: str, detail: str, command: list[str] | None = None) -> dict[str, object]:
    row: dict[str, object] = {"category": category, "preset": preset, "status": status, "detail": detail}
    if command:
        row["command"] = command
    return row


def _matrix_run_command(
    context: JobContext,
    *,
    category: str,
    preset: str,
    command: list[str],
    missing_is_miss: bool = False,
) -> dict[str, object]:
    context.log(f"[MATRIX] {category} / {preset}")
    result = run_process(context, command, extra_env=_tool_env(context.paths.root), check=False, progress_seconds=120)
    status, detail = _matrix_status(category, result, missing_is_miss=missing_is_miss)
    context.log(f"[{status}] {category} / {preset}: {detail}")
    return _matrix_row(category, preset, status, detail, command)


def _matrix_run_sequence(
    context: JobContext,
    *,
    category: str,
    preset: str,
    commands: list[list[str]],
    missing_is_miss: bool = False,
) -> dict[str, object]:
    last_command: list[str] | None = None
    for command in commands:
        last_command = command
        row = _matrix_run_command(context, category=category, preset=preset, command=command, missing_is_miss=missing_is_miss)
        if row["status"] != "OK":
            return row
    return _matrix_row(category, preset, "OK", f"{len(commands)} command(s) completed", last_command)


def _matrix_case_label(preset: dict[str, Any]) -> str:
    return str(preset.get("id") or preset.get("label") or preset.get("label_ru") or "preset")


def _matrix_field_defaults(fields: tuple[dict[str, Any], ...]) -> dict[str, Any]:
    values: dict[str, Any] = {}
    for field in fields:
        key = str(field.get("id") or "").strip()
        if not key:
            continue
        if "default" in field:
            values[key] = field.get("default")
        elif str(field.get("type", "")).lower() in {"checkboxes", "multi_checkbox", "multicheckbox"}:
            values[key] = []
    return values


def _matrix_node(manifest: Any, node_id: str) -> CommandNode | None:
    return next((node for node in _walk_nodes(manifest.operation_groups) if node.id == node_id), None)


def _matrix_profile_cases(root: Path, node_id: str) -> list[dict[str, Any]]:
    manifest = load_manifest(root / "config" / "tool_manifest.yaml")
    node = _matrix_node(manifest, node_id)
    if not node:
        return []
    defaults = _matrix_field_defaults(node.fields)
    profile_field = next(
        (
            field
            for field in node.fields
            if str(field.get("type", "")).lower()
            in {"profile_select", "preset_select", "profile_buttons", "preset_buttons", "profiles", "presets"}
        ),
        None,
    )
    if not profile_field:
        return []
    profile_key = str(profile_field.get("id") or "").strip()
    cases: list[dict[str, Any]] = []
    for preset in profile_field.get("presets", []) or []:
        if not isinstance(preset, dict):
            continue
        params = dict(defaults)
        params[profile_key] = _matrix_case_label(preset)
        values = preset.get("values", {})
        if isinstance(values, dict):
            params.update(values)
        params.update({"overwrite": True, "dry_run": False, "limit_first_file": True})
        cases.append({"id": _matrix_case_label(preset), "params": params, "node": node_id})
    return cases


def _matrix_missing_is_miss(params: dict[str, Any]) -> bool:
    backend = _encode_backend(params)
    decoder = _decode_backend(params)
    targets = set(_as_list(params.get("target_codecs")))
    return backend in {"cuda", "qsv", "amd"} or decoder in {"cuda", "qsv", "amd", "dav1d"} or any("nvenc" in item or "qsv" in item or "amf" in item for item in targets)


def _matrix_create_inputs(context: JobContext, matrix_dir: Path) -> dict[str, Path]:
    root = context.paths.root
    ffmpeg = _ffmpeg(root)
    input_dir = matrix_dir / "inputs"
    input_dir.mkdir(parents=True, exist_ok=True)
    paths = {
        "mp4": input_dir / "matrix_input.mp4",
        "mkv": input_dir / "matrix_input.mkv",
        "mov": input_dir / "matrix_input.mov",
        "mov_edit": input_dir / "matrix_edit.mov",
        "hdr_mp4": input_dir / "matrix_hdr_pq.mp4",
        "wav": input_dir / "matrix_audio.wav",
        "flac": input_dir / "matrix_audio.flac",
        "mp3": input_dir / "matrix_audio.mp3",
        "alac": input_dir / "matrix_alac.m4a",
        "webm_opus": input_dir / "matrix_opus.webm",
        "lut": input_dir / "identity.cube",
    }
    paths["lut"].write_text(
        "\n".join(
            [
                'TITLE "Audion Matrix Identity"',
                "LUT_3D_SIZE 2",
                "0 0 0",
                "0 0 1",
                "0 1 0",
                "0 1 1",
                "1 0 0",
                "1 0 1",
                "1 1 0",
                "1 1 1",
                "",
            ]
        ),
        encoding="utf-8",
        newline="\n",
    )
    commands = [
        [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "testsrc2=size=320x180:rate=24:duration=1",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=1000:sample_rate=48000:duration=1",
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-crf",
            "30",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-b:a",
            "96k",
            "-shortest",
            str(paths["mp4"]),
        ],
        [ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-i", str(paths["mp4"]), "-map", "0", "-c", "copy", str(paths["mkv"])],
        [ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-i", str(paths["mp4"]), "-map", "0", "-c", "copy", "-movflags", "+faststart", str(paths["mov"])],
        [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "testsrc2=size=320x180:rate=24:duration=1",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=800:sample_rate=48000:duration=1",
            "-c:v",
            "prores_ks",
            "-profile:v",
            "2",
            "-pix_fmt",
            "yuv422p10le",
            "-c:a",
            "pcm_s16le",
            "-shortest",
            str(paths["mov_edit"]),
        ],
        [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "testsrc2=size=320x180:rate=24:duration=1",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=600:sample_rate=48000:duration=1",
            "-vf",
            "format=yuv420p10le",
            "-c:v",
            "libx265",
            "-preset",
            "ultrafast",
            "-x265-params",
            "crf=35:colorprim=bt2020:transfer=smpte2084:colormatrix=bt2020nc",
            "-color_primaries",
            "bt2020",
            "-color_trc",
            "smpte2084",
            "-colorspace",
            "bt2020nc",
            "-c:a",
            "aac",
            "-b:a",
            "96k",
            "-shortest",
            str(paths["hdr_mp4"]),
        ],
        [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:sample_rate=48000:duration=1",
            "-c:a",
            "pcm_s24le",
            str(paths["wav"]),
        ],
        [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=520:sample_rate=48000:duration=1",
            "-c:a",
            "flac",
            str(paths["flac"]),
        ],
        [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=620:sample_rate=48000:duration=1",
            "-c:a",
            "libmp3lame",
            "-b:a",
            "128k",
            str(paths["mp3"]),
        ],
        [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=720:sample_rate=48000:duration=1",
            "-c:a",
            "alac",
            str(paths["alac"]),
        ],
        [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=820:sample_rate=48000:duration=1",
            "-c:a",
            "libopus",
            "-b:a",
            "96k",
            str(paths["webm_opus"]),
        ],
    ]
    for command in commands:
        result = run_process(context, command, extra_env=_tool_env(root), check=False, progress_seconds=20)
        if result.exit_code != 0:
            raise RuntimeError("Preset Test Matrix could not create its 1-second fixture files.")
    return paths


def _matrix_encode_case_command(context: JobContext, source: Path, output_dir: Path, params: dict[str, Any], target_codec: str) -> tuple[list[str], str]:
    root = context.paths.root
    ffmpeg = _ffmpeg(root)
    video, extension, suffix, family = _target_video_args(target_codec, params)
    target = _output_path(source, output_dir, suffix, extension)
    command = [ffmpeg, "-hide_banner", "-loglevel", "error", "-stats", "-y", *_decode_args(params, context, has_video_filters=bool(_scale_args(params))), "-i", str(source)]
    audio_mode = str(params.get("audio_mode", "aac_320")).strip()
    audio_bitrate = _audio_bitrate(params)
    if family == "archive":
        archive_audio = "flac" if target_codec == "ffv1" and audio_mode in {"aac_320", "source"} else audio_mode
        command.extend(["-map", "0", "-dn", *video, *_audio_args(archive_audio, audio_bitrate, _mp3_lame_preset(params)), *_encode_audio_filter_args(params, archive_audio), "-c:s", "copy", "-map_metadata", "0"])
    elif family == "editing":
        audio_mode = _container_audio_mode(extension, audio_mode)
        command.extend(["-map", "0:v:0", "-map", "0:a?", "-sn", "-dn", *_scale_args(params), *video, *_audio_args(audio_mode, audio_bitrate, _mp3_lame_preset(params)), *_encode_audio_filter_args(params, audio_mode), "-map_metadata", "0"])
        if extension == "mxf":
            command.extend(["-f", "mxf"])
        elif extension == "mov":
            command.extend(["-movflags", "+faststart"])
    else:
        command.extend(["-map", "0:v:0"])
        if audio_mode != "none":
            command.extend(["-map", "0:a?"])
        command.extend(["-sn", "-dn", *_scale_args(params), *video, *_audio_args(audio_mode, audio_bitrate, _mp3_lame_preset(params)), *_encode_audio_filter_args(params, audio_mode), "-map_metadata", "0"])
        if extension == "mp4":
            command.extend(["-movflags", "+faststart"])
    command.append(str(target))
    return command, str(target)


def _matrix_run_profile_family(
    context: JobContext,
    rows: list[dict[str, object]],
    *,
    category: str,
    node_id: str,
    source: Path,
    output_dir: Path,
    tick: Callable[[], None],
) -> None:
    for case in _matrix_profile_cases(context.paths.root, node_id):
        params = dict(case["params"])
        targets = _as_list(params.get("target_codecs"))
        if not targets:
            targets = ["x264"]
        preset_label = str(case["id"])
        status_row: dict[str, object] | None = None
        try:
            commands: list[list[str]] = []
            for target_codec in targets:
                normalized = {"hevc10": "hevc_x265", "prores422": "prores_422"}.get(target_codec, target_codec)
                command, _target = _matrix_encode_case_command(context, source, output_dir / category, params, normalized)
                commands.append(command)
            status_row = _matrix_run_sequence(
                context,
                category=category,
                preset=preset_label,
                commands=commands,
                missing_is_miss=_matrix_missing_is_miss(params),
            )
        except Exception as exc:
            status_row = _matrix_row(category, preset_label, "FAIL", f"{exc.__class__.__name__}: {exc}")
            context.log(f"[FAIL] {category} / {preset_label}: {status_row['detail']}")
        rows.append(status_row)
        tick()


MATRIX_HARDWARE_BACKENDS = ("cuda", "qsv", "amd")
MATRIX_HARDWARE_TARGETS = ("x264", "hevc_x265", "svt_av1")


def _matrix_run_hardware_backends(
    context: JobContext,
    rows: list[dict[str, object]],
    *,
    source: Path,
    output_dir: Path,
    tick: Callable[[], None],
) -> None:
    """Exercise the hardware branches of the command builders.

    Manifest presets are all CPU, so without this the NVENC/QSV/AMF code paths
    are never executed by the matrix. Machines without the hardware report MISS.
    """
    for backend in MATRIX_HARDWARE_BACKENDS:
        for target in MATRIX_HARDWARE_TARGETS:
            params = {
                "encode_backend": backend,
                "target_codecs": [target],
                "pix_fmt": "auto",
                "cq": 28,
                "output_container": "mp4",
                "audio_mode": "none",
                "overwrite": True,
            }
            label = f"{backend}:{target}"
            try:
                command, _target_path = _matrix_encode_case_command(context, source, output_dir / "hardware_backends", params, target)
                row = _matrix_run_command(
                    context,
                    category="hardware backend",
                    preset=label,
                    command=command,
                    missing_is_miss=_matrix_missing_is_miss(params),
                )
            except Exception as exc:
                row = _matrix_row("hardware backend", label, "FAIL", f"{exc.__class__.__name__}: {exc}")
                context.log(f"[FAIL] hardware backend / {label}: {row['detail']}")
            rows.append(row)
            tick()


def _matrix_run_audio_profiles(
    context: JobContext,
    rows: list[dict[str, object]],
    *,
    inputs: dict[str, Path],
    output_dir: Path,
    tick: Callable[[], None],
) -> None:
    ffmpeg = _ffmpeg(context.paths.root)
    for case in _matrix_profile_cases(context.paths.root, "audio"):
        params = dict(case["params"])
        workflow = _audio_workflow(params)
        source = inputs["wav"] if workflow == "audio_files" else inputs["mp4"]
        preset_label = str(case["id"])
        try:
            lufs_mode = _audio_lufs_mode(params)
            target_lufs = _audio_lufs_target(params)
            if lufs_mode == "report":
                command = [
                    ffmpeg,
                    "-hide_banner",
                    "-nostats",
                    "-i",
                    str(source),
                    "-map",
                    "0:a:0",
                    "-af",
                    f"loudnorm=I={target_lufs if target_lufs != 'off' else '-23'}:TP={_audio_lufs_true_peak(target_lufs)}:LRA=11:print_format=json",
                    "-f",
                    "null",
                    "NUL",
                ]
                row = _matrix_run_command(context, category="audio", preset=preset_label, command=command)
            else:
                lufs_filter = ""
                first_pass: list[str] | None = None
                if lufs_mode == "two_pass":
                    first_pass = [
                        ffmpeg,
                        "-hide_banner",
                        "-nostats",
                        "-i",
                        str(source),
                        "-map",
                        "0:a:0",
                        "-af",
                        f"loudnorm=I={target_lufs}:TP={_audio_lufs_true_peak(target_lufs)}:LRA=11:print_format=json",
                        "-f",
                        "null",
                        "NUL",
                    ]
                    first = run_process(context, first_pass, extra_env=_tool_env(context.paths.root), check=False, progress_seconds=60)
                    if first.exit_code != 0:
                        status, detail = _matrix_status("audio", first)
                        rows.append(_matrix_row("audio", preset_label, status, detail, first_pass))
                        tick()
                        continue
                    lufs_filter, _unused = _audio_lufs_filter(params, _extract_loudnorm_json(first.lines))
                audio_args, extension, suffix = _audio_builder_args(params, lufs_filter, include_lufs=True, audio_only=workflow != "in_video")
                target = _output_path(source, output_dir / "audio", suffix if workflow != "in_video" else f"video_audio_{suffix}", extension if workflow != "in_video" else _audio_video_extension(params, source))
                if workflow == "in_video":
                    _safe_audio_video_container(params, target.suffix.lower().lstrip("."))
                    command = [ffmpeg, "-hide_banner", "-loglevel", "error", "-stats", "-y", "-i", str(source), "-map", "0:v?", "-map", "0:a:0", "-map", "0:s?", "-c:v", "copy", "-c:s", "copy", *audio_args, str(target)]
                else:
                    command = [ffmpeg, "-hide_banner", "-loglevel", "error", "-stats", "-y", "-i", str(source), "-map", "0:a:0", *audio_args, str(target)]
                commands = [item for item in [first_pass, command] if item]
                row = _matrix_run_sequence(context, category="audio", preset=preset_label, commands=commands)
            rows.append(row)
        except Exception as exc:
            row = _matrix_row("audio", preset_label, "FAIL", f"{exc.__class__.__name__}: {exc}")
            rows.append(row)
            context.log(f"[FAIL] audio / {preset_label}: {row['detail']}")
        tick()


def _matrix_run_remux(
    context: JobContext,
    rows: list[dict[str, object]],
    *,
    inputs: dict[str, Path],
    output_dir: Path,
    tick: Callable[[], None],
) -> None:
    ffmpeg = _ffmpeg(context.paths.root)
    video_cases = [
        ("mp4_to_mkv", inputs["mp4"], "mp4", "mkv"),
        ("mp4_to_mov", inputs["mp4"], "mp4", "mov"),
        ("mkv_to_mp4", inputs["mkv"], "mkv", "mp4"),
        ("mkv_to_mov", inputs["mkv"], "mkv", "mov"),
        ("mov_to_mp4", inputs["mov"], "mov", "mp4"),
        ("mov_to_mxf", inputs["mov_edit"], "mov", "mxf"),
    ]
    audio_cases = [
        ("mp4_audio_to_m4a", inputs["mp4"], "mp4", "m4a"),
        ("mp4_audio_to_aac", inputs["mp4"], "mp4", "aac"),
        ("mkv_audio_to_mka", inputs["mkv"], "mkv", "mka"),
        ("mov_audio_to_m4a", inputs["mov"], "mov", "m4a"),
        ("mov_pcm_audio_to_wav", inputs["mov_edit"], "mov", "wav"),
        ("wav_audio_to_wav", inputs["wav"], "wav", "wav"),
        ("wav_audio_to_mka", inputs["wav"], "wav", "mka"),
        ("flac_audio_to_flac", inputs["flac"], "flac", "flac"),
        ("mp3_audio_to_mp3", inputs["mp3"], "mp3", "mp3"),
        ("m4a_alac_to_alac", inputs["alac"], "m4a", "alac"),
        ("webm_opus_to_opus", inputs["webm_opus"], "webm", "opus"),
    ]
    for preset, source, source_format, target_format in video_cases:
        for stream_mode in ["video", "video_audio"]:
            stream_preset = f"{preset}_{stream_mode}"
            try:
                _selected, extension, suffix, remux_args = _remux_plan(source_format, target_format, stream_mode)
                target = _output_path(source, output_dir / "remux", suffix, extension)
                command = [ffmpeg, "-hide_banner", "-loglevel", "error", "-stats", "-y", "-i", str(source), *remux_args, str(target)]
                rows.append(_matrix_run_command(context, category="remux", preset=stream_preset, command=command))
            except Exception as exc:
                rows.append(_matrix_row("remux", stream_preset, "FAIL", f"{exc.__class__.__name__}: {exc}"))
            tick()
    for preset, source, source_format, target_format in audio_cases:
        try:
            _selected, extension, suffix, remux_args = _remux_plan(source_format, target_format, "audio")
            target = _output_path(source, output_dir / "remux", suffix, extension)
            command = [ffmpeg, "-hide_banner", "-loglevel", "error", "-stats", "-y", "-i", str(source), *remux_args, str(target)]
            rows.append(_matrix_run_command(context, category="remux", preset=preset, command=command))
        except Exception as exc:
            rows.append(_matrix_row("remux", preset, "FAIL", f"{exc.__class__.__name__}: {exc}"))
        tick()


def _matrix_run_fps(
    context: JobContext,
    rows: list[dict[str, object]],
    *,
    source: Path,
    output_dir: Path,
    tick: Callable[[], None],
) -> None:
    ffmpeg = _ffmpeg(context.paths.root)
    source_fps = Fraction(24, 1)
    profile_params = {
        "h264": {"fps_audio_pcm_depth": "s24", "fps_audio_oversample": "x1"},
        "hevc": {"fps_audio_pcm_depth": "s24", "fps_audio_oversample": "x1"},
        "prores": {"fps_audio_pcm_depth": "f32", "fps_audio_oversample": "x4"},
        "prores_mxf": {"fps_audio_pcm_depth": "s24", "fps_audio_oversample": "x4"},
        "dnxhr": {"fps_audio_pcm_depth": "f32", "fps_audio_oversample": "x4"},
        "dnxhr_mxf": {"fps_audio_pcm_depth": "s24", "fps_audio_oversample": "x4"},
    }
    for mode in ["varispeed", "conform"]:
        for target_value in ["24000/1001", "25"]:
            for profile, audio_params in profile_params.items():
                preset = f"{mode}_{target_value}_{profile}".replace("/", "_")
                try:
                    params = {
                        "fps_target": target_value,
                        "audio_bitrate": "384k",
                        **audio_params,
                    }
                    target_fps, target_arg, target_label = _target_fps(target_value)
                    k = float(source_fps / target_fps)
                    speed = float(target_fps / source_fps)
                    video_args, audio_args, extension, profile_label = _fps_output_args(profile, params)
                    target = _output_path(source, output_dir / "fps", f"fps_24_to_{target_label}_{mode}_{profile_label}", extension)
                    work_rate = _fps_audio_target_rate(48000, params)
                    output_rate = _fps_audio_output_rate(profile, work_rate)
                    command = _build_fps_command(
                        ffmpeg=ffmpeg,
                        source=str(source),
                        overwrite=True,
                        mode=mode,
                        k=k,
                        speed=speed,
                        target_arg=target_arg,
                        video_args=video_args,
                        audio_args=audio_args,
                        extension=extension,
                        target=str(target),
                        has_audio=True,
                        audio_work_rate=work_rate,
                        audio_output_rate=output_rate,
                    )
                    rows.append(_matrix_run_command(context, category="fps", preset=preset, command=command))
                except Exception as exc:
                    rows.append(_matrix_row("fps", preset, "FAIL", f"{exc.__class__.__name__}: {exc}"))
                tick()


def _matrix_run_grading_profiles(
    context: JobContext,
    rows: list[dict[str, object]],
    *,
    inputs: dict[str, Path],
    output_dir: Path,
    tick: Callable[[], None],
) -> None:
    ffmpeg = _ffmpeg(context.paths.root)
    for case in _matrix_profile_cases(context.paths.root, "grading"):
        params = dict(case["params"])
        params["lut_file"] = str(inputs["lut"])
        script = str(params.get("script_preset", "ff-grade-lut-only-x264.cmd")).strip()
        preset_label = str(case["id"])
        try:
            profile = script_profile(context.paths.root, script)
            lut_path = None if "hdr2sdr" in script.lower() else inputs["lut"]
            filter_expr, color_suffix = _color_filter(script, lut_path, params, profile)
            targets = _as_list(params.get("target_codecs")) or _as_list(profile.get("targets")) or [_color_default_target(script, profile)]
            source = inputs["hdr_mp4"] if "hdr2sdr" in script.lower() else inputs["mp4"]
            commands: list[list[str]] = []
            for target_codec in targets:
                target_codec = {"hevc10": "hevc_x265", "prores422": "prores_422"}.get(target_codec, target_codec)
                video, extension, video_suffix, family = _target_video_args(target_codec, params)
                target_path = _output_path(source, output_dir / "grading", f"{color_suffix}_{video_suffix}", extension)
                audio_mode = _container_audio_mode(extension, str(params.get("audio_mode", "aac_320")).strip())
                command = [ffmpeg, "-hide_banner", "-loglevel", "error", "-stats", "-y", *_decode_args(params, context, has_video_filters=True), "-i", str(source), "-map", "0:v:0", "-map", "0:a?", "-sn", "-dn", "-vf", filter_expr, *video, *_audio_args(audio_mode, _audio_bitrate(params), _mp3_lame_preset(params)), *_encode_audio_filter_args(params, audio_mode), "-map_metadata", "0"]
                if extension in {"mp4", "mov"}:
                    command.extend(["-movflags", "+faststart"])
                if extension == "mxf":
                    command.extend(["-f", "mxf"])
                command.append(str(target_path))
                commands.append(command)
            rows.append(_matrix_run_sequence(context, category="LUT", preset=preset_label, commands=commands, missing_is_miss=_matrix_missing_is_miss(params)))
        except Exception as exc:
            rows.append(_matrix_row("LUT", preset_label, "FAIL", f"{exc.__class__.__name__}: {exc}"))
        tick()


def _write_matrix_report(context: JobContext, rows: list[dict[str, object]]) -> dict[str, str]:
    report_json = context.report_dir / "preset_test_matrix.json"
    report_md = context.report_dir / "preset_test_matrix.md"
    counts = {status: sum(1 for row in rows if row.get("status") == status) for status in ["OK", "FAIL", "MISS", "SKIP"]}
    payload = {"summary": counts, "items": rows}
    report_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = [
        "# Preset Test Matrix",
        "",
        f"- OK: `{counts['OK']}`",
        f"- FAIL: `{counts['FAIL']}`",
        f"- MISS: `{counts['MISS']}`",
        f"- SKIP: `{counts['SKIP']}`",
        "",
        "| Status | Category | Preset | Detail |",
        "|---|---|---|---|",
    ]
    for row in rows:
        detail = str(row.get("detail", "")).replace("|", "\\|")
        lines.append(f"| {row.get('status', '-')} | {row.get('category', '-')} | `{row.get('preset', '-')}` | {detail} |")
    report_md.write_text("\n".join(lines), encoding="utf-8", newline="\n")
    return {"preset_matrix_json": str(report_json), "preset_matrix_md": str(report_md)}


def preset_test_matrix(context: JobContext) -> dict[str, object]:
    matrix_dir = context.report_dir / "preset_matrix"
    output_dir = matrix_dir / "outputs"
    matrix_dir.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, object]] = []
    inputs = _matrix_create_inputs(context, matrix_dir)

    profile_total = sum(len(_matrix_profile_cases(context.paths.root, node_id)) for node_id in ["audio", "archive", "editing", "storage", "delivery", "grading"])
    hardware_backend_total = len(MATRIX_HARDWARE_BACKENDS) * len(MATRIX_HARDWARE_TARGETS)
    total = max(1, profile_total + 2 + hardware_backend_total + 23 + 24)
    done = 0

    def tick() -> None:
        nonlocal done
        done += 1
        context.progress(min(0.98, done / total))

    ffmpeg = _ffmpeg(context.paths.root)
    hardware_tests = [
        ("CPU libx264", [ffmpeg, "-hide_banner", "-loglevel", "error", "-stats", "-y", "-i", str(inputs["mp4"]), "-c:v", "libx264", "-preset", "ultrafast", "-crf", "30", "-an", str(output_dir / "hardware" / "cpu_libx264.mp4")], False),
        ("QSV H.264", [ffmpeg, "-hide_banner", "-loglevel", "error", "-stats", "-y", "-i", str(inputs["mp4"]), "-c:v", "h264_qsv", "-preset", "medium", "-global_quality", "24", "-an", str(output_dir / "hardware" / "qsv_h264.mp4")], True),
    ]
    (output_dir / "hardware").mkdir(parents=True, exist_ok=True)
    for label, command, missing_is_miss in hardware_tests:
        rows.append(_matrix_run_command(context, category="hardware", preset=label, command=command, missing_is_miss=missing_is_miss))
        tick()

    _matrix_run_hardware_backends(context, rows, source=inputs["mp4"], output_dir=output_dir, tick=tick)

    _matrix_run_audio_profiles(context, rows, inputs=inputs, output_dir=output_dir, tick=tick)
    for category in ["archive", "editing", "storage", "delivery"]:
        _matrix_run_profile_family(context, rows, category=category, node_id=category, source=inputs["mp4"], output_dir=output_dir, tick=tick)
    _matrix_run_remux(context, rows, inputs=inputs, output_dir=output_dir, tick=tick)
    _matrix_run_fps(context, rows, source=inputs["mp4"], output_dir=output_dir, tick=tick)
    _matrix_run_grading_profiles(context, rows, inputs=inputs, output_dir=output_dir, tick=tick)

    counts = {status: sum(1 for row in rows if row.get("status") == status) for status in ["OK", "FAIL", "MISS", "SKIP"]}
    for status in ["OK", "FAIL", "MISS", "SKIP"]:
        context.log(f"{status}: {counts[status]}")
    reports = _write_matrix_report(context, rows)
    context.log(f"Preset matrix report: {reports['preset_matrix_md']}")
    context.progress(1.0)
    return {"ok": counts["FAIL"] == 0, "summary": counts, "items": rows, **reports}


def _probe_media_json(root: Path, source: Path) -> dict[str, Any]:
    command = [
        _ffprobe(root),
        "-v",
        "error",
        "-show_entries",
        "format=duration,bit_rate:stream=index,codec_type,codec_name,codec_tag_string,profile,width,height,avg_frame_rate,pix_fmt,color_space,color_transfer,color_primaries,sample_fmt,sample_rate,channels,channel_layout,bits_per_sample,bits_per_raw_sample,bit_rate:stream_tags=language,title",
        "-of",
        "json",
        str(source),
    ]
    completed = subprocess.run(
        command,
        cwd=str(root),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=utf8_subprocess_env(_tool_env(root)),
        **hidden_subprocess_kwargs(),
    )
    if completed.returncode != 0:
        raise RuntimeError((completed.stderr or completed.stdout or f"ffprobe exited {completed.returncode}").strip())
    try:
        data = json.loads(completed.stdout or "{}")
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"ffprobe returned invalid JSON for {source.name}: {exc}") from exc
    return data if isinstance(data, dict) else {}


def _media_duration_seconds(root: Path, source: Path) -> float | None:
    try:
        data = _probe_media_json(root, source)
        fmt = data.get("format", {}) if isinstance(data.get("format"), dict) else {}
        duration = float(fmt.get("duration") or 0.0)
    except Exception:
        return None
    return duration if duration > 0 else None


def _run_ffmpeg_media_process(
    context: JobContext,
    command: list[str],
    source: Path,
    *,
    check: bool = True,
    progress_seconds: float = 600.0,
    label: str = "",
) -> Any:
    root = context.paths.root
    duration = _media_duration_seconds(root, source)
    return run_process(
        context,
        command,
        extra_env=_tool_env(root),
        check=check,
        progress_seconds=progress_seconds,
        ffmpeg_progress=duration is not None,
        progress_total_seconds=duration,
        progress_label=label or source.name,
    )


def _rate_label(value: Any) -> str:
    text = str(value or "").strip()
    if not text or text in {"0/0", "N/A"}:
        return "?"
    try:
        rate = _parse_fps(text)
    except Exception:
        return text
    if rate == Fraction(24000, 1001):
        return "23.976p"
    if rate.denominator == 1:
        return f"{rate.numerator}p"
    return f"{float(rate):.3f}p"


def _stream(data: dict[str, Any], kind: str) -> dict[str, Any]:
    streams = data.get("streams", [])
    if not isinstance(streams, list):
        return {}
    for stream in streams:
        if isinstance(stream, dict) and stream.get("codec_type") == kind:
            return stream
    return {}


def _hdr_label(video: dict[str, Any]) -> str:
    transfer = str(video.get("color_transfer") or "").lower()
    primaries = str(video.get("color_primaries") or "").lower()
    if "smpte2084" in transfer:
        return "HDR10"
    if "arib-std-b67" in transfer:
        return "HLG"
    if "bt2020" in primaries:
        return "BT.2020"
    return ""


def _format_duration(value: Any) -> str:
    try:
        seconds = float(value)
    except (TypeError, ValueError):
        return "?"
    if seconds <= 0:
        return "?"
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    if hours:
        return f"{hours:d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:d}:{secs:02d}"


def _probe_row(source: Path, data: dict[str, Any]) -> dict[str, str]:
    video = _stream(data, "video")
    audio = _stream(data, "audio")
    fmt = data.get("format", {}) if isinstance(data.get("format"), dict) else {}

    video_codec = str(video.get("codec_name") or "-")
    resolution = f"{video.get('width')}x{video.get('height')}" if video.get("width") and video.get("height") else "-"
    fps = _rate_label(video.get("avg_frame_rate"))
    pix_fmt = str(video.get("pix_fmt") or "-")
    hdr = _hdr_label(video)
    audio_codec = str(audio.get("codec_name") or "-")
    sample_rate = f"{audio.get('sample_rate')} Hz" if audio.get("sample_rate") else "-"
    channels = str(audio.get("channel_layout") or audio.get("channels") or "-")
    bits = str(audio.get("bits_per_sample") or "-")
    duration = _format_duration(fmt.get("duration"))

    video_summary = " ".join(item for item in [video_codec.upper(), resolution, fps, pix_fmt, hdr] if item and item != "-")
    audio_summary = " ".join(item for item in [audio_codec.upper(), sample_rate, bits if bits != "0" else "", channels] if item and item != "-")
    return {
        "file": source.name,
        "video": video_summary or "-",
        "audio": audio_summary or "-",
        "duration": duration,
        "fingerprint": "|".join([video_codec, resolution, fps, pix_fmt, hdr, audio_codec, sample_rate, channels, bits]),
    }


def _probe_summary(rows: list[dict[str, str]], total_files: int) -> str:
    if not rows:
        return "Source probe: no media"
    mixed = len({row["fingerprint"] for row in rows}) > 1
    first = rows[0]
    prefix = f"{total_files} file(s)"
    if mixed:
        prefix += ", mixed"
    else:
        prefix += ", uniform"
    return f"{prefix} | V: {first['video']} | A: {first['audio']}"


def probe_source(context: JobContext) -> dict[str, object]:
    root = context.paths.root
    source_dir = cached_source_path(root)
    files = _media_files(source_dir, MEDIA_EXTENSIONS)
    if not files:
        context.log(f"No media files in {source_dir}")
        return {"files": 0, "summary": "Source probe: no media"}

    sample_limit = _as_int(context.operation.parameters.get("sample_limit"), 50)
    sample = files[: max(1, sample_limit)]
    rows: list[dict[str, str]] = []
    context.log(f"Probing Source: {source_dir}")
    context.log(f"Files: {len(files)} total, {len(sample)} probed")
    context.log("")
    context.log(f"{'FILE':40} | {'VIDEO':44} | {'AUDIO':34} | DUR")
    context.log("-" * 128)
    for index, source in enumerate(sample, start=1):
        if context.cancelled():
            context.log("Probe cancelled by user.")
            return {"cancelled": True, "files": len(files), "summary": "Source probe cancelled"}
        try:
            row = _probe_row(source, _probe_media_json(root, source))
        except Exception as exc:
            row = {"file": source.name, "video": f"ERROR: {exc}", "audio": "-", "duration": "-", "fingerprint": f"error:{exc}"}
        rows.append(row)
        context.log(f"{row['file'][:40]:40} | {row['video'][:44]:44} | {row['audio'][:34]:34} | {row['duration']}")
        context.progress(index / len(sample))

    summary = _probe_summary(rows, len(files))
    context.log("")
    context.log(summary)
    return {"files": len(files), "probed": len(sample), "mixed": len({row["fingerprint"] for row in rows}) > 1, "summary": summary}


SOURCE_INFO_COLUMNS = (
    ("file", "file"),
    ("stream", "stream"),
    ("codec", "codec"),
    ("sample_fmt", "sample_fmt"),
    ("sample_rate", "sample_rate"),
    ("bits_per_sample_raw", "bits_per_sample/raw"),
    ("channels_layout", "channels/layout"),
    ("bitrate", "bitrate"),
    ("language_title", "language/title"),
)


def _probe_cell(value: Any, *, zero_blank: bool = False) -> str:
    text = str(value if value is not None else "").strip()
    if not text or text == "N/A" or (zero_blank and text == "0"):
        return "-"
    return text.replace("\r", " ").replace("\n", " ")


def _join_probe_parts(*values: str) -> str:
    parts = [str(value).strip() for value in values if str(value).strip() and str(value).strip() != "-"]
    return " / ".join(parts) if parts else "-"


def _bits_per_sample_label(stream: dict[str, Any]) -> str:
    bits = _probe_cell(stream.get("bits_per_sample"), zero_blank=True)
    raw = _probe_cell(stream.get("bits_per_raw_sample"), zero_blank=True)
    if bits == raw:
        return bits
    if bits != "-" and raw != "-":
        return f"{bits}/{raw}"
    return bits if bits != "-" else raw


def _bitrate_label(value: Any) -> str:
    text = _probe_cell(value, zero_blank=True)
    if text == "-":
        return "-"
    try:
        bits = int(float(text))
    except (TypeError, ValueError):
        return text
    if bits >= 1_000_000:
        return f"{bits / 1_000_000:.2f} Mb/s"
    if bits >= 1_000:
        return f"{bits / 1_000:.0f} kb/s"
    return f"{bits} b/s"


def _source_info_audio_rows(root: Path, source_dir: Path, source: Path) -> list[dict[str, str]]:
    file_label = _source_display_name(source, source_dir)
    try:
        data = _probe_media_json(root, source)
    except Exception as exc:
        return [
            {
                "file": file_label,
                "stream": "ERROR",
                "codec": f"{exc.__class__.__name__}: {exc}",
                "sample_fmt": "-",
                "sample_rate": "-",
                "bits_per_sample_raw": "-",
                "channels_layout": "-",
                "bitrate": "-",
                "language_title": "-",
            }
        ]

    streams = data.get("streams", [])
    if not isinstance(streams, list):
        streams = []

    rows: list[dict[str, str]] = []
    audio_index = 0
    for stream in streams:
        if not isinstance(stream, dict) or stream.get("codec_type") != "audio":
            continue
        tags = stream.get("tags", {}) if isinstance(stream.get("tags"), dict) else {}
        stream_index = _probe_cell(stream.get("index"), zero_blank=False)
        language = _probe_cell(tags.get("language"))
        title = _probe_cell(tags.get("title"))
        rows.append(
            {
                "file": file_label,
                "stream": f"a:{audio_index} / 0:{stream_index}",
                "codec": _probe_cell(stream.get("codec_name")),
                "sample_fmt": _probe_cell(stream.get("sample_fmt")),
                "sample_rate": _probe_cell(stream.get("sample_rate")),
                "bits_per_sample_raw": _bits_per_sample_label(stream),
                "channels_layout": _join_probe_parts(_probe_cell(stream.get("channels")), _probe_cell(stream.get("channel_layout"))),
                "bitrate": _bitrate_label(stream.get("bit_rate")),
                "language_title": _join_probe_parts(language, title),
            }
        )
        audio_index += 1

    if not rows:
        return [
            {
                "file": file_label,
                "stream": "-",
                "codec": "NO AUDIO",
                "sample_fmt": "-",
                "sample_rate": "-",
                "bits_per_sample_raw": "-",
                "channels_layout": "-",
                "bitrate": "-",
                "language_title": "-",
            }
        ]
    return rows


def _source_info_line(row: dict[str, str]) -> str:
    return " | ".join(_probe_cell(row.get(key)).replace("|", "/") for key, _label in SOURCE_INFO_COLUMNS)


def _write_source_info_report(context: JobContext, rows: list[dict[str, str]]) -> dict[str, str]:
    report_json = context.report_dir / "source_info_audio_streams.json"
    report_md = context.report_dir / "source_info_audio_streams.md"
    context.report_dir.mkdir(parents=True, exist_ok=True)
    report_json.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    header = " | ".join(label for _key, label in SOURCE_INFO_COLUMNS)
    separator = " | ".join("---" for _key, _label in SOURCE_INFO_COLUMNS)
    lines = ["# Source Info", "", header, separator]
    lines.extend(_source_info_line(row) for row in rows)
    report_md.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {"source_info_json": str(report_json), "source_info_md": str(report_md)}


def source_info(context: JobContext) -> dict[str, object]:
    root = context.paths.root
    source_dir = cached_source_path(root)
    files = _media_files(source_dir, MEDIA_EXTENSIONS)
    if not files:
        context.log(f"No media files in {source_dir}")
        return {"files": 0, "audio_streams": 0}

    sample_limit = _as_int(context.operation.parameters.get("sample_limit"), 0)
    sample = files[:sample_limit] if sample_limit > 0 else files
    rows: list[dict[str, str]] = []
    audio_streams = 0
    context.log(f"Source Info: {source_dir}")
    context.log(f"Files: {len(files)} total, {len(sample)} probed")
    context.log("")
    context.log(" | ".join(label for _key, label in SOURCE_INFO_COLUMNS))
    context.log(" | ".join("---" for _key, _label in SOURCE_INFO_COLUMNS))

    for index, source in enumerate(sample, start=1):
        if context.cancelled():
            context.log("Source Info cancelled by user.")
            reports = _write_source_info_report(context, rows)
            return {"cancelled": True, "files": len(files), "probed": index - 1, "audio_streams": audio_streams, **reports}
        file_rows = _source_info_audio_rows(root, source_dir, source)
        for row in file_rows:
            if row.get("stream") not in {"-", "ERROR"}:
                audio_streams += 1
            rows.append(row)
            context.log(_source_info_line(row))
        context.progress(index / len(sample))

    reports = _write_source_info_report(context, rows)
    context.log("")
    context.log(f"Audio streams: {audio_streams}")
    context.log(f"Source Info report: {reports['source_info_md']}")
    return {"files": len(files), "probed": len(sample), "audio_streams": audio_streams, **reports}


def encode_targets(context: JobContext) -> dict[str, object]:
    params = dict(context.operation.parameters)
    root = context.paths.root
    source_dir = cached_source_path(root)
    output_dir = cached_output_path(root)
    extensions = _normalize_extensions(_as_list(params.get("input_formats"))) or {"mp4", "mov", "mkv", "mxf", "avi", "webm", "mts", "m2ts"}
    files = _media_files(source_dir, extensions)
    if _as_bool(params.get("limit_first_file"), False):
        files = files[:1]

    targets = _as_list(params.get("target_codecs"))
    if not targets:
        raise RuntimeError("No target codec/profile selected.")
    if not files:
        context.log(f"No matching media files in {source_dir}")
        return {"files": 0}

    ffmpeg = _ffmpeg(root)
    # Scaling runs as a software filter, so it rules out the GPU-only pipeline.
    decode = _decode_args(params, context, has_video_filters=bool(_scale_args(params)))
    audio_mode = str(params.get("audio_mode", "aac_320")).strip()
    audio_bitrate = _audio_bitrate(params)
    dry_run = _as_bool(params.get("dry_run"), False)
    overwrite = _as_bool(params.get("overwrite"), True)

    processed = 0
    total = len(files) * len(targets)
    for source in files:
        for target_codec in targets:
            target_codec = {"hevc10": "hevc_x265", "prores422": "prores_422"}.get(target_codec, target_codec)
            if context.cancelled():
                context.log("Encoding cancelled by user.")
                return {"cancelled": True, "processed": processed}

            video, extension, suffix, family = _target_video_args(target_codec, params)
            source_label = _source_display_name(source, source_dir)
            target_path = _output_path(source, output_dir, suffix, extension, source_root=source_dir, operation=_operation_output_folder(context, _target_family_output_folder(family)))
            command = [ffmpeg, "-hide_banner", "-stats", "-y" if overwrite else "-n", *decode, "-i", str(source)]

            if family == "archive":
                archive_audio = "flac" if target_codec == "ffv1" and audio_mode in {"aac_320", "source"} else audio_mode
                command.extend(["-map", "0", "-dn", *video, *_audio_args(archive_audio, audio_bitrate, _mp3_lame_preset(params)), *_encode_audio_filter_args(params, archive_audio), "-c:s", "copy", "-map_metadata", "0"])
            elif family == "editing":
                edit_audio = _container_audio_mode(extension, audio_mode)
                command.extend(["-map", "0:v:0", "-map", "0:a?", "-sn", "-dn", *_scale_args(params), *video, *_audio_args(edit_audio, audio_bitrate, _mp3_lame_preset(params)), *_encode_audio_filter_args(params, edit_audio), "-map_metadata", "0"])
                if extension == "mxf":
                    command.extend(["-f", "mxf"])
                elif extension == "mov":
                    command.extend(["-movflags", "+faststart"])
            else:
                # Storage and delivery can also target MOV, so the container
                # gate applies here exactly like it does for editing.
                target_audio_mode = _container_audio_mode(extension, audio_mode)
                command.extend(["-map", "0:v:0"])
                if target_audio_mode != "none":
                    command.extend(["-map", "0:a?"])
                command.extend(["-sn", "-dn", *_scale_args(params), *video, *_audio_args(target_audio_mode, audio_bitrate, _mp3_lame_preset(params)), *_encode_audio_filter_args(params, target_audio_mode), "-map_metadata", "0"])
                if extension == "mp4":
                    command.extend(["-movflags", "+faststart"])

            command.append(str(target_path))
            context.log(f"[{processed + 1}/{total}] {source_label} -> {target_codec}")
            if dry_run:
                context.log("[DRY RUN] Command was not executed.")
                context.log(" ".join(f'"{part}"' if " " in part else part for part in command))
            else:
                _run_ffmpeg_media_process(context, command, source, check=True, progress_seconds=900, label=f"{source_label} -> {target_codec}")
            processed += 1
            context.progress(processed / max(1, total))

    return {"processed": processed, "files": len(files), "targets": targets, "dry_run": dry_run}


def _audio_stream_rows(root: Path, source: Path) -> list[dict[str, Any]]:
    try:
        data = _probe_media_json(root, source)
    except Exception:
        return []
    rows: list[dict[str, Any]] = []
    audio_index = 0
    for stream in data.get("streams", []):
        if not isinstance(stream, dict) or stream.get("codec_type") != "audio":
            continue
        tags = stream.get("tags", {}) if isinstance(stream.get("tags"), dict) else {}
        rows.append(
            {
                "stream_index": int(stream.get("index", audio_index)),
                "audio_index": audio_index,
                "codec": str(stream.get("codec_name") or "-"),
                "sample_fmt": str(stream.get("sample_fmt") or ""),
                "sample_rate": str(stream.get("sample_rate") or "-"),
                "channels": str(stream.get("channels") or "-"),
                "channel_layout": str(stream.get("channel_layout") or ""),
                "bits": str(stream.get("bits_per_sample") or ""),
                "bits_per_raw_sample": str(stream.get("bits_per_raw_sample") or ""),
                "bit_rate": str(stream.get("bit_rate") or ""),
                "language": str(tags.get("language") or ""),
                "title": str(tags.get("title") or ""),
            }
        )
        audio_index += 1
    return rows


def _audio_stream_summary(row: dict[str, Any]) -> str:
    rate = f"{row.get('sample_rate')} Hz" if row.get("sample_rate") and row.get("sample_rate") != "-" else ""
    channels = row.get("channel_layout") or (f"{row.get('channels')} ch" if row.get("channels") and row.get("channels") != "-" else "")
    bits = f"{row.get('bits')} bit" if row.get("bits") else ""
    language = f"lang={row.get('language')}" if row.get("language") else ""
    return " ".join(str(item) for item in [row.get("codec", "-"), rate, bits, channels, language] if item)


def _selected_audio_streams(root: Path, source: Path, params: dict[str, Any]) -> list[dict[str, Any]]:
    rows = _audio_stream_rows(root, source)
    if not rows:
        return []
    mode = str(params.get("audio_stream_mode", "first")).strip().lower() or "first"
    if mode == "all":
        return rows
    if mode == "index":
        index = _as_int(params.get("audio_stream_index"), 0)
        return [row for row in rows if int(row.get("audio_index", -1)) == index]
    if mode == "language":
        language = str(params.get("audio_language", "")).strip().lower()
        if not language:
            raise RuntimeError("Audio language tag is empty.")
        return [row for row in rows if str(row.get("language", "")).strip().lower() == language]
    return rows[:1]


def _audio_stream_map_args(row: dict[str, Any]) -> list[str]:
    return ["-map", f"0:{int(row.get('stream_index', 0))}"]


def _audio_stream_suffix(params: dict[str, Any], row: dict[str, Any], selected_count: int) -> str:
    mode = str(params.get("audio_stream_mode", "first")).strip().lower() or "first"
    if mode == "first" and selected_count == 1:
        return ""
    language = str(row.get("language") or "").strip()
    parts = [f"a{row.get('audio_index', 0)}"]
    if language:
        parts.append(language)
    return "_".join(parts)


def _extract_loudnorm_json(lines: tuple[str, ...]) -> dict[str, Any]:
    text = "\n".join(lines)
    matches = re.findall(r"\{[\s\S]*?\}", text)
    for raw in reversed(matches):
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            continue
        required = {"input_i", "input_tp", "input_lra", "input_thresh", "target_offset"}
        if required.issubset(data):
            return data
    raise RuntimeError("Could not parse loudnorm JSON from FFmpeg output.")


def _run_loudnorm_analysis(context: JobContext, ffmpeg: str, source: Path, map_args: list[str], target_lufs: str) -> dict[str, Any]:
    true_peak = _audio_lufs_true_peak(target_lufs)
    command = [
        ffmpeg,
        "-hide_banner",
        "-nostats",
        "-i",
        str(source),
        *map_args,
        "-af",
        f"loudnorm=I={target_lufs}:TP={true_peak}:LRA=11:print_format=json",
        "-f",
        "null",
        "NUL",
    ]
    result = run_process(context, command, extra_env=_tool_env(context.paths.root), check=True, progress_seconds=180)
    return _extract_loudnorm_json(result.lines)


def _write_audio_report(context: JobContext, rows: list[dict[str, Any]]) -> dict[str, str]:
    report_json = context.report_dir / "audio_report.json"
    report_md = context.report_dir / "audio_report.md"
    report_json.write_text(json.dumps({"items": rows}, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = ["# Audio Report", ""]
    if not rows:
        lines.append("- No audio items were processed.")
    else:
        lines.append("| Status | Source | Stream | Input | Output | Mode | LUFS |")
        lines.append("|---|---|---:|---|---|---|---|")
        for row in rows:
            output = str(row.get("output") or "-").replace("|", "\\|")
            source = str(row.get("source") or "-").replace("|", "\\|")
            input_summary = str(row.get("input") or "-").replace("|", "\\|")
            lines.append(
                f"| {row.get('status', '-')} | {source} | {row.get('stream', '-')} | {input_summary} | {output} | {row.get('mode', '-')} | {row.get('lufs', '-')} |"
            )
    report_md.write_text("\n".join(lines), encoding="utf-8", newline="\n")
    return {"audio_report_json": str(report_json), "audio_report_md": str(report_md)}


def _audio_workflow(params: dict[str, Any]) -> str:
    value = str(params.get("audio_workflow", "extract")).strip().lower()
    if value in {"in_video", "video", "inside_video", "container"}:
        return "in_video"
    if value in {"audio_files", "files", "audio_only"}:
        return "audio_files"
    return "extract"


def _audio_video_extension(params: dict[str, Any], source: Path) -> str:
    container = str(params.get("audio_video_container", "source")).strip().lower() or "source"
    if container in {"source", "same", "native"}:
        return source.suffix.lower().lstrip(".") or "mov"
    return container.lstrip(".")


def _safe_audio_video_container(params: dict[str, Any], extension: str) -> None:
    audio_format = str(params.get("audio_format", "wav")).strip().lower()
    if extension == "mp4" and audio_format in {"wav", "flac"}:
        raise RuntimeError("MP4 is not a safe container for PCM/FLAC audio replacement. Choose MOV or MKV for this audio format.")
    if extension == "mov" and audio_format in {"flac", "opus"}:
        raise RuntimeError("MOV is not a safe container for FLAC/Opus audio replacement. Choose MKV for this audio format.")
    if extension == "mxf" and audio_format in {"flac", "alac", "m4a", "mp3", "opus"}:
        raise RuntimeError("MXF is not a safe container for this compressed audio format. Choose MOV or MKV.")


def _audio_in_video_process(
    context: JobContext,
    *,
    params: dict[str, Any],
    files: list[Path],
    ffmpeg: str,
    output_dir: Path,
    operation: str,
    source_root: Path,
    dry_run: bool,
    overwrite: bool,
) -> dict[str, object]:
    processed = 0
    report_rows: list[dict[str, Any]] = []

    for index, source in enumerate(files, start=1):
        source_label = _source_display_name(source, source_root)
        if context.cancelled():
            context.log("Audio-in-video operation cancelled by user.")
            return {"cancelled": True, "processed": processed}

        selected_streams = _selected_audio_streams(context.paths.root, source, params)
        if not selected_streams:
            context.log(f"[{index}/{len(files)}] {source_label}: no matching audio stream")
            report_rows.append({"status": "SKIP", "source": source_label, "stream": "-", "input": "no matching audio stream", "output": "", "mode": "in_video", "lufs": "-"})
            context.progress(index / len(files))
            continue

        lufs_mode = _audio_lufs_mode(params)
        if len(selected_streams) > 1 and lufs_mode == "two_pass":
            raise RuntimeError("Two-pass LUFS inside one video currently supports one selected audio stream. Use first/index/language or extract streams to files.")

        map_args: list[str] = []
        for stream_row in selected_streams:
            map_args.extend(_audio_stream_map_args(stream_row))

        target_lufs = _audio_lufs_target(params)
        lufs_filter = ""
        lufs_stats: dict[str, Any] | None = None
        if lufs_mode in {"report", "two_pass"}:
            stream_row = selected_streams[0]
            context.log(f"[LUFS] {source_label} stream a{stream_row['audio_index']} -> {target_lufs}")
            if dry_run:
                context.log("[DRY RUN] LUFS analysis command was not executed.")
            else:
                lufs_stats = _run_loudnorm_analysis(context, ffmpeg, source, _audio_stream_map_args(stream_row), target_lufs if target_lufs != "off" else "-23")
            if lufs_mode == "report":
                for stream_row in selected_streams:
                    report_rows.append(
                        {
                            "status": "DRY" if dry_run else "OK",
                            "source": source_label,
                            "stream": f"a{stream_row['audio_index']}",
                            "input": _audio_stream_summary(stream_row),
                            "output": "",
                            "mode": "in_video_lufs_report",
                            "lufs": json.dumps(lufs_stats, ensure_ascii=False) if lufs_stats else target_lufs,
                        }
                    )
                processed += len(selected_streams)
                context.progress(index / len(files))
                continue
            if lufs_stats:
                lufs_filter, _unused_suffix = _audio_lufs_filter(params, lufs_stats)

        audio_args, _unused_extension, suffix = _audio_builder_args(params, lufs_filter, include_lufs=True, audio_only=False)
        extension = _audio_video_extension(params, source)
        _safe_audio_video_container(params, extension)
        target = _output_path(source, output_dir, f"video_copy_audio_{suffix}", extension, source_root=source_root, operation=operation)
        command = [
            ffmpeg,
            "-hide_banner",
            "-stats",
            "-y" if overwrite else "-n",
            "-i",
            str(source),
            "-map",
            "0:v?",
            *map_args,
            "-map",
            "0:s?",
            "-c:v",
            "copy",
            "-c:s",
            "copy",
            *audio_args,
            str(target),
        ]
        context.log(f"[{index}/{len(files)}] {source_label}: video copy + audio update -> {extension.upper()}")
        if dry_run:
            context.log("[DRY RUN] Command was not executed.")
            context.log(" ".join(f'"{part}"' if " " in part else part for part in command))
        else:
            _run_ffmpeg_media_process(context, command, source, check=True, progress_seconds=600, label=f"{source_label} audio")

        for stream_row in selected_streams:
            report_rows.append(
                {
                    "status": "DRY" if dry_run else "OK",
                    "source": source_label,
                    "stream": f"a{stream_row['audio_index']}",
                    "input": _audio_stream_summary(stream_row),
                    "output": str(target),
                    "mode": "in_video",
                    "lufs": target_lufs if lufs_mode != "off" else "-",
                }
            )
        processed += len(selected_streams)
        context.progress(index / len(files))

    audio_report = _write_audio_report(context, report_rows)
    context.log(f"Audio report: {audio_report['audio_report_md']}")
    return {"processed": processed, "files": len(files), "task": "audio_in_video", "dry_run": dry_run, "audio_items": report_rows, **audio_report}


def audio_process(context: JobContext) -> dict[str, object]:
    params = dict(context.operation.parameters)
    root = context.paths.root
    source_dir = cached_source_path(root)
    workflow = _audio_workflow(params)
    output_dir = cached_output_path(root)
    operation_folder = "AudioInVideo" if workflow == "in_video" else _operation_output_folder(context, "Audio")
    raw_extensions = _as_list(params.get("input_formats"))
    if raw_extensions:
        extensions = _normalize_extensions(raw_extensions)
    elif workflow == "audio_files":
        extensions = set(PURE_AUDIO_EXTENSIONS)
    else:
        extensions = set(VIDEO_CONTAINER_EXTENSIONS)
    files = _media_files(source_dir, extensions)
    if _as_bool(params.get("limit_first_file"), False):
        files = files[:1]
    if not files:
        context.log(f"No matching audio/video files in {source_dir}")
        return {"files": 0}

    audio_args, extension, suffix = _audio_builder_args(params)
    operation_label = str(params.get("audio_format", "wav")).strip() or "wav"
    ffmpeg = _ffmpeg(root)
    dry_run = _as_bool(params.get("dry_run"), False)
    overwrite = _as_bool(params.get("overwrite"), True)
    if workflow == "in_video":
        return _audio_in_video_process(context, params=params, files=files, ffmpeg=ffmpeg, output_dir=output_dir, operation=operation_folder, source_root=source_dir, dry_run=dry_run, overwrite=overwrite)

    processed = 0
    report_rows: list[dict[str, Any]] = []

    for index, source in enumerate(files, start=1):
        source_label = _source_display_name(source, source_dir)
        if context.cancelled():
            context.log("Audio operation cancelled by user.")
            return {"cancelled": True, "processed": processed}

        selected_streams = _selected_audio_streams(root, source, params)
        if not selected_streams:
            context.log(f"[{index}/{len(files)}] {source_label}: no matching audio stream")
            report_rows.append({"status": "SKIP", "source": source_label, "stream": "-", "input": "no matching audio stream", "output": "", "mode": operation_label, "lufs": "-"})
            context.progress(index / len(files))
            continue

        for stream_row in selected_streams:
            if context.cancelled():
                context.log("Audio operation cancelled by user.")
                return {"cancelled": True, "processed": processed}

            map_args = _audio_stream_map_args(stream_row)
            lufs_mode = _audio_lufs_mode(params)
            target_lufs = _audio_lufs_target(params)
            lufs_stats: dict[str, Any] | None = None
            lufs_filter = ""
            if lufs_mode in {"report", "two_pass"}:
                context.log(f"[LUFS] {source_label} stream a{stream_row['audio_index']} -> {target_lufs}")
                if dry_run:
                    context.log("[DRY RUN] LUFS analysis command was not executed.")
                else:
                    lufs_stats = _run_loudnorm_analysis(context, ffmpeg, source, map_args, target_lufs if target_lufs != "off" else "-23")
                if lufs_mode == "report":
                    report_rows.append(
                        {
                            "status": "DRY" if dry_run else "OK",
                            "source": source_label,
                            "stream": f"a{stream_row['audio_index']}",
                            "input": _audio_stream_summary(stream_row),
                            "output": "",
                            "mode": "lufs_report",
                            "lufs": json.dumps(lufs_stats, ensure_ascii=False) if lufs_stats else target_lufs,
                        }
                    )
                    processed += 1
                    continue
                if lufs_stats:
                    lufs_filter, _unused_suffix = _audio_lufs_filter(params, lufs_stats)

            audio_args, extension, suffix = _audio_builder_args(params, lufs_filter, include_lufs=True, stream_row=stream_row)
            stream_suffix = _audio_stream_suffix(params, stream_row, len(selected_streams))
            target_suffix = "_".join(item for item in [suffix, stream_suffix] if item)
            target = _output_path(source, output_dir, target_suffix, extension, source_root=source_dir, operation=operation_folder)
            command = [ffmpeg, "-hide_banner", "-stats", "-y" if overwrite else "-n", "-i", str(source), *map_args, *audio_args, str(target)]
            context.log(f"[{index}/{len(files)}] {source_label} a{stream_row['audio_index']} -> {operation_label}")
            if dry_run:
                context.log("[DRY RUN] Command was not executed.")
                context.log(" ".join(f'"{part}"' if " " in part else part for part in command))
            else:
                _run_ffmpeg_media_process(context, command, source, check=True, progress_seconds=600, label=f"{source_label} a{stream_row['audio_index']}")
            report_rows.append(
                {
                    "status": "DRY" if dry_run else "OK",
                    "source": source_label,
                    "stream": f"a{stream_row['audio_index']}",
                    "input": _audio_stream_summary(stream_row),
                    "output": str(target),
                    "mode": operation_label,
                    "lufs": target_lufs if lufs_mode != "off" else "-",
                }
            )
            processed += 1
        context.progress(index / len(files))

    audio_report = _write_audio_report(context, report_rows)
    context.log(f"Audio report: {audio_report['audio_report_md']}")
    return {"processed": processed, "files": len(files), "task": operation_label, "dry_run": dry_run, "audio_items": report_rows, **audio_report}


VIDEO_REMUX_COMPATIBILITY = {
    "mp4": {"mp4", "mov", "mkv"},
    "mov": {"mov", "mp4", "mkv", "mxf"},
    "mkv": {"mkv", "mp4", "mov"},
    "mxf": {"mxf", "mov", "mkv"},
    "avi": {"avi", "mkv"},
    "webm": {"webm", "mkv"},
    "mts": {"mp4", "mkv"},
    "m2ts": {"mp4", "mkv"},
}

# Which streams each container accepts on a copy. Measured against the bundled
# FFmpeg, not assumed: the container pair alone lets ProRes into MP4, where the
# muxer has no tag for it and writes an empty file.
#
# These tables say what is known to work, so a codec that appears in no table at
# all is passed through to FFmpeg instead of being refused on a guess. A blanket
# refusal costs the user a working conversion; letting FFmpeg answer costs one
# failed run whose empty output is cleaned up.
VIDEO_COPY_CODECS = {
    "mp4": {"av1", "ffv1", "h264", "hevc", "jpeg2000", "mjpeg", "mpeg2video", "mpeg4", "vp9"},
    "mov": {"dnxhd", "dvvideo", "ffv1", "h264", "hevc", "jpeg2000", "mjpeg", "mpeg2video", "mpeg4", "prores", "theora"},
    "mkv": {"av1", "dnxhd", "dvvideo", "ffv1", "h264", "hevc", "jpeg2000", "mjpeg", "mpeg2video", "mpeg4", "prores", "theora", "vp8", "vp9"},
    "mxf": {"dnxhd", "dvvideo", "ffv1", "h264", "jpeg2000", "mpeg2video", "prores"},
    "avi": {"av1", "dnxhd", "dvvideo", "ffv1", "h264", "hevc", "jpeg2000", "mjpeg", "mpeg2video", "mpeg4", "prores", "theora", "vp8", "vp9"},
    "webm": {"av1", "vp8", "vp9"},
}

AUDIO_COPY_CODECS = {
    "mp4": {"aac", "ac3", "alac", "dts", "eac3", "flac", "mp3", "opus", "pcm_f32le", "pcm_s16le", "pcm_s24le", "vorbis"},
    "mov": {"aac", "ac3", "alac", "dts", "eac3", "mp3", "pcm_f32le", "pcm_s16le", "pcm_s24le", "vorbis", "wmav2"},
    "mkv": {"aac", "ac3", "alac", "dts", "eac3", "flac", "mp3", "opus", "pcm_f32le", "pcm_s16le", "pcm_s24le", "vorbis", "wmav2"},
    "mxf": {"pcm_s16le", "pcm_s24le"},
    "avi": {"aac", "ac3", "dts", "eac3", "flac", "mp3", "pcm_f32le", "pcm_s16le", "pcm_s24le", "vorbis", "wmav2"},
    "webm": {"opus", "vorbis"},
}

KNOWN_VIDEO_COPY_CODECS = set().union(*VIDEO_COPY_CODECS.values())
KNOWN_AUDIO_COPY_CODECS = set().union(*AUDIO_COPY_CODECS.values())

AUDIO_REMUX_COMPATIBILITY = {
    "mp4": {"m4a", "alac", "aac", "mka"},
    "mov": {"m4a", "alac", "aac", "wav", "mka"},
    "mkv": {"mka"},
    "mxf": {"wav", "mka"},
    "avi": {"wav", "mp3", "mka"},
    "webm": {"opus", "ogg", "mka"},
    "mts": {"aac", "ac3", "eac3", "mka"},
    "m2ts": {"aac", "ac3", "eac3", "mka"},
    "m4a": {"m4a", "alac", "aac", "mka"},
    "mka": {"mka"},
    "aac": {"aac", "m4a", "mka"},
    "ac3": {"ac3", "mka"},
    "eac3": {"eac3", "mka"},
    "dts": {"dts", "mka"},
    "flac": {"flac", "mka"},
    "wav": {"wav", "mka"},
    "mp3": {"mp3", "mka"},
    "opus": {"opus", "ogg", "mka"},
    "ogg": {"ogg", "opus", "mka"},
}

AUDIO_REMUX_TARGET_FORMATS = {"m4a", "alac", "mka", "aac", "ac3", "eac3", "dts", "flac", "wav", "mp3", "opus", "ogg"}

LEGACY_REMUX_TASKS = {
    "mp4_to_mkv": ("mp4", "mkv"),
    "mkv_to_mp4": ("mkv", "mp4"),
    "mkv_to_mp4_faststart": ("mkv", "mp4"),
    "mov_to_mxf": ("mov", "mxf"),
    "mxf_to_mov": ("mxf", "mov"),
}


def _remux_stream_mode(params: dict[str, Any]) -> str:
    value = str(params.get("remux_stream_mode", "video_audio")).strip().lower()
    if value in {"video", "v", "video_only"}:
        return "video"
    if value in {"audio", "a", "audio_only"}:
        return "audio"
    return "video_audio"


def _remux_stream_map_args(stream_mode: str) -> tuple[list[str], str]:
    if stream_mode == "video":
        return ["-map", "0:v?", "-an", "-sn", "-dn"], "video"
    if stream_mode == "audio":
        return ["-map", "0:a?", "-vn", "-sn", "-dn"], "audio"
    return ["-map", "0:v?", "-map", "0:a?", "-sn", "-dn"], "video_audio"


def _remux_output_extension(target_format: str) -> str:
    return {"alac": "m4a"}.get(target_format.strip().lower(), target_format.strip().lower())


def _remux_normalized_source_format(source: Path) -> str:
    value = source.suffix.lower().lstrip(".")
    return {
        "m4v": "mp4",
        "3gp": "mp4",
        "mpg": "mpeg",
        "ts": "mts",
        "m4b": "m4a",
        "oga": "ogg",
        "w64": "wav",
        "aif": "wav",
        "aiff": "wav",
    }.get(value, value)


def _remux_target_format(params: dict[str, Any], stream_mode: str) -> str:
    if stream_mode == "audio":
        target_format = str(params.get("remux_audio_target_format", "")).strip().lower()
        if target_format:
            return target_format
        return "mka"
    target_format = str(params.get("remux_target_format", "")).strip().lower()
    if target_format:
        return target_format
    _legacy_source, legacy_target = LEGACY_REMUX_TASKS.get(str(params.get("remux_task", "")).strip().lower(), ("mkv", "mp4"))
    return legacy_target


def _remux_candidate_extensions(stream_mode: str) -> set[str]:
    if stream_mode == "audio":
        return set(MEDIA_EXTENSIONS)
    return set(VIDEO_CONTAINER_EXTENSIONS)


def _remux_source_has_audio(root: Path, source: Path) -> bool:
    return bool(_audio_stream_rows(root, source))


def _audio_copy_target_supported(root: Path, source: Path, target_format: str) -> tuple[bool, str]:
    target_format = target_format.strip().lower()
    rows = _audio_stream_rows(root, source)
    if not rows:
        return False, "no audio streams"
    if target_format == "mka":
        return True, ""
    codec_allowlist = {
        "m4a": {"aac", "alac", "mp3"},
        "alac": {"alac"},
        "aac": {"aac"},
        "ac3": {"ac3"},
        "eac3": {"eac3"},
        "dts": {"dts"},
        "flac": {"flac"},
        "wav": {"pcm_s16le", "pcm_s24le", "pcm_s32le", "pcm_f32le", "pcm_f64le", "pcm_s16be", "pcm_s24be", "pcm_s32be"},
        "mp3": {"mp3"},
        "opus": {"opus"},
        "ogg": {"opus", "vorbis", "flac"},
    }
    allowed = codec_allowlist.get(target_format)
    if not allowed:
        return False, f"{target_format.upper()} is not an audio copy target"
    codecs = [str(row.get("codec") or "").strip().lower() for row in rows]
    unsupported = sorted({codec or "unknown" for codec in codecs if codec not in allowed})
    if unsupported:
        return False, f"{target_format.upper()} does not support copy of {', '.join(unsupported)}"
    single_stream_targets = {"aac", "ac3", "eac3", "dts", "flac", "wav", "mp3", "opus"}
    if target_format in single_stream_targets and len(rows) > 1:
        return False, f"{target_format.upper()} output is single-stream; choose MKA for {len(rows)} audio streams"
    return True, ""


def _discard_empty_output(context: JobContext, target: Path) -> None:
    """Drop the 0-byte file a failed muxer leaves behind.

    Only an empty file is removed: a partial but readable result may still be
    worth keeping, and deleting it would be a surprise.
    """
    try:
        if target.exists() and target.stat().st_size == 0:
            target.unlink()
            context.log(f"[CLEAN] Removed the empty {target.name} left by the failed run.")
    except OSError as exc:
        context.log(f"[WARN] Could not remove {target.name}: {exc}")


def _stream_codecs(root: Path, source: Path, codec_type: str) -> list[str]:
    try:
        data = _probe_media_json(root, source)
    except Exception:
        return []
    return [
        str(stream.get("codec_name") or "").strip().lower()
        for stream in data.get("streams", [])
        if isinstance(stream, dict) and stream.get("codec_type") == codec_type
    ]


def _copy_codecs_supported(codecs: list[str], target_format: str, table: dict[str, set[str]], known: set[str]) -> tuple[bool, str]:
    allowed = table.get(target_format.strip().lower())
    if allowed is None:
        return True, ""
    # Only a codec we have actually measured can be refused here. Anything else
    # goes to FFmpeg, which knows its own muxers better than this table does.
    unsupported = sorted({codec for codec in codecs if codec in known and codec not in allowed})
    if unsupported:
        return False, f"{target_format.upper()} does not support copy of {', '.join(unsupported)}"
    return True, ""


def _video_copy_target_supported(root: Path, source: Path, target_format: str) -> tuple[bool, str]:
    codecs = _stream_codecs(root, source, "video")
    if not codecs:
        return False, "no video streams"
    return _copy_codecs_supported(codecs, target_format, VIDEO_COPY_CODECS, KNOWN_VIDEO_COPY_CODECS)


def _video_audio_copy_target_supported(root: Path, source: Path, target_format: str) -> tuple[bool, str]:
    codecs = _stream_codecs(root, source, "audio")
    if not codecs:
        return True, ""
    return _copy_codecs_supported(codecs, target_format, AUDIO_COPY_CODECS, KNOWN_AUDIO_COPY_CODECS)


def _remux_file_supported(root: Path, source: Path, target_format: str, stream_mode: str) -> tuple[bool, str]:
    source_format = _remux_normalized_source_format(source)
    if stream_mode == "audio":
        if not _remux_source_has_audio(root, source):
            return False, "no audio streams"
        if target_format in AUDIO_REMUX_COMPATIBILITY.get(source_format, set()):
            if target_format == "mka":
                return True, ""
            return _audio_copy_target_supported(root, source, target_format)
        return _audio_copy_target_supported(root, source, target_format)
    if target_format not in VIDEO_REMUX_COMPATIBILITY.get(source_format, set()):
        return False, f"{source_format.upper()} -> {target_format.upper()} is not a safe video container copy pair"
    # A compatible container pair is not enough: MOV carries ProRes and MP4
    # does not, so the codec inside the file decides too.
    supported, reason = _video_copy_target_supported(root, source, target_format)
    if not supported:
        return False, reason
    if stream_mode == "video_audio":
        # MKV -> MP4 used to be refused wholesale here. What actually decides is
        # whether the container can hold these streams, and subtitles and data
        # never reach the muxer because the stream map drops them.
        supported, reason = _video_audio_copy_target_supported(root, source, target_format)
        if not supported:
            return False, reason
    return True, ""


def _remux_plan(source_format: str, target_format: str, stream_mode: str = "video_audio") -> tuple[set[str], str, str, list[str]]:
    source_format = source_format.strip().lower()
    target_format = target_format.strip().lower()
    compatibility = AUDIO_REMUX_COMPATIBILITY if stream_mode == "audio" else VIDEO_REMUX_COMPATIBILITY
    compatible = compatibility.get(source_format, set())
    if target_format not in compatible:
        if stream_mode == "audio" and target_format in AUDIO_REMUX_TARGET_FORMATS:
            compatible = {target_format}
        else:
            layer = "audio" if stream_mode == "audio" else "video"
            raise RuntimeError(f"{layer.title()} remux {source_format.upper()} -> {target_format.upper()} is not enabled because the container pair is not safe enough for stream copy.")
    stream_map_args, stream_suffix = _remux_stream_map_args(stream_mode)
    suffix = f"remux_{source_format}_to_{target_format}_{stream_suffix}"
    muxer_args: list[str] = []
    if target_format == "mkv":
        muxer_args = []
    elif target_format == "mxf":
        muxer_args = ["-f", "mxf"]
    elif target_format in {"mov", "mp4", "m4a", "alac"}:
        muxer_args = ["-movflags", "+faststart"]
    return {source_format}, _remux_output_extension(target_format), suffix, [*stream_map_args, "-c", "copy", *muxer_args]


# How the picture should be shown, written into the container rather than into
# the pixels. `-display_rotation` counts counter-clockwise, so a clockwise turn
# is a negative angle; the flips take no value at all - writing `-display_hflip 1`
# sends the 1 on as an output filename and the run fails.
REMUX_ORIENTATIONS: dict[str, tuple[list[str], str]] = {
    "cw90": (["-display_rotation:v", "-90"], "rotate 90 clockwise"),
    "ccw90": (["-display_rotation:v", "90"], "rotate 90 counter-clockwise"),
    "turn180": (["-display_rotation:v", "180"], "turn upside down"),
    "hflip": (["-display_hflip"], "mirror left to right"),
    "vflip": (["-display_vflip"], "mirror top to bottom"),
}

# Containers that keep a display matrix. Measured: MP4, MOV and MKV do; MXF
# accepts the option and writes an unturned file, which is worse than refusing.
REMUX_ORIENTATION_CONTAINERS = {"mp4", "mov", "mkv"}


def _remux_orientation(params: dict[str, Any]) -> str:
    value = str(params.get("remux_orientation") or "none").strip().lower()
    return value if value in REMUX_ORIENTATIONS else "none"


# Which sources the turn is offered for. The display matrix belongs to the
# container and works with any codec, so this is a scope decision rather than a
# technical limit: turning a file is a camera-original problem, and camera
# originals that arrive unturned are H.264 and HEVC. A mezzanine file that
# already went through an NLE is not this section''s business.
REMUX_ORIENTATION_CODECS = {"h264", "hevc"}


def _remux_orientation_refusal(root: Path, source: Path) -> str:
    """Empty when the file may be turned, the reason in words when it may not."""
    try:
        video = _stream(_probe_media_json(root, source), "video")
    except Exception:
        return "the video stream could not be read"
    codec = str(video.get("codec_name") or "").strip().lower()
    if not codec:
        return "the video stream could not be read"
    if codec not in REMUX_ORIENTATION_CODECS:
        return f"turning is offered for H.264 and HEVC; this file carries {codec.upper()}"
    return ""


def _remux_orientation_args(params: dict[str, Any]) -> list[str]:
    """Input options, so they must sit before `-i` in the command."""
    orientation = _remux_orientation(params)
    return list(REMUX_ORIENTATIONS[orientation][0]) if orientation != "none" else []


def remux_media(context: JobContext) -> dict[str, object]:
    params = dict(context.operation.parameters)
    root = context.paths.root
    source_dir = cached_source_path(root)
    output_dir = cached_output_path(root)
    stream_mode = _remux_stream_mode(params)
    target_format = _remux_target_format(params, stream_mode)
    orientation = _remux_orientation(params)
    if orientation != "none":
        if stream_mode == "audio":
            context.log("[ERROR] There is no picture to turn in an audio-only remux.")
            return {"files": 0, "failed": 1}
        if target_format not in REMUX_ORIENTATION_CONTAINERS:
            # Saying so beats writing a file that looks done and is not: the
            # option is accepted by every muxer and kept by only some.
            context.log(
                f"[ERROR] {target_format.upper()} does not store how the picture should be turned. "
                "MP4, MOV and MKV do."
            )
            return {"files": 0, "failed": 1}
        context.log(
            f"Orientation: {REMUX_ORIENTATIONS[orientation][1]}. Written into the container - "
            "the pixels are copied untouched, and an editor turns the picture on playback."
        )
    files = _media_files(source_dir, _remux_candidate_extensions(stream_mode))
    if not files:
        context.log(f"No matching files in {source_dir}")
        return {"files": 0}

    ffmpeg = _ffmpeg(root)
    dry_run = _as_bool(params.get("dry_run"), False)
    overwrite = _as_bool(params.get("overwrite"), True)
    processed = 0
    failed = 0
    skipped = 0
    jobs: list[tuple[Path, str, str, list[str]]] = []
    for source in files:
        source_format = _remux_normalized_source_format(source)
        supported, reason = _remux_file_supported(root, source, target_format, stream_mode)
        if not supported:
            skipped += 1
            context.log(f"[SKIP] {_source_display_name(source, source_dir)}: {reason}")
            continue
        if orientation != "none":
            refusal = _remux_orientation_refusal(root, source)
            if refusal:
                skipped += 1
                context.log(f"[SKIP] {_source_display_name(source, source_dir)}: {refusal}.")
                continue
        try:
            _selected_extensions, extension, suffix, remux_args = _remux_plan(source_format, target_format, stream_mode)
        except RuntimeError as exc:
            skipped += 1
            context.log(f"[SKIP] {_source_display_name(source, source_dir)}: {exc}")
            continue
        jobs.append((source, extension, suffix, remux_args))
        if _as_bool(params.get("limit_first_file"), False):
            break
    if not jobs:
        context.log(f"No compatible files in {source_dir} for {target_format.upper()} / {stream_mode}")
        return {"files": 0, "scanned": len(files), "skipped": skipped, "target": target_format, "streams": stream_mode, "dry_run": dry_run}

    total = len(jobs)
    for index, (source, extension, suffix, remux_args) in enumerate(jobs, start=1):
        source_format = _remux_normalized_source_format(source)
        source_label = _source_display_name(source, source_dir)
        if context.cancelled():
            context.log("Remux cancelled by user.")
            return {"cancelled": True, "processed": processed}
        target = _output_path(source, output_dir, suffix, extension, source_root=source_dir, operation=_operation_output_folder(context, "Remux"))
        command = [
            ffmpeg,
            "-hide_banner",
            "-stats",
            "-y" if overwrite else "-n",
            # Orientation is an input option: after `-i` it would be read as an
            # output one and the run would fail outright.
            *_remux_orientation_args(params),
            "-i",
            str(source),
            *remux_args,
            str(target),
        ]
        context.log(f"[{index}/{total}] {source_label}: {source_format.upper()} -> {target_format.upper()} / {stream_mode}")
        if dry_run:
            context.log("[DRY RUN] Command was not executed.")
            context.log(" ".join(f'"{part}"' if " " in part else part for part in command))
        else:
            try:
                _run_ffmpeg_media_process(context, command, source, check=True, progress_seconds=420, label=f"{source_label} remux")
            except RuntimeError as exc:
                failed += 1
                _discard_empty_output(context, target)
                context.log(f"[FAIL] {source_label}: {exc}")
                context.progress(index / total)
                continue
        processed += 1
        context.progress(index / total)

    return {"processed": processed, "failed": failed, "files": total, "scanned": len(files), "skipped": skipped, "target": target_format, "streams": stream_mode, "dry_run": dry_run}


def _probe_first_line(context: JobContext, command: list[str]) -> str:
    result = run_process(context, command, extra_env=_tool_env(context.paths.root), check=False, progress_seconds=30)
    return result.lines[0].strip() if result.lines else ""


def _parse_fps(value: str) -> Fraction:
    text = value.strip()
    if not text or text in {"0/0", "N/A"}:
        raise RuntimeError("Input FPS could not be detected.")
    if "/" in text:
        numerator, denominator = text.split("/", 1)
        return Fraction(int(numerator), int(denominator))
    return Fraction(text)


def _video_fps(context: JobContext, source: Path) -> Fraction:
    raw = _probe_first_line(
        context,
        [
            _ffprobe(context.paths.root),
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=avg_frame_rate",
            "-of",
            "default=nokey=1:noprint_wrappers=1",
            str(source),
        ],
    )
    return _parse_fps(raw)


def _has_audio_stream(context: JobContext, source: Path) -> bool:
    raw = _probe_first_line(
        context,
        [
            _ffprobe(context.paths.root),
            "-v",
            "error",
            "-select_streams",
            "a:0",
            "-show_entries",
            "stream=index",
            "-of",
            "default=nokey=1:noprint_wrappers=1",
            str(source),
        ],
    )
    return bool(raw)


def _audio_sample_rate_hz(context: JobContext, source: Path) -> int:
    raw = _probe_first_line(
        context,
        [
            _ffprobe(context.paths.root),
            "-v",
            "error",
            "-select_streams",
            "a:0",
            "-show_entries",
            "stream=sample_rate",
            "-of",
            "default=nokey=1:noprint_wrappers=1",
            str(source),
        ],
    )
    try:
        value = int(str(raw).strip())
    except (TypeError, ValueError):
        return 48000
    return value if value > 0 else 48000


# The names these rates carry in file suffixes and in conversation. A rate that
# is not here is still accepted - it just gets a plain numeric name.
_FPS_NAMES = {
    Fraction(24000, 1001): "23976",
    Fraction(30000, 1001): "2997",
    Fraction(60000, 1001): "5994",
    Fraction(120000, 1001): "11988",
}


def _target_fps(value: str) -> tuple[Fraction, str, str]:
    """Read the chosen target rate exactly as written.

    Anything unreadable is refused rather than quietly replaced: a target that
    was picked and then silently swapped for another is the worst outcome here.
    """
    text = str(value or "").strip() or "24000/1001"
    try:
        rate = Fraction(text)
    except (ValueError, ZeroDivisionError) as exc:
        raise RuntimeError(f"Target frame rate cannot be read: {value!r}") from exc
    if rate <= 0:
        raise RuntimeError(f"Target frame rate must be above zero: {value!r}")
    argument = text if "/" in text else str(rate)
    name = _FPS_NAMES.get(rate)
    if name is None:
        name = str(rate.numerator) if rate.denominator == 1 else f"{float(rate):g}".replace(".", "")
    return rate, argument, name


def _atempo_chain(speed: float) -> str:
    parts: list[float] = []
    value = float(speed)
    while value < 0.5:
        parts.append(0.5)
        value /= 0.5
    while value > 2.0:
        parts.append(2.0)
        value /= 2.0
    parts.append(value)
    return ",".join(f"atempo={item:.8g}" for item in parts)


def _fps_hardware_pix_fmt_args(encoder: str, params: dict[str, Any]) -> list[str]:
    """FPS pages have no pixel format control, so the 8-bit delivery default applies."""
    return _hardware_pix_fmt_args(encoder, str(params.get("pix_fmt") or "yuv420p"))


def _fps_output_args(profile: str, params: dict[str, Any]) -> tuple[list[str], list[str], str, str]:
    profile = str(profile or "h264").strip().lower()
    bitrate = _audio_bitrate(params)
    backend = _encode_backend(params)
    cpu_preset = _cpu_encoder_preset(params)
    nvenc_preset = _nvenc_preset(params)
    qsv_preset = _qsv_encoder_preset(params)
    amf_quality = _amf_quality(params)
    # The FPS presets in config/tool_manifest.yaml ship cq 19, unlike the encode pages.
    cq = _as_int(params.get("cq"), 19)
    if profile in {"prores", "prores_mov"}:
        audio_args, audio_label = _fps_pcm_audio_args(profile, params)
        return (
            ["-c:v", "prores_ks", "-profile:v", "2", "-pix_fmt", "yuv422p10le"],
            audio_args,
            "mov",
            f"prores422_{audio_label}",
        )
    if profile == "prores_mxf":
        audio_args, audio_label = _fps_pcm_audio_args(profile, params)
        return (
            ["-c:v", "prores_ks", "-profile:v", "2", "-pix_fmt", "yuv422p10le"],
            audio_args,
            "mxf",
            f"prores422_mxf_{audio_label}",
        )
    if profile in {"dnxhr", "dnxhr_mov"}:
        audio_args, audio_label = _fps_pcm_audio_args(profile, params)
        return (
            ["-c:v", "dnxhd", "-profile:v", "dnxhr_hqx", "-pix_fmt", "yuv422p10le"],
            audio_args,
            "mov",
            f"dnxhr_hqx_{audio_label}",
        )
    if profile == "dnxhr_mxf":
        audio_args, audio_label = _fps_pcm_audio_args(profile, params)
        return (
            ["-c:v", "dnxhd", "-profile:v", "dnxhr_hqx", "-pix_fmt", "yuv422p10le"],
            audio_args,
            "mxf",
            f"dnxhr_hqx_mxf_{audio_label}",
        )
    if profile in {"hevc", "h265", "x265"}:
        crf = _as_float(params.get("crf"), 16.0)
        if backend == "cuda":
            return (
                ["-c:v", "hevc_nvenc", "-preset", nvenc_preset, "-tune", "hq", "-cq:v", str(cq), "-b:v", "0", *_fps_hardware_pix_fmt_args("hevc_nvenc", params)],
                ["-c:a", "aac", "-b:a", bitrate],
                "mp4",
                f"hevc_nvenc_{nvenc_preset}_cq{cq}",
            )
        if backend == "qsv":
            return (
                ["-c:v", "hevc_qsv", "-preset", qsv_preset, "-global_quality", str(cq), *_fps_hardware_pix_fmt_args("hevc_qsv", params)],
                ["-c:a", "aac", "-b:a", bitrate],
                "mp4",
                f"hevc_qsv_{qsv_preset}_gq{cq}",
            )
        if backend == "amd":
            return (
                ["-c:v", "hevc_amf", "-quality", amf_quality, "-rc", "cqp", "-qp_i", str(cq), "-qp_p", str(cq), *_fps_hardware_pix_fmt_args("hevc_amf", params)],
                ["-c:a", "aac", "-b:a", bitrate],
                "mp4",
                f"hevc_amf_{amf_quality}_qp{cq}",
            )
        return (
            ["-c:v", "libx265", "-preset", cpu_preset, "-x265-params", f"crf={crf:g}", "-pix_fmt", "yuv420p"],
            ["-c:a", "aac", "-b:a", bitrate],
            "mp4",
            f"hevc_crf{crf:g}_{cpu_preset}",
        )
    crf = _as_float(params.get("crf"), 14.0)
    if backend == "cuda":
        return (
            ["-c:v", "h264_nvenc", "-preset", nvenc_preset, "-tune", "hq", "-cq:v", str(cq), "-b:v", "0", *_fps_hardware_pix_fmt_args("h264_nvenc", params)],
            ["-c:a", "aac", "-b:a", bitrate],
            "mp4",
            f"h264_nvenc_{nvenc_preset}_cq{cq}",
        )
    if backend == "qsv":
        return (
            ["-c:v", "h264_qsv", "-preset", qsv_preset, "-global_quality", str(cq), *_fps_hardware_pix_fmt_args("h264_qsv", params)],
            ["-c:a", "aac", "-b:a", bitrate],
            "mp4",
            f"h264_qsv_{qsv_preset}_gq{cq}",
        )
    if backend == "amd":
        return (
            ["-c:v", "h264_amf", "-quality", amf_quality, "-rc", "cqp", "-qp_i", str(cq), "-qp_p", str(cq), "-qp_b", str(cq), *_fps_hardware_pix_fmt_args("h264_amf", params)],
            ["-c:a", "aac", "-b:a", bitrate],
            "mp4",
            f"h264_amf_{amf_quality}_qp{cq}",
        )
    return (
        ["-c:v", "libx264", "-preset", cpu_preset, "-crf", f"{crf:g}", "-pix_fmt", "yuv420p"],
        ["-c:a", "aac", "-b:a", bitrate],
        "mp4",
        f"h264_crf{crf:g}_{cpu_preset}",
    )


def fps_convert(context: JobContext) -> dict[str, object]:
    params = dict(context.operation.parameters)
    root = context.paths.root
    source_dir = cached_source_path(root)
    output_dir = cached_output_path(root)
    extensions = _normalize_extensions(_as_list(params.get("input_formats"))) or {"mp4", "mov", "mkv", "mxf", "avi", "webm", "mts", "m2ts"}
    files = _media_files(source_dir, extensions)
    if not files:
        context.log(f"No matching media files in {source_dir}")
        return {"files": 0}

    mode = str(params.get("fps_mode", "varispeed")).strip()
    target_fps, target_arg, target_label = _target_fps(str(params.get("fps_target", "23976")).strip())
    output_profile = str(params.get("fps_output_profile", "h264")).strip()
    video_args, audio_args, extension, profile_label = _fps_output_args(output_profile, params)
    overwrite = _as_bool(params.get("overwrite"), False)
    dry_run = _as_bool(params.get("dry_run"), False)
    ffmpeg = _ffmpeg(root)
    # setpts/atempo run as filters, so frames have to come back to system memory.
    decode = _decode_args(params, context, has_video_filters=True)

    processed = 0
    for index, source in enumerate(files, start=1):
        source_label = _source_display_name(source, source_dir)
        if context.cancelled():
            context.log("FPS conversion cancelled by user.")
            return {"cancelled": True, "processed": processed}

        source_fps = _video_fps(context, source)
        k = float(source_fps / target_fps)
        speed = float(target_fps / source_fps)
        has_audio = _has_audio_stream(context, source)
        audio_work_rate = _fps_audio_target_rate(_audio_sample_rate_hz(context, source), params) if has_audio else 0
        audio_output_rate = _fps_audio_output_rate(output_profile, audio_work_rate) if has_audio else 0
        suffix = f"fps_{str(source_fps).replace('/', '_')}_to_{target_label}_{mode}_{profile_label}"
        target = _output_path(source, output_dir, suffix, extension, source_root=source_dir, operation=_operation_output_folder(context, "FPS"))

        if has_audio and audio_output_rate != audio_work_rate:
            context.log(f"Audio oversampling work rate: {audio_work_rate} Hz; final container rate: {audio_output_rate} Hz")
        command = _build_fps_command(
            ffmpeg=ffmpeg,
            source=str(source),
            overwrite=overwrite,
            mode=mode,
            k=k,
            speed=speed,
            target_arg=target_arg,
            video_args=video_args,
            audio_args=audio_args,
            extension=extension,
            target=str(target),
            has_audio=has_audio,
            audio_work_rate=audio_work_rate,
            audio_output_rate=audio_output_rate,
            decode_args=decode,
        )

        context.log(f"[{index}/{len(files)}] {source_label}: {float(source_fps):.6g} -> {target_arg} {mode}")
        if dry_run:
            context.log("[DRY RUN] Command was not executed.")
            context.log(" ".join(f'"{part}"' if " " in part else part for part in command))
        else:
            _run_ffmpeg_media_process(context, command, source, check=True, progress_seconds=900, label=f"{source_label} FPS")
        processed += 1
        context.progress(index / len(files))

    return {"processed": processed, "files": len(files), "target": target_arg, "mode": mode, "dry_run": dry_run}


def _color_default_target(script: str, profile: dict[str, Any] | None = None) -> str:
    if profile:
        targets = _as_list(profile.get("targets"))
        if targets:
            target = targets[0]
            return {"hevc10": "hevc_x265", "prores422": "prores_422"}.get(target, target)
    text = script.lower()
    if "proreslt" in text or "prores-lt" in text:
        return "prores_lt"
    if "prores" in text:
        return "prores_422"
    if "hevc" in text or "x265" in text:
        return "hevc_x265"
    return "x264"


def _color_filter(script: str, lut_path: Path | None, params: dict[str, Any], profile: dict[str, Any] | None = None) -> tuple[str, str]:
    filters: list[str] = []
    suffix = "color"
    lowered = script.lower()
    filter_kind = str((profile or {}).get("color_filter", "")).strip().lower()

    if filter_kind == "hdr2sdr_hable" or "hdr2sdr" in lowered or "hable" in lowered:
        filters.append(
            "setparams=color_primaries=bt2020:color_trc=smpte2084:colorspace=bt2020nc:range=tv,"
            "zscale=t=linear:npl=100,format=gbrpf32le,tonemap=hable:desat=0.5,"
            "zscale=t=bt709:m=bt709:p=bt709:r=tv,format=yuv420p"
        )
        suffix = "sdr709_hable"
    else:
        if lut_path is None:
            raise RuntimeError("LUT file was not selected and no LUT file was found.")
        default_gamma = str(params.get("pre_gamma") or (profile or {}).get("pre_gamma", "")).strip()
        if filter_kind == "preexpose_lut" or "preexpose" in lowered:
            gamma = ffmpeg_filter_number(default_gamma or "1.15", name="pre_gamma")
            filters.append(f"eq=gamma={gamma}")
            suffix = "preexpose_lut"
        elif filter_kind == "pregamma_lut" or "pregamma" in lowered:
            gamma = ffmpeg_filter_number(default_gamma or "0.85", name="pre_gamma")
            filters.append(f"eq=gamma={gamma}")
            suffix = "pregamma_lut"
        else:
            suffix = "lut"
        filters.append(f"lut3d=file={ffmpeg_filter_path(lut_path)}:interp=tetrahedral")

    scale = _scale_filter(params)
    if scale:
        filters.append(scale)
    return ",".join(filters), suffix


def run_color_grade(context: JobContext) -> dict[str, object]:
    params = dict(context.operation.parameters)
    root = context.paths.root
    source_dir = cached_source_path(root)
    output_dir = cached_output_path(root)
    script = str(params.get("script_preset", "ff-grade-lut-only-x264.cmd")).strip() or "ff-grade-lut-only-x264.cmd"
    profile = script_profile(root, script)
    extensions = _normalize_extensions(_as_list(params.get("input_formats"))) or {"mp4", "mov", "mkv", "mxf", "avi", "webm", "mts", "m2ts"}
    files = _media_files(source_dir, extensions)
    if _as_bool(params.get("limit_first_file"), False):
        files = files[:1]
    if not files:
        context.log(f"No matching media files in {source_dir}")
        return {"files": 0}

    lut_path: Path | None = None
    if "hdr2sdr" not in script.lower():
        lut_file = str(params.get("lut_file", "")).strip().strip('"')
        lut_path = Path(lut_file) if lut_file else root / "LUTs" / "active.cube"
        if not lut_path.is_absolute():
            lut_path = root / lut_path
        if not lut_path.exists():
            candidates = sorted((root / "LUTs").glob("*.cube"))
            lut_path = candidates[0] if candidates else lut_path
        if not lut_path.exists():
            raise RuntimeError(f"LUT file was not found: {lut_path}")
        context.log(f"LUT: {lut_path}")

    filter_expr, color_suffix = _color_filter(script, lut_path, params, profile)
    targets = _as_list(params.get("target_codecs")) or _as_list(profile.get("targets")) or [_color_default_target(script, profile)]
    ffmpeg = _ffmpeg(root)
    # LUT and tonemapping are software filters and always need frames in system memory.
    decode = _decode_args(params, context, has_video_filters=True)
    audio_mode = str(params.get("audio_mode", "aac_320")).strip()
    audio_bitrate = _audio_bitrate(params)
    dry_run = _as_bool(params.get("dry_run"), False)
    overwrite = _as_bool(params.get("overwrite"), True)

    processed = 0
    total = len(files) * len(targets)
    for source in files:
        source_label = _source_display_name(source, source_dir)
        for target_codec in targets:
            target_codec = {"hevc10": "hevc_x265", "prores422": "prores_422"}.get(target_codec, target_codec)
            if context.cancelled():
                context.log("Color operation cancelled by user.")
                return {"cancelled": True, "processed": processed}

            video, extension, video_suffix, family = _target_video_args(target_codec, params)
            target_audio_mode = _container_audio_mode(extension, audio_mode)
            target_path = _output_path(source, output_dir, f"{color_suffix}_{video_suffix}", extension, source_root=source_dir, operation=_operation_output_folder(context, "Color"))
            command = [ffmpeg, "-hide_banner", "-stats", "-y" if overwrite else "-n", *decode, "-i", str(source)]
            command.extend(["-map", "0:v:0"])
            if target_audio_mode != "none":
                command.extend(["-map", "0:a?"])
            command.extend(["-sn", "-dn", "-vf", filter_expr, *video, *_audio_args(target_audio_mode, audio_bitrate, _mp3_lame_preset(params)), *_encode_audio_filter_args(params, target_audio_mode), "-map_metadata", "0"])
            if extension in {"mp4", "mov"}:
                command.extend(["-movflags", "+faststart"])
            if extension == "mxf":
                command.extend(["-f", "mxf"])
            command.append(str(target_path))

            context.log(f"[{processed + 1}/{total}] {source_label} -> {color_suffix} / {target_codec}")
            if dry_run:
                context.log("[DRY RUN] Command was not executed.")
                context.log(" ".join(f'"{part}"' if " " in part else part for part in command))
            else:
                _run_ffmpeg_media_process(context, command, source, check=True, progress_seconds=900, label=f"{source_label} grade")
            processed += 1
            context.progress(processed / max(1, total))

    return {"processed": processed, "files": len(files), "targets": targets, "dry_run": dry_run}


def _youtube_profile_args(profile: str, parallel: int) -> list[str]:
    common_mp4 = ["-N", str(max(1, parallel)), "-S", "res,ext:mp4:m4a", "--merge-output-format", "mp4"]
    if profile == "safe_mp4":
        return [
            "-N",
            "1",
            "--retries",
            "10",
            "--fragment-retries",
            "10",
            "--retry-sleep",
            "2",
            "--sleep-requests",
            "1",
            "--http-chunk-size",
            "10M",
            "--force-ipv4",
            "-S",
            "res,ext:mp4:m4a",
            "--merge-output-format",
            "mp4",
        ]
    if profile == "av1_mp4":
        return ["-N", str(max(1, parallel)), "-S", "codec:av01,res,ext:mp4:m4a", "--merge-output-format", "mp4"]
    if profile == "vp9_webm":
        return ["-N", str(max(1, parallel)), "-S", "codec:vp9,res,ext:webm:opus", "--merge-output-format", "webm"]
    if profile == "audio_m4a":
        return ["-N", str(max(1, parallel)), "-f", "bestaudio[acodec^=mp4a]/bestaudio", "-x", "--audio-format", "m4a"]
    if profile == "audio_opus":
        return ["-N", str(max(1, parallel)), "-x", "--audio-format", "opus"]
    if profile == "audio_mp3":
        return ["-N", str(max(1, parallel)), "-x", "--audio-format", "mp3", "--audio-quality", "0"]
    if profile == "subs_only":
        return ["--skip-download", "--write-subs", "--write-auto-subs", "--sub-format", "srt/best"]
    return common_mp4


def _youtube_format_args(params: dict[str, Any], profile: str, parallel: int) -> list[str]:
    resolution = str(params.get("youtube_resolution", "best")).strip()
    video_codec = str(params.get("youtube_video_codec", "auto")).strip()
    audio_format = str(params.get("youtube_audio_format", "source")).strip()
    container = str(params.get("youtube_container", "mp4")).strip() or "mp4"

    if profile in {"best_mp4", "safe_mp4", "av1_mp4", "vp9_webm", "audio_m4a", "audio_opus", "audio_mp3", "subs_only"}:
        args = _youtube_profile_args(profile, parallel)
    else:
        args = ["-N", str(max(1, parallel))]

    if profile in {"video_custom", "upload_ready"}:
        sort_parts: list[str] = []
        if resolution != "best":
            sort_parts.append(f"res:{resolution}")
        if video_codec in {"avc", "h264"}:
            sort_parts.append("codec:avc")
        elif video_codec in {"av1", "av01"}:
            sort_parts.append("codec:av01")
        elif video_codec == "vp9":
            sort_parts.append("codec:vp9")
        else:
            sort_parts.append("res")
        if container == "mp4":
            sort_parts.append("ext:mp4:m4a")
        args.extend(["-S", ",".join(sort_parts), "--merge-output-format", container])

    if profile == "audio_custom":
        args = ["-N", str(max(1, parallel)), "-x"]
        if audio_format == "mp3":
            args.extend(["--audio-format", "mp3", "--audio-quality", "0"])
        elif audio_format == "opus":
            args.extend(["--audio-format", "opus"])
        elif audio_format == "m4a":
            args.extend(["--audio-format", "m4a"])
        else:
            args = ["-N", str(max(1, parallel)), "-f", "bestaudio/best"]

    return args


def download_youtube(context: JobContext) -> dict[str, object]:
    params = dict(context.operation.parameters)
    root = context.paths.root
    download_dir = root / "Download"
    download_dir.mkdir(parents=True, exist_ok=True)

    profile = str(params.get("youtube_profile", "best_mp4")).strip() or "best_mp4"
    parallel = _as_int(params.get("parallel_fragments"), 8)
    source_mode = str(params.get("youtube_source_mode", "single")).strip()
    options = _as_list(params.get("youtube_options"))
    subtitles = _as_list(params.get("subtitle_options"))
    client = str(params.get("youtube_client", "default")).strip()
    dry_run = _as_bool(params.get("youtube_dry_run"), False)

    command = [_yt_dlp(root)]
    deno = _deno(root)
    if deno:
        command.extend(["--js-runtimes", f"deno:{deno}"])
    else:
        js_override = os.environ.get("AUDION_YTDLP_JS_RUNTIMES") or os.environ.get("YTDLP_JS_RUNTIMES")
        if js_override:
            command.extend(["--js-runtimes", js_override])
        else:
            context.log("[WARN] No Deno JS runtime found. YouTube formats may be limited.")
    command.extend([
        "-P",
        str(download_dir),
        "-o",
        "%(uploader)s/%(upload_date>%Y-%m-%d)s - %(title).180B [%(id)s].%(ext)s",
        *_youtube_format_args(params, profile, parallel),
    ])

    ffmpeg_bin = root / "Tools" / "ffmpeg" / "bin"
    if ffmpeg_bin.exists():
        command.extend(["--ffmpeg-location", str(ffmpeg_bin)])

    if "safe_retries" in options and profile != "safe_mp4":
        command.extend(["--retries", "10", "--fragment-retries", "10", "--retry-sleep", "2"])
    if "force_ipv4" in options and "--force-ipv4" not in command:
        command.append("--force-ipv4")
    if "embed_metadata" in options and profile != "subs_only":
        command.extend(["--embed-metadata", "--embed-thumbnail"])
    if "no_playlist" in options:
        command.append("--no-playlist")

    if client == "safari" or profile == "safe_mp4":
        command.extend(["--extractor-args", "youtube:player-client=web_safari,default"])
    elif client == "android":
        command.extend(["--extractor-args", "youtube:player-client=android,web"])

    if "write_subs" in subtitles:
        command.append("--write-subs")
    if "write_auto_subs" in subtitles:
        command.append("--write-auto-subs")
    if "embed_subs" in subtitles and profile != "subs_only":
        command.append("--embed-subs")
    sub_langs = str(params.get("subtitle_languages", "")).strip()
    if sub_langs:
        command.extend(["--sub-langs", sub_langs])

    if _as_bool(params.get("download_archive"), False):
        command.extend(["--download-archive", str(download_dir / "download-archive.txt")])

    cookies_browser = os.environ.get("AUDION_YTDLP_COOKIES_BROWSER") or os.environ.get("YTDLP_COOKIES_BROWSER")
    cookies_env = os.environ.get("AUDION_YTDLP_COOKIES") or os.environ.get("YTDLP_COOKIES") or os.environ.get("COOKIES")
    cookies_path = str(params.get("cookies_path", "")).strip().strip('"')
    if cookies_browser:
        command.extend(["--cookies-from-browser", cookies_browser])
    elif cookies_env:
        command.extend(["--cookies", cookies_env])
    elif cookies_path:
        candidate = Path(cookies_path)
        if not candidate.is_absolute():
            candidate = root / candidate
        if candidate.exists():
            command.extend(["--cookies", str(candidate)])

    sponsorblock = os.environ.get("AUDION_YTDLP_SPONSORBLOCK") or os.environ.get("YTDLP_SPONSORBLOCK")
    if sponsorblock and profile not in {"audio_m4a", "audio_opus", "audio_mp3", "audio_custom", "subs_only"}:
        command.extend(["--sponsorblock-remove", sponsorblock])

    if source_mode == "batch":
        batch_file = str(params.get("batch_file", "Download\\urls.txt")).strip().strip('"')
        batch_path = Path(batch_file)
        if not batch_path.is_absolute():
            batch_path = root / batch_path
        if not batch_path.exists():
            raise RuntimeError(f"Batch file was not found: {batch_path}")
        command.extend(["--batch-file", str(batch_path)])
    else:
        url = str(params.get("youtube_url", "")).strip()
        if not url:
            raise RuntimeError("YouTube URL is empty.")
        command.append(url)

    if dry_run:
        context.log("[DRY RUN] yt-dlp command was not executed.")
        context.log(" ".join(f'"{part}"' if " " in part else part for part in command))
        context.progress(1.0)
        return {"dry_run": True, "profile": profile}

    result = run_process(context, command, extra_env=_tool_env(root), check=True, progress_seconds=1800)
    context.progress(1.0)
    return {"profile": profile, "lines": len(result.lines), "download_dir": str(download_dir)}


def _path_is_inside(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def _assert_clear_target(context: JobContext, folder: Path, label: str, *, allow_external: bool = False) -> tuple[Path, bool]:
    root = context.paths.root.resolve()
    target = folder.resolve()
    inside_project = _path_is_inside(target, root)

    if target == root:
        raise RuntimeError(f"{label} points to the project root and will not be cleared: {target}")
    if target.anchor and target == Path(target.anchor).resolve():
        raise RuntimeError(f"{label} points to a drive root and will not be cleared: {target}")
    try:
        home = Path.home().resolve()
        if target == home:
            raise RuntimeError(f"{label} points to the user home folder and will not be cleared: {target}")
    except RuntimeError:
        raise
    except Exception:
        pass
    if len(target.parts) <= 2:
        raise RuntimeError(f"{label} path is too broad to clear safely: {target}")
    if target.name.lower() in {"windows", "program files", "program files (x86)", "users"}:
        raise RuntimeError(f"{label} path is a protected system-level folder: {target}")

    if not inside_project and not allow_external:
        raise RuntimeError(f"{label} is outside project root: {target}")
    if not inside_project and not target.exists():
        raise RuntimeError(f"{label} is outside project root and does not exist: {target}")
    return target, not inside_project


def _clear_folder(context: JobContext, folder: Path, label: str, *, allow_external: bool = False) -> dict[str, object]:
    target, external = _assert_clear_target(context, folder, label, allow_external=allow_external)
    if target.exists() and not target.is_dir():
        raise RuntimeError(f"{label} is not a folder: {target}")
    if external:
        context.log(f"[WARNING] Clearing external {label}: {target}")

    target.mkdir(parents=True, exist_ok=True)
    removed = 0
    for item in target.iterdir():
        if item.name == ".gitkeep":
            continue
        if item.is_dir():
            shutil.rmtree(item)
        else:
            item.unlink()
        removed += 1
        context.log(f"Removed from {label}: {item.name}")
    return {"folder": label, "path": str(target), "external": external, "removed_items": removed}


def cleanup_transcoded(context: JobContext) -> dict[str, object]:
    output = cached_output_path(context.paths.root)
    context.log("Cleaning selected destination/output folder. Source and Download are preserved.")
    result = _clear_folder(context, output, "Transcoded", allow_external=True)
    context.progress(1.0)
    return result


def cleanup_source(context: JobContext) -> dict[str, object]:
    source = cached_source_path(context.paths.root)
    context.log("Cleaning selected Source folder. Transcoded and Download are preserved.")
    target, external = _assert_clear_target(context, source, "Source", allow_external=True)
    if target.is_file():
        if external:
            context.log(f"[WARNING] Deleting external Source file: {target}")
        target.unlink()
        context.log(f"Removed Source file: {target.name}")
        result = {"folder": "Source", "path": str(target), "external": external, "removed_items": 1, "kind": "file"}
    else:
        result = _clear_folder(context, source, "Source", allow_external=True)
    context.progress(1.0)
    return result


def cleanup_workspace(context: JobContext) -> dict[str, object]:
    context.log("Cleaning managed GUI workspace folders. Source, Download and Transcoded are preserved.")
    results = [
        _clear_folder(context, context.paths.workspace, "workspace"),
        _clear_folder(context, context.paths.report, "report"),
    ]
    context.progress(1.0)
    return {"folders": results}


# --- Trim ---------------------------------------------------------------------
#
# A trim copies streams, so the head lands on a keyframe and the tail lands on a
# packet boundary. Everything the operator needs to judge that — the real cut
# point, the offset from the requested one, the shifted timecode, and whatever
# the chosen container is about to cost — is printed before the run, not
# discovered in the finished file.

TRIM_VIDEO_EXTENSIONS = {"mp4", "m4v", "mov", "mkv", "mxf", "avi", "mts", "m2ts", "ts"}

# Camera GOPs run 1-5 s, so a 15 s window around the point always holds one.
TRIM_KEYFRAME_WINDOW = 15.0


def trim_source_files(root: Path | str | None = None) -> list[dict[str, str]]:
    """Dynamic manifest option provider: video files staged in the Source folder."""
    project_root = Path(root).resolve() if root else Path(__file__).resolve().parents[2]
    source_dir = cached_source_path(project_root)
    if not source_dir.exists():
        return [{"value": "", "label": "Source is missing", "label_ru": "Source не найден"}]
    files = _media_files(source_dir, TRIM_VIDEO_EXTENSIONS)
    if not files:
        return [{"value": "", "label": "Source holds no video", "label_ru": "В Source нет видео"}]
    options = []
    for path in files[:200]:
        name = _source_display_name(path, source_dir)
        options.append({"value": name, "label": name, "label_ru": name})
    return options


def trim_source_path(name: str, root: Path | str | None = None) -> Path | None:
    """The staged file behind a chosen name, or nothing if it is not there.

    The panel needs this to hand a file to the player, and the knowledge of
    where Source lives belongs here rather than in the interface.
    """
    chosen = str(name or "").strip()
    if not chosen:
        return None
    project_root = Path(root).resolve() if root else Path(__file__).resolve().parents[2]
    candidate = cached_source_path(project_root) / chosen
    return candidate if candidate.is_file() else None


def trim_source_file_names(root: Path | str | None = None) -> list[str]:
    """Video files staged in Source, in alphabetical order, as plain names."""
    project_root = Path(root).resolve() if root else Path(__file__).resolve().parents[2]
    source_dir = cached_source_path(project_root)
    if not source_dir.exists():
        return []
    return [_source_display_name(path, source_dir) for path in _media_files(source_dir, TRIM_VIDEO_EXTENSIONS)]


def trim_file_key(path: Path | str) -> str:
    """A cheap content fingerprint: size plus the first and last megabyte.

    Hashing an hour of video to remember two numbers would be absurd, and the
    name alone is not an identity - takes get renamed. Two megabytes of reads
    tell one camera file from another reliably enough for a session cache.
    """
    target = Path(path)
    try:
        size = target.stat().st_size
    except OSError:
        return ""
    digest = hashlib.sha1(str(size).encode("ascii"))
    window = 1024 * 1024
    try:
        with open(target, "rb") as handle:
            digest.update(handle.read(window))
            if size > window * 2:
                handle.seek(-window, os.SEEK_END)
                digest.update(handle.read(window))
    except OSError:
        return ""
    return digest.hexdigest()


def _trim_marked_jobs(params: dict[str, Any], source_dir: Path) -> list[tuple[Path, dict[str, Any]]]:
    """Files the operator marked, each with its own pair of points.

    The GUI hands over one entry per marked file. Anything that has since left
    the Source folder is dropped here rather than failing later.
    """
    marks = params.get("trim_marks")
    if isinstance(marks, dict):
        marks = list(marks.values())
    if not isinstance(marks, list):
        return []
    jobs: list[tuple[Path, dict[str, Any]]] = []
    for entry in marks:
        if not isinstance(entry, dict):
            continue
        name = str(entry.get("file") or "").strip()
        if not name:
            continue
        candidate = source_dir / name
        if not candidate.is_file():
            continue
        jobs.append((candidate, entry))
    return jobs


def _trim_action_pattern(params: dict[str, Any]) -> str:
    """Work out the pattern a panel run means, from the action and the points.

    Three of the five patterns are the same decision - keep what lies between
    the points - and which one applies is already visible in the fields: a start
    on its own drops the head, an end on its own drops the tail, both drop both
    ends. Offering them as separate buttons asked the operator to say twice what
    they had already said once, and let the two answers disagree.
    """
    action = str(params.get("trim_action") or "").strip().lower()
    if action in {"cut", "middle", "gap"}:
        return "middle"
    if action == "split":
        return "split"
    if action not in {"keep", "between", ""}:
        return ""
    has_start = bool(str(params.get("trim_start") or "").strip())
    has_end = bool(str(params.get("trim_end") or "").strip())
    if has_start and has_end:
        return "both"
    if has_start:
        return "start"
    if has_end:
        return "end"
    # Neither point set: let the planner say "nothing would be trimmed" in its
    # own words rather than guessing a pattern here.
    return "both"


def _trim_pattern(params: dict[str, Any]) -> str:
    # Empty rather than "start" by default: an absent pattern means the caller
    # is the panel, which says what it wants through the action and the points.
    value = str(params.get("trim_pattern") or "").strip().lower()
    if value in {"start", "end", "both", "split", "middle"}:
        # Named outright - a CLI wrapper, or a per-file mark. Explicit wins.
        return value
    derived = _trim_action_pattern(params)
    return derived or "start"


def _trim_container(params: dict[str, Any], source: Path) -> str:
    value = str(params.get("trim_container") or "source").strip().lower().lstrip(".")
    if value in {"", "source", "same", "as_is", "keep"}:
        return source.suffix.lower().lstrip(".") or "mp4"
    return value


def _trim_source_timecode(root: Path, source: Path) -> str:
    """The camera timecode, read from the video stream first, then the container."""
    command = [
        _ffprobe(root),
        "-v",
        "error",
        "-show_entries",
        "stream_tags=timecode:format_tags=timecode",
        "-of",
        "default=nokey=1:noprint_wrappers=1",
        str(source),
    ]
    result = _capture_tool(root, command)
    for line in (result.stdout or "").splitlines():
        text = line.strip()
        if text and text.upper() != "N/A" and re.match(r"^\d{1,2}[:;.]\d{2}[:;.]\d{2}[:;.]\d{2}$", text):
            return text
    return ""


# Dragging a fader asks for the same window over and over, and the keyframes of
# a file nobody is writing do not move. Keyed by size and mtime so a replaced
# file is read again; small enough that it never becomes a memory question.
_TRIM_KEYFRAME_CACHE: dict[tuple[str, int, int, int], list[float]] = {}
_TRIM_KEYFRAME_CACHE_LIMIT = 64


def _trim_keyframes(root: Path, source: Path, around: float) -> list[float]:
    """Keyframe positions near a point, falling back to a full scan when empty."""
    try:
        stat = source.stat()
        # One key per window rather than per position: neighbouring points share
        # a window, which is what makes the cache worth having.
        window_index = int(max(0.0, around) // TRIM_KEYFRAME_WINDOW)
        key = (str(source), int(stat.st_size), int(stat.st_mtime), window_index)
    except OSError:
        key = None
    if key is not None:
        cached = _TRIM_KEYFRAME_CACHE.get(key)
        if cached is not None:
            return cached

    ffprobe = _ffprobe(root)
    windowed = _capture_tool(root, keyframe_probe_command(ffprobe, str(source), start=around, window=TRIM_KEYFRAME_WINDOW))
    times = parse_keyframe_times(windowed.stdout or "")
    if not times:
        full = _capture_tool(root, keyframe_probe_command(ffprobe, str(source)))
        times = parse_keyframe_times(full.stdout or "")
    if key is not None and times:
        if len(_TRIM_KEYFRAME_CACHE) >= _TRIM_KEYFRAME_CACHE_LIMIT:
            _TRIM_KEYFRAME_CACHE.clear()
        _TRIM_KEYFRAME_CACHE[key] = times
    return times


def _capture_probe_json(root: Path, command: list[str]) -> dict[str, Any]:
    """Run a probe and parse its JSON, with the warnings kept out of the way.

    ffprobe writes complaints to stderr - a Sony MXF greets every read with
    "could not resolve file descriptor strong ref" - and merging those into
    stdout turns valid JSON into a parse error.
    """
    completed = subprocess.run(
        command,
        cwd=str(root),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=utf8_subprocess_env(_tool_env(root)),
        **hidden_subprocess_kwargs(),
    )
    try:
        data = json.loads(completed.stdout or "{}")
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


# Said in one place because two paths need it: the trim and the preview.
TRIM_UNREADABLE_VIDEO = (
    "FFmpeg cannot read this video stream: camera RAW inside MXF (Sony X-OCN, ARRIRAW) has no "
    "decoder here, so there is no stream to copy. Such material is trimmed in the camera vendor's "
    "own software (Sony Catalyst, ARRI Reference Tool) or transcoded first."
)


# Codecs the GPU vendors actually decode, read off this build's own decoder list
# (`ffmpeg -decoders`, the qsv / cuvid / amf entries). Anything else gets
# software, which it would fall back to anyway - only later, and after paying
# for the refusal. The editing codecs are absent on purpose: no vendor decodes
# ProRes, DNxHR, FFV1 or v210 in hardware.
TRIM_HARDWARE_DECODED = {
    "h264",
    "hevc",
    "av1",
    "vp9",
    "vp8",
    "vvc",
    "vc1",
    "mpeg2video",
    "mpeg1video",
    "mpeg4",
    "mjpeg",
}


def _decodes_as_gbr(video: dict[str, Any]) -> bool:
    """True for a codec whose decoder hands back GBR whatever the tags claim.

    ProRes 4444 (`ap4h`, `ap4x`) is the one that matters here: ffprobe reports
    bt709 on the stream, the decoder produces `csp:gbr prim:reserved`, and
    swscale refuses it with "Unsupported input". Knowing in advance saves the
    preview a failed attempt on every move of the fader.
    """
    codec = str(video.get("codec_name") or "").strip().lower()
    pixel = str(video.get("pix_fmt") or "").strip().lower()
    return codec == "prores" and "444" in pixel


def _video_stream_is_unreadable(video: dict[str, Any]) -> bool:
    """True when FFmpeg found a video stream but cannot say what is in it.

    Camera RAW wrapped in MXF reads exactly this way - no codec name, no
    dimensions - and every attempt to touch it ends in "dimensions not set".
    """
    codec_name = str(video.get("codec_name") or "").strip().lower()
    try:
        width = int(video.get("width") or 0)
    except (TypeError, ValueError):
        width = 0
    return not codec_name or codec_name == "unknown" or width <= 0


# The interactive path asks for these on every move; the CLI asks once per run.
# Keyed by size and mtime, so a file that was rewritten is read again.
_TRIM_FACTS_CACHE: dict[tuple[str, int, int], dict[str, Any]] = {}
_TRIM_FACTS_CACHE_LIMIT = 32


def _trim_stream_facts(root: Path, source: Path) -> dict[str, Any]:
    try:
        stat = source.stat()
        key = (str(source), int(stat.st_size), int(stat.st_mtime))
    except OSError:
        key = None
    if key is not None:
        held = _TRIM_FACTS_CACHE.get(key)
        if held is not None:
            return dict(held)
    facts = _trim_stream_facts_uncached(root, source)
    if key is not None and facts.get("duration"):
        if len(_TRIM_FACTS_CACHE) >= _TRIM_FACTS_CACHE_LIMIT:
            _TRIM_FACTS_CACHE.clear()
        _TRIM_FACTS_CACHE[key] = dict(facts)
    return facts


def _trim_stream_facts_uncached(root: Path, source: Path) -> dict[str, Any]:
    """Rate, timeline origin and duration, read straight from the video stream.

    `start_time` matters: MPEG-TS routinely begins at 1.44 s, and every position
    FFmpeg is given counts in that timeline while the operator counts from the
    beginning of the picture.
    """
    command = [
        _ffprobe(root),
        "-v",
        "error",
        "-select_streams",
        "v:0",
        "-show_entries",
        "stream=avg_frame_rate,r_frame_rate,start_time:format=duration,start_time",
        "-of",
        "json",
        str(source),
    ]
    data = _capture_probe_json(root, command)
    streams = data.get("streams") or [{}]
    stream = streams[0] if isinstance(streams[0], dict) else {}
    fmt = data.get("format") if isinstance(data.get("format"), dict) else {}
    fmt = fmt or {}

    def number(value: Any) -> float:
        try:
            number_value = float(value)
        except (TypeError, ValueError):
            return 0.0
        return number_value if number_value > 0 else 0.0

    origin = number(stream.get("start_time")) or number(fmt.get("start_time"))
    # `avg_frame_rate` is `0/0` on a stream FFmpeg cannot parse; the nominal rate
    # is then the only one there is.
    average = str(stream.get("avg_frame_rate") or "").strip()
    nominal = str(stream.get("r_frame_rate") or "").strip()
    if average in {"", "0/0", "N/A"}:
        average = nominal
    return {
        "avg_frame_rate": average,
        "r_frame_rate": nominal or average,
        "origin": origin,
        "duration": number(fmt.get("duration")),
    }


# Muxers that will simply refuse a codec. FFmpeg answers these with "Could not
# find tag for codec ... in stream #0" and writes a zero-byte file, which is a
# poor way for an operator to learn that MP4 cannot hold ProRes.
# Measured, not assumed: each entry is a one-second `-c copy` round trip that
# came back missing or altered. See Docs/TRIM_MATRIX_RU.md for the full table.
TRIM_CONTAINER_REFUSALS = {
    "mp4": {"prores", "dnxhd", "ffv1", "rawvideo", "v210", "huffyuv", "utvideo", "cineform"},
    "m4v": {"prores", "dnxhd", "ffv1", "rawvideo", "v210", "huffyuv", "utvideo", "cineform"},
    "mov": {"av1", "vp9"},
    "m2ts": {"prores", "dnxhd", "ffv1", "rawvideo", "v210", "vp9", "av1"},
    "ts": {"prores", "dnxhd", "ffv1", "rawvideo", "v210", "vp9", "av1"},
    "mxf": {"vp9", "av1", "hevc"},
}

# Audio the container will not take, by the same round trip.
TRIM_AUDIO_REFUSALS = {
    "mov": {"flac", "opus", "vorbis"},
    "m2ts": {"flac", "alac", "vorbis"},
    "ts": {"flac", "alac", "vorbis"},
}


def _trim_container_refusal(container: str, video_codec: str, audio_codec: str) -> str:
    """Why this container cannot hold this stream, or an empty string."""
    target = str(container or "").strip().lower()
    video = str(video_codec or "").strip().lower()
    audio = str(audio_codec or "").strip().lower()
    if video in TRIM_CONTAINER_REFUSALS.get(target, set()):
        return f"{target.upper()} cannot hold {video.upper()} video. MOV or MKV can; the container choice has to change."
    if target in {"m2ts", "ts"} and audio.startswith("pcm_"):
        return f"{target.upper()} cannot hold PCM audio. MOV keeps camera PCM as it is."
    if audio in TRIM_AUDIO_REFUSALS.get(target, set()):
        return f"{target.upper()} cannot hold {audio.upper()} audio. MKV takes it; MP4 takes it as well."
    # Measured: the MXF muxer accepts PCM and refuses aac, ac3, mp3, alac and
    # flac outright ("not supported by the bitstream filter"), so the useful
    # answer is given here rather than as an exit code.
    if target == "mxf" and audio and not audio.startswith("pcm_"):
        return (
            f"MXF takes PCM audio only, and this file carries {audio.upper()}. "
            "MOV keeps it as it is; converting the track to PCM is a separate decision, not one a trim should make."
        )
    return ""


def _video_stream_duration(root: Path, target: Path) -> float:
    """Duration of the picture itself, which is what a variable rate needs."""
    result = _capture_tool(
        root,
        [
            _ffprobe(root),
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=duration",
            "-of",
            "default=nokey=1:noprint_wrappers=1",
            str(target),
        ],
    )
    try:
        return float((result.stdout or "").strip().splitlines()[0])
    except (ValueError, IndexError):
        return 0.0


def _trim_container_warnings(container: str, audio_codec: str, timecode: str, source_container: str = "") -> list[str]:
    """What the chosen container is about to cost, said before the run."""
    warnings: list[str] = []
    container = str(container or "").strip().lower()
    codec = str(audio_codec or "").strip().lower()
    if container == "mkv" and timecode:
        warnings.append(
            "MKV keeps a timecode as a text tag, not as a tmcd track. Editors that sync by timecode may not read it — MOV or MP4 do carry it."
        )
    # Only worth saying when the container is being changed: cameras that shoot
    # HEVC with LPCM already write exactly this MP4, and repeating it on every
    # such file is noise, not a warning.
    if container in {"mp4", "m4v"} and codec.startswith("pcm_") and str(source_container).strip().lower() not in {"mp4", "m4v"}:
        warnings.append(
            "PCM audio in MP4 is written as the non-standard ipcm tag. MOV is the safe home for camera PCM."
        )
    if container == "mxf":
        warnings.append("MXF rejects most camera stream layouts on a plain copy. Check the first file before running a batch.")

    return warnings


def _trim_seek_warnings(source: Path) -> list[str]:
    """Containers whose seek is an estimate rather than a lookup."""
    if source.suffix.lower().lstrip(".") in {"ts", "m2ts", "mts", "m2t"}:
        return [
            "MPEG-TS carries no index, so the seek is interpolated from byte positions. "
            "It is accurate in the middle of a file and can overshoot near its end; "
            "repackaging to MOV or MP4 first (Package / remux) makes the cut exact."
        ]
    return []


def _discard_unusable_trim(context: JobContext, target: Path) -> None:
    """Remove a result that cannot be opened; keep one that can.

    A run stopped mid-write leaves a file with no index - gigabytes that no
    player will touch - under the name the finished piece would have had. A
    partial file that does open is another matter: it is still footage, and
    deleting it would be the surprise.
    """
    try:
        if not target.exists():
            return
        if target.stat().st_size == 0:
            target.unlink()
            context.log(f"    [CLEAN] Removed the empty {target.name} left by the stopped run.")
            return
    except OSError as exc:
        context.log(f"    [WARN] Could not inspect {target.name}: {exc}")
        return

    duration = _video_stream_duration(context.paths.root, target)
    if duration > 0:
        context.log(f"    [KEPT] {target.name} stops early but opens: {format_seconds(duration)}.")
        return
    try:
        size_mb = target.stat().st_size / (1024 * 1024)
        target.unlink()
        context.log(
            f"    [CLEAN] Removed {target.name} ({size_mb:.0f} MB): the run stopped before the index was "
            "written, so nothing can open it."
        )
    except OSError as exc:
        context.log(f"    [WARN] Could not remove {target.name}: {exc}")


def _trim_plan(
    context: JobContext,
    source: Path,
    params: dict[str, Any],
    *,
    source_dir: Path,
    output_dir: Path,
    name_suffix: str = "",
) -> dict[str, Any]:
    """Everything decided about one file before FFmpeg is called."""
    root = context.paths.root
    label = _source_display_name(source, source_dir)
    data = _probe_media_json(root, source)
    video = _stream(data, "video")
    audio = _stream(data, "audio")
    if not video:
        raise RuntimeError("no video stream")
    # A codec FFmpeg does not recognise cannot be copied. Camera RAW wrapped in
    # MXF reads exactly this way - Sony X-OCN from a BURANO, ARRIRAW from an
    # Alexa Mini - a stream with no name and no dimensions, and any attempt ends
    # in "dimensions not set" and a file of zero bytes. Better to say so than to
    # let a wrong cause be reported.
    if _video_stream_is_unreadable(video):
        raise RuntimeError(TRIM_UNREADABLE_VIDEO)
    facts = _trim_stream_facts(root, source)
    duration = facts["duration"]
    if duration <= 0:
        raise RuntimeError("duration could not be read")

    variable_rate = is_variable_rate(facts.get("r_frame_rate"), facts.get("avg_frame_rate"))
    # On a variable-rate source the average is not the rate of any given second,
    # so the nominal one is the honest basis for timecode and for display.
    rate_source = facts.get("r_frame_rate") if variable_rate else facts.get("avg_frame_rate")
    # Exactly what the file states: ffprobe reports 24000/1001 for 23.976 and
    # 24/1 for a true 24.000, so there is nothing left to infer.
    rate = parse_rate(rate_source or video.get("avg_frame_rate"))
    # Positions the operator types are counted from the first picture, not from
    # whatever timestamp the container happens to start at.
    origin = float(facts.get("origin") or 0.0)

    pattern = _trim_pattern(params)
    if pattern == "middle":
        # Planned as two cuts and a join, by _trim_gap_plan - never as one.
        raise RuntimeError("cutting a piece out of the middle is planned as two cuts, not as one")
    # Keyframes are only probed when the head actually moves; a cut that starts
    # at zero needs no snapping and no scan.
    head = parse_seconds(params.get("trim_start") or 0) if pattern in {"start", "both"} else 0.0
    # ffprobe reports keyframes in the stream's timeline; the cut is planned in
    # the operator's, so the origin comes off here and goes back on at seek time.
    keyframes = [item - origin for item in _trim_keyframes(root, source, head + origin)] if head > 0 else []
    try:
        cut = plan_cut(
            pattern=pattern,
            start=params.get("trim_start"),
            end=params.get("trim_end"),
            duration=duration,
            rate=rate,
            keyframes=keyframes,
            frame_exact=not variable_rate,
        )
    except ValueError as exc:
        raise RuntimeError(str(exc)) from exc
    start = cut.start
    requested_end = cut.requested_end

    container = _trim_container(params, source)
    audio_codec = str(audio.get("codec_name") or "")
    audio_mode = str(params.get("trim_audio") or "copy").strip().lower()
    if not audio:
        audio_mode = "none"
    channel_mode = str(params.get("trim_audio_channel") or "both").strip().lower()
    if audio_mode not in {"none", "off"}:
        complaint = audio_channel_complaint(channel_mode, _audio_stream_channels(audio))
        if complaint:
            raise RuntimeError(complaint)
    audio_filter = "" if audio_mode in {"none", "off"} else audio_channel_filter(channel_mode)
    audio_args: list[str] = []
    lossless_audio = True
    rewrite_pcm = False
    if audio_filter:
        audio_args, lossless_audio = audio_reencode_args(
            audio_codec,
            sample_fmt=str(audio.get("sample_fmt") or ""),
            bitrate=_audio_bitrate(params),
        )
    elif (
        audio_mode not in {"none", "off"}
        and audio_codec.lower().startswith("pcm_")
        and (container == "mxf" or _as_bool(params.get("trim_sample_exact"), False))
    ):
        # Copying PCM carries the samples between the chunk boundary and the cut
        # - a few milliseconds of sound that belong on the other side of it.
        # Rewriting the same PCM at the same depth lands on the sample instead,
        # byte for byte identical to a reference cut, so nothing is lost and
        # nothing shifts.
        #
        # Always true for MXF, whose chunks are large. Also asked for when two
        # pieces are about to be joined: there the surplus does not merely sit
        # at the end, it pushes the second piece''s sound out of sync with its
        # picture. Measured on a 25 fps PCM take: 72 ms of drift without this.
        #
        # Little-endian is forced here: MXF accepts `pcm_s16le` and `pcm_s24le`
        # and refuses `pcm_s16be`, which is what a Canon file carries. Same
        # samples, the byte order the container requires.
        audio_args, lossless_audio = audio_reencode_args(
            audio_codec.replace("be", "le"),
            sample_fmt=str(audio.get("sample_fmt") or ""),
            bitrate=_audio_bitrate(params),
        )
        rewrite_pcm = True

    source_timecode = _trim_source_timecode(root, source)
    timecode_mode = str(params.get("trim_timecode") or "shift").strip().lower()
    if timecode_mode in {"zero", "reset"}:
        timecode = zero_timecode(rate, drop=timecode_is_drop_frame(source_timecode))
    elif source_timecode:
        timecode = shift_timecode(source_timecode, start, rate)
    else:
        timecode = ""

    # Telemetry and subtitles: on by default, and honest about what the chosen
    # container will actually take.
    keep_data, keep_subtitles, extra_warnings = extra_stream_plan(
        data.get("streams") or [],
        container,
        want_data=_as_bool(params.get("trim_data"), True),
        want_subtitles=_as_bool(params.get("trim_subtitles"), True),
        source_container=source.suffix,
    )

    refusal = _trim_container_refusal(container, str(video.get("codec_name") or ""), audio_codec)
    if refusal:
        raise RuntimeError(refusal)
    warnings = _trim_container_warnings(
        container, audio_codec, timecode or source_timecode, source.suffix.lower().lstrip(".")
    )
    warnings.extend(_trim_seek_warnings(source))
    warnings.extend(extra_warnings)
    if variable_rate:
        warnings.append(
            "The source has a variable frame rate, so the cut is made by time rather than by frame count. "
            "The tail lands within a packet, not on an exact frame."
        )
    if audio_filter and not lossless_audio:
        warnings.append(
            f"Picking a channel rebuilds the audio, and {audio_codec.upper()} cannot be rebuilt without a generation loss. PCM sources are free."
        )
    if source_timecode and timecode_mode not in {"zero", "reset"} and not timecode:
        warnings.append("The source carries no timecode, so nothing can be shifted.")

    target = _output_path(
        source,
        output_dir,
        "",
        container,
        source_root=source_dir,
        operation=_operation_output_folder(context, "Trim"),
    )
    if name_suffix:
        target = target.with_name(f"{target.stem}_{name_suffix}{target.suffix}")
    command = build_trim_command(
        ffmpeg=_ffmpeg(root),
        source=str(source),
        target=str(target),
        overwrite=_as_bool(params.get("overwrite"), True),
        start_seconds=start + origin,
        frame_count=cut.frames,
        duration_seconds=cut.tail_seconds,
        # A piece headed for a join carries its own length as well, so its sound
        # reaches the end of it rather than stopping with the last frame.
        sound_to_seconds=(cut.kept if cut.frames and _as_bool(params.get("trim_sample_exact"), False) else None),
        extension=container,
        audio_mode=audio_mode,
        audio_args=audio_args,
        audio_filter=audio_filter,
        rewrite_audio=rewrite_pcm,
        timecode=timecode,
        faststart=_as_bool(params.get("trim_faststart"), True),
        keep_data=keep_data,
        keep_subtitles=keep_subtitles,
    )
    return {
        "label": f"{label} [{name_suffix}]" if name_suffix else label,
        "source": source,
        "target": target,
        "command": command,
        "rate": rate,
        "duration": duration,
        "pattern": pattern,
        "requested_start": cut.requested_start,
        "requested_end": cut.requested_end,
        "start": cut.start,
        "keyframe_offset": cut.keyframe_offset,
        "kept": cut.kept,
        "frames": cut.frames,
        "rewrite_pcm": rewrite_pcm,
        "variable_rate": variable_rate,
        "origin": origin,
        "container": container,
        "audio_mode": audio_mode,
        "channel_mode": channel_mode if audio_filter else "both",
        "source_timecode": source_timecode,
        "timecode": timecode,
        "keep_data": keep_data,
        "keep_subtitles": keep_subtitles,
        "warnings": warnings,
    }


def _trim_gap_plan(
    context: JobContext,
    source: Path,
    params: dict[str, Any],
    *,
    source_dir: Path,
    output_dir: Path,
) -> dict[str, Any]:
    """One file with a piece taken out of its middle: two cuts and a join."""
    root = context.paths.root
    facts = _trim_stream_facts(root, source)
    duration = facts["duration"]
    if duration <= 0:
        raise RuntimeError("duration could not be read")
    variable_rate = is_variable_rate(facts.get("r_frame_rate"), facts.get("avg_frame_rate"))
    rate_source = facts.get("r_frame_rate") if variable_rate else facts.get("avg_frame_rate")
    rate = parse_rate(rate_source or "")
    origin = float(facts.get("origin") or 0.0)

    gap_end = parse_seconds(params.get("trim_end") or 0)
    # The tail has to start past the removed piece, so the scan begins there.
    keyframes = [item - origin for item in _trim_keyframes(root, source, gap_end + origin)]
    try:
        gap = plan_gap(
            start=params.get("trim_start"),
            end=params.get("trim_end"),
            duration=duration,
            rate=rate,
            keyframes=keyframes,
            frame_exact=not variable_rate,
        )
    except ValueError as exc:
        raise RuntimeError(str(exc)) from exc

    container = _trim_container(params, source)
    stage = context.paths.workspace / "trim_gap"
    stage.mkdir(parents=True, exist_ok=True)
    label = _source_display_name(source, source_dir)

    # Both pieces are cut sample-exactly where the format allows it: a surplus
    # of sound at the end of the head, or at the start of the tail, lands
    # straight on the join.
    shared = {**params, "trim_sample_exact": True}
    head_params = {**shared, "trim_pattern": "end", "trim_end": format_seconds(gap.requested_start), "trim_start": ""}
    tail_params = {**shared, "trim_pattern": "start", "trim_start": format_seconds(gap.tail_start), "trim_end": ""}
    head = _trim_plan(context, source, head_params, source_dir=source_dir, output_dir=stage, name_suffix="gap_head")
    tail = _trim_plan(context, source, tail_params, source_dir=source_dir, output_dir=stage, name_suffix="gap_tail")

    target = _output_path(
        source,
        output_dir,
        "",
        container,
        source_root=source_dir,
        operation=_operation_output_folder(context, "Trim"),
    )
    list_file = stage / f"{target.stem}_parts.txt"

    warnings = list(head["warnings"])
    for warning in tail["warnings"]:
        if warning not in warnings:
            warnings.append(warning)
    if gap.keyframe_offset > 0:
        warnings.append(
            "The tail starts at the first keyframe past the removed piece, so "
            f"{format_offset(gap.keyframe_offset).lstrip('+')} more than asked for was removed. "
            "Starting earlier would leave part of the removed piece in the result."
        )
    return {
        "kind": "gap",
        "label": label,
        "source": source,
        "target": target,
        "parts": [head, tail],
        "list_file": list_file,
        "rate": rate,
        "duration": duration,
        "pattern": "middle",
        "container": container,
        "gap": gap,
        # The fields the shared verification reads. `frames` is deliberately
        # empty: the tail runs to the end of the file, so the total is not known
        # before it is written, and the picture's own duration is the honest
        # measure here.
        "kept": gap.kept,
        "frames": None,
        "timecode": head["timecode"],
        "source_timecode": head["source_timecode"],
        "warnings": warnings,
        "command": _concat_command(root, list_file, target, container, params, head["timecode"]),
    }


def _concat_command(
    root: Path,
    list_file: Path,
    target: Path,
    container: str,
    params: dict[str, Any],
    timecode: str = "",
) -> list[str]:
    """Glue the two pieces by copying packets - no decoding, no re-encoding."""
    command = [
        _ffmpeg(root),
        "-hide_banner",
        "-stats",
        "-y" if _as_bool(params.get("overwrite"), True) else "-n",
        "-nostdin",
        "-f",
        "concat",
        # The pieces sit in `workspace`, an absolute path the demuxer refuses
        # to read without this.
        "-safe",
        "0",
        "-i",
        str(list_file),
        # Picture and sound by name, the way every other cut here maps them.
        # `-map 0` would also pick up the timecode track, which MOV refuses to
        # take from a concat input - the run fails with "unsupported type" and
        # nothing is written. The timecode is written below as a value instead.
        "-map",
        "0:v:0",
        "-map",
        "0:a?",
        "-sn",
        "-dn",
        "-c",
        "copy",
        "-map_metadata",
        "0",
    ]
    if timecode:
        command += ["-timecode", timecode]
    if container in {"mp4", "m4v", "mov"}:
        flags = "use_metadata_tags"
        if _as_bool(params.get("trim_faststart"), True):
            flags += "+faststart"
        command += ["-movflags", flags]
    command.append(str(target))
    return command


def _log_gap_plan(context: JobContext, plan: dict[str, Any], index: int, total: int) -> None:
    gap = plan["gap"]
    context.log(
        f"[{index}/{total}] {plan['label']} | {rate_label(plan['rate'])} | {format_seconds(plan['duration'])} | -> {plan['container'].upper()}"
    )
    context.log(f"    remove  {format_seconds(gap.requested_start)} .. {format_seconds(gap.requested_end)}")
    if gap.keyframe_offset > 0:
        context.log(
            f"    tail at {format_seconds(gap.tail_start)} (first keyframe past the piece, {format_offset(gap.keyframe_offset)})"
        )
    else:
        context.log(f"    tail at {format_seconds(gap.tail_start)} (a keyframe sits exactly there)")
    head_text = f"{gap.head_frames} frames" if gap.head_frames else format_seconds(gap.head_seconds)
    context.log(f"    head    {head_text} ({format_seconds(gap.head_seconds)})")
    context.log(f"    removed {format_seconds(gap.removed)}, keeping {format_seconds(gap.kept)}")
    for warning in plan["warnings"]:
        context.log(f"    [WARNING] {warning}")


def _run_gap_plan(context: JobContext, plan: dict[str, Any]) -> None:
    """Cut the two pieces, join them, and take the pieces away afterwards."""
    parts: list[Path] = []
    try:
        for part in plan["parts"]:
            _run_ffmpeg_media_process(
                context,
                part["command"],
                part["source"],
                check=True,
                progress_seconds=420,
                label=f"{part['label']} trim",
            )
            _top_up_short_tail(context, part)
            parts.append(part["target"])
            if not part["target"].exists() or part["target"].stat().st_size == 0:
                raise RuntimeError(f"{part['label']}: the piece was not written")

        list_file = Path(plan["list_file"])
        # The concat demuxer reads one path per line; a quote inside a name is
        # escaped rather than dropped, or the list would point at nothing.
        lines = ["file '" + str(item).replace("'", "'\\''") + "'" for item in parts]
        list_file.write_text("\n".join(lines) + "\n", encoding="utf-8")

        _run_ffmpeg_media_process(
            context,
            plan["command"],
            plan["source"],
            check=True,
            progress_seconds=420,
            label=f"{plan['label']} join",
        )
    finally:
        for item in parts:
            item.unlink(missing_ok=True)
        Path(plan["list_file"]).unlink(missing_ok=True)


def _log_trim_plan(context: JobContext, plan: dict[str, Any], index: int, total: int) -> None:
    context.log(
        f"[{index}/{total}] {plan['label']} | {rate_label(plan['rate'])} | {format_seconds(plan['duration'])} | -> {plan['container'].upper()}"
    )
    if plan["keyframe_offset"]:
        context.log(
            f"    cut in  {format_seconds(plan['requested_start'])} -> keyframe {format_seconds(plan['start'])} ({format_offset(plan['keyframe_offset'])})"
        )
    else:
        context.log(f"    cut in  {format_seconds(plan['start'])}")
    if plan["frames"]:
        context.log(
            f"    cut out {format_seconds(plan['requested_end'])} -> frame {plan['frames']} of the piece ({format_seconds(plan['kept'])})"
        )
    elif plan.get("variable_rate"):
        context.log(f"    cut out {format_seconds(plan['requested_end'])} (by time: variable frame rate)")
    else:
        context.log(f"    cut out {format_seconds(plan['requested_end'])} (end of file)")
    context.log(f"    keeping {format_seconds(plan['kept'])}")
    if plan["timecode"]:
        origin = plan["source_timecode"] or "none"
        context.log(f"    timecode {origin} -> {plan['timecode']}")
    carried = [
        name
        for name, flag in (("telemetry", plan.get("keep_data")), ("subtitles", plan.get("keep_subtitles")))
        if flag
    ]
    if carried:
        context.log(f"    carried over: {', '.join(carried)}")
    if plan.get("rewrite_pcm"):
        context.log("    audio: PCM rewritten sample-accurately for MXF (same depth, no generation lost)")
    if plan["channel_mode"] != "both":
        context.log(f"    audio channel: {plan['channel_mode']}")
    elif plan["audio_mode"] in {"none", "off"}:
        context.log("    audio: dropped")
    for warning in plan["warnings"]:
        context.log(f"    [WARNING] {warning}")


def _counted_video_frames(root: Path, target: Path) -> int:
    """Packets actually written, counted rather than taken from the header.

    Counting packets parses the file instead of decoding it — 0.14 s against
    5.7 s on four minutes of 59.94 — and for most streams one packet is one
    frame. Where that does not hold (a long-GOP tail whose B-frames reference a
    picture past the cut), `_decodable_video_frames` gives the honest number.
    """
    result = _capture_tool(
        root,
        [
            _ffprobe(root),
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-count_packets",
            "-show_entries",
            "stream=nb_read_packets",
            "-of",
            "default=nokey=1:noprint_wrappers=1",
            str(target),
        ],
    )
    try:
        return int((result.stdout or "").strip().splitlines()[0])
    except (ValueError, IndexError):
        return 0


# HEVC with a B-pyramid writes a few frames fewer than `-frames:v` asks for. The
# shortfall is stable for a given stream but does not follow `has_b_frames`, so
# it is measured rather than guessed, and the cut is redone once with the count
# raised by exactly that much.
TRIM_TOP_UP_LIMIT = 16


def _decodable_video_frames(root: Path, target: Path) -> int:
    """Frames a decoder actually hands over — the number a viewer will see.

    This one decodes, so it is reserved for the case that needs it.
    """
    result = _capture_tool(
        root,
        [
            _ffprobe(root),
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-count_frames",
            "-show_entries",
            "stream=nb_read_frames",
            "-of",
            "default=nokey=1:noprint_wrappers=1",
            str(target),
        ],
    )
    try:
        return int((result.stdout or "").strip().splitlines()[0])
    except (IndexError, ValueError):
        return 0


def _undecodable_tail(root: Path, plan: dict[str, Any], planned: int) -> int:
    """How many written packets the decoder refuses at the end of the piece.

    Every packet asked for was written, which is not the same as every frame
    arriving: an HEVC B-pyramid tail points at a picture past the cut and gets
    dropped. The stream duration gives it away without decoding anything, so
    the expensive count only runs when the duration comes up short.
    """
    rate = plan.get("rate")
    if not rate:
        return 0
    frame_seconds = 1.0 / float(rate)
    planned_seconds = planned * frame_seconds
    actual_seconds = _video_stream_duration(root, plan["target"])
    if actual_seconds <= 0 or planned_seconds - actual_seconds < frame_seconds / 2:
        return 0
    decoded = _decodable_video_frames(root, plan["target"])
    return planned - decoded if decoded else 0


def _top_up_short_tail(context: JobContext, plan: dict[str, Any]) -> None:
    planned = plan.get("frames")
    if not planned:
        return
    root = context.paths.root
    written = _counted_video_frames(root, plan["target"])
    if not written:
        return
    shortfall = int(planned) - written
    if shortfall <= 0:
        shortfall = _undecodable_tail(root, plan, int(planned))
    if shortfall <= 0 or shortfall > TRIM_TOP_UP_LIMIT:
        return
    command = list(plan["command"])
    try:
        position = command.index("-frames:v")
    except ValueError:
        return
    command[position + 1] = str(int(planned) + shortfall)
    context.log(
        f"    [RETRY] {planned - shortfall} of {planned} frames arrived; asking for {command[position + 1]} to land on {planned}."
    )
    _run_ffmpeg_media_process(
        context,
        command,
        plan["source"],
        check=True,
        progress_seconds=420,
        label=f"{plan['label']} trim (top-up)",
    )
    # The retry deliberately writes more packets than frames, so the report has
    # to speak of what a decoder returns or it will claim a longer piece than
    # anyone will see.
    plan["decoded"] = _decodable_video_frames(root, plan["target"])


def _verify_trim_output(context: JobContext, plan: dict[str, Any]) -> dict[str, Any]:
    """Report what actually landed on disk: real duration and real timecode."""
    root = context.paths.root
    target = plan["target"]
    try:
        data = _probe_media_json(root, target)
        fmt = data.get("format", {}) if isinstance(data.get("format"), dict) else {}
        container_duration = float(fmt.get("duration") or 0.0)
    except Exception as exc:
        # An unreadable result is a failed trim, not a trim with an unknown size.
        context.log(f"    [ERROR] The result cannot be read back: {exc}")
        return {"short": True, "unreadable": True}
    # After a top-up the honest count is already known and was paid for once.
    frames = int(plan.get("decoded") or 0) or _counted_video_frames(root, target)
    if plan.get("frames") and frames:
        # A frame-exact plan is measured in frames; the container rounds.
        video_duration = frames_to_seconds(frames, plan["rate"])
    else:
        # On a variable rate a frame count says nothing about elapsed time, so
        # the picture's own duration is the only honest number.
        video_duration = _video_stream_duration(root, target) or container_duration
    written_timecode = _trim_source_timecode(root, target)
    drift = video_duration - float(plan["kept"])
    counted = f"{frames} frames, " if frames else ""
    planned_frames = plan.get("frames")
    if planned_frames and frames and abs(frames - int(planned_frames)) > 1:
        # The frame-exact tail only holds when `-ss` lands on a real keyframe;
        # a mismatch means the seek went somewhere else, and saying so beats
        # letting the editor discover it.
        context.log(
            f"    [WARNING] {frames} frames were written where the plan asked for {planned_frames}. "
            "The seek did not land on the keyframe it was given."
        )
    context.log(
        f"    result  {counted}{format_seconds(video_duration)} ({format_offset(drift, decimals=3)} from the plan)"
        + (f", timecode {written_timecode}" if written_timecode else ", no timecode")
    )
    # An audio tail rounds up to a whole packet; only say so when it is enough
    # to notice, and never call it a drift of the picture.
    audio_tail = container_duration - video_duration
    if abs(audio_tail) > 0.1:
        where = "past the last frame" if audio_tail > 0 else "short of the last frame"
        context.log(f"    audio runs {format_offset(abs(audio_tail), decimals=3)} {where} (packet boundary)")
    if plan["timecode"] and not written_timecode:
        context.log("    [WARNING] The timecode did not survive this container. Sync data is lost for the editor.")
    # A result far shorter than the plan is not a trim; it is a seek that missed.
    expected = float(plan["kept"])
    short = expected > 0.2 and video_duration < expected * 0.5
    if short:
        context.log(
            f"    [ERROR] Only {format_seconds(video_duration)} of the planned {format_seconds(expected)} was written. "
            "The seek did not land where it was sent - on MPEG-TS this happens near the end of a file."
        )
    return {
        "duration": video_duration,
        "frames": frames,
        "timecode": written_timecode,
        "drift": drift,
        "short": short,
    }


def trim_media(context: JobContext) -> dict[str, object]:
    """Cut the head, the tail, or both off camera footage without re-encoding."""
    params = dict(context.operation.parameters)
    root = context.paths.root
    source_dir = cached_source_path(root)
    output_dir = cached_output_path(root)

    # Marked files come with their own points; each is trimmed where it was
    # marked, which is the whole reason the arrows exist.
    marked = _trim_marked_jobs(params, source_dir)
    per_file_points: dict[Path, dict[str, Any]] = {}
    if marked:
        files = [path for path, _entry in marked]
        per_file_points = {path: entry for path, entry in marked}
        context.log(f"Trimming {len(files)} marked file(s), each at its own points.")
    else:
        selected = str(params.get("trim_file") or "").strip()
        if selected:
            candidate = source_dir / selected
            files = [candidate] if candidate.is_file() else []
            if not files:
                context.log(f"[ERROR] Selected file is not in Source: {selected}")
                return {"files": 0, "failed": 1}
        else:
            # One file at a time: two takes rarely share a keyframe, let alone a
            # cut point. The CLI wrappers still walk the whole folder on purpose.
            staged = _media_files(source_dir, TRIM_VIDEO_EXTENSIONS)
            files = staged[:1]
            if len(staged) > 1:
                context.log(f"Trimming the first of {len(staged)} files: {_source_display_name(files[0], source_dir)}")
    if not files:
        context.log(f"No video files in {source_dir}")
        return {"files": 0}
    if _as_bool(params.get("limit_first_file"), False):
        files = files[:1]

    dry_run = _as_bool(params.get("dry_run"), False)
    overwrite = _as_bool(params.get("overwrite"), True)
    plans: list[dict[str, Any]] = []
    # A split is the same operation twice: everything up to the point into one
    # file, everything from it into another. Nothing is thrown away.
    split_mode = _trim_pattern(params) == "split"
    # And the fifth: the piece between the points goes, and what is left is
    # joined. Two cuts and a concat, planned as one job.
    gap_mode = _trim_pattern(params) == "middle"
    skipped = 0
    for source in files:
        file_params = dict(params)
        marks = per_file_points.get(source)
        if marks:
            file_params["trim_pattern"] = str(marks.get("pattern") or params.get("trim_pattern") or "both")
            file_params["trim_start"] = marks.get("start", "")
            file_params["trim_end"] = marks.get("end", "")
        try:
            if gap_mode:
                plans.append(_trim_gap_plan(context, source, file_params, source_dir=source_dir, output_dir=output_dir))
            elif split_mode:
                point = file_params.get("trim_start") or file_params.get("trim_end") or ""
                head = {**file_params, "trim_pattern": "end", "trim_end": point, "trim_start": ""}
                tail = {**file_params, "trim_pattern": "start", "trim_start": point, "trim_end": ""}
                plans.append(_trim_plan(context, source, head, source_dir=source_dir, output_dir=output_dir, name_suffix="part1"))
                plans.append(_trim_plan(context, source, tail, source_dir=source_dir, output_dir=output_dir, name_suffix="part2"))
            else:
                plans.append(_trim_plan(context, source, file_params, source_dir=source_dir, output_dir=output_dir))
        except Exception as exc:
            skipped += 1
            context.log(f"[SKIP] {_source_display_name(source, source_dir)}: {exc}")
    if not plans:
        context.log("Nothing to trim.")
        return {"files": 0, "scanned": len(files), "skipped": skipped}

    processed = 0
    failed = 0
    total = len(plans)
    for index, plan in enumerate(plans, start=1):
        if context.cancelled():
            context.log("Trim cancelled by user.")
            _discard_unusable_trim(context, plan["target"])
            return {"cancelled": True, "processed": processed, "files": total}
        if plan.get("kind") == "gap":
            _log_gap_plan(context, plan, index, total)
        else:
            _log_trim_plan(context, plan, index, total)
        if not overwrite and plan["target"].exists():
            # FFmpeg would answer `-n` with exit code 0 and write nothing, which
            # reads as success and leaves the previous file in place.
            skipped += 1
            context.log(f"    [SKIP] {plan['target'].name} already exists and Overwrite is off.")
            context.progress(index / total)
            continue
        if dry_run:
            context.log("    [DRY RUN] Command was not executed.")
            context.log("    " + " ".join(f'"{part}"' if " " in part else part for part in plan["command"]))
            processed += 1
            context.progress(index / total)
            continue
        try:
            if plan.get("kind") == "gap":
                _run_gap_plan(context, plan)
            else:
                _run_ffmpeg_media_process(
                    context,
                    plan["command"],
                    plan["source"],
                    check=True,
                    progress_seconds=420,
                    label=f"{plan['label']} trim",
                )
                _top_up_short_tail(context, plan)
        except RuntimeError as exc:
            failed += 1
            # Includes the cancel path: `run_process` terminates FFmpeg and
            # raises, and whatever it had written so far is usually headless.
            _discard_unusable_trim(context, plan["target"])
            context.log(f"    [FAIL] {plan['label']}: {exc}")
            context.progress(index / total)
            continue
        verified = _verify_trim_output(context, plan)
        if verified.get("short"):
            failed += 1
            context.progress(index / total)
            continue
        processed += 1
        context.progress(index / total)

    return {
        "processed": processed,
        "failed": failed,
        "files": total,
        "scanned": len(files),
        "skipped": skipped,
        "dry_run": dry_run,
    }


# --- Trim preview -------------------------------------------------------------
#
# The preview answers one question: what is at the point the cut will really
# land on. A frame and four seconds of waveform are enough for that, and both
# are cheap — 90 ms and 60 ms on a five-minute clip — so they can be redrawn
# every time a slider is released. A player with a scrub bar is a different
# product; this is a still and an oscilloscope.

TRIM_PREVIEW_WIDTH = 320
TRIM_PREVIEW_WAVE_SECONDS = 4.0


def _capture_bytes(root: Path, command: list[str]) -> bytes:
    completed = subprocess.run(
        command,
        cwd=str(root),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        env=utf8_subprocess_env(_tool_env(root)),
        **hidden_subprocess_kwargs(),
    )
    return completed.stdout if completed.returncode == 0 else b""


def _data_uri(payload: bytes, mime: str) -> str:
    return f"data:{mime};base64,{base64.b64encode(payload).decode('ascii')}" if payload else ""


def _trim_preview_source(root: Path, file_name: str) -> Path | None:
    source_dir = cached_source_path(root)
    if file_name:
        candidate = source_dir / file_name
        return candidate if candidate.is_file() else None
    files = _media_files(source_dir, TRIM_VIDEO_EXTENSIONS)
    return files[0] if files else None


def trim_media_info(file_name: str = "", root: Path | str | None = None) -> dict[str, Any]:
    """Duration, frame rate and timecode of the file the sliders will drive."""
    project_root = Path(root).resolve() if root else Path(__file__).resolve().parents[2]
    source = _trim_preview_source(project_root, str(file_name or ""))
    if source is None:
        return {"ok": False, "error": "No video file is staged in Source."}
    try:
        data = _probe_media_json(project_root, source)
        # Asked before anything is decoded: a still of a stream FFmpeg cannot
        # parse produces its own complaint, which is no answer for the panel.
        video = _stream(data, "video")
        if _video_stream_is_unreadable(video):
            return {"ok": False, "error": TRIM_UNREADABLE_VIDEO}
        facts = _trim_stream_facts(project_root, source)
        duration = facts["duration"]
        variable_rate = is_variable_rate(facts.get("r_frame_rate"), facts.get("avg_frame_rate"))
        rate_source = facts.get("r_frame_rate") if variable_rate else facts.get("avg_frame_rate")
        rate = parse_rate(rate_source)
    except Exception as exc:
        return {"ok": False, "error": str(exc)}
    if duration <= 0:
        return {"ok": False, "error": "Duration could not be read."}
    return {
        "ok": True,
        "file": _source_display_name(source, cached_source_path(project_root)),
        "path": str(source),
        "duration": duration,
        "duration_label": format_seconds(duration, decimals=1, separator=","),
        "rate": rate_label(rate),
        "rate_exact": f"{rate.numerator}/{rate.denominator}",
        "frame_seconds": float(1 / rate),
        "origin": float(facts.get("origin") or 0.0),
        "variable_rate": variable_rate,
        "timecode": _trim_source_timecode(project_root, source),
        "has_audio": bool(_stream(data, "audio")),
        "decodes_as_gbr": _decodes_as_gbr(video),
        "codec": str(video.get("codec_name") or "").strip().lower(),
    }


# The strip is rendered wide enough to cover a 4K display at the default
# 1600x900 window; stretching it further only interpolates, which is fine for a
# waveform. Peaks a few seconds apart are all this view has to show.
TRIM_WAVE_WIDTH = 2560
# Drawn taller than the strip is shown so the shape stays crisp when the pane
# stretches it - the fine strip is 72 px and can be resized by the window.
TRIM_WAVE_HEIGHT = 128
# The section's orange, shared with the fader handle: one warm colour against
# the cold ground, so the strip and the control it drives read as one instrument.
TRIM_WAVE_COLOR = "#cc5500"
# Cube root: compared on the same ten seconds of speech, `lin` draws a hairline,
# `sqrt` a thin form, `log` a solid block, `cbrt` a body where the phrase reads.
TRIM_WAVE_SCALE = "cbrt"
# Pixels of transparent air kept above and below the drawn shape, in the
# rendered picture. At 128 px rendered into a 56 px strip, 8 px reads as the
# 3-4 px of air a peak at 0 dB should keep from the border.
TRIM_WAVE_AIR = 8


def _trim_wave_cache_dir(root: Path) -> Path:
    folder = root / "workspace" / "trim_waves"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def _trim_wave_cache_name(source: Path, start: float, end: float, width: int, height: int, gain: float = 1.0) -> str:
    try:
        stat = source.stat()
        stamp = f"{int(stat.st_mtime)}-{stat.st_size}"
    except OSError:
        stamp = "0-0"
    # The drawing rules belong in the key: a change of scale, colour or air
    # produces a different picture from the same audio, and without them the
    # strip cached before the change is served forever.
    style = f"{TRIM_WAVE_SCALE}|{TRIM_WAVE_COLOR}|{TRIM_WAVE_AIR}"
    key = f"{source.resolve()}|{stamp}|{start:.3f}|{end:.3f}|{width}x{height}|{gain:.2f}|{style}"
    return hashlib.sha1(key.encode("utf-8")).hexdigest() + ".png"


# One peak per file, so the strip keeps a fixed scale: loud passages stay tall
# and quiet ones stay small, and nothing rescales under a standing cursor.
_TRIM_TRACK_PEAKS: dict[tuple[str, int, int], float] = {}


def _trim_track_peak(root: Path, source: Path) -> float:
    """Loudest sample of the whole track, 0..1, or 0 when it is not in memory.

    Peak, not RMS: RMS draws a fuller body but flattens transients, and a cut is
    aimed at exactly those - the attack of a word, the click of a door.

    Read from the track already held for scrubbing, so this is a scan of memory
    rather than another pass of ffmpeg. If the track has not arrived yet the
    answer is 0 and the strip is drawn as recorded, then redrawn once it has.
    """
    key = _trim_scrub_key(source)
    if key is None:
        return 0.0
    held = _TRIM_TRACK_PEAKS.get(key)
    if held is not None:
        return held
    with _TRIM_SCRUB_LOCK:
        track = _TRIM_SCRUB_TRACKS.get(key)
    if not track:
        return 0.0
    even = track[: len(track) // 2 * 2]
    if not even:
        return 0.0
    if _audioop is not None:
        # 0.06 s over an hour of audio against 9.8 s for the loop below, and the
        # loop runs before the first strip can be drawn.
        loudest = _audioop.max(even, 2)
    else:
        samples = array.array("h")
        samples.frombytes(even)
        # Every eighth sample: a thinned scan can miss a lone peak by a little,
        # which for a drawing scale costs nothing and keeps an hour usable.
        loudest = max((abs(int(value)) for value in samples[::8]), default=0)
    peak = min(1.0, loudest / 32768.0)
    if len(_TRIM_TRACK_PEAKS) >= TRIM_SCRUB_TRACK_LIMIT * 4:
        _TRIM_TRACK_PEAKS.clear()
    _TRIM_TRACK_PEAKS[key] = peak
    return peak


def _wave_gain(peak: float) -> float:
    """How much to lift the window so its loudest peak reaches the edge.

    Capped at 32× so a near-silent stretch turns into a readable shape rather
    than into amplified noise, and never below 1: nothing is ever drawn quieter
    than it was recorded.
    """
    if peak <= 0.0:
        return 1.0
    return max(1.0, min(32.0, 0.98 / peak))


def _render_waveform(
    root: Path,
    source: Path,
    start: float,
    end: float,
    width: int,
    height: int,
    gain: float = 1.0,
) -> bytes:
    """`showwavespic` over one span, on a transparent background.

    The audio is resampled down to 8 kHz first: the strip shows peaks, not
    spectra, and the lower rate takes a fifth off the decode of a long file.
    `gain` lifts a quiet window so the shape fills the strip.
    """
    span = max(0.05, float(end) - float(start))
    command = [_ffmpeg(root), "-v", "error"]
    if start > 0:
        command.extend(["-ss", f"{float(start):.3f}"])
    command.extend(
        [
            "-t",
            f"{span:.3f}",
            "-i",
            str(source),
            "-filter_complex",
            # The scale decides whether the strip can be read at all. Compared
            # on the same ten seconds of speech: `lin` draws a hairline with
            # occasional spikes, `sqrt` is thin, `log` fills solid and loses the
            # shape, `cbrt` gives a body where the structure of a phrase still
            # shows. `draw=full` keeps quiet passages visible too.
            f"aresample=8000,volume={max(1.0, float(gain)):.4f},"
            f"showwavespic=s={int(width)}x{max(8, int(height) - 2 * TRIM_WAVE_AIR)}"
            f":colors={TRIM_WAVE_COLOR}:draw=full:scale={TRIM_WAVE_SCALE},"
            # Transparent air above and below, so the loudest peak stops short
            # of the border rather than being cut off by it.
            f"pad={int(width)}:{int(height)}:0:{TRIM_WAVE_AIR}:color=0x00000000",
            "-frames:v",
            "1",
            "-update",
            "1",
            "-f",
            "image2",
            "-c:v",
            "png",
            "pipe:1",
        ]
    )
    return _capture_bytes(root, command)


def trim_waveform(
    file_name: str = "",
    start: float = 0.0,
    end: float = 0.0,
    root: Path | str | None = None,
    *,
    width: int = TRIM_WAVE_WIDTH,
    height: int = TRIM_WAVE_HEIGHT,
    use_cache: bool = True,
) -> dict[str, Any]:
    """One waveform strip as a data URI, plus the span it covers.

    `use_cache` is on for the whole-file strip, which is expensive and never
    changes, and off for the moving window, which is cheap and always different.
    """
    project_root = Path(root).resolve() if root else Path(__file__).resolve().parents[2]
    source = _trim_preview_source(project_root, str(file_name or ""))
    if source is None:
        return {"ok": False, "error": "No video file is staged in Source."}
    facts = _trim_stream_facts(project_root, source)
    origin = float(facts.get("origin") or 0.0)
    span_end = float(end) if end and end > start else None
    if span_end is None:
        duration = facts["duration"] or (_media_duration_seconds(project_root, source) or 0.0)
        if duration <= 0:
            return {"ok": False, "error": "Duration could not be read."}
        span_end = duration
    span_start = max(0.0, float(start))

    cache_file = None
    if use_cache:
        cache_file = _trim_wave_cache_dir(project_root) / _trim_wave_cache_name(
            source, span_start, span_end, width, height, _wave_gain(_trim_track_peak(project_root, source))
        )
        if cache_file.is_file():
            try:
                return {
                    "ok": True,
                    "start": span_start,
                    "end": span_end,
                    "image": _data_uri(cache_file.read_bytes(), "image/png"),
                    "cached": True,
                }
            except OSError:
                pass

    # The whole track's peak, so every window of this file is drawn to the same
    # scale. Zero while the track is still arriving - the strip is then drawn as
    # recorded and redrawn at its proper level on the next pass.
    gain = _wave_gain(_trim_track_peak(project_root, source))
    payload = _render_waveform(project_root, source, span_start + origin, span_end + origin, width, height, gain)
    if not payload:
        return {"ok": False, "error": "This file carries no audio to draw.", "start": span_start, "end": span_end}
    if cache_file is not None:
        try:
            cache_file.write_bytes(payload)
        except OSError:
            pass
    return {"ok": True, "start": span_start, "end": span_end, "image": _data_uri(payload, "image/png"), "cached": False}


def trim_probe_table(file_name: str = "", root: Path | str | None = None) -> dict[str, Any]:
    """What ffprobe knows about the file, as rows for a table.

    The questions this answers are the ones asked before a cut: what codec is
    inside, at what rate, is the rate honest, is there a timecode to carry, and
    where does this file's clock start.
    """
    project_root = Path(root).resolve() if root else Path(__file__).resolve().parents[2]
    source = _trim_preview_source(project_root, str(file_name or ""))
    if source is None:
        return {"ok": False, "error": "No video file is staged in Source."}
    try:
        data = _probe_media_json(project_root, source)
        facts = _trim_stream_facts(project_root, source)
    except Exception as exc:
        return {"ok": False, "error": f"{exc.__class__.__name__}: {exc}"}

    video = _stream(data, "video")
    audio = _stream(data, "audio")
    fmt = data.get("format", {}) if isinstance(data.get("format"), dict) else {}
    variable = is_variable_rate(facts.get("r_frame_rate"), facts.get("avg_frame_rate"))
    try:
        rate = parse_rate(facts.get("r_frame_rate") if variable else facts.get("avg_frame_rate"))
    except Exception:
        rate = None
    duration = float(facts.get("duration") or 0.0)
    timecode = _trim_source_timecode(project_root, source)

    def size_label() -> str:
        try:
            size = source.stat().st_size
        except OSError:
            return "-"
        for unit in ("B", "KB", "MB", "GB"):
            if size < 1024 or unit == "GB":
                return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
            size /= 1024.0
        return "-"

    rows: list[tuple[str, str]] = [
        ("File", source.name),
        ("Container", str(fmt.get("format_name") or source.suffix.lstrip(".")).split(",")[0].upper()),
        ("Size", size_label()),
        ("Duration", format_seconds(duration) if duration else "-"),
        ("Frames", str(seconds_to_frames(duration, rate)) if rate and duration else "-"),
        ("Video", " ".join(part for part in (str(video.get("codec_name") or "-").upper(), str(video.get("profile") or "")) if part).strip()),
        ("Resolution", f"{video.get('width', '-')}x{video.get('height', '-')}"),
        ("Frame rate", (rate_label(rate) if rate else "-") + (" (variable)" if variable else "")),
        ("Exact rate", f"{rate.numerator}/{rate.denominator}" if rate else "-"),
        ("Pixel format", str(video.get("pix_fmt") or "-")),
        ("Colour", " ".join(part for part in (str(video.get("color_space") or ""), str(video.get("color_transfer") or "")) if part) or "-"),
        ("Audio", str(audio.get("codec_name") or "none").upper()),
        ("Channels", str(audio.get("channels") or "-")),
        ("Sample rate", f"{audio.get('sample_rate')} Hz" if audio.get("sample_rate") else "-"),
        ("Sample format", str(audio.get("sample_fmt") or "-")),
        ("Timecode", timecode or "none"),
        ("Timeline starts", format_seconds(float(facts.get("origin") or 0.0))),
        ("Bit rate", f"{int(fmt.get('bit_rate')) // 1000} kb/s" if str(fmt.get("bit_rate") or "").isdigit() else "-"),
    ]
    return {"ok": True, "file": source.name, "rows": [{"field": name, "value": value} for name, value in rows]}




# One frame, the way an editor scrubs: the chunk begins on the frame boundary
# and lasts exactly as long as the frame does. `frames` raises that for a caller
# that wants more; the fallback is used only when a file states no usable rate.
TRIM_SCRUB_SECONDS = 0.04
# Mono at 24 kHz: this is for recognising speech under the cursor, not judging a
# mix, and a quarter of the bytes arrive four times sooner.
TRIM_SCRUB_RATE = 24000
TRIM_SCRUB_BLOCK_SECONDS = 120.0
# Six blocks is twenty minutes of sound, about 33 MB. Blocks are the answer
# until the whole track arrives, and the only answer for a file too big to hold.
TRIM_SCRUB_BLOCK_LIMIT = 6
_TRIM_SCRUB_BLOCKS: dict[tuple[str, int, int, int], bytes] = {}

# Three hours at 24 kHz mono is about 500 MB. Below that the whole track is
# held, because there is no telling whether the work is at the start, the middle
# or the end - and the material this is for is small: a Zoom call is nothing, a
# twenty-minute project reel is 55 MB, half an hour is 82 MB. Past three hours
# the blocks remain the answer.
TRIM_SCRUB_TRACK_CEILING = 3 * 60 * 60 * TRIM_SCRUB_RATE * 2
# Two tracks: the one in hand and the one just left.
TRIM_SCRUB_TRACK_LIMIT = 2
_TRIM_SCRUB_TRACKS: dict[tuple[str, int, int], bytes] = {}
_TRIM_SCRUB_LOADING: set[tuple[str, int, int]] = set()
_TRIM_SCRUB_LOCK = threading.Lock()


def _trim_scrub_key(source: Path) -> tuple[str, int, int] | None:
    try:
        stat = source.stat()
    except OSError:
        return None
    return (str(source), int(stat.st_size), int(stat.st_mtime))


def _trim_scrub_load_track(root: Path, source: Path, key: tuple[str, int, int]) -> None:
    """Decode the whole track and keep it. Runs off the caller's thread."""
    track = _capture_bytes(
        root,
        [
            _ffmpeg(root),
            "-v",
            "error",
            "-i",
            str(source),
            "-vn",
            "-ac",
            "1",
            "-ar",
            str(TRIM_SCRUB_RATE),
            "-c:a",
            "pcm_s16le",
            "-f",
            "s16le",
            "pipe:1",
        ],
    )
    with _TRIM_SCRUB_LOCK:
        _TRIM_SCRUB_LOADING.discard(key)
        if not track:
            return
        if len(_TRIM_SCRUB_TRACKS) >= TRIM_SCRUB_TRACK_LIMIT:
            _TRIM_SCRUB_TRACKS.clear()
        _TRIM_SCRUB_TRACKS[key] = track


def _trim_scrub_track(root: Path, source: Path) -> bytes:
    """The whole track if it is held; otherwise start holding it and say so.

    Never blocks: the first slices come from a block while this arrives. The
    duration is only consulted when a decision has to be made - a track already
    in hand needs no probe, and probing per slice would cost more than the slice.
    """
    key = _trim_scrub_key(source)
    if key is None:
        return b""
    with _TRIM_SCRUB_LOCK:
        held = _TRIM_SCRUB_TRACKS.get(key)
        if held is not None:
            return held
        if key in _TRIM_SCRUB_LOADING:
            return b""
    duration = float(_trim_stream_facts(root, source).get("duration") or 0.0)
    with _TRIM_SCRUB_LOCK:
        if key in _TRIM_SCRUB_LOADING or _TRIM_SCRUB_TRACKS.get(key) is not None:
            return _TRIM_SCRUB_TRACKS.get(key) or b""
        if duration <= 0 or duration * TRIM_SCRUB_RATE * 2 > TRIM_SCRUB_TRACK_CEILING:
            return b""
        _TRIM_SCRUB_LOADING.add(key)
    thread = threading.Thread(
        target=_trim_scrub_load_track,
        args=(root, source, key),
        name="trim-scrub-track",
        daemon=True,
    )
    thread.start()
    return b""


def _trim_scrub_block(root: Path, source: Path, index: int) -> bytes:
    """Two minutes of raw mono PCM, decoded once and kept.

    Holding the sound is what makes the fader audible without a process per
    move: the whole track of a 55-second 4K file decodes in 0.16 s, and after
    that a slice is a memory copy.
    """
    try:
        stat = source.stat()
        key = (str(source), int(stat.st_size), int(stat.st_mtime), int(index))
    except OSError:
        key = None
    if key is not None:
        held = _TRIM_SCRUB_BLOCKS.get(key)
        if held is not None:
            return held
    start = max(0.0, index * TRIM_SCRUB_BLOCK_SECONDS)
    block = _capture_bytes(
        root,
        [
            _ffmpeg(root),
            "-v",
            "error",
            "-ss",
            f"{start:.3f}",
            "-t",
            f"{TRIM_SCRUB_BLOCK_SECONDS:.3f}",
            "-i",
            str(source),
            "-vn",
            "-ac",
            "1",
            "-ar",
            str(TRIM_SCRUB_RATE),
            "-c:a",
            "pcm_s16le",
            "-f",
            "s16le",
            "pipe:1",
        ],
    )
    if key is not None and block:
        if len(_TRIM_SCRUB_BLOCKS) >= TRIM_SCRUB_BLOCK_LIMIT:
            _TRIM_SCRUB_BLOCKS.clear()
        _TRIM_SCRUB_BLOCKS[key] = block
    return block


def _reversed_pcm(pcm: bytes) -> bytes:
    """Same samples, last first. 16-bit mono, so the frame is two bytes."""
    if len(pcm) < 4:
        return pcm
    samples = array.array("h")
    samples.frombytes(pcm[: len(pcm) // 2 * 2])
    samples.reverse()
    return samples.tobytes()


def _wav_from_pcm(pcm: bytes, rate: int = TRIM_SCRUB_RATE) -> bytes:
    """Wrap raw mono 16-bit PCM in the 44-byte header a browser expects."""
    header = bytearray()
    header += b"RIFF"
    header += (36 + len(pcm)).to_bytes(4, "little")
    header += b"WAVEfmt "
    header += (16).to_bytes(4, "little")
    header += (1).to_bytes(2, "little")            # PCM, uncompressed
    header += (1).to_bytes(2, "little")            # one channel
    header += int(rate).to_bytes(4, "little")
    header += int(rate * 2).to_bytes(4, "little")  # bytes per second
    header += (2).to_bytes(2, "little")            # block align
    header += (16).to_bytes(2, "little")           # bits per sample
    header += b"data"
    header += len(pcm).to_bytes(4, "little")
    return bytes(header) + pcm


# A track longer than this is not handed to the browser whole: decoded, it costs
# four bytes a sample there, and twenty-five minutes is already 140 MB.
TRIM_TRACK_DOWNLOAD_CEILING = 25 * 60 * TRIM_SCRUB_RATE * 2


def trim_audio_track(file_name: str = "", root: Path | str | None = None) -> dict[str, Any]:
    """The whole scrub track as one WAV, for the panel to decode and keep.

    Returns `too_long` rather than a wall of bytes when the file is big enough
    that holding it decoded in a browser would cost more than it is worth.
    """
    project_root = Path(root).resolve() if root else Path(__file__).resolve().parents[2]
    source = _trim_preview_source(project_root, str(file_name or ""))
    if source is None:
        return {"ok": False, "error": "No video file is staged in Source."}
    track = _trim_scrub_track(project_root, source)
    if not track:
        # Not held yet - the loader was started by the call above, and the panel
        # asks again in a moment.
        return {"ok": False, "pending": True}
    if len(track) > TRIM_TRACK_DOWNLOAD_CEILING:
        return {"ok": False, "too_long": True, "seconds": len(track) / (TRIM_SCRUB_RATE * 2)}
    return {
        "ok": True,
        "wav": _wav_from_pcm(track),
        "rate": TRIM_SCRUB_RATE,
        "seconds": len(track) / (TRIM_SCRUB_RATE * 2),
    }


def trim_audio_slice(
    file_name: str = "",
    position: float = 0.0,
    root: Path | str | None = None,
    *,
    frames: int = 1,
    seconds: float = 0.0,
    reverse: bool = False,
) -> dict[str, Any]:
    """The sound of the frame at `position`, as a WAV the page can play.

    `reverse` plays it backwards, which is what a jog wheel does when it is
    turned back: the direction of travel is heard rather than guessed.

    Frame-sized by default and aligned to the frame boundary, which is what an
    editor gives you when you scrub: you hear the frame you are standing on, not
    the second that follows it. `seconds` overrides the length for a caller that
    wants a longer listen.

    Cut out of the track held in memory, so a move of the fader costs a copy
    rather than a seek and a decode.
    """
    project_root = Path(root).resolve() if root else Path(__file__).resolve().parents[2]
    source = _trim_preview_source(project_root, str(file_name or ""))
    if source is None:
        return {"ok": False, "error": "No video file is staged in Source."}
    where = max(0.0, float(position))
    frame_seconds = 0.0
    try:
        facts = _trim_stream_facts(project_root, source)
        rate = parse_rate(facts.get("avg_frame_rate") or facts.get("r_frame_rate"))
        frame_seconds = 1.0 / float(rate)
    except Exception:
        rate = None
    if seconds and float(seconds) > 0:
        span = float(seconds)
    elif frame_seconds > 0:
        span = frame_seconds * max(1, int(frames))
        # Start where the frame starts: half a frame of drift is audible as the
        # wrong syllable when the point is at the head of a word.
        where = math.floor(where / frame_seconds) * frame_seconds
    else:
        span = TRIM_SCRUB_SECONDS * max(1, int(frames))
    length = int(span * TRIM_SCRUB_RATE) * 2

    # The whole track, once it has arrived: no block boundaries to stitch, and
    # nothing to guess about which part of the file the work is in.
    track = _trim_scrub_track(project_root, source)
    if track:
        first = int(where * TRIM_SCRUB_RATE) * 2
        pcm = track[first : first + length]
        if not pcm:
            return {"ok": False, "error": "No audio at this point."}
        if reverse:
            pcm = _reversed_pcm(pcm)
        return {
            "ok": True,
            "audio": "data:audio/wav;base64," + base64.b64encode(_wav_from_pcm(pcm)).decode("ascii"),
            "seconds": len(pcm) / (TRIM_SCRUB_RATE * 2),
            "at": where,
            "reversed": bool(reverse),
            "source": "track",
        }

    index = int(where // TRIM_SCRUB_BLOCK_SECONDS)
    block = _trim_scrub_block(project_root, source, index)
    if not block:
        return {"ok": False, "error": "No audio at this point."}
    offset = where - index * TRIM_SCRUB_BLOCK_SECONDS
    first = int(offset * TRIM_SCRUB_RATE) * 2
    pcm = block[first : first + length]
    if len(pcm) < length:
        # The slice runs past the end of this block; the next one carries the
        # rest, and at the end of the file there simply is no rest.
        pcm += _trim_scrub_block(project_root, source, index + 1)[: length - len(pcm)]
    if not pcm:
        return {"ok": False, "error": "No audio at this point."}
    if reverse:
        pcm = _reversed_pcm(pcm)
    return {
        "ok": True,
        "audio": "data:audio/wav;base64," + base64.b64encode(_wav_from_pcm(pcm)).decode("ascii"),
        "seconds": len(pcm) / (TRIM_SCRUB_RATE * 2),
        "at": where,
        "reversed": bool(reverse),
        "source": "block",
    }












def trim_save_still(
    file_name: str = "",
    position: float = 0.0,
    image_format: str = "png",
    root: Path | str | None = None,
) -> dict[str, Any]:
    """Write the frame at a position to disk, full resolution.

    The preview is 320 px wide because it only has to identify a moment. A
    still that leaves the tool is worth its actual size.
    """
    project_root = Path(root).resolve() if root else Path(__file__).resolve().parents[2]
    source = _trim_preview_source(project_root, str(file_name or ""))
    if source is None:
        return {"ok": False, "error": "No video file is staged in Source."}
    fmt = str(image_format or "png").strip().lower()
    if fmt not in {"png", "jpg", "jpeg"}:
        fmt = "png"
    extension = "jpg" if fmt in {"jpg", "jpeg"} else "png"

    facts = _trim_stream_facts(project_root, source)
    origin = float(facts.get("origin") or 0.0)
    folder = cached_output_path(project_root) / "Stills"
    folder.mkdir(parents=True, exist_ok=True)
    stamp = format_seconds(float(position), decimals=3, separator="-").replace(":", "-")
    target = folder / f"{source.stem}_{stamp}.{extension}"

    command = [
        _ffmpeg(project_root),
        "-v",
        "error",
        "-y",
        "-ss",
        f"{max(0.0, float(position)) + origin:.6f}",
        "-i",
        str(source),
        "-frames:v",
        "1",
    ]
    if extension == "jpg":
        command.extend(["-q:v", "2"])
    command.append(str(target))
    result = _capture_tool(project_root, command)
    if result.returncode != 0 or not target.is_file():
        return {"ok": False, "error": (result.stdout or "ffmpeg wrote nothing").strip()[:200]}
    return {"ok": True, "path": str(target), "name": target.name}


def trim_keyframe_neighbours(
    file_name: str = "",
    position: float = 0.0,
    root: Path | str | None = None,
) -> dict[str, Any]:
    """The keyframe before and after a point, for step-by-keyframe navigation.

    A copied stream can only be cut on a keyframe, so these are the places the
    head of a piece can actually land.
    """
    project_root = Path(root).resolve() if root else Path(__file__).resolve().parents[2]
    source = _trim_preview_source(project_root, str(file_name or ""))
    if source is None:
        return {"ok": False, "error": "No video file is staged in Source."}
    times = _trim_keyframes(project_root, source, float(position))
    if not times:
        return {"ok": False, "error": "No keyframes were found."}
    earlier = [item for item in times if item < float(position) - 0.001]
    later = [item for item in times if item > float(position) + 0.001]
    return {
        "ok": True,
        "previous": earlier[-1] if earlier else None,
        "next": later[0] if later else None,
    }


def trim_preview(
    file_name: str = "",
    position: float = 0.0,
    root: Path | str | None = None,
    *,
    snap: bool = True,
    width: int = TRIM_PREVIEW_WIDTH,
    with_wave: bool = True,
) -> dict[str, Any]:
    """A still from the real cut point, plus the waveform around it.

    `snap` moves the point to the nearest keyframe, which is where a copied
    stream can actually be cut. The offset comes back with it so the interface
    can say how far the cut moved instead of correcting it in silence.
    """
    project_root = Path(root).resolve() if root else Path(__file__).resolve().parents[2]
    info = trim_media_info(file_name, project_root)
    if not info.get("ok"):
        return info
    source = Path(str(info["path"]))
    duration = float(info["duration"])
    requested = max(0.0, min(float(position), duration))

    # Everything the operator sees is counted from the first picture; the
    # container's own clock may start elsewhere, and only FFmpeg needs that.
    origin = float(info.get("origin") or 0.0)
    # Two different questions. The still answers "what is here", so it is taken
    # at the point itself - a picture that lags the hand cannot be searched
    # with. `keyframe` answers "where would the cut begin", which is a caption,
    # not a picture.
    point = requested
    offset = 0.0
    keyframe_at = None
    if requested > 0:
        candidates = [item - origin for item in _trim_keyframes(project_root, source, requested + origin)]
        snapped = nearest_keyframe(candidates, requested)
        if snapped is not None:
            keyframe_at = snapped
            offset = snapped - requested

    ffmpeg = _ffmpeg(project_root)
    height = max(2, int(round(width * 9 / 16)) // 2 * 2)
    # A seek to the very end lands past the last frame and returns nothing, so
    # the still for an end point is taken one frame back.
    frame_seconds = float(info.get("frame_seconds") or 0.04)
    seek = min(point, max(0.0, duration - frame_seconds)) + origin
    def still(decode_args: list[str], extra_filters: list[str]) -> bytes:
        return _capture_bytes(
            project_root,
            [
                ffmpeg,
                "-v",
                "error",
                *decode_args,
                "-ss",
                f"{seek:.3f}",
                "-i",
                str(source),
                "-frames:v",
                "1",
                *extra_filters,
                "-s",
                f"{width}x{height}",
                "-q:v",
                "4",
                "-f",
                "mjpeg",
                "pipe:1",
            ],
        )

    # Two independent quirks decide the order here.
    #
    # Colour: ARRI ProRes 4444 XQ decodes to GBR with reserved primaries, and
    # swscale refuses a picture described that way - "Unsupported input", no
    # still at all. Naming a working colour space fixes it.
    #
    # Speed: a 4K H.264 still costs 0.85 s on the CPU and 0.48 s with
    # `-hwaccel auto`, which is felt on every move of the fader. It is offered
    # to the codecs QSV, NVDEC and AMF decode (see TRIM_HARDWARE_DECODED) and to
    # no others: asking for a hardware path that does not exist costs a refusal,
    # and for ProRes it also breaks the colour route its still depends on.
    # Whatever happens, the list ends on plain software decoding.
    colour_hint = ["-vf", "setparams=colorspace=bt709:color_primaries=bt709:color_trc=bt709"]
    hardware = ["-hwaccel", "auto"]
    if info.get("decodes_as_gbr"):
        attempts = [([], colour_hint), ([], [])]
    elif str(info.get("codec") or "") in TRIM_HARDWARE_DECODED:
        attempts = [(hardware, []), ([], []), ([], colour_hint)]
    else:
        attempts = [([], []), ([], colour_hint)]
    frame = b""
    for decode_args, filters in attempts:
        frame = still(decode_args, filters)
        if frame:
            break
    wave = b""
    if with_wave and info.get("has_audio"):
        window = TRIM_PREVIEW_WAVE_SECONDS
        wave = _capture_bytes(
            project_root,
            [
                ffmpeg,
                "-v",
                "error",
                "-ss",
                f"{max(0.0, point - window / 2) + origin:.3f}",
                "-t",
                f"{window:.3f}",
                "-i",
                str(source),
                "-filter_complex",
                f"showwavespic=s={width}x64:colors=#e08a63",
                "-frames:v",
                "1",
                "-update",
                "1",
                "-f",
                "image2",
                "-c:v",
                "png",
                "pipe:1",
            ],
        )

    source_timecode = str(info.get("timecode") or "")
    point_timecode = ""
    if source_timecode:
        try:
            facts = _trim_stream_facts(project_root, source)
            rate_source = facts.get("r_frame_rate") if info.get("variable_rate") else facts.get("avg_frame_rate")
            point_timecode = shift_timecode(source_timecode, point, parse_rate(rate_source))
        except Exception:
            point_timecode = ""

    return {
        **info,
        "keyframe": keyframe_at,
        "keyframe_label": format_seconds(keyframe_at, decimals=1, separator=",") if keyframe_at is not None else "",
        "requested": requested,
        "point": point,
        "offset": offset,
        "point_label": format_seconds(point, decimals=1, separator=","),
        "offset_label": format_offset(offset, separator=",") if offset else "",
        "point_timecode": point_timecode,
        "frame": _data_uri(frame, "image/jpeg"),
        "wave": _data_uri(wave, "image/png"),
    }
