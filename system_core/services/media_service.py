from __future__ import annotations

import warnings
import time
from pathlib import Path
from typing import Any, Callable
from fractions import Fraction
import importlib
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile

from system_core.core.ansi_terminal import ansi_status
from system_core.core.audio_contract import (
    mp3_encoder_args,
    mp3_preset_label,
    normalize_mp3_preset,
    normalize_sample_rate,
    resample_filter_args,
    soxr_resample_filter,
)
from system_core.core.camera_raw import develops, ffmpeg_reads, hint, raw_of, refuses
from system_core.core.encoder_backends import (
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
    fps_audio_mode as _fps_audio_mode,
    fps_audio_output_rate as _fps_audio_output_rate,
    fps_audio_target_rate as _fps_audio_target_rate,
    fps_pcm_audio_args as _fps_pcm_audio_args,
)
from system_core.core.jobs import JobContext, hidden_subprocess_kwargs, run_cmd_script, run_process, utf8_subprocess_env
from system_core.core.logging_utils import timestamp
from system_core.core.manifest import CommandNode, load_manifest
from system_core.core.path_cache import cached_output_path, cached_source_path, only_formats
from system_core.core.script_profiles import load_script_profiles, script_profile
from system_core.services import raw_develop
from system_core.core.trim_contract import (
    audio_channel_complaint,
    audio_channel_filter,
    audio_reencode_args,
    AUDIO_COVER_CONTAINERS,
    PACKET_COPY_RULES,
    audio_codec_is_lossless,
    audio_trim_encoding,
    audio_trim_metadata,
    build_audio_trim_command,
    build_packet_copy_command,
    build_packet_join_command,
    plan_audio_trim,
    plan_packet_copy,
    build_trim_command,
    format_offset,
    format_seconds,
    frames_to_seconds,
    is_variable_rate,
    stream_rate,
    keyframe_probe_command,
    extra_stream_plan,
    parse_keyframe_times,
    plan_gap,
    plan_split,
    parse_split_interval,
    split_interval_points,
    TrimCut,
    parse_rate,
    parse_seconds,
    plan_cut,
    rate_label,
    seconds_to_frames,
    shift_timecode,
    timecode_is_drop_frame,
    TRIM_MAX_VARIANTS,
    SubtitleCue,
    cues_for_spans,
    format_srt,
    parse_srt,
    subtitle_extract_command,
    subtitle_input_codecs,
    subtitle_input_maps,
    subtitle_stream_plan,
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
    only = only_formats()
    if only:
        extensions = set(extensions) & only
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
    # A ProRes RAW master in the workspace stands for its source.
    source = raw_develop.original_of(source)
    try:
        return source.resolve().parent.relative_to(source_root.resolve())
    except (OSError, ValueError):
        return Path()


def _without_camera_raw(context: JobContext, files: list[Path], source_dir: Path, service: str) -> tuple[list[Path], int]:
    """The files a service takes without the camera RAW it refuses (core\\camera_raw.py: the services that decode the
    picture - every one, the ones that copy the stream - what FFmpeg does not read): each said in one line with what
    opens it and failed, the rest go on; the preflight has said it before the run."""
    reads = ffmpeg_reads(_ffprobe(context.paths.root))
    kept: list[Path] = []
    for path in files:
        raw = raw_of(path, reads)
        if raw and refuses(service, raw):
            label = _source_display_name(path, source_dir)
            if develops(context.paths.root, service, raw):
                # cineraw develops it on the video card into a ProRes 4444 master the service reads; the result is named
                # and placed as the source (raw_develop.original_of), the master goes when the run ends.
                if _as_bool(context.operation.parameters.get("dry_run"), False):
                    context.log(f"[DRY RUN] {label}: {raw.name} would be developed first on the video card by cineraw.")
                    kept.append(path)
                    continue
                try:
                    kept.append(raw_develop.develop_master(context, path, label))
                except RuntimeError as error:
                    context.log(f"[FAIL] {label}: {raw.name} was not developed - {error}")
                continue
            done = "developed" if raw.read else "read"
            context.log(f"[FAIL] {label}: {raw.name} is not {done} by the program - {hint(raw)}")
        else:
            kept.append(path)
    return kept, len(files) - len(kept)


def _source_display_name(source: Path, source_root: Path | None = None) -> str:
    source = raw_develop.original_of(source)
    if source_root is not None:
        try:
            relative = source.resolve().relative_to(source_root.resolve()).as_posix()
            # A Source that is one file is its own root: "." would name nothing.
            if relative not in {"", "."}:
                return relative
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


# 5.1 to stereo the way the wrapper audio-downmix-51-to-20 always did it: fronts at full level, centre -3 dB, surrounds
# -6 dB (the back and the side pair both named, whichever the layout has), LFE out. A stereo source passes unchanged.
SURROUND_6DB_DOWNMIX = ("pan=stereo|FL=1.0*FL+0.707*FC+0.5*BL+0.5*SL+0.0*LFE"
                        "|FR=1.0*FR+0.707*FC+0.5*BR+0.5*SR+0.0*LFE")
# The sound laid on its timestamps from zero: gaps filled, overlaps trimmed (the wrappers audio-resample-*_sync).
RESYNC_FILTER = "aresample=async=1:first_pts=0"


def _audio_filter_args(params: dict[str, Any], lufs_override: str = "", *, include_lufs: bool = True) -> tuple[list[str], list[str]]:
    channel_mode = str(params.get("audio_channel_mode", "")).strip().lower()
    if _as_bool(params.get("downmix_stereo"), False) and not channel_mode:
        channel_mode = "stereo"
    channel_mode = channel_mode or "keep"
    matrix = _as_bool(params.get("matrix_51"), False) and channel_mode == "stereo"
    downmix = matrix or channel_mode in {"stereo", "mono", "dual_mono"}
    by_pan = channel_mode == "stereo" and not matrix and str(params.get("downmix_formula", "")).strip().lower() == "surround_6db"
    filters: list[str] = []
    suffixes: list[str] = []
    sample_rate = _audio_sample_rate(params)

    if matrix:
        filters.append("aresample=matrix_encoding=dplii")
        suffixes.append("dplii")
    if by_pan:
        filters.append(SURROUND_6DB_DOWNMIX)
        suffixes.append("stereo")

    if sample_rate != "source":
        filters.append(soxr_resample_filter(sample_rate))
        suffixes.append("soxr")
    if _as_bool(params.get("audio_resync"), False):
        filters.append(RESYNC_FILTER)
        suffixes.append("sync")

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
        elif channel_mode != "dual_mono" and not by_pan:
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


# The PCM a WAV (RIFF) file holds as it is, measured with the bundled FFmpeg: the little-endian kinds, unsigned 8-bit,
# A-law and mu-law. Big-endian PCM, signed 8-bit, DVD and Blu-ray PCM are refused there.
WAV_COPY_PCM = {"pcm_s16le", "pcm_s24le", "pcm_s32le", "pcm_f32le", "pcm_f64le", "pcm_u8", "pcm_alaw", "pcm_mulaw"}


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
        # WAV holds little-endian PCM only: a copy of big-endian PCM there is refused by FFmpeg.
        return "wav" if codec in WAV_COPY_PCM else "mka"
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
        ("input", source_path),
        ("output", output_path),
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
    if _as_bool(context.operation.parameters.get("dry_run"), False):
        # A dry run runs nothing, an installer neither: it would download. It says what it would run, as the
        # wrapper yt-update always did.
        context.log("[DRY RUN] The installer was not run.")
        context.log(subprocess.list2cmdline(["cmd.exe", "/d", "/c", "call", str(context.paths.root / script), "/NOPAUSE"]))
        context.progress(1.0)
        return {"script": str(script), "lines": 0, "dry_run": True}
    context.log(f"Installing/updating {label}...")
    result = run_cmd_script(context, str(script), ["/NOPAUSE"], check=True, extra_env=_tool_env(context.paths.root))
    context.progress(1.0)
    return {"script": str(script), "lines": len(result.lines)}


# The installers of SERVICE: an operation and its script in install\, with the words of its log. FFmpeg is installed
# by the script of Gyan: it picks the release the NVIDIA driver allows; the one of BtbN hands over to it under the policy
# of exact stable releases (install\FFmpeg-Driver-Fallback-Policy.md), so it is no choice of its own.
INSTALLER_SCRIPTS = {
    "install_7zip": ("Install-Portable-7Zip.cmd", "portable 7-Zip"),
    "install_ffmpeg": ("Install-Portable-FFmpeg-Gyan.cmd", "portable FFmpeg Gyan Stable"),
    "install_ytdlp": ("Install-Portable-yt-dlp.cmd", "portable yt-dlp"),
    "install_mpv": ("Install-Portable-mpv.cmd", "portable mpv"),
    # Built here from its sources: libcraw publishes no builds (install\Install-Cineraw.ps1).
    "install_cineraw": ("Install-Cineraw.cmd", "cineraw - ProRes RAW on the video card"),
}


def install_portable_7zip(context: JobContext) -> dict[str, object]:
    return _run_installer(context, *INSTALLER_SCRIPTS["install_7zip"])


def install_portable_ffmpeg(context: JobContext) -> dict[str, object]:
    context.log("FFmpeg is a GPL/reviewed external tool payload; install stays explicit.")
    return _run_installer(context, *INSTALLER_SCRIPTS["install_ffmpeg"])


def install_portable_ytdlp(context: JobContext) -> dict[str, object]:
    return _run_installer(context, *INSTALLER_SCRIPTS["install_ytdlp"])


def install_portable_mpv(context: JobContext) -> dict[str, object]:
    return _run_installer(context, *INSTALLER_SCRIPTS["install_mpv"])


def install_cineraw(context: JobContext) -> dict[str, object]:
    return _run_installer(context, *INSTALLER_SCRIPTS["install_cineraw"])


def installer_plan(root: Path, operation: str) -> dict[str, object]:
    """What an installer of SERVICE would download, said by the script itself and nothing fetched: it runs to the point of
    its download (the release, the policy of the NVIDIA driver, the mirror) with AUDION_INSTALL_PLAN=1 and says every
    file - install\\Plan-Download.ps1: "[PLAN] component|file|url|bytes"; "cache" for an url is a verified archive at
    hand. The window names the files, their source and their size before it runs the installer; a [WARN] of the policy
    (FFmpeg under an NVIDIA driver below the LTS 610.88: not every operation is possible) is said with them."""
    if operation not in INSTALLER_SCRIPTS:
        raise ValueError(f"{operation!r} is no installer of SERVICE")
    script = Path(root) / "install" / INSTALLER_SCRIPTS[operation][0]
    environment = {**os.environ, **_tool_env(Path(root)), "AUDION_INSTALL_PLAN": "1", "AUDION_NO_PAUSE": "1"}
    creation = getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0
    try:
        done = subprocess.run(["cmd.exe", "/d", "/c", str(script), "/NOPAUSE"], cwd=str(root), env=environment,
                              capture_output=True, timeout=240, creationflags=creation)
    except (OSError, subprocess.SubprocessError) as error:
        return {"operation": operation, "ok": False, "files": [], "notes": [], "error": f"{type(error).__name__}: {error}"}
    said = ((done.stdout or b"") + b"\n" + (done.stderr or b"")).decode("utf-8", errors="replace")
    files: list[dict[str, object]] = []
    notes: list[str] = []
    trouble: list[str] = []
    for line in (raw.strip() for raw in said.splitlines()):
        if line.startswith("[PLAN] "):
            what, name, url, size = (line[len("[PLAN] "):].split("|") + ["", "", "", ""])[:4]
            files.append({"what": what, "name": name, "url": "" if url == "cache" else url, "cached": url == "cache",
                          "size": int(size) if size.isdigit() else None})
        elif line.startswith("[POLICY]"):
            notes.append(line[len("[POLICY]"):].strip())
        elif line.startswith("[WARN] NVIDIA driver"):
            notes.append(line[len("[WARN]"):].strip())
        elif line.startswith(("[ERROR]", "WARNING:", "[WARN]")) or "Exception" in line:
            trouble.append(line)
    ok = done.returncode == 0 and bool(files)
    return {"operation": operation, "ok": ok, "files": files, "notes": notes,
            "error": "" if ok else " ".join(trouble[-3:]) or f"the installer said no file (exit {done.returncode})"}


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


# What the wrappers of the cut cut: the head (start), the tail (end), both ends (both), a piece out of the middle.
TRIM_WRAPPER_PATTERNS = {"start", "end", "both", "middle"}


def _validate_script_profile(profile_id: str, profile: dict[str, Any]) -> list[dict[str, str]]:
    kind = str(profile.get("kind", "")).strip().lower()
    issues: list[dict[str, str]] = []
    allowed = {"audio", "color", "editing", "encode", "ff_selftest", "fps", "remux", "subtitles", "trim", "youtube"}
    if kind not in allowed:
        return [_profile_doctor_status("ERROR", profile_id, f"Unsupported or missing kind: {kind or '<empty>'}")]

    required_by_kind = {
        "audio": ["action"],
        "color": ["color_filter", "targets"],
        "editing": ["target", "extension"],
        "encode": ["target"],
        "fps": ["source_fps", "target_fps", "mode"],
        "remux": ["source", "target"],
        "trim": ["pattern"],
        "youtube": [],
    }
    for key in required_by_kind.get(kind, []):
        value = profile.get(key)
        if key not in profile or value is None or value == "" or value == []:
            issues.append(_profile_doctor_status("ERROR", profile_id, f"Missing required key: {key}"))

    if kind == "trim" and profile.get("pattern") and profile.get("pattern") not in TRIM_WRAPPER_PATTERNS:
        issues.append(_profile_doctor_status("ERROR", profile_id, f"Unknown trim pattern: {profile.get('pattern')}"))
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
        "format=duration,bit_rate:stream=index,codec_type,codec_name,codec_tag_string,profile,width,height,r_frame_rate,avg_frame_rate,field_order,pix_fmt,color_space,color_transfer,color_primaries,sample_fmt,sample_rate,channels,channel_layout,bits_per_sample,bits_per_raw_sample,bit_rate:stream_tags=language,title",
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


def _claim_target(context: JobContext, source: Path, target: Path) -> Path:
    """The file this source writes in this run. Two sources of one batch never share one: a second of the same stem -
    take.wav beside take.flac, both to M4A - gets the extension of its own in the name (take_wav.m4a), and the journal
    says so. The same order of the Source gives the same names at every run."""
    claimed = getattr(context, "claimed", None)
    if claimed is None:
        return target
    tag = source.suffix.lstrip(".").lower() or "file"
    candidate, number = target, 1
    while claimed.get(os.path.normcase(str(candidate)), str(source)) != str(source):
        number += 1
        candidate = target.with_name(f"{target.stem}_{tag}{number if number > 2 else ''}{target.suffix}")
    if candidate != target:
        context.log(f"    [NOTE] {target.name} is written from {Path(claimed[os.path.normcase(str(target))]).name} in this "
                    f"run: {source.name} goes to {candidate.name}.")
    claimed[os.path.normcase(str(candidate))] = str(source)
    return candidate


# The pixel formats a lossless archive encoder takes as they are, read from the bundled FFmpeg (`ffmpeg -h encoder=`).
ARCHIVE_PIXEL_FORMATS = {
    "ffv1": {
        "yuv420p", "yuva420p", "yuva422p", "yuv444p", "yuva444p", "yuv440p", "yuv422p", "yuv411p", "yuv410p", "bgr0", "bgra",
        "yuv420p16le", "yuv422p16le", "yuv444p16le", "yuv444p9le", "yuv422p9le", "yuv420p9le", "yuv420p10le", "yuv422p10le",
        "yuv444p10le", "yuv420p12le", "yuv422p12le", "yuv444p12le", "yuva444p16le", "yuva422p16le", "yuva420p16le",
        "yuva444p12le", "yuva422p12le", "yuva444p10le", "yuva422p10le", "yuva420p10le", "yuva444p9le", "yuva422p9le",
        "yuva420p9le", "gray16le", "gray", "gbrp9le", "gbrp10le", "gbrp12le", "gbrp14le", "gbrap14le", "gbrap10le",
        "gbrap12le", "ya8", "gray10le", "gray12le", "gray14le", "gbrp16le", "rgb48le", "gbrap16le", "rgba64le", "gray9le",
        "yuv420p14le", "yuv422p14le", "yuv444p14le", "yuv440p10le", "yuv440p12le", "yaf16le", "grayf16le", "gbrpf16le",
        "gbrpf32le",
    },
    "x264_lossless": {
        "yuv420p", "yuvj420p", "yuv422p", "yuvj422p", "yuv444p", "yuvj444p", "nv12", "nv16", "nv21", "yuv420p10le",
        "yuv422p10le", "yuv444p10le", "nv20le", "gray", "gray10le",
    },
}
# The same samples in another layout: a conversion between them loses nothing.
SAME_SAMPLES = {
    "nv12": "yuv420p", "nv21": "yuv420p", "nv16": "yuv422p", "p010le": "yuv420p10le", "p016le": "yuv420p16le",
    "yuyv422": "yuv422p", "uyvy422": "yuv422p", "yuvj420p": "yuv420p", "yuvj422p": "yuv422p", "yuvj444p": "yuv444p",
    "rgb24": "bgr0", "bgr24": "bgr0", "gbrp": "bgr0", "rgb0": "bgr0", "0rgb": "bgr0", "0bgr": "bgr0", "rgba": "bgra",
    "argb": "bgra", "abgr": "bgra",
}
ARCHIVE_NAMES = {"ffv1": "FFV1", "x264_lossless": "x264 lossless"}
# Sound FLAC cannot hold: float and 64-bit PCM.
FLAC_CANNOT_HOLD = ("pcm_f", "pcm_s64")


def _archive_refusal(context: JobContext, source: Path, target: str, params: dict[str, Any]) -> str:
    """Why a lossless archive target would not keep this source as it is - its pixel format is not one the encoder
    takes; "" - it keeps it. A pixel format named by hand for x264 is the person's choice."""
    takes = ARCHIVE_PIXEL_FORMATS.get(target)
    if not takes:
        return ""
    chosen = str(params.get("pix_fmt") or "auto").strip().lower()
    if target == "x264_lossless" and chosen not in {"", "auto"}:
        return ""
    try:
        streams = _probe_media_json(context.paths.root, source).get("streams") or []
    except (OSError, RuntimeError, ValueError):
        return ""
    pixel = next((str(stream.get("pix_fmt") or "").strip().lower() for stream in streams
                  if isinstance(stream, dict) and stream.get("codec_type") == "video"), "")
    if not pixel or pixel in takes or SAME_SAMPLES.get(pixel) in takes:
        return ""
    other = next((name for key, name in ARCHIVE_NAMES.items() if key != target
                  and (pixel in ARCHIVE_PIXEL_FORMATS[key] or SAME_SAMPLES.get(pixel) in ARCHIVE_PIXEL_FORMATS[key])), "")
    return (f"{ARCHIVE_NAMES[target]} cannot keep {pixel} as it is - the bits, the planes or the alpha would be lost"
            + (f"; {other} keeps it." if other else "."))


def _archive_audio(context: JobContext, source: Path, mode: str) -> str:
    """FLAC for the sound of an archive, where FLAC holds it exactly; float or 64-bit PCM is copied as it is."""
    if mode != "flac":
        return mode
    try:
        streams = _probe_media_json(context.paths.root, source).get("streams") or []
    except (OSError, RuntimeError, ValueError):
        return mode
    codecs = [str(stream.get("codec_name") or "").lower() for stream in streams
              if isinstance(stream, dict) and stream.get("codec_type") == "audio"]
    kept = sorted({codec for codec in codecs if codec.startswith(FLAC_CANNOT_HOLD)})
    if not kept:
        return mode
    context.log(f"    [NOTE] FLAC cannot hold {', '.join(kept)} exactly: the sound is copied as it is.")
    return "source"


# The scan of an interlaced source, field `scan_mode`: bwdif, one frame of each frame or one of each field, and the tag
# the folder of the settings gets - a progressive result is not mixed with the one that kept its fields.
SCAN_FILTERS = {
    "progressive": ("bwdif=mode=send_frame:parity=auto:deint=all", "progressive"),
    "double": ("bwdif=mode=send_field:parity=auto:deint=all", "progressive_2x"),
}


def _field_order(context: JobContext, source: Path) -> str:
    """The field order of the video of a source as ffprobe tells it; "" - not told."""
    try:
        streams = _probe_media_json(context.paths.root, source).get("streams") or []
    except (OSError, RuntimeError, ValueError):
        return ""
    return next((str(stream.get("field_order") or "").strip().lower() for stream in streams
                 if isinstance(stream, dict) and stream.get("codec_type") == "video"), "")


def _scan_plan(context: JobContext, source: Path, params: dict[str, Any], video: list[str]) -> tuple[list[str], str, str]:
    """For a source of two fields: the video arguments, a filter that makes it progressive and a tag for the folder of
    the settings. Progressive and Progressive x2 run bwdif; Keep fields keeps them - x264 codes a picture of two fields
    as one progressive frame unless told, and marks the file progressive (+ildct+ilme tells it); the other encoders keep
    the mark by themselves (measured: ProRes, FFV1, x265, AV1). A progressive source is not touched."""
    order = _field_order(context, source)
    if order not in INTERLACED_FIELD_ORDERS:
        return video, "", ""
    mode = str(params.get("scan_mode") or "keep").strip().lower()
    if mode in SCAN_FILTERS:
        chain, tag = SCAN_FILTERS[mode]
        how = "a whole frame of each frame" if mode == "progressive" else "a frame of each field, the rate doubled"
        context.log(f"    [NOTE] {source.name} is interlaced ({order}): bwdif makes it progressive - {how}.")
        return video, chain, tag
    if "libx264" in video:
        context.log(f"    [NOTE] {source.name} is interlaced ({order}): x264 codes its fields and keeps their order.")
        return [*video, "-flags", "+ildct+ilme"], "", ""
    return video, "", ""


def _video_filters(*chains: str) -> list[str]:
    """One -vf of the filters given, in their order; nothing when there are none."""
    chain = ",".join(part for part in chains if part)
    return ["-vf", chain] if chain else []


def _kept_in_place(context: JobContext, target: Path, overwrite: bool) -> bool:
    """A file already in the Target, and Overwrite off: it is passed by before FFmpeg is asked. FFmpeg answers `-n` on
    it with "already exists. Exiting." and exit code 0, so the run would count as written a file it never touched, and
    the next check would measure the old one. The cut looks at its target the same way."""
    if overwrite or not target.exists():
        return False
    context.log(f"    [SKIP] {target.name} already exists and Overwrite is off.")
    return True


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


# ffprobe's field_order for a picture of two fields: top first, bottom first, and the two mixed orders.
INTERLACED_FIELD_ORDERS = {"tt", "bb", "tb", "bt"}


def _rate_label(value: Any, scan: str = "p") -> str:
    """`23.976p`, `25i`, `29.97p` - the rate as it is spoken about; `scan` "" leaves the number bare."""
    text = str(value or "").strip()
    if not text or text in {"0/0", "N/A"}:
        return "?"
    try:
        rate = _parse_fps(text)
    except Exception:
        return text
    if rate <= 0:
        return "?"
    return rate_label(rate)[:-1] + scan


def _video_rate_label(video: dict[str, Any]) -> str:
    """The rate column of SOURCE INFO: `25i` for a picture of two fields, `VFR 30 (avg 28.875)` for a phone's
    variable rate - both rates, since neither alone says what the file holds."""
    nominal, average = video.get("r_frame_rate"), video.get("avg_frame_rate")
    if is_variable_rate(nominal, average):
        return f"VFR {_rate_label(nominal, '')} (avg {_rate_label(average, '')})"
    scan = "i" if str(video.get("field_order") or "").strip().lower() in INTERLACED_FIELD_ORDERS else "p"
    return _rate_label(stream_rate(nominal, average), scan)


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


# The video column of a file FFmpeg sees a video stream in but cannot read (TRIM_UNREADABLE_VIDEO says why).
PROBE_UNREADABLE_VIDEO = "camera RAW, FFmpeg has no decoder"
PROBE_BUSY = "busy: being copied or open elsewhere"
PROBE_UNREADABLE_SAID = (
    "FFmpeg sees a video stream it cannot read: camera RAW inside MXF (Sony X-OCN, ARRIRAW) has no decoder here. "
    "Such material is read in the camera vendor's own software (Sony Catalyst, ARRI Reference Tool) or transcoded first."
)


def _probe_row(source: Path, data: dict[str, Any]) -> dict[str, str]:
    video = _stream(data, "video")
    audio = _stream(data, "audio")
    fmt = data.get("format", {}) if isinstance(data.get("format"), dict) else {}
    if video and _video_stream_is_unreadable(video):
        return {"file": source.name, "video": PROBE_UNREADABLE_VIDEO, "audio": "-", "duration": _format_duration(fmt.get("duration")),
                "fingerprint": "unreadable", "kind": "unreadable"}

    video_codec = str(video.get("codec_name") or "-")
    resolution = f"{video.get('width')}x{video.get('height')}" if video.get("width") and video.get("height") else "-"
    fps = _video_rate_label(video) if video else "-"
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
        "kind": "read",
    }


