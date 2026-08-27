"""Shared trimming contract for the GUI service and the CLI runner.

Trimming copies streams (`-c:v copy`), so a cut can only land on a keyframe.
Four things here are not obvious, and each one costs a broken file:

1. `-ss` placed before `-i` resets the output timestamps, so a `-to` that
   follows it counts from the new zero rather than from the source timeline.
   The end point therefore has to travel as a duration (`-t`), never as an
   absolute source position. Verified against FFmpeg 8.0.1.
2. A copied stream keeps the source `tmcd` value unchanged. Editors sync
   cameras to each other by it, so the shift has to be written out explicitly
   with `-timecode`.
3. Timecode counts frames, not seconds. At 23.976 the shift is
   `round(offset * 24000/1001)` frames added to a 24-frame base, and at 29.97
   drop-frame the base is 30 with two frames dropped every minute except each
   tenth. Rounding the rate first is exactly the error that costs four seconds
   per hour.
4. Timestamps do not always start at zero. MPEG-TS commonly starts at 1.44 s,
   and `-ss` counts in the stream's own timeline while the operator counts from
   the beginning of the picture; the offset has to be added back at seek time.
5. Only the start is bound to a keyframe. The tail is counted in frames
   (`-frames:v`), not in seconds: `-t` stops on a packet boundary and overshoots
   by two or three frames on a B-frame stream, while a frame count lands exactly.
   `-avoid_negative_ts make_zero` is deliberately absent — with a seek before
   `-i` it pushes video 0.1 s behind the audio.

Cut points are wall-clock time, never timecode. On NTSC rates the two disagree
by design: non-drop 00:04:00:00 at 29.97 is frame 7200, which is 240.24 s of
real time, and a tool that quietly treats one as the other drifts by 1001/1000.
Timecode lives here only as metadata to shift, and every conversion between
seconds and frames goes through the exact `Fraction`.
"""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
from typing import Any, Iterable
import re


TRIM_PATTERNS = ("start", "end", "both", "split", "middle")

# A timecode rate is the integer the fractional rate rounds up to: 23.976 counts
# on a 24-frame clock, 29.97 on a 30-frame one.
_TIMECODE_BASES = (24, 25, 30, 48, 50, 60, 96, 100, 120)

# The NTSC family. A file that says 30 usually means 30000/1001, and PAL rates
# (25, 50, 100) are never pulled down.
_TIME_TOKEN = re.compile(r"^\d+(?:[.,]\d+)?$")


def parse_seconds(value: Any) -> float:
    """Read a position written as seconds, `mm:ss`, `hh:mm:ss` or `hh:mm:ss,ms`."""
    if isinstance(value, bool):
        raise ValueError(f"Invalid time position: {value!r}")
    if isinstance(value, (int, float)):
        seconds = float(value)
        if seconds < 0:
            raise ValueError(f"Time position cannot be negative: {value!r}")
        return seconds
    text = str(value or "").strip().replace(" ", "")
    if not text:
        raise ValueError("Time position is empty.")
    parts = text.split(":")
    if len(parts) > 3:
        raise ValueError(f"Invalid time position: {value!r}")
    for part in parts:
        if not _TIME_TOKEN.match(part):
            raise ValueError(f"Invalid time position: {value!r}")
    total = 0.0
    for part in parts:
        total = total * 60.0 + float(part.replace(",", "."))
    return total


