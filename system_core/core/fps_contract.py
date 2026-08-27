from __future__ import annotations

from typing import Any


MXF_PROFILES = {"prores_mxf", "dnxhr_mxf"}


def fps_pcm_audio_args(profile: str, params: dict[str, Any]) -> tuple[list[str], str]:
    """Return the PCM encoder contract shared by GUI and CLI FPS paths."""
    profile = str(profile or "").strip().lower()
    depth = str(params.get("fps_audio_pcm_depth", "s24") or "s24").strip().lower()
    if depth in {"16", "s16", "pcm_s16", "pcm16"}:
        return ["-c:a", "pcm_s16le"], "pcm16"
    if depth in {"32", "32f", "f32", "float", "pcm_f32", "pcm32f"} and profile not in MXF_PROFILES:
        return ["-c:a", "pcm_f32le"], "pcm32f"
    return ["-c:a", "pcm_s24le"], "pcm24"


def fps_oversample_factor(params: dict[str, Any]) -> int:
    value = str(params.get("fps_audio_oversample", "x1") or "x1").strip().lower()
    if value in {"4", "x4", "4x", "176400", "192000"}:
        return 4
    if value in {"2", "x2", "2x", "88200", "96000"}:
        return 2
    return 1


def fps_audio_target_rate(source_rate: int, params: dict[str, Any]) -> int:
    source_rate = source_rate if source_rate > 0 else 48000
    factor = fps_oversample_factor(params)
    if factor <= 1:
        return source_rate
    if source_rate % 44100 == 0 or source_rate in {44100, 88200, 176400}:
        return min(176400, max(source_rate, 44100 * factor))
    if source_rate % 48000 == 0 or source_rate in {48000, 96000, 192000}:
        return min(192000, max(source_rate, 48000 * factor))
    return min(192000, max(source_rate, source_rate * factor))


def fps_audio_output_rate(profile: str, work_rate: int) -> int:
    return 48000 if str(profile or "").strip().lower() in MXF_PROFILES else work_rate


def _soxr_resample_filter(sample_rate: int) -> str:
    return f"aresample={sample_rate}:resampler=soxr:precision=28"


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


def fps_audio_filter(mode: str, k: float, speed: float, work_rate: int, output_rate: int | None = None) -> str:
    work_resample = _soxr_resample_filter(work_rate)
    if str(mode).strip().lower() == "conform":
        parts = [work_resample, _atempo_chain(speed), work_resample]
    else:
        parts = [work_resample, f"asetrate={work_rate}/{k:.12g}", work_resample]
    if output_rate and output_rate != work_rate:
        parts.append(_soxr_resample_filter(output_rate))
    parts.append("aresample=async=1:first_pts=0")
    return ",".join(parts)


def build_fps_command(
    *,
    ffmpeg: str,
    source: str,
    overwrite: bool,
    mode: str,
    k: float,
    speed: float,
    target_arg: str,
    video_args: list[str],
    audio_args: list[str],
    extension: str,
    target: str,
    has_audio: bool,
    audio_work_rate: int = 0,
    audio_output_rate: int = 0,
    decode_args: list[str] | None = None,
) -> list[str]:
    """Build the common FPS FFmpeg command used by both front-ends."""
    command = [ffmpeg, "-hide_banner", "-stats", "-y" if overwrite else "-n", *(decode_args or []), "-i", source]
    if has_audio:
        audio_filter = fps_audio_filter(mode, k, speed, audio_work_rate, audio_output_rate)
        command.extend(
            [
                "-filter_complex",
                f"[0:v]setpts={k:.12g}*PTS[v];[0:a]{audio_filter}[a]",
                "-map",
                "[v]",
                "-map",
                "[a]",
            ]
        )
    else:
        command.extend(["-filter_complex", f"[0:v]setpts={k:.12g}*PTS[v]", "-map", "[v]", "-an"])
    command.extend(
        [
            "-r",
            target_arg,
            "-map_metadata",
            "-1",
            "-metadata:s:v:0",
            "timecode=00:00:00:00",
            "-timecode",
            "00:00:00:00",
            *video_args,
        ]
    )
    if has_audio:
        command.extend(audio_args)
    if extension == "mp4":
        command.extend(["-movflags", "+faststart"])
    command.append(target)
    return command