def _file_is_busy(source: Path) -> bool:
    """A file still being copied, or held by a program that shares it with no one: Windows will not open it."""
    try:
        with source.open("rb"):
            return False
    except PermissionError:
        return True
    except OSError:
        return False


def _probe_summary(rows: list[dict[str, str]], total_files: int) -> str:
    """The folder in one line, said by the files read: what most of them are, and what could not be read.

    A file being copied, a camera RAW and a failed probe say nothing about the folder; neither does the first
    file of the list, which was what the line once showed.
    """
    if not rows:
        return "Source probe: no media"
    read = [row for row in rows if row.get("kind") == "read"]
    left = {kind: sum(1 for row in rows if row.get("kind") == kind) for kind in ("busy", "unreadable", "error")}
    tail = "".join(f", {count} {kind}" for kind, count in left.items() if count)
    if not read:
        return f"{total_files} file(s), none could be read{tail}"
    counts: dict[str, int] = {}
    for row in read:
        counts[row["fingerprint"]] = counts.get(row["fingerprint"], 0) + 1
    most = max(counts, key=counts.get)
    like = next(row for row in read if row["fingerprint"] == most)
    if len(counts) == 1:
        prefix = f"{total_files} file(s), uniform"
    else:
        prefix = f"{total_files} file(s), mixed: {counts[most]} of {len(read)} read like this"
    return f"{prefix}{tail} | V: {like['video']} | A: {like['audio']}"


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
        busy = {"file": source.name, "video": PROBE_BUSY, "audio": "-", "duration": "-", "fingerprint": "busy", "kind": "busy"}
        if _file_is_busy(source):
            row = busy
        else:
            try:
                row = _probe_row(source, _probe_media_json(root, source))
            except Exception as exc:
                row = busy if "permission denied" in str(exc).lower() else {
                    "file": source.name, "video": f"ERROR: {exc}", "audio": "-", "duration": "-", "fingerprint": f"error:{exc}", "kind": "error"}
        rows.append(row)
        context.log(f"{row['file'][:40]:40} | {row['video'][:44]:44} | {row['audio'][:34]:34} | {row['duration']}")
        context.progress(index / len(sample))

    summary = _probe_summary(rows, len(files))
    context.log("")
    if any(row.get("kind") == "unreadable" for row in rows):
        context.log(PROBE_UNREADABLE_SAID)
    if any(row.get("kind") == "busy" for row in rows):
        context.log("A busy file is read once the copy ends or the program holding it lets it go.")
    context.log(summary)
    read = {row["fingerprint"] for row in rows if row.get("kind") == "read"}
    return {"files": len(files), "probed": len(sample), "mixed": len(read) > 1, "summary": summary}


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
    files, camera_raw_failed = _without_camera_raw(context, files, source_dir, "encode_targets")
    if camera_raw_failed and not files:
        return {"files": 0, "failed": camera_raw_failed}

    targets = _as_list(params.get("target_codecs"))
    if not targets:
        raise RuntimeError("No target codec/profile selected.")
    if not files:
        context.log(f"No matching media files in {source_dir}")
        return {"files": 0}

    ffmpeg = _ffmpeg(root)
    # Scaling runs as a software filter, so it rules out the GPU-only pipeline.
    # Scaling and a deinterlace run as software filters, so either rules out the GPU-only pipeline.
    scanning = str(params.get("scan_mode") or "keep").strip().lower() in SCAN_FILTERS
    decode = _decode_args(params, context, has_video_filters=bool(_scale_args(params)) or scanning)
    audio_mode = str(params.get("audio_mode", "aac_320")).strip()
    audio_bitrate = _audio_bitrate(params)
    dry_run = _as_bool(params.get("dry_run"), False)
    overwrite = _as_bool(params.get("overwrite"), True)

    processed = 0
    skipped = 0
    refused = 0
    total = len(files) * len(targets)
    context.units(total)
    for source in files:
        for target_codec in targets:
            target_codec = {"hevc10": "hevc_x265", "prores422": "prores_422"}.get(target_codec, target_codec)
            if context.cancelled():
                context.log("Encoding cancelled by user.")
                return {"cancelled": True, "processed": processed, "skipped": skipped, "refused": refused}

            video, extension, suffix, family = _target_video_args(target_codec, params)
            video, deinterlace, scan_tag = _scan_plan(context, source, params, video)
            if scan_tag:
                suffix = f"{suffix}_{scan_tag}"
            source_label = _source_display_name(source, source_dir)
            target_path = _output_path(source, output_dir, suffix, extension, source_root=source_dir, operation=_operation_output_folder(context, _target_family_output_folder(family)))
            target_path = _claim_target(context, source, target_path)
            if _kept_in_place(context, target_path, overwrite):
                skipped += 1
                context.progress((processed + skipped) / max(1, total))
                continue
            command = [ffmpeg, "-hide_banner", "-stats", "-y" if overwrite else "-n", *decode, "-i", str(source)]

            if family == "archive":
                refusal = _archive_refusal(context, source, target_codec, params)
                if refusal:
                    refused += 1
                    context.log(f"[SKIP] {source_label} -> {target_codec}: {refusal}")
                    context.progress((processed + skipped + refused) / max(1, total))
                    continue
                archive_audio = "flac" if target_codec == "ffv1" and audio_mode in {"aac_320", "source"} else audio_mode
                archive_audio = _archive_audio(context, source, archive_audio)
                command.extend(["-map", "0", "-dn", *video, *_audio_args(archive_audio, audio_bitrate, _mp3_lame_preset(params)), *_encode_audio_filter_args(params, archive_audio), "-c:s", "copy", "-map_metadata", "0"])
            elif family == "editing":
                edit_audio = _container_audio_mode(extension, audio_mode)
                command.extend(["-map", "0:v:0", "-map", "0:a?", "-sn", "-dn", *_video_filters(deinterlace, _scale_filter(params)), *video, *_audio_args(edit_audio, audio_bitrate, _mp3_lame_preset(params)), *_encode_audio_filter_args(params, edit_audio), "-map_metadata", "0"])
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
                command.extend(["-sn", "-dn", *_video_filters(deinterlace, _scale_filter(params)), *video, *_audio_args(target_audio_mode, audio_bitrate, _mp3_lame_preset(params)), *_encode_audio_filter_args(params, target_audio_mode), "-map_metadata", "0"])
                if extension == "mp4":
                    command.extend(["-movflags", "+faststart"])

            command.append(str(target_path))
            context.log(f"[{processed + skipped + 1}/{total}] {source_label} -> {target_codec}")
            if dry_run:
                context.log("[DRY RUN] Command was not executed.")
                context.log(" ".join(f'"{part}"' if " " in part else part for part in command))
            else:
                _run_ffmpeg_media_process(context, command, source, check=True, progress_seconds=900, label=f"{source_label} -> {target_codec}")
            processed += 1
            context.progress((processed + skipped + refused) / max(1, total))

    # A file an archive target would not keep as it is was refused: the run says so, not green.
    return {"ok": refused == 0, "processed": processed, "skipped": skipped, "refused": refused, "files": len(files),
            "failed": camera_raw_failed, "targets": targets, "dry_run": dry_run}


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
    skipped = 0
    report_rows: list[dict[str, Any]] = []
    context.units(len(files))

    for index, source in enumerate(files, start=1):
        source_label = _source_display_name(source, source_root)
        if context.cancelled():
            context.log("Audio-in-video operation cancelled by user.")
            return {"cancelled": True, "processed": processed, "skipped": skipped}

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
        if lufs_mode == "report":
            # Every chosen track measured on its own: one number written to every row read as the loudness of each.
            for stream_row in selected_streams:
                context.log(f"[LUFS] {source_label} stream a{stream_row['audio_index']} -> {target_lufs}")
                track_stats: dict[str, Any] | None = None
                if dry_run:
                    context.log("[DRY RUN] LUFS analysis command was not executed.")
                else:
                    track_stats = _run_loudnorm_analysis(context, ffmpeg, source, _audio_stream_map_args(stream_row), target_lufs if target_lufs != "off" else "-23")
                report_rows.append(
                    {
                        "status": "DRY" if dry_run else "OK",
                        "source": source_label,
                        "stream": f"a{stream_row['audio_index']}",
                        "input": _audio_stream_summary(stream_row),
                        "output": "",
                        "mode": "in_video_lufs_report",
                        "lufs": json.dumps(track_stats, ensure_ascii=False) if track_stats else target_lufs,
                    }
                )
            processed += len(selected_streams)
            context.progress(index / len(files))
            continue
        if lufs_mode == "two_pass":
            stream_row = selected_streams[0]
            context.log(f"[LUFS] {source_label} stream a{stream_row['audio_index']} -> {target_lufs}")
            if dry_run:
                context.log("[DRY RUN] LUFS analysis command was not executed.")
            else:
                lufs_stats = _run_loudnorm_analysis(context, ffmpeg, source, _audio_stream_map_args(stream_row), target_lufs if target_lufs != "off" else "-23")
            if lufs_stats:
                lufs_filter, _unused_suffix = _audio_lufs_filter(params, lufs_stats)

        audio_args, _unused_extension, suffix = _audio_builder_args(params, lufs_filter, include_lufs=True, audio_only=False)
        extension = _audio_video_extension(params, source)
        _safe_audio_video_container(params, extension)
        target = _output_path(source, output_dir, f"video_copy_audio_{suffix}", extension, source_root=source_root, operation=operation)
        target = _claim_target(context, source, target)
        if _kept_in_place(context, target, overwrite):
            skipped += 1
            report_rows.append({"status": "SKIP", "source": source_label, "stream": "-", "input": "already in the Target, Overwrite is off", "output": str(target), "mode": "in_video", "lufs": "-"})
            context.progress(index / len(files))
            continue
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
    return {"processed": processed, "skipped": skipped, "files": len(files), "task": "audio_in_video", "dry_run": dry_run, "audio_items": report_rows, **audio_report}


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
    skipped = 0
    report_rows: list[dict[str, Any]] = []
    context.units(len(files))

    for index, source in enumerate(files, start=1):
        source_label = _source_display_name(source, source_dir)
        if context.cancelled():
            context.log("Audio operation cancelled by user.")
            return {"cancelled": True, "processed": processed, "skipped": skipped}

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
            target = _claim_target(context, source, target)
            if _kept_in_place(context, target, overwrite):
                skipped += 1
                report_rows.append({"status": "SKIP", "source": source_label, "stream": f"a{stream_row['audio_index']}", "input": "already in the Target, Overwrite is off", "output": str(target), "mode": operation_label, "lufs": "-"})
                continue
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
    return {"processed": processed, "skipped": skipped, "files": len(files), "task": operation_label, "dry_run": dry_run, "audio_items": report_rows, **audio_report}


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


