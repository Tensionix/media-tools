"""Single source of truth for encoder/decoder backend selection.

The GUI manifest, the media services, preflight and the CLI script runner must
agree on what "CUDA", "QSV", "AMD" or "dav1d" mean before a command is built.
Every alias table, target-to-encoder mapping and preset scale lives here so the
four layers cannot drift apart again.
"""

from __future__ import annotations

from typing import Any


CPU_ENCODER_PRESETS = {"fast", "medium", "slow", "slower", "veryslow"}
NVENC_PRESETS = {"p5", "p6", "p7"}
QSV_ENCODER_PRESETS = {"veryfast", "faster", "fast", "medium", "slow", "slower", "veryslow"}
AMF_QUALITY_PRESETS = {"speed", "balanced", "quality"}

HARDWARE_ENCODE_BACKENDS = ("cuda", "qsv", "amd")
HARDWARE_DECODE_BACKENDS = ("cuda", "qsv", "amd", "dav1d")

ENCODE_BACKEND_ALIASES = {
    "": "cpu",
    "auto": "cpu",
    "software": "cpu",
    "cuda/nvenc": "cuda",
    "nvenc": "cuda",
    "nvidia": "cuda",
    "quicksync": "qsv",
    "quicksync/qsv": "qsv",
    "intel": "qsv",
    "amf": "amd",
    "amd/amf": "amd",
}

DECODE_BACKEND_ALIASES = {
    "": "auto",
    "cpu": "auto",
    "none": "auto",
    "software": "auto",
    "cuda/nvenc": "cuda",
    "nvenc": "cuda",
    "nvidia": "cuda",
    "quicksync": "qsv",
    "quicksync/qsv": "qsv",
    "intel": "qsv",
    "amd/d3d11va": "amd",
    "d3d11va": "amd",
    "dxva2": "amd",
    "libdav1d": "dav1d",
}

DECODE_BACKEND_ARGS = {
    "cuda": (["-hwaccel", "cuda"], "CUDA"),
    "qsv": (["-hwaccel", "qsv"], "QuickSync"),
    "amd": (["-hwaccel", "d3d11va"], "AMD/D3D11VA"),
    "dav1d": (["-c:v", "libdav1d"], "dav1d AV1"),
}

TARGET_ALIASES = {
    "hevc10": "hevc_x265",
    "prores422": "prores_422",
}

BACKEND_TARGETS = {
    "cuda": {
        "x264": "h264_nvenc",
        "h264": "h264_nvenc",
        "hevc_x265": "hevc_nvenc",
        "x265": "hevc_nvenc",
        "hevc": "hevc_nvenc",
        "svt_av1": "av1_nvenc",
        "av1": "av1_nvenc",
    },
    "qsv": {
        "x264": "h264_qsv",
        "h264": "h264_qsv",
        "hevc_x265": "hevc_qsv",
        "x265": "hevc_qsv",
        "hevc": "hevc_qsv",
        "svt_av1": "av1_qsv",
        "av1": "av1_qsv",
    },
    "amd": {
        "x264": "h264_amf",
        "h264": "h264_amf",
        "hevc_x265": "hevc_amf",
        "x265": "hevc_amf",
        "hevc": "hevc_amf",
        "svt_av1": "av1_amf",
        "av1": "av1_amf",
    },
}

HARDWARE_TARGETS = {
    "h264_nvenc",
    "hevc_nvenc",
    "av1_nvenc",
    "h264_qsv",
    "hevc_qsv",
    "av1_qsv",
    "h264_amf",
    "hevc_amf",
    "av1_amf",
}

TARGET_ENCODERS = {
    "ffv1": "ffv1",
    "x264_lossless": "libx264",
    "x264": "libx264",
    "h264": "libx264",
    "hevc_x265": "libx265",
    "x265": "libx265",
    "hevc": "libx265",
    "svt_av1": "libsvtav1",
    "h264_nvenc": "h264_nvenc",
    "hevc_nvenc": "hevc_nvenc",
    "av1_nvenc": "av1_nvenc",
    "h264_qsv": "h264_qsv",
    "hevc_qsv": "hevc_qsv",
    "av1_qsv": "av1_qsv",
    "h264_amf": "h264_amf",
    "hevc_amf": "hevc_amf",
    "av1_amf": "av1_amf",
    "prores_proxy": "prores_ks",
    "prores_lt": "prores_ks",
    "prores_422": "prores_ks",
    "prores_hq": "prores_ks",
    "dnxhr_hq": "dnxhd",
    "dnxhr_hqx": "dnxhd",
}

