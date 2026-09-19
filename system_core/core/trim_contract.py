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
from typing import Any, Iterable, Sequence
import bisect
import math
import re

from system_core.core.audio_contract import (
    mp3_bitrate,
    mp3_encoder_args,
    normalize_mp3_preset,
    soxr_resample_filter,
)


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


@dataclass(frozen=True)
class TrimSplitPart:
    """One part of a split: it starts on a keyframe and ends where the next begins."""

    index: int
    start: float
    end: float | None
    frames: int | None
    seconds: float


@dataclass(frozen=True)
class TrimSplit:
    """Where the points were asked for, where they landed, and the parts between."""

    requested: tuple[float, ...]
    boundaries: tuple[float, ...]
    offsets: tuple[float, ...]
    parts: tuple[TrimSplitPart, ...]


def plan_split(
    *,
    points: Iterable[Any],
    duration: float,
    rate: Fraction,
    keyframes: Iterable[float],
    frame_exact: bool = True,
) -> TrimSplit:
    """Plan a split at one point or two, so the parts add back up to the file.

    Each point snaps to its nearest keyframe, and that keyframe is the joint for
    both neighbours: the part before ends on the frame just ahead of it, the part
    after starts on it. Nothing lands in two parts and nothing falls between.
    """
    if duration <= 0:
        raise ValueError("Source duration could not be read.")
    requested = sorted(parse_seconds(item) for item in points if str(item if item is not None else "").strip())
    if not requested:
        raise ValueError("A split needs a point: set IN, or IN and OUT for three parts.")
    if len(requested) > 2:
        raise ValueError("A split takes one point or two.")
    for point in requested:
        if point <= 0 or point >= duration:
            raise ValueError(f"The point {format_seconds(point)} lies outside the file.")

    candidates = [float(item) for item in keyframes]
    boundaries: list[float] = []
    for point in requested:
        keyframe = nearest_keyframe(candidates, point)
        if keyframe is None:
            raise ValueError(f"No keyframe was found near {format_seconds(point)}.")
        if keyframe <= 0 or keyframe >= duration:
            raise ValueError(
                f"The point {format_seconds(point)} lands on the keyframe at the edge of the file, "
                "so there is nothing to split off there."
            )
        boundaries.append(keyframe)
    if len(boundaries) == 2 and boundaries[0] == boundaries[1]:
        raise ValueError(
            f"Both points land on the keyframe at {format_seconds(boundaries[0])}, "
            "so the middle part would be empty. Move them further apart."
        )

    starts = [0.0, *boundaries]
    ends: list[float | None] = [*boundaries, None]
    parts: list[TrimSplitPart] = []
    for index, (start, end) in enumerate(zip(starts, ends), start=1):
        if end is None:
            parts.append(TrimSplitPart(index=index, start=start, end=None, frames=None, seconds=float(duration) - start))
            continue
        if frame_exact:
            # Round, not ceil: a keyframe timestamp is already a frame boundary.
            frames = seconds_to_frames(end, rate) - seconds_to_frames(start, rate)
            parts.append(TrimSplitPart(index=index, start=start, end=end, frames=frames, seconds=frames_to_seconds(frames, rate)))
        else:
            parts.append(TrimSplitPart(index=index, start=start, end=end, frames=None, seconds=end - start))

    return TrimSplit(
        requested=tuple(requested),
        boundaries=tuple(boundaries),
        offsets=tuple(boundary - point for boundary, point in zip(boundaries, requested)),
        parts=tuple(parts),
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


# ---------------------------------------------------------------------------
# Sound files
#
# A file of sound alone has no keyframes, so nothing has to snap: a point is the
# sample nearest to it. Each piece is decoded from the start of the file and cut
# by sample number with `atrim`, which is exact for every codec. Measured on WAV,
# FLAC, MP3, AAC and Vorbis: the piece is, bit for bit, the same slice of the
# fully decoded source. `asetpts=N/SR/TB` numbers the samples as the decoder
# hands them over, so a file whose clock starts late - an MP3 with its encoder
# delay - still counts from the first sample a player plays.
# ---------------------------------------------------------------------------

# Codecs that give back exactly the samples they were given.
LOSSLESS_AUDIO_CODECS = {"flac", "alac", "wavpack", "tta", "ape", "tak", "mlp", "truehd", "shorten", "mp4als", "ralf"}


def audio_codec_is_lossless(codec: str) -> bool:
    name = str(codec or "").strip().lower()
    return name.startswith("pcm_") or name in LOSSLESS_AUDIO_CODECS


@dataclass(frozen=True)
class AudioPiece:
    """Samples from `start` up to, and not including, `end`; no `end` runs to the end of the file."""

    start: int
    end: int | None


@dataclass(frozen=True)
class AudioTrim:
    """Where a sound file is cut, in samples."""

    action: str
    sample_rate: int
    total: int
    requested: tuple[float, ...]
    pieces: tuple[AudioPiece, ...]
    # A cut joins its pieces into one file; a keep or a split writes each to its own.
    joined: bool

    def length(self, piece: AudioPiece) -> int:
        return (self.total if piece.end is None else piece.end) - piece.start

    @property
    def kept(self) -> int:
        return sum(self.length(piece) for piece in self.pieces)


def seconds_to_sample(seconds: float, sample_rate: int) -> int:
    """The sample nearest to a wall-clock position; a tie goes to the later one."""
    return int(math.floor(float(seconds) * int(sample_rate) + 0.5))


def _point_given(value: Any) -> bool:
    return str(value if value is not None else "").strip() != ""


def plan_audio_trim(
    *,
    pattern: str,
    start: Any,
    end: Any,
    duration: float,
    sample_rate: int,
    total_samples: int | None = None,
) -> AudioTrim:
    """Turn a trim pattern into sample numbers for a file of sound alone.

    The patterns and the refusals are the ones the picture uses, so both paths
    answer the same question the same way. Only nothing snaps: there is no
    keyframe to wait for, and the joint between two pieces is one sample
    boundary.
    """
    mode = str(pattern or "").strip().lower()
    if mode not in TRIM_PATTERNS:
        raise ValueError(f"Unknown trim pattern: {pattern!r}")
    rate = int(sample_rate or 0)
    if rate <= 0:
        raise ValueError("The sample rate could not be read.")
    # A count the file states outright beats one worked out from its duration.
    total = int(total_samples or 0)
    if total <= 0:
        total = seconds_to_sample(float(duration or 0.0), rate)
    if total <= 0:
        raise ValueError("Source duration could not be read.")

    def sample(value: Any) -> int:
        return min(max(seconds_to_sample(parse_seconds(value), rate), 0), total)

    if mode == "split":
        asked = sorted(parse_seconds(item) for item in (start, end) if _point_given(item))
        if not asked:
            raise ValueError("A split needs a point: set IN, or IN and OUT for three parts.")
        cuts: list[int] = []
        for point in asked:
            at = seconds_to_sample(point, rate)
            if at <= 0 or at >= total:
                raise ValueError(f"The point {format_seconds(point)} lies outside the file.")
            cuts.append(at)
        if len(cuts) == 2 and cuts[0] == cuts[1]:
            raise ValueError(
                f"Both points fall on sample {cuts[0]}, so the middle part would be empty. Move them further apart."
            )
        starts = [0, *cuts]
        ends: list[int | None] = [*cuts, None]
        pieces = tuple(AudioPiece(first, last) for first, last in zip(starts, ends))
        return AudioTrim("split", rate, total, tuple(asked), pieces, joined=False)

    if mode == "middle":
        if not (_point_given(start) and _point_given(end)):
            raise ValueError("Cutting a piece out needs both IN and OUT.")
        first, last = parse_seconds(start), parse_seconds(end)
        gap_start, gap_end = sample(start), sample(end)
        if gap_start >= gap_end:
            raise ValueError(f"The piece to remove is empty: {format_seconds(first)} .. {format_seconds(last)}")
        if gap_start <= 0:
            raise ValueError("The piece to remove starts at zero: Keep it with IN alone does exactly that.")
        if gap_end >= total:
            raise ValueError("The piece to remove reaches the end of the file: Keep it with OUT alone does exactly that.")
        pieces = (AudioPiece(0, gap_start), AudioPiece(gap_end, None))
        return AudioTrim("cut", rate, total, (first, last), pieces, joined=True)

    head_given = mode in {"start", "both"} and _point_given(start)
    tail_given = mode in {"end", "both"} and _point_given(end)
    first = parse_seconds(start) if head_given else 0.0
    last = parse_seconds(end) if tail_given else total / rate
    head = sample(start) if head_given else 0
    tail = sample(end) if tail_given else total
    if head <= 0 and tail >= total:
        raise ValueError("Nothing would be trimmed: no cut point is set.")
    if head >= tail:
        raise ValueError(f"The kept piece is empty: {format_seconds(first)} .. {format_seconds(last)}")
    piece = AudioPiece(head, None if tail >= total else tail)
    return AudioTrim("keep", rate, total, (first, last), (piece,), joined=False)


def _atrim(piece: AudioPiece) -> str:
    bounds = []
    if piece.start > 0:
        bounds.append(f"start_sample={piece.start}")
    if piece.end is not None:
        bounds.append(f"end_sample={piece.end}")
    return f"atrim={':'.join(bounds)}," if bounds else ""


def audio_trim_filter(piece: AudioPiece, tail_filter: str = "") -> str:
    """One piece: number the samples, cut on them, start the piece's clock at zero."""
    chain = f"asetpts=N/SR/TB,{_atrim(piece)}asetpts=PTS-STARTPTS"
    return f"{chain},{tail_filter}" if tail_filter else chain


def audio_join_graph(pieces: Sequence[AudioPiece], tail_filter: str = "") -> str:
    """Pieces of one file joined into one, in a single pass - a cut.

    Measured: the result is bit for bit the source without the removed samples,
    on WAV and on FLAC. Nothing is written in between.
    """
    count = len(pieces)
    head = f"[0:a:0]asetpts=N/SR/TB,asplit={count}" + "".join(f"[s{index}]" for index in range(count))
    chains = [f"[s{index}]{_atrim(piece)}asetpts=PTS-STARTPTS[p{index}]" for index, piece in enumerate(pieces)]
    join = "".join(f"[p{index}]" for index in range(count)) + f"concat=n={count}:v=0:a=1"
    if tail_filter:
        join += f",{tail_filter}"
    return ";".join([head, *chains, join + "[out]"])


def build_audio_trim_command(
    *,
    ffmpeg: str,
    source: str,
    target: str,
    overwrite: bool,
    pieces: Sequence[AudioPiece],
    codec_args: Sequence[str],
    tail_filter: str = "",
    keep_cover: bool = False,
    metadata: Sequence[str] = (),
    muxer_args: Sequence[str] = (),
) -> list[str]:
    """The FFmpeg call for a piece of a sound file, or for several joined into one."""
    if not pieces:
        raise ValueError("There is no piece to write.")
    command = [ffmpeg, "-hide_banner", "-stats", "-y" if overwrite else "-n", "-nostdin", "-i", source]
    if len(pieces) == 1:
        command += ["-map", "0:a:0", "-af", audio_trim_filter(pieces[0], tail_filter)]
    else:
        command += ["-filter_complex", audio_join_graph(pieces, tail_filter), "-map", "[out]"]
    if keep_cover:
        # Cover art is a still picture: copied as it is, and marked as the cover again.
        command += ["-map", "0:v?", "-c:v", "copy", "-disposition:v:0", "attached_pic"]
    else:
        command.append("-vn")
    command += ["-sn", "-dn", *codec_args, "-map_metadata", "0", *metadata, *muxer_args, target]
    return command


AUDIO_TRIM_FORMATS = ("source", "wav", "flac", "alac", "m4a", "mp3", "opus")

# Where a codec can be written back as itself, by the extension the file came in.
AUDIO_AS_IS_CONTAINERS = {
    "pcm": {"wav", "w64", "aif", "aiff", "aifc", "caf", "au", "snd", "mka"},
    "flac": {"flac", "mka", "oga", "ogg"},
    "alac": {"m4a", "m4b", "caf", "mka"},
    "wavpack": {"wv", "mka"},
    "tta": {"tta", "mka"},
    "mp3": {"mp3", "mka"},
    "aac": {"m4a", "m4b", "aac", "mka"},
    "opus": {"opus", "ogg", "oga", "mka"},
    "vorbis": {"ogg", "oga", "mka"},
    "ac3": {"ac3", "mka"},
    "eac3": {"eac3", "mka"},
}

# A compressed codec written back as itself: the encoder, the bitrate used when
# the file states none, and the ceiling.
AUDIO_LOSSY_REWRITERS = {
    "mp3": ("libmp3lame", 320, 320),
    "aac": ("aac", 256, 512),
    "opus": ("libopus", 192, 510),
    "vorbis": ("libvorbis", 320, 500),
    "ac3": ("ac3", 448, 640),
    "eac3": ("eac3", 640, 1536),
}
MP3_CBR_STEPS = (32, 40, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320)
OPUS_SAMPLE_RATES = {8000, 12000, 16000, 24000, 48000}
# Containers that keep an attached cover picture. Measured: WAV and Opus refuse one.
AUDIO_COVER_CONTAINERS = {"mp3", "m4a", "m4b", "flac", "mka"}
# Extensions FFmpeg does not map to their muxer on its own.
AUDIO_MUXER_BY_EXTENSION = {"snd": "au"}
WAV_CODEC_BY_DEPTH = {
    "u8": "pcm_u8",
    "s16": "pcm_s16le",
    "s24": "pcm_s24le",
    "s32": "pcm_s32le",
    "f32": "pcm_f32le",
    "f64": "pcm_f64le",
}
DEPTH_WORDS = {
    "u8": "8-bit",
    "s16": "16-bit",
    "s24": "24-bit",
    "s32": "32-bit",
    "f32": "32-bit float",
    "f64": "64-bit float",
}


@dataclass(frozen=True)
class AudioEncoding:
    """How a piece of a sound file is written, and what that costs."""

    codec_args: tuple[str, ...]
    extension: str
    output_rate: int
    # True when the piece holds exactly the samples the decoder gives for that stretch.
    lossless: bool
    label: str
    tail_filter: str = ""
    muxer_args: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()


def audio_sample_depth(codec: str, sample_fmt: str = "", bits: Any = None) -> str:
    """What the source's samples really hold: u8, s16, s24, s32, f32 or f64.

    A 24-bit FLAC decodes to 32-bit integers, so the format alone overstates it;
    `bits_per_raw_sample` says what is really there.
    """
    name = str(codec or "").strip().lower()
    match = re.match(r"pcm_([suf])(\d+)", name)
    if match:
        kind, width = match.group(1), int(match.group(2))
        if kind == "f":
            return "f64" if width == 64 else "f32"
        if kind == "u" and width == 8:
            return "u8"
        return "s16" if width <= 16 else "s24" if width <= 24 else "s32"
    fmt = str(sample_fmt or "").strip().lower()
    if fmt.endswith("p"):
        fmt = fmt[:-1]
    if fmt in {"flt", "dbl", "u8", "s16"}:
        return {"flt": "f32", "dbl": "f64", "u8": "u8", "s16": "s16"}[fmt]
    try:
        width = int(bits or 0)
    except (TypeError, ValueError):
        width = 0
    if 0 < width <= 16:
        return "s16"
    if 0 < width <= 24:
        return "s24"
    return "s32"


def _kbps(value: Any, default: int) -> int:
    text = str(value or "").strip().lower()
    for suffix in ("kbps", "kb/s", "k"):
        if text.endswith(suffix):
            text = text[: -len(suffix)]
            break
    try:
        number = int(float(text))
    except ValueError:
        return default
    return number if number > 0 else default


def _rewrite_kbps(family: str, bit_rate: Any) -> int:
    """The source's own bitrate, raised to a step the encoder takes, never above its ceiling."""
    _encoder, fallback, ceiling = AUDIO_LOSSY_REWRITERS[family]
    try:
        kbps = math.ceil(int(bit_rate) / 1000)
    except (TypeError, ValueError):
        kbps = fallback
    if kbps <= 0:
        kbps = fallback
    if family == "mp3":
        kbps = next((step for step in MP3_CBR_STEPS if step >= kbps), MP3_CBR_STEPS[-1])
    return min(kbps, ceiling)


def audio_trim_encoding(
    *,
    choice: str,
    codec: str,
    extension: str,
    sample_rate: int,
    channels: int,
    sample_fmt: str = "",
    bits: Any = None,
    bit_rate: Any = None,
    mp3_preset: Any = "v0",
    bitrate: Any = "320k",
) -> AudioEncoding:
    """Decide what a piece is written as: what the source was, or a format from the Audio set.

    Every path starts from the decoded sound, cut on the sample. What is decided
    here is only what that sound is written as, and whether writing it spends a
    generation.
    """
    wanted = str(choice or "source").strip().lower()
    if wanted not in AUDIO_TRIM_FORMATS:
        raise ValueError(f"Unknown format for a piece of sound: {choice!r}")
    name = str(codec or "").strip().lower()
    title = name.upper() or "This codec"
    ext = str(extension or "").strip().lower().lstrip(".")
    rate = int(sample_rate)
    count = int(channels or 0)
    lossless_source = audio_codec_is_lossless(name)
    # A compressed source decodes to float, and float is the sound there is to keep.
    depth = audio_sample_depth(name, sample_fmt, bits) if lossless_source else "f32"

    if wanted == "source":
        if name.startswith("dsd_"):
            raise ValueError("DSD cannot be written back as DSD. Choose FLAC or WAV: they keep the decoded sound.")
        family = "pcm" if name.startswith("pcm_") else name
        containers = AUDIO_AS_IS_CONTAINERS.get(family)
        if containers is None:
            raise ValueError(
                f"{title} cannot be written back as it is. "
                "Choose FLAC or WAV for the same sound, or M4A, MP3 or Opus to compress it."
            )
        if ext not in containers:
            raise ValueError(f"{title} cannot be written back into .{ext}. Choose FLAC or WAV for the same sound.")
        muxer: tuple[str, ...] = ("-f", AUDIO_MUXER_BY_EXTENSION[ext]) if ext in AUDIO_MUXER_BY_EXTENSION else ()
        if ext == "wav":
            # A piece of a long multichannel take can pass 4 GB, where plain RIFF ends.
            muxer += ("-rf64", "auto")
        if lossless_source:
            args = ("-c:a", "flac", "-compression_level", "8") if family == "flac" else ("-c:a", name)
            return AudioEncoding(args, ext, rate, True, f"{title} as it was, sample for sample", muxer_args=muxer)
        encoder = AUDIO_LOSSY_REWRITERS[family][0]
        kbps = _rewrite_kbps(family, bit_rate)
        return AudioEncoding(
            ("-c:a", encoder, "-b:a", f"{kbps}k"),
            ext,
            rate,
            False,
            f"{title} encoded again at {kbps} kbps",
            muxer_args=muxer,
            warnings=(
                f"{title} is compressed, so a cut on the sample encodes it once more: one generation. "
                "WAV or FLAC keep the decoded sound with nothing lost after the cut.",
            ),
        )

    if wanted == "wav":
        return AudioEncoding(
            ("-c:a", WAV_CODEC_BY_DEPTH[depth]),
            "wav",
            rate,
            True,
            f"WAV {DEPTH_WORDS[depth]}",
            muxer_args=("-rf64", "auto"),
        )

    if wanted in {"flac", "alac"}:
        title_out = wanted.upper()
        if count > 8:
            raise ValueError(f"{title_out} holds up to eight channels; this file has {count}. Choose WAV.")
        fits = depth in {"u8", "s16", "s24"}
        warnings: tuple[str, ...] = ()
        if lossless_source and not fits:
            warnings = (
                f"{title_out} holds 24 bits at most, so this {DEPTH_WORDS[depth]} source is stored at 24. WAV keeps every bit.",
            )
        stored = {"u8": "16-bit", "s16": "16-bit"}.get(depth, "24-bit")
        if wanted == "flac":
            args: tuple[str, ...] = ("-c:a", "flac", "-compression_level", "8")
            return AudioEncoding(args, "flac", rate, lossless_source and fits, f"FLAC {stored}", warnings=warnings)
        return AudioEncoding(("-c:a", "alac"), "m4a", rate, lossless_source and fits, f"ALAC {stored}", warnings=warnings)

    if wanted == "m4a":
        kbps = min(_kbps(bitrate, 320), 512)
        return AudioEncoding(("-c:a", "aac", "-b:a", f"{kbps}k"), "m4a", rate, False, f"AAC {kbps} kbps")

    if wanted == "mp3":
        if count > 2:
            raise ValueError(f"MP3 holds one or two channels; this file has {count}. Choose M4A, Opus, FLAC or WAV.")
        # LAME stops at 48 kHz; below that the rate stays as it is.
        tail = soxr_resample_filter(48000) if rate > 48000 else ""
        preset = normalize_mp3_preset(mp3_preset)
        label = {"v0": "MP3 VBR V0", "insane": "MP3 CBR 320 kbps"}.get(preset) or (
            f"MP3 CBR {mp3_bitrate(bitrate).removesuffix('k')} kbps"
        )
        return AudioEncoding(
            tuple(mp3_encoder_args(mp3_preset, bitrate)),
            "mp3",
            48000 if tail else rate,
            False,
            label,
            tail_filter=tail,
        )

    if count > 8:
        raise ValueError(f"Opus holds up to eight channels; this file has {count}. Choose WAV or FLAC.")
    kbps = min(_kbps(bitrate, 256), 256)
    # Opus works at 48 kHz and a few divisions of it; anything else goes there through soxr.
    tail = "" if rate in OPUS_SAMPLE_RATES else soxr_resample_filter(48000)
    return AudioEncoding(
        ("-c:a", "libopus", "-b:a", f"{kbps}k"),
        "opus",
        48000 if tail else rate,
        False,
        f"Opus {kbps} kbps",
        tail_filter=tail,
    )


# FFmpeg reads a Broadcast WAV's `bext` chunk into tags named its own way and
# writes the chunk back only when asked, from tags named another way again.
# Measured: without `-write_bext 1` the chunk is gone; with it, description,
# originator, date and time come back empty unless handed over by these names.
BEXT_FIELDS_FROM_TAGS = (
    ("description", "comment"),
    ("originator", "encoded_by"),
    ("origination_date", "date"),
    ("origination_time", "creation_time"),
)


def audio_trim_metadata(
    tags: dict[str, Any] | None,
    *,
    start_sample: int,
    extension: str,
    broadcast_wav: bool,
) -> tuple[list[str], list[str], tuple[int, int] | None]:
    """Tags and muxer options for one piece, and the time reference before and after.

    A recorder stamps its WAV with the samples since midnight at which the take
    began. A piece that starts later began later, exactly as a shifted timecode
    says for picture, so the reference moves by the samples cut off the head.
    """
    values = {str(key).lower(): str(value) for key, value in (tags or {}).items()}
    metadata: list[str] = []
    muxer: list[str] = []
    moved: tuple[int, int] | None = None
    reference = values.get("time_reference", "").strip()
    if reference.isdigit():
        moved = (int(reference), int(reference) + int(start_sample))
        if moved[1] != moved[0]:
            metadata += ["-metadata", f"time_reference={moved[1]}"]
    if broadcast_wav and str(extension or "").strip().lower() == "wav":
        muxer += ["-write_bext", "1"]
        for field, tag in BEXT_FIELDS_FROM_TAGS:
            value = values.get(tag, "").strip()
            if value:
                metadata += ["-metadata", f"{field}={value}"]
    return metadata, muxer, moved


# ---------------------------------------------------------------------------
# Sound copied packet by packet - for the purist, with Exact cut off.
#
# Nothing is decoded and nothing is encoded, so no generation is spent, and each
# point moves to the nearest packet boundary instead of the sample. What a joint
# then costs depends on the codec. Every rule below was measured on a 30 s stereo
# take by decoding the pieces and comparing them, sample by sample, with the
# decoded source.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PacketCopyRule:
    """How one codec is copied, and what that was measured to cost."""

    codec: str
    containers: frozenset[str]
    # Packets copied ahead of a piece: a Vorbis decoder throws the first packet's sound away.
    lead_in: int
    # MP3 keeps its encoder-delay header only on a piece that starts the file;
    # anywhere else the decoder would cut the delay off again and shift the sound.
    header_only_at_start: bool
    # An AAC join replays the priming the source's edit list hid, unless its
    # clock is moved back by exactly that much.
    join_clock_back: bool
    warning: str


PACKET_COPY_RULES = {
    "mp3": PacketCopyRule(
        "mp3",
        frozenset({"mp3"}),
        0,
        True,
        False,
        "MP3 copied packet by packet: after a joint the first 34 ms sound slightly different, because an MP3 frame "
        "borrows bits from the frame before it (1 632 samples, measured). A piece that runs to the end without "
        "starting the file keeps the encoder's end padding, under one frame.",
    ),
    "aac": PacketCopyRule(
        "aac",
        frozenset({"m4a", "m4b"}),
        0,
        False,
        True,
        "AAC copied packet by packet: after a joint the first 21 ms sound slightly different, because each frame "
        "overlaps the one before it (1 024 samples, measured).",
    ),
    "vorbis": PacketCopyRule(
        "vorbis",
        frozenset({"ogg", "oga"}),
        1,
        False,
        False,
        "Vorbis copied packet by packet: a piece starts one packet early, since the decoder throws its first packet "
        "away, and is then the source bit for bit. The joint of a cut sounds different for 21 ms (1 024 samples, measured).",
    ),
    "opus": PacketCopyRule(
        "opus",
        frozenset({"opus", "ogg", "oga"}),
        0,
        False,
        False,
        "Opus copied packet by packet: after a joint the decoder takes about half a second to settle, and a piece "
        "that does not start the file begins late by the codec's pre-skip - 312 samples on the measured take. "
        "Exact cut avoids both.",
    ),
}


@dataclass(frozen=True)
class PacketPiece:
    """A piece copied packet by packet, and where its sound sits in the decoded source."""

    packet: int
    end_packet: int | None
    start_sample: int
    end_sample: int | None
    # Output seek points, halfway through the packet before a boundary, so no
    # rounding can put a packet on the wrong side. None: from the first packet, or to the end.
    copy_from: float | None
    copy_to: float | None
    # MP3 only: whether the encoder-delay header is written.
    header: bool


@dataclass(frozen=True)
class PacketCopy:
    """A sound trim moved onto packet boundaries."""

    trim: AudioTrim
    rule: PacketCopyRule
    # Each point asked for, and the packet boundary it landed on, in samples.
    moves: tuple[tuple[int, int], ...]
    pieces: tuple[PacketPiece, ...]

    def length(self, piece: PacketPiece) -> int:
        return (self.trim.total if piece.end_sample is None else piece.end_sample) - piece.start_sample

    @property
    def kept(self) -> int:
        return sum(self.length(piece) for piece in self.pieces)


def plan_packet_copy(*, trim: AudioTrim, rule: PacketCopyRule, packet_starts: Sequence[int]) -> PacketCopy:
    """Move every sample boundary of a sound trim to the nearest packet boundary.

    `packet_starts` holds where each packet's sound begins in the decoded source,
    in samples - negative for the priming an MP3 or an AAC file hides.
    """
    starts = [int(item) for item in packet_starts]
    if len(starts) < 2:
        raise ValueError("The packets of this file could not be read.")
    rate = trim.sample_rate
    moves: list[tuple[int, int]] = []
    landed: dict[int, int] = {}

    def land(sample: int) -> int:
        if sample not in landed:
            index = bisect.bisect_left(starts, sample)
            candidates = [item for item in (index - 1, index) if 1 <= item < len(starts)]
            if candidates:
                packet = min(candidates, key=lambda item: (abs(starts[item] - sample), item))
            else:
                packet = 1 if index <= 1 else len(starts) - 1
            landed[sample] = packet
            moves.append((sample, starts[packet]))
        return landed[sample]

    def seek(packet: int) -> float:
        return (starts[packet] + starts[packet - 1]) / (2 * rate)

    pieces: list[PacketPiece] = []
    for piece in trim.pieces:
        first = 0 if piece.start <= 0 else land(piece.start)
        last = None if piece.end is None else land(piece.end)
        if last is not None and first >= last:
            raise ValueError(
                f"Both points land on the packet boundary at {format_seconds(starts[last] / rate)}, so the piece "
                "between them would be empty. Move them further apart, or turn Exact cut on."
            )
        # A joined stream decodes straight on through the joint, so nothing is thrown away there.
        lead = 0 if (trim.joined or first == 0) else rule.lead_in
        copy_packet = max(0, first - lead)
        pieces.append(
            PacketPiece(
                packet=first,
                end_packet=last,
                start_sample=0 if first == 0 else starts[first],
                end_sample=None if last is None else starts[last],
                copy_from=None if copy_packet == 0 else seek(copy_packet),
                copy_to=None if last is None else seek(last),
                header=trim.joined or first == 0 or not rule.header_only_at_start,
            )
        )
    if trim.joined and pieces[0].end_packet is not None and pieces[0].end_packet >= pieces[-1].packet:
        raise ValueError(
            "The piece to remove is shorter than a packet, so nothing would be removed. Turn Exact cut on to remove it on the sample."
        )
    return PacketCopy(trim, rule, tuple(moves), tuple(pieces))


def build_packet_copy_command(
    *,
    ffmpeg: str,
    source: str,
    target: str,
    overwrite: bool,
    piece: PacketPiece,
    keep_cover: bool = False,
    metadata: Sequence[str] = (),
) -> list[str]:
    """One piece, packets copied untouched. The seek is an output option: it drops packets, it decodes nothing."""
    command = [ffmpeg, "-hide_banner", "-stats", "-y" if overwrite else "-n", "-nostdin", "-i", source, "-map", "0:a:0"]
    if keep_cover:
        command += ["-map", "0:v?", "-c:v", "copy", "-disposition:v:0", "attached_pic"]
    else:
        command.append("-vn")
    command += ["-sn", "-dn", "-c:a", "copy", "-map_metadata", "0", *metadata]
    if not piece.header:
        command += ["-write_xing", "0"]
    if piece.copy_from is not None:
        command += ["-ss", f"{piece.copy_from:.6f}"]
    if piece.copy_to is not None:
        command += ["-to", f"{piece.copy_to:.6f}"]
    command.append(target)
    return command


def build_packet_join_command(
    *,
    ffmpeg: str,
    list_file: str,
    source: str,
    target: str,
    overwrite: bool,
    clock_back: float = 0.0,
    keep_cover: bool = False,
) -> list[str]:
    """Copied pieces glued by the concat demuxer; tags and the cover come from the source itself."""
    command = [
        ffmpeg,
        "-hide_banner",
        "-stats",
        "-y" if overwrite else "-n",
        "-nostdin",
        "-f",
        "concat",
        "-safe",
        "0",
        "-i",
        list_file,
        "-i",
        source,
        "-map",
        "0:a:0",
    ]
    if keep_cover:
        command += ["-map", "1:v?", "-c:v", "copy", "-disposition:v:0", "attached_pic"]
    command += ["-c:a", "copy", "-map_metadata", "1"]
    if clock_back > 0:
        # Measured on AAC in M4A: with the clock moved back by the priming, the
        # join is exactly as long as planned; without it, 1 024 samples long and shifted.
        command += ["-output_ts_offset", f"{-clock_back:.6f}"]
    command.append(target)
    return command