def extract_subtitles(context: JobContext) -> dict[str, object]:
    """Every subtitle stream of a video, copied as it is into an MKS file of its name.

    Matroska holds every kind of subtitle a camera or a download carries - text, mov_text, pictures - so
    nothing is converted. A video with no subtitle stream is passed over and said so: the wrapper
    ff-extract-subs used to write an empty file for it.
    """
    params = dict(context.operation.parameters)
    root = context.paths.root
    source_dir = cached_source_path(root)
    output_dir = cached_output_path(root)
    files = _media_files(source_dir, VIDEO_CONTAINER_EXTENSIONS)
    if not files:
        context.log(f"No matching files in {source_dir}")
        return {"files": 0}
    ffmpeg, ffprobe = _ffmpeg(root), _ffprobe(root)
    dry_run = _as_bool(params.get("dry_run"), False)
    overwrite = _as_bool(params.get("overwrite"), False)
    processed = skipped = failed = 0
    context.units(len(files))
    for index, source in enumerate(files, start=1):
        label = _source_display_name(source, source_dir)
        if context.cancelled():
            context.log("Subtitles: cancelled by user.")
            return {"cancelled": True, "processed": processed}
        has_subtitles = _probe_first_line(context, [ffprobe, "-v", "error", "-select_streams", "s", "-show_entries", "stream=index",
                                                    "-of", "csv=p=0", str(source)])
        if not has_subtitles:
            skipped += 1
            context.log(f"[SKIP] {label}: no subtitle stream")
            context.progress(index / len(files))
            continue
        target = _output_path(source, output_dir, "", "mks", source_root=source_dir, operation=_operation_output_folder(context, "Subtitles"))
        target = _claim_target(context, source, target)
        if _kept_in_place(context, target, overwrite):
            skipped += 1
            context.progress(index / len(files))
            continue
        command = [ffmpeg, "-hide_banner", "-stats", "-y" if overwrite else "-n", "-nostdin", "-i", str(source),
                   "-map", "0:s", "-c", "copy", "-f", "matroska", str(target)]
        context.log(f"[{index}/{len(files)}] {label} -> {target.name}")
        if dry_run:
            context.log("[DRY RUN] Command was not executed.")
            context.log(" ".join(f'"{part}"' if " " in part else part for part in command))
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            result = run_process(context, command, check=False, progress_seconds=120)
            if result.exit_code != 0:
                failed += 1
                context.progress(index / len(files))
                continue
        processed += 1
        if _as_bool(params.get("limit_first_file"), False):
            break
        context.progress(index / len(files))
    return {"processed": processed, "skipped": skipped, "failed": failed, "files": len(files), "dry_run": dry_run,
            "ok": failed == 0}


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
    files, camera_raw_failed = _without_camera_raw(context, files, source_dir, "remux_media")
    if camera_raw_failed and not files:
        return {"files": 0, "failed": camera_raw_failed}
    if not files:
        context.log(f"No matching files in {source_dir}")
        return {"files": 0}

    ffmpeg = _ffmpeg(root)
    dry_run = _as_bool(params.get("dry_run"), False)
    overwrite = _as_bool(params.get("overwrite"), True)
    processed = 0
    failed = camera_raw_failed
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
    context.units(total)
    for index, (source, extension, suffix, remux_args) in enumerate(jobs, start=1):
        source_format = _remux_normalized_source_format(source)
        source_label = _source_display_name(source, source_dir)
        if context.cancelled():
            context.log("Remux cancelled by user.")
            return {"cancelled": True, "processed": processed}
        target = _output_path(source, output_dir, suffix, extension, source_root=source_dir, operation=_operation_output_folder(context, "Remux"))
        target = _claim_target(context, source, target)
        if _kept_in_place(context, target, overwrite):
            skipped += 1
            context.progress(index / total)
            continue
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
    command = [_ffprobe(context.paths.root), "-v", "error", "-select_streams", "v:0", "-show_entries",
               "stream=r_frame_rate,avg_frame_rate", "-of", "default=noprint_wrappers=1", str(source)]
    result = run_process(context, command, extra_env=_tool_env(context.paths.root), check=False, progress_seconds=30)
    fields = dict(line.strip().split("=", 1) for line in result.lines if "=" in line)
    # A conform from a rate the file does not have moves a 23.976 source by the error of its average.
    return _parse_fps(stream_rate(fields.get("r_frame_rate"), fields.get("avg_frame_rate"), variable="average"))


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
    files, camera_raw_failed = _without_camera_raw(context, files, source_dir, "fps_convert")
    if camera_raw_failed and not files:
        return {"files": 0, "failed": camera_raw_failed}
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
    skipped = 0
    context.units(len(files))
    for index, source in enumerate(files, start=1):
        source_label = _source_display_name(source, source_dir)
        if context.cancelled():
            context.log("FPS conversion cancelled by user.")
            return {"cancelled": True, "processed": processed, "skipped": skipped}

        source_fps = _video_fps(context, source)
        k = float(source_fps / target_fps)
        speed = float(target_fps / source_fps)
        has_audio = _has_audio_stream(context, source)
        audio_work_rate = _fps_audio_target_rate(_audio_sample_rate_hz(context, source), params) if has_audio else 0
        audio_output_rate = _fps_audio_output_rate(output_profile, audio_work_rate) if has_audio else 0
        suffix = f"fps_{str(source_fps).replace('/', '_')}_to_{target_label}_{mode}_{profile_label}"
        target = _output_path(source, output_dir, suffix, extension, source_root=source_dir, operation=_operation_output_folder(context, "FPS"))
        target = _claim_target(context, source, target)
        if _kept_in_place(context, target, overwrite):
            skipped += 1
            context.progress(index / len(files))
            continue

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
        if has_audio and mode == "conform" and _fps_audio_mode(mode, speed) == "varispeed":
            if abs(speed - 1.0) < 1e-9:
                context.log("Sound: the rate is the file's own - the picture is laid on its exact grid, the sound keeps its samples")
            else:
                context.log(f"Sound: the speed changes by {abs(speed - 1.0) * 100:.3g} %, within 1 % - it keeps its samples, its pitch follows")
        if dry_run:
            context.log("[DRY RUN] Command was not executed.")
            context.log(" ".join(f'"{part}"' if " " in part else part for part in command))
        else:
            _run_ffmpeg_media_process(context, command, source, check=True, progress_seconds=900, label=f"{source_label} FPS")
        processed += 1
        context.progress(index / len(files))

    return {"processed": processed, "skipped": skipped, "files": len(files), "failed": camera_raw_failed, "target": target_arg,
            "mode": mode, "dry_run": dry_run}


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
    files, camera_raw_failed = _without_camera_raw(context, files, source_dir, "run_color_grade")
    if camera_raw_failed and not files:
        return {"files": 0, "failed": camera_raw_failed}
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
    skipped = 0
    total = len(files) * len(targets)
    context.units(total)
    for source in files:
        source_label = _source_display_name(source, source_dir)
        for target_codec in targets:
            target_codec = {"hevc10": "hevc_x265", "prores422": "prores_422"}.get(target_codec, target_codec)
            if context.cancelled():
                context.log("Color operation cancelled by user.")
                return {"cancelled": True, "processed": processed, "skipped": skipped}

            video, extension, video_suffix, family = _target_video_args(target_codec, params)
            video, deinterlace, scan_tag = _scan_plan(context, source, params, video)
            if scan_tag:
                video_suffix = f"{video_suffix}_{scan_tag}"
            target_audio_mode = _container_audio_mode(extension, audio_mode)
            target_path = _output_path(source, output_dir, f"{color_suffix}_{video_suffix}", extension, source_root=source_dir, operation=_operation_output_folder(context, "Color"))
            target_path = _claim_target(context, source, target_path)
            if _kept_in_place(context, target_path, overwrite):
                skipped += 1
                context.progress((processed + skipped) / max(1, total))
                continue
            command = [ffmpeg, "-hide_banner", "-stats", "-y" if overwrite else "-n", *decode, "-i", str(source)]
            command.extend(["-map", "0:v:0"])
            if target_audio_mode != "none":
                command.extend(["-map", "0:a?"])
            command.extend(["-sn", "-dn", *_video_filters(deinterlace, filter_expr), *video, *_audio_args(target_audio_mode, audio_bitrate, _mp3_lame_preset(params)), *_encode_audio_filter_args(params, target_audio_mode), "-map_metadata", "0"])
            if extension in {"mp4", "mov"}:
                command.extend(["-movflags", "+faststart"])
            if extension == "mxf":
                command.extend(["-f", "mxf"])
            command.append(str(target_path))

            context.log(f"[{processed + skipped + 1}/{total}] {source_label} -> {color_suffix} / {target_codec}")
            if dry_run:
                context.log("[DRY RUN] Command was not executed.")
                context.log(" ".join(f'"{part}"' if " " in part else part for part in command))
            else:
                _run_ffmpeg_media_process(context, command, source, check=True, progress_seconds=900, label=f"{source_label} grade")
            processed += 1
            context.progress((processed + skipped) / max(1, total))

    return {"processed": processed, "skipped": skipped, "files": len(files), "failed": camera_raw_failed, "targets": targets,
            "dry_run": dry_run}


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
            # H.264 in MP4 is asked for where Opus is not taken (editors, upload forms): AAC with it. "codec:avc" alone
            # leaves the sound to yt-dlp's own order, which puts Opus first.
            sort_parts.append("codec:avc:m4a" if container == "mp4" else "codec:avc")
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
            # AAC as the site keeps it, when it has one: an Opus made into AAC would be a lossy copy of a lossy copy.
            args = ["-N", str(max(1, parallel)), "-f", "bestaudio[acodec^=mp4a]/bestaudio", "-x", "--audio-format", "m4a"]
        else:
            args = ["-N", str(max(1, parallel)), "-f", "bestaudio/best"]

    return args