AUTO_PIX_FMTS = {"", "auto", "source", "native", "original"}

# Manifest pixel format -> native pixel format of each hardware encoder.
# A format missing from a table is not encodable by that encoder: H.264 hardware
# encoders are 8-bit only, and QSV/AMF have no planar 4:2:2 path at all.
HARDWARE_PIX_FMTS = {
    "h264_nvenc": {"yuv420p": "yuv420p"},
    "hevc_nvenc": {
        "yuv420p": "yuv420p",
        "yuv420p10le": "p010le",
        "yuv422p": "nv16",
        "yuv422p10le": "p210le",
    },
    "av1_nvenc": {"yuv420p": "yuv420p", "yuv420p10le": "p010le"},
    "h264_qsv": {"yuv420p": "nv12"},
    "hevc_qsv": {
        "yuv420p": "nv12",
        "yuv420p10le": "p010le",
        "yuv422p": "yuyv422",
        "yuv422p10le": "y210le",
    },
    "av1_qsv": {"yuv420p": "nv12", "yuv420p10le": "p010le"},
    "h264_amf": {"yuv420p": "yuv420p"},
    "hevc_amf": {"yuv420p": "yuv420p", "yuv420p10le": "p010le"},
    "av1_amf": {"yuv420p": "yuv420p", "yuv420p10le": "p010le"},
}

CPU_PRESET_ALIASES = {
    "ultrafast": "fast",
    "superfast": "fast",
    "veryfast": "fast",
    "faster": "fast",
    "placebo": "veryslow",
}

NVENC_PRESET_ALIASES = {
    "slow": "p5",
    "slower": "p6",
    "veryslow": "p7",
    "slowest": "p7",
    "hq": "p6",
    "uhq": "p7",
}

AMF_QUALITY_ALIASES = {
    "fast": "speed",
    "veryfast": "speed",
    "faster": "speed",
    "medium": "balanced",
    "slow": "quality",
    "slower": "quality",
    "veryslow": "quality",
    "p5": "quality",
    "p6": "quality",
    "p7": "quality",
}


def scalar_value(value: Any, default: str = "") -> str:
    """Reduce a GUI/CLI field value to a single lowercase token."""
    if isinstance(value, (list, tuple)):
        items = [str(item).strip() for item in value if str(item).strip()]
        value = items[0] if items else None
    text = str(value if value is not None else default).strip().lower()
    return text or default


def normalize_encode_backend(value: Any, default: str = "cpu") -> str:
    backend = scalar_value(value, default)
    return ENCODE_BACKEND_ALIASES.get(backend, backend)


def normalize_decode_backend(value: Any, default: str = "auto") -> str:
    backend = scalar_value(value, default)
    return DECODE_BACKEND_ALIASES.get(backend, backend)


def encode_backend_from_params(params: dict[str, Any]) -> str:
    value = params.get("encode_backend")
    if value is None:
        value = params.get("backend")
    return normalize_encode_backend(value)


def decode_backend_from_params(params: dict[str, Any]) -> str:
    value = params.get("decode_backend")
    if value is None:
        value = params.get("decode_stack") or params.get("decode_hw")
    return normalize_decode_backend(value)


def normalize_target(target: str) -> str:
    normalized = str(target or "").strip().lower()
    return TARGET_ALIASES.get(normalized, normalized)


def target_for_backend(target: str, backend: str) -> str:
    normalized = normalize_target(target)
    if normalized in HARDWARE_TARGETS:
        return normalized
    return BACKEND_TARGETS.get(backend, {}).get(normalized, normalized)


def encoder_for_target(target: str) -> str:
    return TARGET_ENCODERS.get(normalize_target(target), "")


# Frames can stay in GPU memory when the same vendor decodes and encodes.
# Values follow the vendor guides: NVIDIA documents -hwaccel_output_format cuda,
# AMD recommends d3d11 with -hwaccel d3d11va, and QSV uses its own qsv frames.
FULL_GPU_OUTPUT_FORMATS = {
    "cuda": "cuda",
    "qsv": "qsv",
    "amd": "d3d11",
}