def format_seconds(seconds: float, *, decimals: int = 3, separator: str = ".") -> str:
    """`hh:mm:ss.mmm` for logs and reports."""
    value = max(0.0, float(seconds))
    hours = int(value // 3600)
    minutes = int((value % 3600) // 60)
    rest = value - hours * 3600 - minutes * 60
    if decimals <= 0:
        return f"{hours:02d}:{minutes:02d}:{int(round(rest)):02d}"
    text = f"{rest:0{decimals + 3}.{decimals}f}"
    return f"{hours:02d}:{minutes:02d}:{text}".replace(".", separator)


def format_offset(seconds: float, *, decimals: int = 1, separator: str = ".") -> str:
    """`-1.6 s`: the distance between the asked-for cut and the real one."""
    value = float(seconds)
    sign = "-" if value < 0 else "+"
    text = f"{abs(value):.{decimals}f}".replace(".", separator)
    return f"{sign}{text} s"


def parse_rate(value: Any) -> Fraction:
    """Frame rate as an exact fraction, the way ffprobe reports it."""
    text = str(value or "").strip()
    if not text or text in {"0/0", "N/A"}:
        raise ValueError("Frame rate could not be detected.")
    if "/" in text:
        numerator, denominator = text.split("/", 1)
        denominator_value = int(denominator)
        if denominator_value == 0:
            raise ValueError("Frame rate could not be detected.")
        return Fraction(int(numerator), denominator_value)
    return Fraction(text)


def rate_label(rate: Fraction) -> str:
    """`23.976p` / `29.97p` / `25p`, the way the rate is spoken about."""
    value = Fraction(rate)
    if value.denominator == 1:
        return f"{value.numerator}p"
    return f"{float(value):.3f}".rstrip("0").rstrip(".") + "p"


def timecode_base(rate: Fraction) -> int:
    """The integer clock a fractional rate counts on: 24000/1001 -> 24."""
    value = float(rate)
    for base in _TIMECODE_BASES:
        if value <= base + 0.001:
            return base
    return int(round(value))


def timecode_is_drop_frame(text: str) -> bool:
    """SMPTE writes drop-frame with a semicolon before the frames field."""
    return ";" in str(text or "")


def _drop_frames_per_minute(base: int) -> int:
    """29.97 drops two frames a minute, 59.94 drops four; 23.976 drops none."""
    if base == 30:
        return 2
    if base == 60:
        return 4
    if base == 120:
        return 8
    return 0


def parse_timecode(text: str, base: int) -> int:
    """`hh:mm:ss:ff` (or `;ff` for drop-frame) as a frame count."""
    raw = str(text or "").strip()
    if not raw:
        raise ValueError("Timecode is empty.")
    drop = timecode_is_drop_frame(raw)
    # Only the SMPTE separators. A dot would swallow `00:01:28.400`, which is a
    # time with milliseconds, and read 400 as a frame number.
    parts = re.split(r"[:;]", raw)
    if len(parts) != 4:
        raise ValueError(f"Invalid timecode: {text!r}")
    try:
        hours, minutes, seconds, frames = (int(part) for part in parts)
    except ValueError as exc:
        raise ValueError(f"Invalid timecode: {text!r}") from exc
    if base <= 0:
        raise ValueError(f"Invalid timecode base: {base!r}")
    total = ((hours * 60 + minutes) * 60 + seconds) * base + frames
    if drop:
        dropped = _drop_frames_per_minute(base)
        total_minutes = hours * 60 + minutes
        total -= dropped * (total_minutes - total_minutes // 10)
    return total


def format_timecode(frames: int, base: int, *, drop: bool = False) -> str:
    """A frame count back into `hh:mm:ss:ff`, wrapping at 24 hours."""
    if base <= 0:
        raise ValueError(f"Invalid timecode base: {base!r}")
    count = int(frames)
    day = base * 60 * 60 * 24
    if drop:
        day -= _drop_frames_per_minute(base) * (24 * 60 - 24 * 60 // 10)
    if day > 0:
        count %= day
    if count < 0:
        count += day
    separator = ";" if drop else ":"
    if drop:
        dropped = _drop_frames_per_minute(base)
        frames_per_10_minutes = base * 60 * 10 - dropped * 9
        frames_per_minute = base * 60 - dropped
        block, rest = divmod(count, frames_per_10_minutes)
        # The first minute of every ten-minute block keeps its dropped frames.
        if rest < frames_per_minute + dropped:
            minutes_in_block, rest_in_minute = 0, rest
        else:
            offset = rest - (frames_per_minute + dropped)
            minutes_in_block = 1 + offset // frames_per_minute
            rest_in_minute = offset % frames_per_minute + dropped
        total_minutes = block * 10 + minutes_in_block
        hours, minutes = divmod(total_minutes, 60)
        seconds, frame = divmod(rest_in_minute, base)
    else:
        seconds_total, frame = divmod(count, base)
        minutes_total, seconds = divmod(seconds_total, 60)
        hours, minutes = divmod(minutes_total, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}{separator}{frame:02d}"


def seconds_to_frames(seconds: float, rate: Fraction) -> int:
    """Frame index for a wall-clock position, counted on the exact rate.

    Rounding the rate first is the Shutter Encoder 20.2 defect: `round(29.97)`
    turns four requested minutes into 240.27 s, and the error grows by four
    seconds an hour.
    """
    exact = Fraction(str(float(seconds))) * Fraction(rate)
    return int(exact + Fraction(1, 2))


def frames_covering(seconds: float, rate: Fraction) -> int:
    """How many frames a span holds: the end rounds up, not to nearest.

    At 29.97 a thirty-second point lands on frame 899.1, and frame 899 stands at
    29.9966 - inside the piece. Rounding to nearest would leave it out.
    """
    exact = Fraction(str(float(seconds))) * Fraction(rate)
    whole = exact.numerator // exact.denominator
    return int(whole if exact == whole else whole + 1)


def frames_to_seconds(frames: int, rate: Fraction) -> float:
    """Wall-clock position of a frame index, counted on the exact rate."""
    return float(Fraction(int(frames)) / Fraction(rate))


def shift_timecode(text: str, offset_seconds: float, rate: Fraction) -> str:
    """Move a source timecode forward by the trimmed-away head."""
    base = timecode_base(rate)
    drop = timecode_is_drop_frame(text)
    frames = parse_timecode(text, base)
    return format_timecode(frames + seconds_to_frames(offset_seconds, rate), base, drop=drop)


def timecode_at(text: str, seconds: float, rate: Fraction) -> str:
    """The source timecode standing at a wall-clock position, for display."""
    return shift_timecode(text, seconds, rate)


def zero_timecode(rate: Fraction, *, drop: bool = False) -> str:
    return format_timecode(0, timecode_base(rate), drop=drop)


def keyframe_probe_command(ffprobe: str, source: str, *, start: float = 0.0, window: float = 0.0) -> list[str]:
    """ffprobe call listing keyframe positions, optionally only around a point.

    A whole-file scan on an hour of footage is slow enough to be felt, so the
    interactive path asks for a window: ffprobe answers from the keyframe at or
    before `start`, which is exactly the candidate a cut needs.

    Packets, not frames. `-skip_frame nokey` still decodes everything it does
    not skip, and on all-intra material there is nothing to skip: an ARRI ProRes
    window took 55 seconds that way, against 0.76 s here. The K flag on a packet
    says the same thing without a decoder - verified identical on long-GOP,
    all-intra, VFR, MPEG-TS and drop-frame sources.
    """
    command = [
        ffprobe,
        "-v",
        "error",
        "-select_streams",
        "v:0",
        "-show_packets",
    ]
    if window > 0:
        begin = max(0.0, float(start) - float(window))
        span = float(window) * 2
        command.extend(["-read_intervals", f"{begin:.3f}%+{span:.3f}"])
    command.extend(["-show_entries", "packet=pts_time,flags", "-of", "csv=p=0", source])
    return command


def parse_keyframe_times(output: str | Iterable[str]) -> list[float]:
    """Keyframe positions from `pts_time,flags` rows, or from bare times.

    A packet row reads `6.000000,K__`; the K marks a keyframe and the rest are
    skipped. Rows carrying only a time are still accepted, so a caller feeding
    plain timestamps keeps working.
    """
    lines = output.splitlines() if isinstance(output, str) else list(output)
    times: list[float] = []
    for line in lines:
        text = str(line).strip()
        if not text:
            continue
        parts = text.split(",")
        if len(parts) > 1 and parts[1].strip():
            if "K" not in parts[1]:
                continue
        try:
            times.append(float(parts[0].strip()))
        except ValueError:
            continue
    return sorted(set(times))


def nearest_keyframe(times: Iterable[float], requested: float) -> float | None:
    """The keyframe closest to the requested point, ties going to the earlier one."""
    candidates = [float(item) for item in times]
    if not candidates:
        return None
    target = float(requested)
    return min(candidates, key=lambda item: (abs(item - target), item))


def keyframe_at_or_after(times: Iterable[float], requested: float) -> float | None:
    """The first keyframe not earlier than the point asked for.

    Used only when removing a piece: the tail has to start past the end of what
    is being cut out, or the cut piece partly survives. Everywhere else the
    nearest keyframe is what is wanted, even if it sits earlier.
    """
    candidates = sorted(float(item) for item in times if float(item) >= float(requested) - 1e-9)
    return candidates[0] if candidates else None


def is_variable_rate(r_frame_rate: Any, avg_frame_rate: Any, *, tolerance: float = 0.01) -> bool:
    """True when the container's two rate fields disagree, which means VFR.

    A phone writes 30 fps in `r_frame_rate` and whatever it actually averaged in
    `avg_frame_rate`. Frame arithmetic on the average covers the wrong span, so
    such a source is trimmed by time instead.
    """
    try:
        nominal = float(parse_rate(r_frame_rate))
        average = float(parse_rate(avg_frame_rate))
    except (ValueError, ZeroDivisionError):
        return False
    if nominal <= 0 or average <= 0:
        return False
    return abs(nominal - average) / nominal > float(tolerance)


@dataclass(frozen=True)
class TrimCut:
    """Where the cut really lands, once keyframes and the exact rate are in."""

    requested_start: float
    requested_end: float
    start: float
    keyframe_offset: float
    frames: int | None
    tail_seconds: float | None
    kept: float
    to_end_of_file: bool


def plan_cut(
    *,
    pattern: str,
    start: Any,
    end: Any,
    duration: float,
    rate: Fraction,
    keyframes: Iterable[float],
    frame_exact: bool = True,
) -> TrimCut:
    """Turn a requested pattern into the cut FFmpeg will actually make.

    Both front-ends call this, so a trim from the GUI and a trim from the CLI
    land on the same frame. The head snaps to a keyframe because the video is
    copied; the tail is a frame count taken on the exact rate.
    """
    mode = str(pattern or "start").strip().lower()
    if mode not in TRIM_PATTERNS:
        raise ValueError(f"Unknown trim pattern: {pattern!r}")
    if mode == "middle":
        raise ValueError("Cutting a piece out of the middle is a separate operation.")
    if mode == "split":
        raise ValueError("A split is planned as two cuts, not as one.")
    if duration <= 0:
        raise ValueError("Source duration could not be read.")

    if mode == "start":
        requested_start, requested_end = parse_seconds(start or 0), float(duration)
    elif mode == "end":
        requested_start, requested_end = 0.0, parse_seconds(end if end not in (None, "") else duration)
    else:
        requested_start = parse_seconds(start or 0)
        requested_end = parse_seconds(end if end not in (None, "") else duration)

    to_end_of_file = mode == "start" or requested_end >= duration
    requested_end = min(requested_end, float(duration))
    if requested_start <= 0 and to_end_of_file:
        # Copying the whole file and calling it a trim is the one outcome that
        # looks like success and is not.
        raise ValueError("Nothing would be trimmed: no cut point is set.")
    if requested_start >= requested_end:
        raise ValueError(
            f"The kept piece is empty: {format_seconds(requested_start)} .. {format_seconds(requested_end)}"
        )

    cut_start = requested_start
    keyframe_offset = 0.0
    if requested_start > 0:
        candidates = [item for item in keyframes if item < requested_end]
        snapped = nearest_keyframe(candidates, requested_start)
        if snapped is None:
            raise ValueError("No keyframe was found for the requested cut.")
        cut_start = snapped
        keyframe_offset = snapped - requested_start
    if cut_start >= requested_end:
        raise ValueError("The nearest keyframe sits past the end point.")

    if to_end_of_file:
        return TrimCut(
            requested_start=requested_start,
            requested_end=requested_end,
            start=cut_start,
            keyframe_offset=keyframe_offset,
            frames=None,
            tail_seconds=None,
            kept=float(duration) - cut_start,
            to_end_of_file=True,
        )
    if not frame_exact:
        # Variable rate: a frame count would cover the wrong span, so the tail
        # travels as a duration and lands within a packet instead of a frame.
        tail = requested_end - cut_start
        return TrimCut(
            requested_start=requested_start,
            requested_end=requested_end,
            start=cut_start,
            keyframe_offset=keyframe_offset,
            frames=None,
            tail_seconds=tail,
            kept=tail,
            to_end_of_file=False,
        )
    frames = max(1, frames_covering(requested_end, rate) - seconds_to_frames(cut_start, rate))
    return TrimCut(
        requested_start=requested_start,
        requested_end=requested_end,
        start=cut_start,
        keyframe_offset=keyframe_offset,
        frames=frames,
        tail_seconds=None,
        kept=frames_to_seconds(frames, rate),
        to_end_of_file=False,
    )


@dataclass(frozen=True)
class TrimGap:
    """A piece removed from the middle, and the two pieces that get joined."""

    requested_start: float
    requested_end: float
    head_frames: int | None
    head_seconds: float
    tail_start: float
    keyframe_offset: float
    removed: float
    kept: float


def plan_gap(
    *,
    start: Any,
    end: Any,
    duration: float,
    rate: Fraction,
    keyframes: Iterable[float],
    frame_exact: bool = True,
) -> TrimGap:
    """Plan the removal of everything between two points.

    The head keeps whole frames up to A, counted on the exact rate. The tail
    starts at the first keyframe at or after B - never before it, or the piece
    being removed would partly survive.
    """
    if duration <= 0:
        raise ValueError("Source duration could not be read.")
    gap_start = parse_seconds(start or 0)
    gap_end = parse_seconds(end if end not in (None, "") else duration)
    if gap_end > duration:
        gap_end = float(duration)
    if gap_start <= 0:
        # That is "drop the head", which needs no joining and no second pass.
        raise ValueError("The piece to remove starts at zero: use 'drop the head' instead.")
    if gap_start >= gap_end:
        raise ValueError(
            f"The piece to remove is empty: {format_seconds(gap_start)} .. {format_seconds(gap_end)}"
        )
    if gap_end >= duration:
        # And that is "drop the tail".
        raise ValueError("The piece to remove reaches the end of the file: use 'drop the tail' instead.")

    tail_start = keyframe_at_or_after(keyframes, gap_end)
    if tail_start is None:
        raise ValueError(
            "No keyframe was found at or after the end of the removed piece, so the tail cannot be started."
        )
    if tail_start >= duration:
        raise ValueError("The first keyframe past the removed piece sits at the end of the file.")

    if frame_exact:
        head_frames: int | None = max(1, frames_covering(gap_start, rate))
        head_seconds = frames_to_seconds(head_frames, rate)
    else:
        # Variable rate: a frame count would cover the wrong span, so the head
        # travels as a duration, landing within a packet instead of a frame.
        head_frames, head_seconds = None, gap_start

    return TrimGap(
        requested_start=gap_start,
        requested_end=gap_end,
        head_frames=head_frames,
        head_seconds=head_seconds,
        tail_start=tail_start,
        keyframe_offset=tail_start - gap_end,
        removed=tail_start - head_seconds,
        kept=head_seconds + (float(duration) - tail_start),
    )


# Containers that will take a data stream at all. Measured, and one of them the
# hard way: Matroska answers "Only audio, video, and subtitles are supported for
# Matroska" and takes none. MXF was assumed to be the same and is not - a broadcast
# original carries its SMPTE 436M ancillary track (timecode, captions, camera
# metadata from the SDI stream) and takes it straight back on a cut.
DATA_STREAM_CONTAINERS = {"mov", "mp4", "m4v", "mxf"}

# And subtitles, which all of these carry in some form.
SUBTITLE_STREAM_CONTAINERS = {"mov", "mp4", "m4v", "mkv"}


def stream_display_name(stream: dict[str, Any]) -> str:
    """What to call a stream in a message the operator reads.

    The four-character tag is the recognisable name where there is one - `gpmd`
    for a GoPro, `tmcd` for a timecode track. MXF leaves it empty and ffprobe
    reports `[0][0][0][0]`, which tells nobody anything; there the codec name is
    what carries the meaning, and a broadcast original reads as
    `smpte_436m_anc`.
    """
    tag = str(stream.get("codec_tag_string") or "").strip()
    if tag and not tag.startswith("[0]"):
        return tag
    return str(stream.get("codec_name") or "data")


def stream_is_nameable(stream: dict[str, Any]) -> bool:
    """False for a stream whose codec FFmpeg cannot name.

    MP4 stops on one - "Could not find tag for codec none" - and a timecode
    track is exactly that. It travels as a value instead, so nothing is lost by
    leaving it behind.
    """
    codec = str(stream.get("codec_name") or "").strip().lower()
    return bool(codec) and codec not in {"none", "unknown"}


def extra_stream_plan(
    streams: Iterable[dict[str, Any]],
    container: str,
    *,
    want_data: bool = True,
    want_subtitles: bool = True,
    source_container: str = "",
) -> tuple[bool, bool, list[str]]:
    """What can be carried through a cut besides picture and sound.

    A GoPro writes its telemetry as a data stream and a DJI writes flight data
    as subtitles; both used to be dropped without a word. Returns whether each
    can travel, and what to say about the ones that cannot - before the run,
    not after it.
    """
    items = [item for item in streams if isinstance(item, dict)]
    data_streams = [item for item in items if str(item.get("codec_type") or "").lower() == "data"]
    subtitle_streams = [item for item in items if str(item.get("codec_type") or "").lower() == "subtitle"]
    target = str(container or "").strip().lower()
    origin = str(source_container or "").strip().lower().lstrip(".")
    warnings: list[str] = []

    keep_data = False
    if data_streams:
        names = ", ".join(sorted({stream_display_name(item) for item in data_streams}))
        if not want_data:
            warnings.append(f"The data stream ({names}) is not carried over: the checkbox is off.")
        elif target not in DATA_STREAM_CONTAINERS:
            warnings.append(
                f"{target.upper()} cannot hold a data stream, so the telemetry ({names}) stays behind. "
                "MOV, MP4 and MXF can."
            )
        elif origin and origin != target:
            # Measured the hard way: a broadcast MXF's SMPTE 436M track goes
            # straight back into MXF, and MOV refuses it outright - the run died
            # with "exit 4294967274" rather than saying anything useful. A data
            # stream is written for the format it lives in, so it travels home
            # and nowhere else.
            warnings.append(
                f"The data stream ({names}) was written for {origin.upper()} and {target.upper()} will not take it, "
                f"so it stays behind. Keeping the container as {origin.upper()} carries it over."
            )
        elif not any(stream_is_nameable(item) for item in data_streams):
            warnings.append(
                f"The data stream ({names}) has no codec FFmpeg can name, so it cannot be copied. "
                "A timecode track reads exactly like this and is written as a value instead."
            )
        else:
            keep_data = True

    keep_subtitles = False
    if subtitle_streams:
        names = ", ".join(sorted({str(item.get("codec_name") or "subtitle") for item in subtitle_streams}))
        if not want_subtitles:
            warnings.append(f"Subtitles ({names}) are not carried over: the checkbox is off.")
        elif target not in SUBTITLE_STREAM_CONTAINERS:
            warnings.append(f"{target.upper()} cannot hold subtitles ({names}), so they stay behind.")
        else:
            keep_subtitles = True

    return keep_data, keep_subtitles, warnings


def audio_channel_filter(mode: str) -> str:
    """`pan` for picking the shotgun, the lav, or a mono fold of both."""
    value = str(mode or "both").strip().lower()
    if value in {"first", "left", "c0", "1"}:
        return "pan=mono|c0=c0"
    if value in {"second", "right", "c1", "2"}:
        return "pan=mono|c0=c1"
    if value in {"mono", "downmix", "fold"}:
        return "pan=mono|c0=0.5*c0+0.5*c1"
    return ""


def audio_channel_requirement(mode: str) -> int:
    """How many channels the source must have for this choice to mean anything.

    `pan` happily maps a channel that is not there and writes silence, so the
    requirement is checked instead of trusted.
    """
    value = str(mode or "both").strip().lower()
    if value in {"first", "left", "c0", "1"}:
        return 1
    if value in {"second", "right", "c1", "2"}:
        return 2
    if value in {"mono", "downmix", "fold"}:
        return 2
    return 0


def audio_channel_complaint(mode: str, channels: int) -> str:
    """Why this channel cannot be picked from this file, or an empty string."""
    needed = audio_channel_requirement(mode)
    if needed <= 0 or channels >= needed:
        return ""
    heard = "no audio track" if channels <= 0 else f"{channels} channel" + ("s" if channels > 1 else "")
    if str(mode).strip().lower() in {"mono", "downmix", "fold"}:
        return f"Folding to mono needs two channels; this file has {heard}."
    return f"The requested channel needs at least {needed} channels; this file has {heard}."


def audio_reencode_args(codec: str, *, sample_fmt: str = "", bitrate: str = "384k") -> tuple[list[str], bool]:
    """Encoder for a rebuilt audio track, and whether that rebuild is lossless.

    PCM off a camera re-encodes to PCM at no cost in quality. A long-GOP codec
    such as AAC cannot: picking a channel there spends a generation, and the
    caller is expected to say so before the run.
    """
    name = str(codec or "").strip().lower()
    if name.startswith("pcm_"):
        # Keep the source's own endianness: a Canon MOV/MP4 stores `pcm_s16be`
        # (`twos`), and rewriting it little-endian changes the tag in the file
        # for no reason. Both containers accept either.
        big_endian = name.endswith("be")
        depth = str(sample_fmt or "").strip().lower()
        if name in {"pcm_f32le", "pcm_f32be"} or depth.startswith("flt"):
            return ["-c:a", "pcm_f32be" if big_endian else "pcm_f32le"], True
        if name in {"pcm_s16le", "pcm_s16be"} or depth in {"s16", "s16p"}:
            return ["-c:a", "pcm_s16be" if big_endian else "pcm_s16le"], True
        return ["-c:a", "pcm_s24be" if big_endian else "pcm_s24le"], True
    if name in {"flac", "alac"}:
        return ["-c:a", name], True
    if name in {"opus", "libopus"}:
        return ["-c:a", "libopus", "-b:a", bitrate], False
    if name in {"mp3", "libmp3lame"}:
        return ["-c:a", "libmp3lame", "-b:a", bitrate], False
    return ["-c:a", "aac", "-b:a", bitrate], False


def build_trim_command(
    *,
    ffmpeg: str,
    source: str,
    target: str,
    overwrite: bool,
    start_seconds: float,
    frame_count: int | None = None,
    duration_seconds: float | None = None,
    # Only for a piece that will be joined to another: see below.
    sound_to_seconds: float | None = None,
    extension: str,
    audio_mode: str = "copy",
    audio_args: list[str] | None = None,
    audio_filter: str = "",
    rewrite_audio: bool = False,
    timecode: str = "",
    faststart: bool = True,
    keep_metadata: bool = True,
    keep_data: bool = False,
    keep_subtitles: bool = False,
) -> list[str]:
    """The FFmpeg call both front-ends use for a single-piece trim.

    `-ss` sits before `-i` so the seek is a fast one. The tail is a frame count
    whenever the frame rate is known, because `-t` overshoots by a frame or
    three on a stream with B-frames; `duration_seconds` is the fallback for a
    source whose rate could not be read.
    """
    command = [ffmpeg, "-hide_banner", "-stats", "-y" if overwrite else "-n", "-nostdin"]
    if start_seconds > 0:
        command.extend(["-ss", f"{float(start_seconds):.6f}"])
    command.extend(["-i", source])
    if frame_count is not None and int(frame_count) > 0:
        command.extend(["-frames:v", str(int(frame_count))])
        if sound_to_seconds is not None and sound_to_seconds > 0:
            # `-frames:v` stops the picture on the frame asked for and stops
            # everything else with it, leaving the sound a few milliseconds
            # short - measured at 16 ms on a 25 fps PCM take. Harmless at the
            # end of a file, and not harmless when this piece is about to be
            # joined to another, where the shortfall lands on the joint. The
            # caller asks for this explicitly; a frame count still wins over a
            # plain duration everywhere else.
            command.extend(["-t", f"{float(sound_to_seconds):.6f}"])
    elif duration_seconds is not None and duration_seconds > 0:
        command.extend(["-t", f"{float(duration_seconds):.6f}"])
    command.extend(["-map", "0:v:0"])
    silent = str(audio_mode or "copy").strip().lower() in {"none", "off", "mute", "drop"}
    if silent:
        command.append("-an")
    else:
        command.extend(["-map", "0:a?"])
    # Everything that is neither picture nor sound: a GoPro's telemetry rides in
    # a data stream, a DJI's flight log in subtitles. Dropped by default because
    # most containers refuse them, kept when the operator asks and the caller
    # has checked that this container will take them.
    if keep_subtitles:
        command.extend(["-map", "0:s?"])
    else:
        command.append("-sn")
    if keep_data:
        # `-copy_unknown` is required: a data stream FFmpeg cannot name is
        # dropped without it, and the run fails outright with it in a container
        # that will not take the stream - which is why the caller checks first.
        command.extend(["-map", "0:d?", "-copy_unknown"])
    else:
        command.append("-dn")
    command.extend(["-c:v", "copy"])
    if not silent:
        if audio_filter:
            command.extend(["-af", audio_filter, *(audio_args or ["-c:a", "aac", "-b:a", "384k"])])
        elif rewrite_audio and audio_args:
            # Same format, written again: the encoder cuts on the sample asked
            # for, where a copy would carry whole chunks.
            command.extend(audio_args)
        else:
            command.extend(["-c:a", "copy"])
    if keep_metadata:
        command.extend(["-map_metadata", "0"])
    if timecode:
        command.extend(["-timecode", timecode])
    if str(extension or "").strip().lower() in {"mp4", "m4v", "mov"}:
        # `use_metadata_tags` is what actually carries the camera's own fields -
        # make, model, the brand string - across a remux. `-map_metadata` alone
        # leaves the muxer writing generic brands and dropping the rest.
        flags = "use_metadata_tags"
        if faststart:
            flags += "+faststart"
        command.extend(["-movflags", flags])
    command.append(target)
    return command