DEFAULT_LINK_LIST = "input\\urls.txt"


DOWNLOAD_ENV = ("AUDION_DOWNLOAD", "AUDION_DOWNLOAD_DIR")


def youtube_download_dir(root: Path) -> Path:
    """Where a download goes: a result like any other, to the Target under a folder of its own - or to the folder the
    wrappers of Scripts\\ have always taken from AUDION_DOWNLOAD."""
    given = next((os.environ[name].strip().strip('"') for name in DOWNLOAD_ENV if os.environ.get(name, "").strip()), "")
    if given:
        path = Path(given)
        return path if path.is_absolute() else root / path
    return cached_output_path(root) / "Download"


def youtube_list_path(root: Path, params: dict[str, Any]) -> Path:
    """The list of links of a batch download. The default one is urls.txt of the Source, wherever the Source is."""
    given = str(params.get("batch_file", DEFAULT_LINK_LIST) or DEFAULT_LINK_LIST).strip().strip('"')
    if given.replace("/", "\\").lower() == DEFAULT_LINK_LIST:
        source = cached_source_path(root)
        return (source.parent if source.is_file() else source) / "urls.txt"
    path = Path(given)
    return path if path.is_absolute() else root / path


def _ytdlp_runtime_args(context: JobContext, root: Path) -> list[str]:
    """What every call of yt-dlp starts with. --ignore-config: the personal yt-dlp.conf of the user (%APPDATA%\\yt-dlp\\config)
    must not change a call of the program in silence - Media Downloader 5.6.6 passes it always; then the JS runtime deno,
    without which YouTube gives fewer formats."""
    told = ["--ignore-config"]
    deno = _deno(root)
    if deno:
        told.extend(["--js-runtimes", f"deno:{deno}"])
    else:
        js_override = os.environ.get("AUDION_YTDLP_JS_RUNTIMES") or os.environ.get("YTDLP_JS_RUNTIMES")
        if js_override:
            told.extend(["--js-runtimes", js_override])
        else:
            context.log("[WARN] No Deno JS runtime found. YouTube formats may be limited.")
    return told


# Browsers yt-dlp reads the cookies of at the call (--cookies-from-browser): the program keeps nothing of them.
COOKIE_BROWSERS = ("chrome", "edge", "firefox", "brave")
# The cookies file taken by the program, sealed with DPAPI for the account of Windows (core\secret_store.py).
SEALED_COOKIES = Path("config") / "cookies.dpapi"


def _cookies_file_of(root: Path, params: dict[str, Any]) -> Path | None:
    """The file of the field Cookies, from the program folder when it is named relative; None - none named."""
    named = str(params.get("cookies_path", "")).strip().strip('"')
    if not named:
        return None
    path = Path(named)
    return path if path.is_absolute() else root / path


def _ytdlp_cookies(context: JobContext, root: Path, params: dict[str, Any], opened: bool = True) -> tuple[list[str], Callable[[], None]]:
    """The cookies of a call of yt-dlp, and what is done after the call.

    The environment first, as it always was (AUDION_YTDLP_COOKIES_BROWSER, AUDION_YTDLP_COOKIES). Then the choice of the
    form, cookies_source: a browser - yt-dlp reads its profile at the call, the program keeps nothing; the file - the copy
    sealed with DPAPI (config\\cookies.dpapi), opened into a file of its own for the call and sealed again after it, with
    what yt-dlp renewed in it, the open file then gone; without that copy, the file of the field Cookies when it is there,
    as before; none - no cookies. A dry run (`opened` False) opens nothing and names the copy.
    """
    nothing: Callable[[], None] = lambda: None
    cookies_browser = os.environ.get("AUDION_YTDLP_COOKIES_BROWSER") or os.environ.get("YTDLP_COOKIES_BROWSER")
    cookies_env = os.environ.get("AUDION_YTDLP_COOKIES") or os.environ.get("YTDLP_COOKIES") or os.environ.get("COOKIES")
    if cookies_browser:
        return ["--cookies-from-browser", cookies_browser], nothing
    if cookies_env:
        return ["--cookies", cookies_env], nothing
    source = str(params.get("cookies_source", "file") or "file").strip().lower()
    if source in COOKIE_BROWSERS:
        return ["--cookies-from-browser", source], nothing
    if source == "none":
        return [], nothing
    sealed = root / SEALED_COOKIES
    if sealed.is_file():
        if not opened:
            return ["--cookies", f"<{SEALED_COOKIES}, opened for the call>"], nothing
        from system_core.core.secret_store import open_sealed, seal

        plain = open_sealed(sealed.read_bytes())
        handle, name = tempfile.mkstemp(prefix="audion-cookies-", suffix=".txt")
        with os.fdopen(handle, "wb") as file:
            file.write(plain)
        context.log(f"[COOKIES] The copy sealed with DPAPI: {SEALED_COOKIES}")

        def done() -> None:
            opened_file = Path(name)
            try:
                renewed = opened_file.read_bytes()
                if renewed and renewed != plain:
                    sealed.write_bytes(seal(renewed))
            except OSError:
                pass
            finally:
                opened_file.unlink(missing_ok=True)

        return ["--cookies", name], done
    candidate = _cookies_file_of(root, params)
    if candidate is not None and candidate.exists():
        return ["--cookies", str(candidate)], nothing
    return [], nothing


def seal_cookies_file(root: Path, path: Path) -> int:
    """A cookies file of a browser (Netscape format) sealed with DPAPI into config\\cookies.dpapi; the number of its
    cookies. Nothing of what it holds is written anywhere else, nor said."""
    from system_core.core.secret_store import seal

    if not path.is_file():
        raise RuntimeError(f"There is no cookies file at {path}: export the cookies of the site from the browser "
                           "(Netscape format, cookies.txt) and name the file in the field Cookies.")
    data = path.read_bytes()
    lines = data.decode("utf-8", errors="replace").splitlines()
    # A line of a cookie: seven fields parted by tabs; "#HttpOnly_" opens one too, any other "#" a comment.
    entries = [line for line in lines if line.strip() and (not line.startswith("#") or line.startswith("#HttpOnly_"))]
    cookies = [line for line in entries if len(line.split("\t")) >= 7]
    headed = any(line.lstrip().startswith(("# Netscape HTTP Cookie File", "# HTTP Cookie File")) for line in lines[:5])
    if not cookies or (not headed and len(cookies) != len(entries)):
        raise RuntimeError(f"{path.name} is not a cookies file of the Netscape format: a line of a cookie has seven fields "
                           "parted by tabs.")
    sealed = root / SEALED_COOKIES
    sealed.parent.mkdir(parents=True, exist_ok=True)
    sealed.write_bytes(seal(data))
    return len(cookies)


def import_youtube_cookies(context: JobContext) -> dict[str, object]:
    """The cookies file of the field Cookies sealed with DPAPI for this account of Windows (seal_cookies_file): downloads
    with Cookies - File take this copy, and the open file is no longer needed. The window runs it beside the field."""
    params = dict(context.operation.parameters)
    root = context.paths.root
    path = _cookies_file_of(root, params)
    if path is None:
        raise RuntimeError("The field Cookies names no file.")
    if _as_bool(params.get("youtube_dry_run"), False):
        context.log(f"[DRY RUN] Nothing sealed: {path} would be sealed with DPAPI into {SEALED_COOKIES}.")
        context.progress(1.0)
        return {"dry_run": True}
    count = seal_cookies_file(root, path)
    context.log(f"[OK] {count} cookies sealed with DPAPI for this account of Windows: {SEALED_COOKIES}")
    context.log(f"[NOTE] The open file is still at {path}; downloads take the sealed copy now.")
    context.progress(1.0)
    return {"cookies": count}


