"""Shared audio contract for the GUI services and the CLI runner.

Sample rate changes go through SoX/libsoxr rather than a plain `-ar`, and
"source" means the input rate is preserved. Both layers resolve the rate here so
the same audio mode cannot be resampled differently depending on the entry point.

MP3 lives here for the same reason: the LAME preset scale is one scale for the
whole project, not one per page.
"""

from __future__ import annotations

from typing import Any


SOURCE_SAMPLE_RATES = {"source", "native", "original", "auto", ""}
SUPPORTED_SAMPLE_RATES = {
    "44100": ("44100", "44.1", "44.1k", "44100hz"),
    "48000": ("48000", "48", "48k", "48000hz"),
    "88200": ("88200", "88.2", "88.2k", "88200hz"),
    "96000": ("96000", "96", "96k", "96000hz"),
    "176400": ("176400", "176.4", "176.4k", "176400hz"),
    "192000": ("192000", "192", "192k", "192000hz"),
}
# Audio modes that copy or drop the stream, so no resampling can apply.
UNFILTERED_AUDIO_MODES = {"", "none", "source", "native", "original", "copy"}

# MPEG-1 Layer III stops at 320 kbps, so the 384k entry of the shared AAC
# bitrate scale is clamped here. LAME clamps it silently otherwise, which makes
# the file name and the log claim a bitrate the encoder never wrote.
MP3_MAX_BITRATE = "320k"
MP3_BITRATES = ("192k", "256k", "320k")
MP3_PRESETS = ("v0", "insane", "bitrate")


def soxr_resample_filter(sample_rate: int | str) -> str:
    return f"aresample=resampler=soxr:precision=33:osr={sample_rate}"


def normalize_sample_rate(value: Any, default: str = "48000") -> str:
    """Return a supported rate, or "source" to keep the input rate."""
    text = str(value if value is not None else default).strip().lower()
    if text in SOURCE_SAMPLE_RATES:
        return "source"
    for rate, aliases in SUPPORTED_SAMPLE_RATES.items():
        if text in aliases:
            return rate
    return default


def normalize_mp3_preset(value: Any, default: str = "v0") -> str:
    """Return one of the LAME presets offered by the GUI."""
    text = str(value if value is not None else default).strip().lower()
    aliases = {
        "v0": "v0", "vbr": "v0", "extreme": "v0", "vbr_v0": "v0",
        "insane": "insane", "320": "insane", "cbr320": "insane",
        "bitrate": "bitrate", "custom": "bitrate",
    }
    return aliases.get(text, default if default in MP3_PRESETS else "v0")


def mp3_bitrate(value: Any, default: str = MP3_MAX_BITRATE) -> str:
    """Clamp a bitrate from the shared AAC scale to what MP3 can actually hold."""
    text = str(value if value is not None else default).strip().lower()
    if text.isdigit():
        text = f"{text}k"
    return text if text in MP3_BITRATES else MP3_MAX_BITRATE


def mp3_encoder_args(preset: Any, bitrate: Any = MP3_MAX_BITRATE) -> list[str]:
    """Encoder arguments for the selected LAME preset."""
    name = normalize_mp3_preset(preset)
    if name == "insane":
        return ["-c:a", "libmp3lame", "-b:a", MP3_MAX_BITRATE]
    if name == "bitrate":
        return ["-c:a", "libmp3lame", "-b:a", mp3_bitrate(bitrate)]
    return ["-c:a", "libmp3lame", "-q:a", "0"]


def mp3_preset_label(preset: Any, bitrate: Any = MP3_MAX_BITRATE) -> str:
    """Suffix fragment describing how the MP3 was encoded."""
    name = normalize_mp3_preset(preset)
    if name == "insane":
        return "insane_320"
    if name == "bitrate":
        return mp3_bitrate(bitrate)
    return "v0_extreme"


def resample_filter_args(sample_rate: Any, audio_mode: str, default: str = "48000") -> list[str]:
    """`-af` arguments for an encode, or an empty list when nothing is resampled."""
    if str(audio_mode or "").strip().lower() in UNFILTERED_AUDIO_MODES:
        return []
    rate = normalize_sample_rate(sample_rate, default)
    if rate == "source":
        return []
    return ["-af", soxr_resample_filter(rate)]