# QSV is the one stack whose implicit default is a hardware surface: FFmpeg logs
# "defaulting hwaccel_output_format to qsv ... DEPRECATED" and every software
# filter then fails with "Impossible to convert between the formats". CUDA and
# D3D11VA already hand frames back in system memory, so they need no override.
HW_SURFACE_DEFAULT_BACKENDS = {"qsv"}


def software_decode_format(bit_depth: int = 8) -> str:
    """Planar format a hardware decoder should download frames into."""
    return "p010le" if int(bit_depth or 8) > 8 else "nv12"


def can_keep_frames_on_gpu(
    decode_backend: str,
    encode_backend: str,
    *,
    pix_fmt: Any = "auto",
    has_video_filters: bool = False,
) -> bool:
    """True when nothing between decode and encode needs system memory."""
    decode = normalize_decode_backend(decode_backend)
    if decode != normalize_encode_backend(encode_backend) or decode not in FULL_GPU_OUTPUT_FORMATS:
        return False
    if has_video_filters:
        return False
    return scalar_value(pix_fmt, "auto") in AUTO_PIX_FMTS


def decode_output_format_args(
    decode_backend: str,
    encode_backend: str,
    *,
    pix_fmt: Any = "auto",
    has_video_filters: bool = False,
    source_bit_depth: int = 8,
) -> list[str]:
    """`-hwaccel_output_format` for a hardware decode.

    Set to the GPU format when decode and encode can share video memory. When
    anything needs system memory, only the stacks that default to a hardware
    surface get an explicit download format - forcing one on CUDA or D3D11VA
    would pin a bit depth FFmpeg otherwise negotiates from the source.
    """
    decode = normalize_decode_backend(decode_backend)
    if decode not in FULL_GPU_OUTPUT_FORMATS:
        return []
    if can_keep_frames_on_gpu(decode, encode_backend, pix_fmt=pix_fmt, has_video_filters=has_video_filters):
        return ["-hwaccel_output_format", FULL_GPU_OUTPUT_FORMATS[decode]]
    if decode in HW_SURFACE_DEFAULT_BACKENDS:
        return ["-hwaccel_output_format", software_decode_format(source_bit_depth)]
    return []


def decode_args(backend: str) -> list[str]:
    args, _label = DECODE_BACKEND_ARGS.get(normalize_decode_backend(backend), ([], ""))
    return list(args)


def decode_label(backend: str) -> str:
    _args, label = DECODE_BACKEND_ARGS.get(normalize_decode_backend(backend), ([], "CPU/auto"))
    return label or "CPU/auto"


def is_hardware_encoder(encoder: str) -> bool:
    return str(encoder or "").strip().lower() in HARDWARE_PIX_FMTS


def hardware_pix_fmt(encoder: str, pix_fmt: Any) -> str:
    """Return the native pixel format a hardware encoder needs for the requested one.

    An empty result means "let FFmpeg negotiate". A pixel format the encoder
    cannot produce raises instead of being silently downgraded: FFmpeg would
    otherwise pick the nearest supported format and write a file that does not
    match what the operator selected.
    """
    requested = scalar_value(pix_fmt, "auto")
    table = HARDWARE_PIX_FMTS.get(str(encoder or "").strip().lower())
    if table is None or requested in AUTO_PIX_FMTS:
        return "" if requested in AUTO_PIX_FMTS else requested
    native = table.get(requested)
    if native:
        return native
    supported = ", ".join(sorted(table))
    raise RuntimeError(
        f"{encoder} cannot encode {requested}. Supported by this hardware encoder: {supported}. "
        "Use a CPU encoder for other pixel formats."
    )


def normalize_cpu_preset(value: Any, default: str = "medium") -> str:
    preset = scalar_value(value, default) or default
    preset = CPU_PRESET_ALIASES.get(preset, preset)
    return preset if preset in CPU_ENCODER_PRESETS else default


def normalize_nvenc_preset(value: Any, default: str = "p6") -> str:
    preset = scalar_value(value, default) or default
    preset = NVENC_PRESET_ALIASES.get(preset, preset)
    return preset if preset in NVENC_PRESETS else default


def normalize_qsv_preset(value: Any, default: str = "medium") -> str:
    preset = scalar_value(value, default) or default
    return preset if preset in QSV_ENCODER_PRESETS else default


def normalize_amf_quality(value: Any, default: str = "quality") -> str:
    quality = scalar_value(value, default) or default
    quality = AMF_QUALITY_ALIASES.get(quality, quality)
    return quality if quality in AMF_QUALITY_PRESETS else default