def list_youtube_formats(context: JobContext) -> dict[str, object]:
    """The formats a link offers - resolution, codecs, size, the id each is taken by - as yt-dlp lists them (-F), into the
    journal; nothing is downloaded. Of a link to a video in a playlist, the video alone. The window runs it beside the URL
    of a download page with the values of that page (config\\window_layout.yaml, buttons)."""
    params = dict(context.operation.parameters)
    root = context.paths.root
    url = str(params.get("youtube_url", "")).strip()
    if not url:
        raise RuntimeError("YouTube URL is empty.")
    command = [_yt_dlp(root), *_ytdlp_runtime_args(context, root), "--no-playlist"]
    client = str(params.get("youtube_client", "default")).strip()
    if client == "safari":
        command.extend(["--extractor-args", "youtube:player-client=web_safari,default"])
    elif client == "android":
        command.extend(["--extractor-args", "youtube:player-client=android,web"])
    dry_run = _as_bool(params.get("youtube_dry_run"), False)
    cookie_args, cookies_done = _ytdlp_cookies(context, root, params, opened=not dry_run)
    command.extend([*cookie_args, "-F", url])
    if dry_run:
        context.log("[DRY RUN] yt-dlp command was not executed.")
        context.log(" ".join(f'"{part}"' if " " in part else part for part in command))
        context.progress(1.0)
        return {"dry_run": True}
    try:
        result = run_process(context, command, extra_env=_tool_env(root), check=True, progress_seconds=120)
    finally:
        cookies_done()
    context.progress(1.0)
    return {"lines": len(result.lines)}


def download_youtube(context: JobContext) -> dict[str, object]:
    params = dict(context.operation.parameters)
    root = context.paths.root
    download_dir = youtube_download_dir(root)
    download_dir.mkdir(parents=True, exist_ok=True)

    profile = str(params.get("youtube_profile", "best_mp4")).strip() or "best_mp4"
    parallel = _as_int(params.get("parallel_fragments"), 8)
    source_mode = str(params.get("youtube_source_mode", "single")).strip()
    options = _as_list(params.get("youtube_options"))
    subtitles = _as_list(params.get("subtitle_options"))
    client = str(params.get("youtube_client", "default")).strip()
    dry_run = _as_bool(params.get("youtube_dry_run"), False)

    command = [_yt_dlp(root), *_ytdlp_runtime_args(context, root)]
    playlist = source_mode == "playlist"
    # A playlist is kept whole and in its order: every file numbered, a video that fails passed over.
    template = ("%(playlist_index)03d - %(title).200B [%(id)s].%(ext)s" if playlist
                else "%(uploader)s/%(upload_date>%Y-%m-%d)s - %(title).180B [%(id)s].%(ext)s")
    command.extend(["-P", str(download_dir), "-o", template, *_youtube_format_args(params, profile, parallel)])
    if playlist:
        command.extend(["--ignore-errors", "--continue"])
        # Which videos of the playlist, by their numbers in it: 1-10,15 or -5: for the last five.
        items = str(params.get("youtube_playlist_items", "") or "").strip()
        if items:
            command.extend(["--playlist-items", items])
    sections = str(params.get("youtube_sections", "") or "").strip()
    if sections:
        # A part of the video only: *00:01:00-00:02:00, as yt-dlp writes it.
        command.extend(["--download-sections", sections])

    ffmpeg_bin = root / "Tools" / "ffmpeg" / "bin"
    if ffmpeg_bin.exists():
        command.extend(["--ffmpeg-location", str(ffmpeg_bin)])

    if "safe_retries" in options and profile != "safe_mp4":
        command.extend(["--retries", "10", "--fragment-retries", "10", "--retry-sleep", "2"])
    if "force_ipv4" in options and "--force-ipv4" not in command:
        command.append("--force-ipv4")
    if "embed_metadata" in options and profile != "subs_only":
        command.extend(["--embed-metadata", "--embed-thumbnail"])
    # One link is one video: a link to a video in a playlist (watch?v=...&list=...) must not bring the playlist along -
    # Media Downloader 5.6.6 passes --no-playlist unless asked otherwise. The tick is for the links of input\urls.txt.
    if source_mode == "single" or ("no_playlist" in options and not playlist):
        command.append("--no-playlist")

    if client == "safari" or profile == "safe_mp4":
        command.extend(["--extractor-args", "youtube:player-client=web_safari,default"])
    elif client == "android":
        command.extend(["--extractor-args", "youtube:player-client=android,web"])

    # SUBTITLES writes them by itself; a tick of the same asks once.
    if "write_subs" in subtitles and "--write-subs" not in command:
        command.append("--write-subs")
    if "write_auto_subs" in subtitles and "--write-auto-subs" not in command:
        command.append("--write-auto-subs")
    if "embed_subs" in subtitles and profile != "subs_only":
        command.append("--embed-subs")
    sub_langs = str(params.get("subtitle_languages", "")).strip()
    if sub_langs:
        command.extend(["--sub-langs", sub_langs])

    if _as_bool(params.get("download_archive"), False):
        # The list of what was downloaded is the program's state, not a result: clearing the Target keeps it.
        command.extend(["--download-archive", str(root / "config" / "download-archive.txt")])

    # The cookies stand here; a sealed copy is opened only when the call is near (below).
    cookies_at = len(command)

    sponsorblock = os.environ.get("AUDION_YTDLP_SPONSORBLOCK") or os.environ.get("YTDLP_SPONSORBLOCK")
    if sponsorblock and profile not in {"audio_m4a", "audio_opus", "audio_mp3", "audio_custom", "subs_only"}:
        command.extend(["--sponsorblock-remove", sponsorblock])

    if source_mode == "batch":
        batch_path = youtube_list_path(root, params)
        if not batch_path.exists():
            raise RuntimeError(f"Batch file was not found: {batch_path}")
        command.extend(["--batch-file", str(batch_path)])
    else:
        url = str(params.get("youtube_url", "")).strip()
        if not url:
            raise RuntimeError("YouTube URL is empty.")
        command.append(url)

    cookie_args, cookies_done = _ytdlp_cookies(context, root, params, opened=not dry_run)
    command[cookies_at:cookies_at] = cookie_args
    if dry_run:
        context.log("[DRY RUN] yt-dlp command was not executed.")
        context.log(" ".join(f'"{part}"' if " " in part else part for part in command))
        context.progress(1.0)
        return {"dry_run": True, "profile": profile}

    started = time.time()
    try:
        result = run_process(context, command, extra_env=_tool_env(root), check=True, progress_seconds=1800)
    finally:
        cookies_done()
    context.progress(1.0)
    # yt-dlp says which files it found already there; a file of this run came into being after the run began.
    existing = sorted({match.group(1).strip() for line in result.lines for match in [DOWNLOAD_ALREADY.search(line)] if match})
    known = {os.path.normcase(os.path.abspath(path)) for path in existing}
    downloaded = [path for path in _files_born_since(download_dir, started)
                  if os.path.normcase(os.path.abspath(str(path))) not in known]
    for path in downloaded:
        context.log(f"[OK] {path}")
    return {"profile": profile, "lines": len(result.lines), "download_dir": str(download_dir), "processed": len(downloaded),
            "downloaded": [str(path) for path in downloaded], "existing": existing}


# What yt-dlp leaves while it works and takes away when a file is whole.
DOWNLOAD_LEFTOVERS = {".part", ".ytdl", ".tmp", ".temp"}
# What yt-dlp says of a file that is there already: "[download] PATH has already been downloaded".
DOWNLOAD_ALREADY = re.compile(r"^\[download\] (.+?) has already been downloaded")


def _files_born_since(folder: Path, started: float) -> list[Path]:
    """The files of a folder, its subfolders too, that came into being since `started` (seconds of the epoch): what a
    download wrote. By the time of birth, not of change - yt-dlp may set a file's time of change to its upload date. No
    slack: a file of the run before, born a moment earlier, is not this run's."""
    if not folder.is_dir():
        return []
    born: list[Path] = []
    for path in folder.rglob("*"):
        if not path.is_file() or path.suffix.lower() in DOWNLOAD_LEFTOVERS:
            continue
        stat = path.stat()
        if getattr(stat, "st_birthtime", stat.st_ctime) >= started:
            born.append(path)
    return sorted(born)


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
    context.log("Cleaning the selected output folder. The input is preserved.")
    result = _clear_folder(context, output, "output", allow_external=True)
    context.progress(1.0)
    return result


def cleanup_source(context: JobContext) -> dict[str, object]:
    source = cached_source_path(context.paths.root)
    context.log("Cleaning the selected input folder. The output is preserved.")
    target, external = _assert_clear_target(context, source, "input", allow_external=True)
    if target.is_file():
        if external:
            context.log(f"[WARNING] Deleting an external input file: {target}")
        target.unlink()
        context.log(f"Removed the input file: {target.name}")
        result = {"folder": "input", "path": str(target), "external": external, "removed_items": 1, "kind": "file"}
    else:
        result = _clear_folder(context, source, "input", allow_external=True)
    context.progress(1.0)
    return result


def cleanup_workspace(context: JobContext) -> dict[str, object]:
    context.log("Cleaning managed GUI workspace folders. The input and the output are preserved.")
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


def _take_in(source: Path, name: str) -> Path | None:
    """The take a name chooses in a Source: the Source itself when it is one file - named by its own name, or not named;
    a file of the Source folder by its name there. None - no such take. The cut, the player, the details and the length
    of a take all ask this one, so a Source of one file is a Source like any other."""
    chosen = str(name or "").strip()
    if source.is_file():
        return source if not chosen or Path(chosen).name.lower() == source.name.lower() else None
    if not chosen:
        return None
    candidate = source / chosen
    return candidate if candidate.is_file() else None


def trim_source_path(name: str, root: Path | str | None = None) -> Path | None:
    """The staged file behind a chosen name, or nothing if it is not there.

    The panel needs this to hand a file to the player, and the knowledge of
    where Source lives belongs here rather than in the interface.
    """
    chosen = str(name or "").strip()
    if not chosen:
        return None
    project_root = Path(root).resolve() if root else Path(__file__).resolve().parents[2]
    return _take_in(cached_source_path(project_root), chosen)


_TRIM_LENGTHS: dict[tuple[str, int, int], float] = {}


def trim_file_seconds(name: str, root: Path | str | None = None) -> float | None:
    """How long a staged take plays - for the piece lengths the panel shows.

    Only needed when a row has one point: IN alone runs to the end of the file.
    Asked of ffprobe once per version of the file, since the panel redraws on
    every click.
    """
    source = trim_source_path(name, root)
    if source is None:
        return None
    try:
        stat = source.stat()
    except OSError:
        return None
    key = (str(source), stat.st_size, stat.st_mtime_ns)
    if key not in _TRIM_LENGTHS:
        project_root = Path(root).resolve() if root else Path(__file__).resolve().parents[2]
        try:
            data = _probe_media_json(project_root, source)
            fmt = data.get("format") if isinstance(data.get("format"), dict) else {}
            _TRIM_LENGTHS[key] = float(fmt.get("duration") or 0.0)
        except (OSError, RuntimeError, ValueError):
            _TRIM_LENGTHS[key] = 0.0
    return _TRIM_LENGTHS[key] or None


def trim_file_frame_seconds(name: str, root: Path | str | None = None) -> float | None:
    """One frame of a staged take: the step of the smallest section of a point.

    A millisecond changes nothing in a cut on 25p, a frame does. The rate is the
    one the cut itself uses - nominal on a variable-rate source. None for a
    sound file, which has no frame and steps by the millisecond instead.
    """
    source = trim_source_path(name, root)
    if source is None or trim_media_kind(source.name) == "audio":
        return None
    project_root = Path(root).resolve() if root else Path(__file__).resolve().parents[2]
    try:
        facts = _trim_stream_facts(project_root, source)
        variable_rate = is_variable_rate(facts.get("r_frame_rate"), facts.get("avg_frame_rate"))
        rate = parse_rate(stream_rate(facts.get("r_frame_rate"), facts.get("avg_frame_rate")) or "")
    except (OSError, RuntimeError, ValueError, KeyError):
        return None
    return float(1 / rate) if rate > 0 else None


def trim_source_file_names(root: Path | str | None = None) -> list[str]:
    """Video and sound files staged in Source, in alphabetical order, as plain names."""
    project_root = Path(root).resolve() if root else Path(__file__).resolve().parents[2]
    source_dir = cached_source_path(project_root)
    if not source_dir.exists():
        return []
    staged = _media_files(source_dir, TRIM_VIDEO_EXTENSIONS | PURE_AUDIO_EXTENSIONS)
    return [_source_display_name(path, source_dir) for path in staged]


def trim_media_kind(name: str) -> str:
    """"audio" for a file of sound alone, "video" for everything else.

    Told by the extension, because the panel asks on every step through the
    folder; the run then looks at the streams before it cuts anything.
    """
    suffix = Path(str(name or "")).suffix.lower().lstrip(".")
    return "audio" if suffix in PURE_AUDIO_EXTENSIONS else "video"


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


def _trim_split_points(params: dict[str, Any], *, duration: float | None = None) -> list[Any]:
    """The points a split cuts at: the panel's list, or IN and OUT from a wrapper."""
    if str(params.get("trim_split_mode") or "points") == "duration":
        return split_interval_points(params.get("trim_split_duration", "89"), float(duration or 0))
    points = params.get("trim_points")
    if isinstance(points, (list, tuple)):
        given = [item for item in points if str(item if item is not None else "").strip()]
        if given:
            return given
    return [params.get("trim_start"), params.get("trim_end")]


def _trim_part_suffix(index: int, total: int) -> str:
    """Pad to the total's width, so Explorer keeps any number of parts in order."""
    width = len(str(total))
    return f"part{index:0{width}d}"


def _trim_variants(params: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    """Every filled row of the panel as a run of its own, with the suffix it is named by.

    The rows are not pieces of one timeline. Each is a separate answer to the
    same question - which piece to keep, or which to cut out - so each writes
    its own file, and two rows may overlap as freely as two separate runs could.
    Row 1 is IN and OUT; the rows after it arrive in `trim_rows`. One filled row
    is today's run exactly, with no suffix.
    """
    rows: list[tuple[int, Any, Any]] = [(1, params.get("trim_start"), params.get("trim_end"))]
    extra = params.get("trim_rows")
    if isinstance(extra, (list, tuple)):
        for number, row in enumerate(extra, start=2):
            if isinstance(row, dict):
                rows.append((number, row.get("start"), row.get("end")))

    def given(value: Any) -> bool:
        return str(value if value is not None else "").strip() != ""

    filled = [row for row in rows if given(row[1]) or given(row[2])]
    if len(filled) <= 1:
        if not filled:
            return [("", params)]
        _number, start, end = filled[0]
        return [("", {**params, "trim_start": start or "", "trim_end": end or ""})]
    if len(filled) > TRIM_MAX_VARIANTS:
        raise RuntimeError(f"{len(filled)} rows are filled, and one run takes at most {TRIM_MAX_VARIANTS}.")
    word = "cut" if _trim_pattern(params) == "middle" else "keep"
    return [
        (f"{word}{number:02d}", {**params, "trim_start": start or "", "trim_end": end or ""})
        for number, start, end in filled
    ]


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


def _discard_unusable_trim(context: JobContext, target: Path, *, sound: bool = False) -> None:
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

    # A sound piece has no picture to measure; its own stream says whether it opens.
    root = context.paths.root
    duration = _audio_stream_duration(root, target) if sound else _video_stream_duration(root, target)
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


def _trim_split_plans(
    context: JobContext,
    source: Path,
    params: dict[str, Any],
    *,
    source_dir: Path,
    output_dir: Path,
) -> list[dict[str, Any]]:
    """A split at N points gives N + 1 parts.

    The joints come from `plan_split`, which snaps each point to its nearest
    keyframe and makes that keyframe the end of one part and the start of the
    next - so the parts add back up to the file, frame for frame.
    """
    root = context.paths.root
    facts = _trim_stream_facts(root, source)
    duration = facts["duration"]
    if duration <= 0:
        raise RuntimeError("duration could not be read")
    variable_rate = is_variable_rate(facts.get("r_frame_rate"), facts.get("avg_frame_rate"))
    rate = parse_rate(stream_rate(facts.get("r_frame_rate"), facts.get("avg_frame_rate")) or "")
    origin = float(facts.get("origin") or 0.0)

    interval = params.get("trim_split_duration", "89") if params.get("trim_split_mode") == "duration" else None
    points = _trim_split_points(params, duration=duration)
    asked: list[float] = []
    for point in points:
        if str(point if point is not None else "").strip():
            try:
                asked.append(parse_seconds(point))
            except ValueError as exc:
                raise RuntimeError(str(exc)) from exc
    keyframes = sorted({item - origin for point in asked for item in _trim_keyframes(root, source, point + origin)})
    try:
        split = plan_split(
            points=points,
            duration=duration,
            rate=rate,
            keyframes=keyframes,
            frame_exact=not variable_rate,
            split_interval=interval,
        )
    except ValueError as exc:
        raise RuntimeError(str(exc)) from exc

    label = _source_display_name(source, source_dir)
    context.log(f"Split {label} into {len(split.parts)} parts:")
    if interval is not None:
        context.log(f"    equal part length: {format_seconds(parse_split_interval(interval))}; the last part is the remainder")
    for point, boundary, offset in zip(split.requested, split.boundaries, split.offsets):
        if abs(offset) < 1e-6:
            context.log(f"    point {format_seconds(point)} is a keyframe")
        else:
            context.log(f"    point {format_seconds(point)} -> keyframe {format_seconds(boundary)} ({format_offset(offset)})")

    plans: list[dict[str, Any]] = []
    for part in split.parts:
        last = part.end is None
        cut = TrimCut(
            requested_start=part.start,
            requested_end=float(duration) if last else float(part.end),
            start=part.start,
            keyframe_offset=0.0,
            frames=part.frames,
            tail_seconds=None if (last or part.frames is not None) else part.seconds,
            kept=part.seconds,
            to_end_of_file=last,
        )
        # Sample-exact sound for every part: neighbouring parts meet at the same
        # joint for sound as for picture, or the sound doubles or drops there.
        part_params = {**params, "trim_pattern": "both", "trim_sample_exact": True}
        plans.append(
            _trim_plan(
                context,
                source,
                part_params,
                source_dir=source_dir,
                output_dir=output_dir,
                name_suffix=_trim_part_suffix(part.index, len(split.parts)),
                forced_cut=cut,
            )
        )
    return plans


def _trim_plan(
    context: JobContext,
    source: Path,
    params: dict[str, Any],
    *,
    source_dir: Path,
    output_dir: Path,
    name_suffix: str = "",
    forced_cut: TrimCut | None = None,
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
    rate_source = stream_rate(facts.get("r_frame_rate"), facts.get("avg_frame_rate"))
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
    if forced_cut is not None:
        # A part of a split: its joint with the neighbouring parts was decided
        # once, for all of them, so the start and the length arrive as given.
        cut = forced_cut
    else:
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
    subtitle_inputs: list[tuple[str, str, str]] = []
    if keep_subtitles and not params.get("_subtitles_at_join"):
        # The lines of the piece as it really runs: from the keyframe the
        # picture starts on, for exactly as long as it is kept.
        subtitle_inputs = _trim_subtitle_inputs(
            context,
            source,
            data.get("streams") or [],
            container,
            [(cut.start, cut.start + cut.kept, 0.0)],
            name=target.stem,
            origin=origin,
            warnings=warnings,
        )
    command = build_trim_command(
        ffmpeg=_ffmpeg(root),
        source=str(source),
        target=str(target),
        overwrite=_as_bool(params.get("overwrite"), True),
        # The keyframe as the video stream of the file counts it: its timestamp, the start of the file included.
        start_seconds=start + origin,
        seek_timestamp=True,
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
        subtitle_inputs=subtitle_inputs,
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
        "keep_subtitles": bool(subtitle_inputs),
        # Whether the operator's subtitles could travel at all - a piece headed
        # for a join leaves them to the join, which rebuilds them for the result.
        "subtitles_wanted": keep_subtitles,
        "temp_files": [Path(path) for path, _encoder, _language in subtitle_inputs],
        "warnings": warnings,
    }


_TRIM_CUES: dict[tuple[str, int, int, int], list[SubtitleCue]] = {}


def _trim_source_cues(root: Path, source: Path, position: int, origin: float) -> list[SubtitleCue]:
    """Every line of one subtitle stream, on the operator's timeline.

    Read once per version of the file: the lines of every variant, part and
    join of the same take come from the same reading.
    """
    stat = source.stat()
    key = (str(source), stat.st_size, stat.st_mtime_ns, int(position))
    if key not in _TRIM_CUES:
        completed = subprocess.run(
            subtitle_extract_command(_ffmpeg(root), str(source), position),
            cwd=str(root),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=utf8_subprocess_env(_tool_env(root)),
            **hidden_subprocess_kwargs(),
        )
        if completed.returncode != 0:
            detail = completed.stderr.decode("utf-8", errors="replace").strip().splitlines()
            raise RuntimeError(detail[-1] if detail else f"ffmpeg exited {completed.returncode}")
        cues = parse_srt(completed.stdout.decode("utf-8", errors="replace"))
        if len(_TRIM_CUES) >= 64:
            _TRIM_CUES.clear()
        _TRIM_CUES[key] = [SubtitleCue(cue.start - origin, cue.end - origin, cue.text) for cue in cues]
    return list(_TRIM_CUES[key])


def _trim_subtitle_inputs(
    context: JobContext,
    source: Path,
    streams: list[dict[str, Any]],
    container: str,
    spans: list[tuple[float, float, float]],
    *,
    name: str,
    origin: float,
    warnings: list[str],
) -> list[tuple[str, str, str]]:
    """The rebuilt lines of every text subtitle stream, one SRT each, for this result.

    A stream with no line inside the kept spans adds no track; one that cannot
    be read stays behind with the reason in the log rather than stopping the cut.
    """
    root = context.paths.root
    plan, _notes = subtitle_stream_plan(streams, container)
    subtitles = [item for item in streams if isinstance(item, dict) and str(item.get("codec_type") or "").lower() == "subtitle"]
    stage = context.paths.workspace / "trim_subtitles"
    inputs: list[tuple[str, str, str]] = []
    for position, encoder in plan:
        try:
            cues = _trim_source_cues(root, source, position, origin)
        except (OSError, RuntimeError) as exc:
            warnings.append(f"Subtitle stream {position + 1} could not be read, so it stays behind: {exc}")
            continue
        kept = cues_for_spans(cues, spans)
        if not kept:
            continue
        stage.mkdir(parents=True, exist_ok=True)
        path = stage / f"{name}_s{position}.srt"
        path.write_text(format_srt(kept), encoding="utf-8")
        tags = subtitles[position].get("tags") if position < len(subtitles) else None
        language = str((tags or {}).get("language") or "").strip()
        inputs.append((str(path), encoder, "" if language == "und" else language))
    return inputs


def _trim_gap_plan(
    context: JobContext,
    source: Path,
    params: dict[str, Any],
    *,
    source_dir: Path,
    output_dir: Path,
    name_suffix: str = "",
) -> dict[str, Any]:
    """One file with a piece taken out of its middle: two cuts and a join."""
    root = context.paths.root
    facts = _trim_stream_facts(root, source)
    duration = facts["duration"]
    if duration <= 0:
        raise RuntimeError("duration could not be read")
    variable_rate = is_variable_rate(facts.get("r_frame_rate"), facts.get("avg_frame_rate"))
    rate_source = stream_rate(facts.get("r_frame_rate"), facts.get("avg_frame_rate"))
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
    # straight on the join. Their subtitles are left to the join, which lays
    # the lines of both spans onto the result's timeline in one go.
    shared = {**params, "trim_sample_exact": True, "_subtitles_at_join": True}
    head_params = {**shared, "trim_pattern": "end", "trim_end": format_seconds(gap.requested_start), "trim_start": ""}
    tail_params = {**shared, "trim_pattern": "start", "trim_start": format_seconds(gap.tail_start), "trim_end": ""}
    # A variant's pieces carry its suffix too, so no two variants share a piece on disk.
    piece = f"{name_suffix}_gap" if name_suffix else "gap"
    head = _trim_plan(context, source, head_params, source_dir=source_dir, output_dir=stage, name_suffix=f"{piece}_head")
    tail = _trim_plan(context, source, tail_params, source_dir=source_dir, output_dir=stage, name_suffix=f"{piece}_tail")

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
        label = f"{label} [{name_suffix}]"
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
    if head.get("keep_data"):
        # Subtitles go through the join; a data stream has not been measured
        # there, so it is said out loud rather than dropped without a word.
        warnings.append(
            "Cutting a piece out joins picture, sound and subtitles; the data stream (telemetry) does not pass the "
            "join and stays behind. Keep it or Split carries it over."
        )
    subtitle_inputs: list[tuple[str, str, str]] = []
    if head.get("subtitles_wanted"):
        # The head as it runs, then the tail from its keyframe, laid on where the head ends.
        subtitle_inputs = _trim_subtitle_inputs(
            context,
            source,
            _probe_media_json(root, source).get("streams") or [],
            container,
            [(0.0, gap.head_seconds, 0.0), (gap.tail_start, float(duration), gap.head_seconds)],
            name=f"{target.stem}_join",
            origin=origin,
            warnings=warnings,
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
        "keep_subtitles": bool(subtitle_inputs),
        "temp_files": [Path(path) for path, _encoder, _language in subtitle_inputs],
        "command": _concat_command(
            root, list_file, target, container, params, head["timecode"], subtitle_inputs=subtitle_inputs
        ),
    }


def _concat_command(
    root: Path,
    list_file: Path,
    target: Path,
    container: str,
    params: dict[str, Any],
    timecode: str = "",
    *,
    subtitle_inputs: list[tuple[str, str, str]] | None = None,
) -> list[str]:
    """Glue the two pieces by copying packets - no decoding, no re-encoding.

    The subtitles come in beside the pieces, already laid onto the result's
    timeline. Carrying the pieces' own subtitle packets through the concat was
    measured wrong: a line of 0.5-1.5 s came out a microsecond long and the next
    one a second early.
    """
    inputs = list(subtitle_inputs or [])
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
        *[part for path, _encoder, _language in inputs for part in ("-i", str(path))],
        # Picture and sound by name, the way every other cut here maps them.
        # `-map 0` would also pick up the timecode track, which MOV refuses to
        # take from a concat input - the run fails with "unsupported type" and
        # nothing is written. The timecode is written below as a value instead.
        "-map",
        "0:v:0",
        "-map",
        "0:a?",
        *(subtitle_input_maps(inputs, first_input=1) if inputs else ["-sn"]),
        "-dn",
        "-c",
        "copy",
        *subtitle_input_codecs(inputs),
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
    if plan.get("keep_subtitles"):
        context.log("    carried over: subtitles, laid onto the join")
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
    # The piece of the first pass is this run's own: the retry writes over it, Overwrite or not.
    command = ["-y" if part == "-n" else part for part in plan["command"]]
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


def _sound_number(value: Any) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    return number if number > 0 else 0.0


def _trim_sound_probe(root: Path, source: Path) -> dict[str, Any]:
    """What a sound cut needs from ffprobe: the streams, cover pictures, and the tags."""
    command = [
        _ffprobe(root),
        "-v",
        "error",
        "-show_entries",
        "format=duration,bit_rate:format_tags:stream=index,codec_type,codec_name,sample_fmt,sample_rate,channels,"
        "bits_per_raw_sample,bit_rate,duration,duration_ts,time_base,start_time:stream_disposition=attached_pic",
        "-of",
        "json",
        str(source),
    ]
    return _capture_probe_json(root, command)


def _trim_sound_packet_starts(root: Path, source: Path, *, rate: int, origin: float) -> list[int]:
    """Where each packet's sound begins in the decoded source, in samples."""
    result = _capture_tool(
        root,
        [
            _ffprobe(root),
            "-v",
            "error",
            "-select_streams",
            "a:0",
            "-show_entries",
            "packet=pts_time",
            "-of",
            "csv=p=0",
            str(source),
        ],
    )
    starts: list[int] = []
    for line in (result.stdout or "").splitlines():
        try:
            starts.append(round((float(line.strip().rstrip(",")) - origin) * rate))
        except ValueError:
            continue
    return starts


def _riff_chunk_ids(path: Path) -> list[str]:
    """The chunk names of a RIFF or RF64 WAV, read from the bytes; empty for anything else."""
    try:
        with path.open("rb") as handle:
            head = handle.read(12)
            if len(head) < 12 or head[:4] not in {b"RIFF", b"RF64", b"BW64"} or head[8:12] != b"WAVE":
                return []
            names: list[str] = []
            data_size: int | None = None
            while len(names) < 512:
                header = handle.read(8)
                if len(header) < 8:
                    break
                name, size = header[:4], int.from_bytes(header[4:8], "little")
                if name == b"ds64" and size >= 16:
                    body = handle.read(size + (size & 1))
                    data_size = int.from_bytes(body[8:16], "little")
                    names.append("ds64")
                    continue
                if name == b"data" and size == 0xFFFFFFFF and data_size is not None:
                    size = data_size
                names.append(name.decode("latin-1"))
                handle.seek(size + (size & 1), 1)
            return names
    except OSError:
        return []


def _trim_audio_plans(
    context: JobContext,
    source: Path,
    params: dict[str, Any],
    *,
    source_dir: Path,
    output_dir: Path,
    name_suffix: str = "",
) -> list[dict[str, Any]]:
    """A file of sound alone, cut on the sample - or, with Exact cut off, on packets."""
    root = context.paths.root
    data = _trim_sound_probe(root, source)
    streams = [item for item in (data.get("streams") or []) if isinstance(item, dict)]
    sounds = [item for item in streams if item.get("codec_type") == "audio"]
    if not sounds:
        raise RuntimeError("no audio stream")
    pictures = [item for item in streams if item.get("codec_type") == "video"]
    covers = [item for item in pictures if (item.get("disposition") or {}).get("attached_pic")]
    if len(covers) != len(pictures):
        raise RuntimeError("the file carries moving pictures as well as sound, so it is not cut as a sound file")
    stream = sounds[0]
    fmt = data.get("format") if isinstance(data.get("format"), dict) else {}
    tags = fmt.get("tags") if isinstance(fmt.get("tags"), dict) else {}
    codec = str(stream.get("codec_name") or "").strip().lower()
    rate = int(_sound_number(stream.get("sample_rate")))
    duration = _sound_number(stream.get("duration")) or _sound_number(fmt.get("duration"))
    stated = str(stream.get("duration_ts") or "")
    # The count a lossless file states is exact - measured on WAV, FLAC, ALAC,
    # WavPack and TTA. A compressed header is not: an AAC file decoded 768
    # samples past its stated duration, and an Opus header counts its pre-skip.
    lossless = audio_codec_is_lossless(codec)
    total = int(stated) if lossless and stated.isdigit() and str(stream.get("time_base") or "") == f"1/{rate}" else None
    arguments = {
        "pattern": _trim_pattern(params),
        "start": params.get("trim_start"),
        "end": params.get("trim_end"),
        "duration": duration,
        "sample_rate": rate,
        "points": params.get("trim_points") if params.get("trim_split_mode") == "duration" else _trim_split_points(params),
        "split_interval": params.get("trim_split_duration", "89") if params.get("trim_split_mode") == "duration" else None,
    }
    try:
        trim = plan_audio_trim(**arguments, total_samples=total)
        if total is None and any(piece.end is None for piece in trim.pieces):
            # A piece runs to the end: count that end the way a decoder gives it,
            # or the plan promises a length the file never had.
            trim = plan_audio_trim(**arguments, total_samples=_decoded_sample_count(root, source))
    except ValueError as exc:
        raise RuntimeError(str(exc)) from exc

    chunks = _riff_chunk_ids(source)
    warnings: list[str] = []
    if len(sounds) > 1:
        warnings.append(f"Only the first of {len(sounds)} audio tracks is cut.")
    if "iXML" in chunks:
        warnings.append(
            "The recorder's iXML chunk - track names, scene and take - stays behind: FFmpeg can neither read nor "
            "write it. The bext chunk and its time reference do travel."
        )
    label = _source_display_name(source, source_dir)
    facts = {
        "label": f"{label} [{name_suffix}]" if name_suffix else label,
        "suffix": name_suffix,
        "stream": stream,
        "format": fmt,
        "tags": tags,
        "codec": codec,
        "rate": rate,
        "channels": int(_sound_number(stream.get("channels"))),
        "duration": duration,
        "covers": covers,
        "broadcast_wav": "bext" in chunks or any(str(key).lower() == "time_reference" for key in tags),
        "warnings": warnings,
    }
    # Lossless unless asked otherwise, as the form: a compressed sound cut exactly is encoded once more.
    exact = _as_bool(params.get("trim_exact"), False)
    if exact or audio_codec_is_lossless(codec):
        return _trim_sound_exact_plans(context, source, params, trim, facts, exact=exact, source_dir=source_dir, output_dir=output_dir)
    return _trim_sound_packet_plans(context, source, params, trim, facts, source_dir=source_dir, output_dir=output_dir)


def _trim_sound_exact_plans(
    context: JobContext,
    source: Path,
    params: dict[str, Any],
    trim: Any,
    facts: dict[str, Any],
    *,
    exact: bool,
    source_dir: Path,
    output_dir: Path,
) -> list[dict[str, Any]]:
    """Decoded, cut on the sample, written as the source was or in the chosen format."""
    root = context.paths.root
    stream, fmt = facts["stream"], facts["format"]
    codec, rate = facts["codec"], facts["rate"]
    try:
        encoding = audio_trim_encoding(
            choice=str(params.get("trim_audio_format") or "source") if exact else "source",
            codec=codec,
            extension=source.suffix,
            sample_rate=rate,
            channels=facts["channels"],
            sample_fmt=str(stream.get("sample_fmt") or ""),
            bits=stream.get("bits_per_raw_sample"),
            bit_rate=stream.get("bit_rate") or fmt.get("bit_rate"),
            mp3_preset=params.get("trim_mp3_preset") or "v0",
            bitrate=params.get("trim_audio_bitrate") or "320k",
        )
    except ValueError as exc:
        raise RuntimeError(str(exc)) from exc
    warnings = [*facts["warnings"], *encoding.warnings]
    notes: list[str] = []
    if not exact:
        notes.append(f"Exact cut is off, but {codec.upper()} loses nothing on the sample, so it is cut there all the same.")
    keep_cover = bool(facts["covers"]) and encoding.extension in AUDIO_COVER_CONTAINERS
    if facts["covers"] and not keep_cover:
        warnings.append(f"The cover picture stays behind: {encoding.extension.upper()} cannot hold one.")
    base = _output_path(
        source,
        output_dir,
        "",
        encoding.extension,
        source_root=source_dir,
        operation=_operation_output_folder(context, "Trim"),
    )
    if facts["suffix"]:
        base = base.with_name(f"{base.stem}_{facts['suffix']}{base.suffix}")
    groups = [trim.pieces] if trim.joined else [(piece,) for piece in trim.pieces]
    if trim.action == "split":
        context.log(f"Split {facts['label']} into {len(groups)} parts on the sample:")
        for piece in trim.pieces[1:]:
            context.log(f"    at {format_seconds(piece.start / rate)} (sample {piece.start})")
    common = {
        "kind": "audio",
        "source": source,
        "action": trim.action,
        "sample_rate": rate,
        "output_rate": encoding.output_rate,
        "channels": facts["channels"],
        "codec": codec,
        "container": encoding.extension,
        "duration": facts["duration"],
        "codec_label": encoding.label,
        "lossless": encoding.lossless,
        "notes": notes,
        "warnings": warnings,
    }
    plans: list[dict[str, Any]] = []
    for index, group in enumerate(groups, start=1):
        suffix = _trim_part_suffix(index, len(groups)) if trim.action == "split" else ""
        target = base.with_name(f"{base.stem}_{suffix}{base.suffix}") if suffix else base
        metadata, muxer, moved = audio_trim_metadata(
            facts["tags"],
            start_sample=group[0].start,
            extension=encoding.extension,
            broadcast_wav=facts["broadcast_wav"],
        )
        kept = sum(trim.length(piece) for piece in group)
        command = build_audio_trim_command(
            ffmpeg=_ffmpeg(root),
            source=str(source),
            target=str(target),
            overwrite=_as_bool(params.get("overwrite"), True),
            pieces=group,
            codec_args=encoding.codec_args,
            tail_filter=encoding.tail_filter,
            keep_cover=keep_cover,
            metadata=metadata,
            muxer_args=(*encoding.muxer_args, *muxer),
        )
        plans.append(
            {
                **common,
                "label": f"{facts['label']} [{suffix}]" if suffix else facts["label"],
                "target": target,
                "command": command,
                "spans": [(piece.start, piece.end) for piece in group],
                "kept_samples": kept,
                "expected_samples": round(kept * encoding.output_rate / rate),
                "time_reference": moved if moved and moved[0] != moved[1] else None,
            }
        )
    return plans


def _trim_sound_packet_plans(
    context: JobContext,
    source: Path,
    params: dict[str, Any],
    trim: Any,
    facts: dict[str, Any],
    *,
    source_dir: Path,
    output_dir: Path,
) -> list[dict[str, Any]]:
    """Compressed packets copied untouched, every point moved to a packet boundary."""
    root = context.paths.root
    codec, rate = facts["codec"], facts["rate"]
    extension = source.suffix.lower().lstrip(".")
    rule = PACKET_COPY_RULES.get(codec)
    if rule is None or extension not in rule.containers:
        raise RuntimeError(
            f"Copying {codec.upper()} out of .{extension} packet by packet has not been measured, so it is not "
            "offered. Turn Exact cut on: it cuts on the sample."
        )
    starts = _trim_sound_packet_starts(root, source, rate=rate, origin=_sound_number(facts["stream"].get("start_time")))
    try:
        copy = plan_packet_copy(trim=trim, rule=rule, packet_starts=starts)
    except ValueError as exc:
        raise RuntimeError(str(exc)) from exc
    context.log(f"Copying {facts['label']} packet by packet (Exact cut is off):")
    for asked, landed in copy.moves:
        context.log(
            f"    point {format_seconds(asked / rate)} -> packet boundary {format_seconds(landed / rate)} "
            f"({(landed - asked) * 1000 / rate:+.1f} ms, sample {landed})"
        )
    warnings = [*facts["warnings"], rule.warning]
    keep_cover = bool(facts["covers"]) and extension in AUDIO_COVER_CONTAINERS
    if facts["covers"] and not keep_cover:
        warnings.append(f"The cover picture stays behind: {extension.upper()} cannot hold one.")
    overwrite = _as_bool(params.get("overwrite"), True)
    base = _output_path(
        source,
        output_dir,
        "",
        extension,
        source_root=source_dir,
        operation=_operation_output_folder(context, "Trim"),
    )
    if facts["suffix"]:
        base = base.with_name(f"{base.stem}_{facts['suffix']}{base.suffix}")
    common = {
        "kind": "audio",
        "source": source,
        "action": trim.action,
        "sample_rate": rate,
        "output_rate": rate,
        "channels": facts["channels"],
        "codec": codec,
        "container": extension,
        "duration": facts["duration"],
        "codec_label": f"{codec.upper()} packets, copied untouched",
        "lossless": False,
        "notes": [],
        "warnings": warnings,
    }
    if trim.joined:
        # Two pieces into workspace, glued by the concat demuxer, and taken away afterwards.
        stage = context.paths.workspace / "trim_gap"
        stage.mkdir(parents=True, exist_ok=True)
        parts = []
        for index, piece in enumerate(copy.pieces, start=1):
            part_target = stage / f"{base.stem}_sound_piece{index}{base.suffix}"
            parts.append(
                {
                    "label": f"{facts['label']} [piece {index}]",
                    "source": source,
                    "target": part_target,
                    "command": build_packet_copy_command(
                        ffmpeg=_ffmpeg(root), source=str(source), target=str(part_target), overwrite=True, piece=piece
                    ),
                }
            )
        list_file = stage / f"{base.stem}_sound_pieces.txt"
        clock_back = -starts[0] / rate if rule.join_clock_back and starts[0] < 0 else 0.0
        command = build_packet_join_command(
            ffmpeg=_ffmpeg(root),
            list_file=str(list_file),
            source=str(source),
            target=str(base),
            overwrite=overwrite,
            clock_back=clock_back,
            keep_cover=keep_cover,
        )
        return [
            {
                **common,
                "label": facts["label"],
                "target": base,
                "command": command,
                "parts": parts,
                "list_file": list_file,
                "spans": [(piece.start_sample, piece.end_sample) for piece in copy.pieces],
                "kept_samples": copy.kept,
                "expected_samples": copy.kept,
                "time_reference": None,
            }
        ]
    plans: list[dict[str, Any]] = []
    for index, piece in enumerate(copy.pieces, start=1):
        suffix = _trim_part_suffix(index, len(copy.pieces)) if trim.action == "split" else ""
        target = base.with_name(f"{base.stem}_{suffix}{base.suffix}") if suffix else base
        metadata, _muxer, moved = audio_trim_metadata(
            facts["tags"], start_sample=piece.start_sample, extension=extension, broadcast_wav=False
        )
        command = build_packet_copy_command(
            ffmpeg=_ffmpeg(root),
            source=str(source),
            target=str(target),
            overwrite=overwrite,
            piece=piece,
            keep_cover=keep_cover,
            metadata=metadata,
        )
        plans.append(
            {
                **common,
                "label": f"{facts['label']} [{suffix}]" if suffix else facts["label"],
                "target": target,
                "command": command,
                "spans": [(piece.start_sample, piece.end_sample)],
                "kept_samples": copy.length(piece),
                "expected_samples": copy.length(piece),
                "time_reference": moved if moved and moved[0] != moved[1] else None,
            }
        )
    return plans


def _log_audio_trim_plan(context: JobContext, plan: dict[str, Any], index: int, total: int) -> None:
    rate = int(plan["sample_rate"])
    context.log(
        f"[{index}/{total}] {plan['label']} | {plan['codec'].upper()} {rate} Hz {plan['channels']} ch | "
        f"{format_seconds(plan['duration'])} | -> {plan['container'].upper()}"
    )

    def at(sample: int | None) -> str:
        return "end of file" if sample is None else f"{format_seconds(sample / rate)} (sample {sample})"

    spans = plan["spans"]
    if plan["action"] == "cut":
        context.log(f"    remove  {at(spans[0][1])} .. {at(spans[1][0])}")
    else:
        for first, last in spans:
            context.log(f"    piece   {at(first)} .. {at(last)}")
    context.log(f"    keeping {plan['kept_samples']} samples ({format_seconds(plan['kept_samples'] / rate)})")
    context.log(f"    writes  {plan['codec_label']}")
    moved = plan.get("time_reference")
    if moved:
        context.log(f"    time reference {moved[0]} -> {moved[1]} (samples since midnight)")
    for note in plan.get("notes") or ():
        context.log(f"    {note}")
    for warning in plan["warnings"]:
        context.log(f"    [WARNING] {warning}")


def _decoded_sample_count(root: Path, target: Path) -> int:
    """Samples a decoder hands over for the first audio stream, counted one by one.

    Headers disagree with the sound: an AAC header measured 29 samples short
    while its decoder gave 243 more, an Opus header 312 long. One byte per
    sample of one channel costs little to count and answers exactly.
    """
    command = [
        _ffmpeg(root),
        "-hide_banner",
        "-loglevel",
        "error",
        "-nostdin",
        "-i",
        str(target),
        "-map",
        "0:a:0",
        "-af",
        "pan=mono|c0=c0",
        "-c:a",
        "pcm_u8",
        "-f",
        "u8",
        "-",
    ]
    process = subprocess.Popen(
        command,
        cwd=str(root),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=utf8_subprocess_env(_tool_env(root)),
        **hidden_subprocess_kwargs(),
    )
    count = 0
    stream = process.stdout
    if stream is not None:
        while True:
            chunk = stream.read(1 << 20)
            if not chunk:
                break
            count += len(chunk)
    _unused, stderr = process.communicate()
    if process.returncode != 0:
        lines = (stderr or b"").decode("utf-8", errors="replace").strip().splitlines()
        raise RuntimeError(lines[-1] if lines else f"ffmpeg exited {process.returncode}")
    return count


def _audio_stream_duration(root: Path, target: Path) -> float:
    result = _capture_tool(
        root,
        [
            _ffprobe(root),
            "-v",
            "error",
            "-select_streams",
            "a:0",
            "-show_entries",
            "stream=duration:format=duration",
            "-of",
            "default=nokey=1:noprint_wrappers=1",
            str(target),
        ],
    )
    for line in (result.stdout or "").splitlines():
        value = _sound_number(line.strip())
        if value > 0:
            return value
    return 0.0


def _verify_audio_trim_output(context: JobContext, plan: dict[str, Any]) -> dict[str, Any]:
    """Count what a decoder gets back from the piece, rather than trust a header."""
    root = context.paths.root
    try:
        counted = _decoded_sample_count(root, plan["target"])
    except RuntimeError as exc:
        context.log(f"    [ERROR] The result cannot be read back: {exc}")
        return {"short": True, "unreadable": True}
    rate = int(plan["output_rate"])
    expected = int(plan["expected_samples"])
    drift = counted - expected
    context.log(f"    result  {counted} samples, {format_seconds(counted / rate)} ({drift:+d} from the plan)")
    if drift and plan.get("lossless"):
        context.log(f"    [WARNING] A lossless piece lands on the sample, and this one is {drift:+d} samples off.")
    elif drift:
        context.log(f"    {plan['codec_label']}: the end is {drift:+d} samples off the sample, {abs(drift) * 1000 / rate:.1f} ms")
    short = expected > rate * 0.2 and counted < expected * 0.5
    if short:
        context.log(
            f"    [ERROR] Only {format_seconds(counted / rate)} of the planned {format_seconds(expected / rate)} came back."
        )
    return {"samples": counted, "drift": drift, "short": short}


def trim_media(context: JobContext) -> dict[str, object]:
    """Cut the head, the tail, or both off camera footage without re-encoding; sound files on the sample."""
    try:
        return _trim_media_run(context)
    finally:
        # The rebuilt subtitle lines live only as long as the run: however it
        # ended, whatever was planned, refused or stopped.
        shutil.rmtree(context.paths.workspace / "trim_subtitles", ignore_errors=True)


def _trim_media_run(context: JobContext) -> dict[str, object]:
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
            candidate = _take_in(source_dir, selected)
            files = [candidate] if candidate is not None else []
            if not files:
                context.log(f"[ERROR] Selected file is not in Source: {selected}")
                return {"ok": False, "files": 0, "failed": 1}
        else:
            # One file at a time: two takes rarely share a keyframe, let alone a
            # cut point. The CLI wrappers still walk the whole folder on purpose.
            staged = _media_files(source_dir, TRIM_VIDEO_EXTENSIONS)
            files = staged[:1]
            if len(staged) > 1:
                context.log(f"Trimming the first of {len(staged)} files: {_source_display_name(files[0], source_dir)}")
    if not files:
        context.log(f"No video files in {source_dir}")
        return {"ok": False, "files": 0}
    if _as_bool(params.get("limit_first_file"), False):
        files = files[:1]
    files, camera_raw_failed = _without_camera_raw(context, files, source_dir, "trim_media")
    if camera_raw_failed and not files:
        return {"ok": False, "files": 0, "refused": camera_raw_failed}

    dry_run = _as_bool(params.get("dry_run"), False)
    overwrite = _as_bool(params.get("overwrite"), True)
    plans: list[dict[str, Any]] = []
    # A split throws nothing away: IN alone gives two parts, IN and OUT give
    # three, and the parts join on keyframes so they add back up to the file.
    split_mode = _trim_pattern(params) == "split"
    # And the fifth: the piece between the points goes, and what is left is
    # joined. Two cuts and a concat, planned as one job.
    gap_mode = _trim_pattern(params) == "middle"
    skipped = 0
    # A file or a row the planner refused is an error the operator has to see,
    # unlike a result kept because Overwrite is off. The run's `ok` counts it. Camera RAW is one of them.
    refused = camera_raw_failed
    for source in files:
        file_params = dict(params)
        marks = per_file_points.get(source)
        if marks:
            file_params["trim_pattern"] = str(marks.get("pattern") or params.get("trim_pattern") or "both")
            file_params["trim_start"] = marks.get("start", "")
            file_params["trim_end"] = marks.get("end", "")
            # A mark is one pair of points; the panel's rows and split points belong to another file.
            file_params.pop("trim_rows", None)
            file_params.pop("trim_points", None)
        label = _source_display_name(source, source_dir)
        try:
            # A split is one timeline of points; a keep or a cut may come as several rows.
            variants = [("", file_params)] if split_mode else _trim_variants(file_params)
        except RuntimeError as exc:
            skipped += 1
            refused += 1
            context.log(f"[SKIP] {label}: {exc}")
            continue
        if len(variants) > 1:
            context.log(f"{label}: {len(variants)} variants, each written to a file of its own.")
        for suffix, variant_params in variants:
            try:
                if source.suffix.lower().lstrip(".") in PURE_AUDIO_EXTENSIONS:
                    # Sound alone has no keyframe to wait for: every action lands on the sample.
                    plans.extend(
                        _trim_audio_plans(
                            context, source, variant_params, source_dir=source_dir, output_dir=output_dir, name_suffix=suffix
                        )
                    )
                elif gap_mode:
                    plans.append(
                        _trim_gap_plan(
                            context, source, variant_params, source_dir=source_dir, output_dir=output_dir, name_suffix=suffix
                        )
                    )
                elif split_mode:
                    plans.extend(_trim_split_plans(context, source, variant_params, source_dir=source_dir, output_dir=output_dir))
                else:
                    plans.append(
                        _trim_plan(context, source, variant_params, source_dir=source_dir, output_dir=output_dir, name_suffix=suffix)
                    )
            except Exception as exc:
                skipped += 1
                refused += 1
                context.log(f"[SKIP] {label}{f' [{suffix}]' if suffix else ''}: {exc}")
    if not plans:
        context.log("Nothing to trim.")
        return {"ok": False, "files": 0, "scanned": len(files), "skipped": skipped, "refused": refused}

    processed = 0
    failed = 0
    total = len(plans)
    context.units(total)
    for index, plan in enumerate(plans, start=1):
        if context.cancelled():
            # Nothing of this plan has been written yet, so nothing is cleaned:
            # a file already under its name belongs to an earlier run, and
            # Overwrite may well be off. A piece stopped mid-write is cleaned
            # where it failed, below.
            context.log("Trim cancelled by user.")
            return {
                "ok": False,
                "cancelled": True,
                "processed": processed,
                "failed": failed,
                "files": total,
                "skipped": skipped,
                "refused": refused,
            }
        if plan.get("kind") == "gap":
            _log_gap_plan(context, plan, index, total)
        elif plan.get("kind") == "audio":
            _log_audio_trim_plan(context, plan, index, total)
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
            if plan.get("parts"):
                # Pieces first, then the join: a cut out of a video, or a packet-copied sound.
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
            _discard_unusable_trim(context, plan["target"], sound=plan.get("kind") == "audio")
            context.log(f"    [FAIL] {plan['label']}: {exc}")
            context.progress(index / total)
            continue
        verified = (
            _verify_audio_trim_output(context, plan) if plan.get("kind") == "audio" else _verify_trim_output(context, plan)
        )
        if verified.get("short"):
            failed += 1
            context.progress(index / total)
            continue
        processed += 1
        context.progress(index / total)

    if context.cancelled():
        # Stopped during the last piece: it failed above, and the run is a cancel, not a finish.
        context.log("Trim cancelled by user.")
    return {
        # The executor reads only this: without it a failed or refused run was
        # reported as done, with a green status and exit code 0.
        "ok": failed == 0 and refused == 0 and not context.cancelled(),
        "cancelled": context.cancelled(),
        "processed": processed,
        "failed": failed,
        "files": total,
        "scanned": len(files),
        "skipped": skipped,
        "refused": refused,
        "dry_run": dry_run,
    }


# --- Trim file details --------------------------------------------------------
#
# What ffprobe knows of the take chosen in CUT, asked by the button beside its
# name. The points themselves are found in mpv, which the window drives.


def _trim_preview_source(root: Path, file_name: str) -> Path | None:
    source_dir = cached_source_path(root)
    if file_name:
        return _take_in(source_dir, file_name)
    files = _media_files(source_dir, TRIM_VIDEO_EXTENSIONS)
    return files[0] if files else None


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
        rate = parse_rate(stream_rate(facts.get("r_frame_rate"), facts.get("avg_frame_rate")))
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
    return {"ok": True, "file": source.name,
            "rows": [{"field": name, "field_ru": TRIM_PROBE_FIELDS_RU.get(name, name), "value": value} for name, value in rows]}


# The names of the rows of the table above in a Russian window.
TRIM_PROBE_FIELDS_RU = {
    "File": "Файл", "Container": "Контейнер", "Size": "Размер", "Duration": "Длительность", "Frames": "Кадров",
    "Video": "Видео", "Resolution": "Разрешение", "Frame rate": "Частота кадров", "Exact rate": "Точная частота",
    "Pixel format": "Формат пикселей", "Colour": "Цвет", "Audio": "Звук", "Channels": "Каналы", "Sample rate": "Частота дискретизации",
    "Sample format": "Формат сэмпла", "Timecode": "Таймкод", "Timeline starts": "Начало шкалы", "Bit rate": "Битрейт",
}


