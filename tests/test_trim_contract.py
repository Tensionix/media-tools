"""The trimming arithmetic is checked here, because the field it lives in lies.

Every number in this file traces back to a measured defect. Shutter Encoder 20.2
converts a timecode to a frame index through `round(fps)`, so a four-minute cut
on 29.97 comes out 0.273 s long and an hour comes out four seconds long. The
tests below pin the two habits that prevent it: seconds and frames always meet
through the exact `Fraction`, and a cut point is wall-clock time rather than a
timecode that only looks like it.
"""

from __future__ import annotations

from fractions import Fraction

import pytest

from system_core.core.trim_contract import (
    audio_channel_complaint,
    audio_channel_requirement,
    build_trim_command,
    DATA_STREAM_CONTAINERS,
    extra_stream_plan,
    stream_display_name,
    format_offset,
    format_seconds,
    format_timecode,
    frames_covering,
    frames_to_seconds,
    is_variable_rate,
    keyframe_at_or_after,
    keyframe_probe_command,
    nearest_keyframe,
    parse_keyframe_times,
    parse_rate,
    parse_seconds,
    rate_label,
    parse_timecode,
    plan_cut,
    plan_gap,
    seconds_to_frames,
    shift_timecode,
    timecode_base,
)


NTSC_24 = Fraction(24000, 1001)
NTSC_30 = Fraction(30000, 1001)
NTSC_60 = Fraction(60000, 1001)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("12.5", 12.5),
        ("12,5", 12.5),
        ("90", 90.0),
        ("1:02.5", 62.5),
        ("00:01:28,400", 88.4),
        ("01:00:00", 3600.0),
    ],
)
def test_parse_seconds_reads_the_usual_spellings(text: str, expected: float) -> None:
    assert parse_seconds(text) == pytest.approx(expected)


@pytest.mark.parametrize("text", ["", "abc", "1:2:3:4", "-5", "10:xx"])
def test_parse_seconds_rejects_nonsense(text: str) -> None:
    with pytest.raises(ValueError):
        parse_seconds(text)


def test_parse_seconds_refuses_a_four_field_timecode() -> None:
    """`00:04:00:00` is a timecode, not a duration, and mixing them is the bug."""
    with pytest.raises(ValueError):
        parse_seconds("00:04:00:00")


def test_format_seconds_and_offset_read_like_the_interface() -> None:
    assert format_seconds(88.4, decimals=1, separator=",") == "00:01:28,4"
    assert format_seconds(3661.5) == "01:01:01.500"
    assert format_offset(-1.6, separator=",") == "-1,6 s"
    assert format_offset(0.25) == "+0.2 s"


@pytest.mark.parametrize(
    ("rate", "base"),
    [(NTSC_24, 24), (Fraction(25), 25), (NTSC_30, 30), (Fraction(50), 50), (NTSC_60, 60)],
)
def test_timecode_base_rounds_up_to_the_clock(rate: Fraction, base: int) -> None:
    assert timecode_base(rate) == base


def test_parse_rate_keeps_the_fraction_exact() -> None:
    assert parse_rate("24000/1001") == NTSC_24
    assert parse_rate("25") == Fraction(25)
    with pytest.raises(ValueError):
        parse_rate("0/0")


def test_seconds_to_frames_uses_the_exact_rate() -> None:
    """Four minutes at 29.97 is frame 7193. Rounding the rate says 7200."""
    assert seconds_to_frames(240.0, NTSC_30) == 7193
    assert seconds_to_frames(240.0, NTSC_60) == 14386
    assert seconds_to_frames(240.0, Fraction(25)) == 6000
    assert seconds_to_frames(3600.0, NTSC_30) == 107892


def test_frames_to_seconds_is_the_inverse() -> None:
    assert frames_to_seconds(7193, NTSC_30) == pytest.approx(240.0, abs=0.02)
    assert frames_to_seconds(144, NTSC_24) == pytest.approx(6.006, abs=1e-6)


def test_an_hour_of_ntsc_does_not_drift() -> None:
    """The defect this project was built against: 1001/1000 over an hour."""
    frames = seconds_to_frames(3600.0, NTSC_30)
    assert frames_to_seconds(frames, NTSC_30) == pytest.approx(3600.0, abs=0.02)
    rounded = int(round(3600.0 * round(float(NTSC_30))))
    assert frames_to_seconds(rounded, NTSC_30) - 3600.0 == pytest.approx(3.6, abs=0.05)


def test_non_drop_timecode_round_trips() -> None:
    assert parse_timecode("10:00:00:00", 24) == 24 * 3600 * 10
    assert format_timecode(24 * 3600 * 10, 24) == "10:00:00:00"
    assert format_timecode(parse_timecode("00:04:00:00", 30), 30) == "00:04:00:00"


def test_drop_frame_timecode_skips_the_first_two_frames_of_a_minute() -> None:
    assert format_timecode(parse_timecode("00:00:59;29", 30) + 1, 30, drop=True) == "00:01:00;02"


def test_drop_frame_keeps_every_tenth_minute_whole() -> None:
    assert format_timecode(parse_timecode("00:09:59;29", 30) + 1, 30, drop=True) == "00:10:00;00"


def test_drop_frame_round_trips_across_an_hour() -> None:
    for text in ("00:00:00;00", "00:01:00;02", "00:10:00;00", "01:00:00;00", "00:59:59;29"):
        assert format_timecode(parse_timecode(text, 30), 30, drop=True) == text


def test_shift_timecode_moves_by_the_trimmed_head() -> None:
    assert shift_timecode("10:00:00:00", 6.006, NTSC_24) == "10:00:06:00"
    assert shift_timecode("01:00:00:00", 10.0, Fraction(25)) == "01:00:10:00"


def test_shift_timecode_keeps_the_drop_frame_flavour() -> None:
    assert shift_timecode("00:00:59;29", 1.0 / float(NTSC_30), NTSC_30) == "00:01:00;02"


def test_nearest_keyframe_prefers_the_earlier_one_on_a_tie() -> None:
    times = [0.0, 2.002, 4.004, 6.006]
    assert nearest_keyframe(times, 4.5) == 4.004
    assert nearest_keyframe(times, 5.5) == 6.006
    assert nearest_keyframe(times, 5.005) == 4.004
    assert nearest_keyframe([], 1.0) is None


def test_parse_keyframe_times_survives_ffprobe_punctuation() -> None:
    assert parse_keyframe_times("0.000000,\n2.002000\n\n4.004000\n") == [0.0, 2.002, 4.004]


def test_keyframe_probe_command_can_ask_for_a_window() -> None:
    full = keyframe_probe_command("ffprobe", "in.mp4")
    assert "-read_intervals" not in full
    windowed = keyframe_probe_command("ffprobe", "in.mp4", start=8.0, window=3.0)
    assert windowed[windowed.index("-read_intervals") + 1] == "5.000%+6.000"


def test_trim_command_seeks_before_input_and_sends_the_tail_as_duration() -> None:
    """`-ss` before `-i` moves zero, so an absolute `-to` after it would lie."""
    command = build_trim_command(
        ffmpeg="ffmpeg",
        source="in.mp4",
        target="out.mp4",
        overwrite=True,
        start_seconds=6.006,
        duration_seconds=6.494,
        extension="mp4",
        timecode="10:00:06:00",
    )
    assert command.index("-ss") < command.index("-i")
    assert command.index("-i") < command.index("-t")
    assert "-to" not in command
    assert command[command.index("-t") + 1] == "6.494000"
    assert command[command.index("-c:v") + 1] == "copy"
    assert command[command.index("-timecode") + 1] == "10:00:06:00"
    assert command[-1] == "out.mp4"


def test_trim_command_drops_audio_on_request() -> None:
    command = build_trim_command(
        ffmpeg="ffmpeg",
        source="in.mov",
        target="out.mov",
        overwrite=True,
        start_seconds=0.0,
        duration_seconds=None,
        extension="mov",
        audio_mode="none",
    )
    assert "-an" in command
    assert "-ss" not in command
    assert "-t" not in command


def test_a_declared_rate_is_taken_exactly_as_written() -> None:
    """No rate is inferred: 24/1 stays 24, 24000/1001 stays 24000/1001.

    An ARRI Alexa shooting a true 24.000 states `24/1`, and reading that as
    23.976 would cut five frames short over four minutes.
    """
    assert parse_rate("24/1") == Fraction(24)
    assert parse_rate("24000/1001") == NTSC_24
    assert parse_rate("30000/1001") == NTSC_30
    assert parse_rate("25") == Fraction(25)


def test_rate_label_speaks_the_usual_names() -> None:
    assert rate_label(NTSC_24) == "23.976p"
    assert rate_label(NTSC_30) == "29.97p"
    assert rate_label(NTSC_60) == "59.94p"
    assert rate_label(Fraction(25)) == "25p"


def test_plan_cut_counts_the_tail_in_frames_on_the_exact_rate() -> None:
    """Four minutes off a 29.97 clip is 7193 frames. A rounded rate says 7200."""
    cut = plan_cut(pattern="end", start=0, end="240.0", duration=300.033, rate=NTSC_30, keyframes=[])
    assert cut.frames == 7193
    assert cut.kept == pytest.approx(240.0, abs=0.01)
    assert cut.start == 0.0
    assert not cut.to_end_of_file


def test_plan_cut_snaps_the_head_to_a_keyframe_and_reports_the_offset() -> None:
    cut = plan_cut(
        pattern="both",
        start="5.0",
        end="20.0",
        duration=30.03,
        rate=NTSC_24,
        keyframes=[0.0, 2.002, 4.004, 6.006, 8.008],
    )
    assert cut.start == 4.004
    assert cut.keyframe_offset == pytest.approx(-0.996)
    assert cut.frames == 384


def test_plan_cut_keeps_everything_to_the_end_for_the_start_pattern() -> None:
    cut = plan_cut(pattern="start", start="4.004", end="", duration=30.03, rate=NTSC_24, keyframes=[0.0, 4.004])
    assert cut.to_end_of_file
    assert cut.frames is None
    assert cut.kept == pytest.approx(26.026)


def test_plan_cut_refuses_an_empty_piece() -> None:
    with pytest.raises(ValueError):
        plan_cut(pattern="both", start="20.0", end="10.0", duration=30.0, rate=NTSC_24, keyframes=[0.0])


def test_plan_cut_refuses_the_middle_pattern_until_it_exists() -> None:
    with pytest.raises(ValueError):
        plan_cut(pattern="middle", start="5", end="10", duration=30.0, rate=NTSC_24, keyframes=[0.0])


def test_plan_cut_needs_a_keyframe_when_the_head_moves() -> None:
    with pytest.raises(ValueError):
        plan_cut(pattern="both", start="5.0", end="20.0", duration=30.0, rate=NTSC_24, keyframes=[])


def test_trim_command_prefers_a_frame_count_over_a_duration() -> None:
    command = build_trim_command(
        ffmpeg="ffmpeg",
        source="in.mp4",
        target="out.mp4",
        overwrite=True,
        start_seconds=4.004,
        frame_count=384,
        duration_seconds=16.0,
        extension="mp4",
    )
    assert command[command.index("-frames:v") + 1] == "384"
    assert "-t" not in command
    assert "-avoid_negative_ts" not in command


def test_frames_covering_rounds_the_end_up() -> None:
    """Frame 899 stands at 29.9966 s, so a 30-second end point includes it."""
    assert frames_covering(30.0, NTSC_30) == 900
    assert frames_covering(240.0, NTSC_30) == 7193
    assert frames_covering(9.0, Fraction(25)) == 225
    assert frames_covering(20.0, NTSC_24) == 480


def test_plan_cut_keeps_the_frame_just_inside_the_end() -> None:
    cut = plan_cut(
        pattern="both",
        start="12.0",
        end="30.0",
        duration=40.007,
        rate=NTSC_30,
        keyframes=[0.0, 10.01, 20.02, 30.03],
    )
    assert cut.start == 10.01
    assert cut.frames == 600


def test_plan_cut_switches_to_a_time_tail_on_variable_rate() -> None:
    cut = plan_cut(
        pattern="both",
        start="4.0",
        end="16.0",
        duration=33.9,
        rate=Fraction(30),
        keyframes=[0.0, 2.0, 4.0],
        frame_exact=False,
    )
    assert cut.frames is None
    assert cut.tail_seconds == pytest.approx(12.0)
    assert cut.kept == pytest.approx(12.0)


def test_variable_rate_is_detected_from_the_two_rate_fields() -> None:
    assert is_variable_rate("30/1", "2000/113") is True
    assert is_variable_rate("30000/1001", "30000/1001") is False
    assert is_variable_rate("25/1", "25/1") is False
    assert is_variable_rate("0/0", "25/1") is False


def test_parse_timecode_refuses_a_time_with_milliseconds() -> None:
    """`00:01:28.400` is a time, and reading 400 as a frame number is nonsense."""
    with pytest.raises(ValueError):
        parse_timecode("00:01:28.400", 25)


def test_channel_requirement_matches_the_choice() -> None:
    assert audio_channel_requirement("both") == 0
    assert audio_channel_requirement("first") == 1
    assert audio_channel_requirement("second") == 2
    assert audio_channel_requirement("mono") == 2


def test_a_channel_the_file_lacks_is_refused() -> None:
    """`pan=mono|c0=c1` on a mono file writes silence and reports success."""
    assert "at least 2" in audio_channel_complaint("second", 1)
    assert "two channels" in audio_channel_complaint("mono", 1)
    assert "no audio track" in audio_channel_complaint("first", 0)


def test_a_channel_the_file_has_is_allowed() -> None:
    assert audio_channel_complaint("second", 2) == ""
    assert audio_channel_complaint("first", 1) == ""
    assert audio_channel_complaint("both", 0) == ""


def test_keyframe_times_read_the_packet_flag() -> None:
    """A packet row names a keyframe with K; anything else is not one.

    Reading packets is what keeps an all-intra preview usable: decoding the
    window costs 55 seconds on ARRI ProRes and 0.76 s this way.
    """
    rows = "0.000000,K__\n0.041667,___\n1.000000,K__\n"
    assert parse_keyframe_times(rows) == [0.0, 1.0]


def test_keyframe_times_still_accept_bare_timestamps() -> None:
    assert parse_keyframe_times("0.000000\n2.500000\n") == [0.0, 2.5]


def test_plan_gap_removes_what_was_asked_for_and_says_how_much_more() -> None:
    """The fifth cut: a piece out of the middle, and the two ends joined.

    The tail must start at or after the end of the removed piece. Starting at
    the nearest keyframe - the rule everywhere else here - would leave part of
    the very thing being removed in the result.
    """
    keyframes = [index * 2.0 for index in range(16)]

    exact = plan_gap(start=10.0, end=14.0, duration=30.0, rate=Fraction(25, 1), keyframes=keyframes)
    assert exact.head_frames == 250
    assert exact.tail_start == 14.0
    assert exact.keyframe_offset == 0.0
    assert exact.removed == pytest.approx(4.0)
    assert exact.kept == pytest.approx(26.0)

    # A point between keyframes: the tail waits for the next one, and the extra
    # is reported rather than hidden.
    rounded = plan_gap(start=10.0, end=13.0, duration=30.0, rate=Fraction(25, 1), keyframes=keyframes)
    assert rounded.tail_start == 14.0
    assert rounded.keyframe_offset == pytest.approx(1.0)
    assert rounded.removed == pytest.approx(4.0)


def test_plan_gap_sends_the_edge_cases_to_the_cut_that_fits_them() -> None:
    """Removing from zero, or up to the end, is one of the simpler cuts."""
    keyframes = [index * 2.0 for index in range(16)]
    with pytest.raises(ValueError, match="drop the head"):
        plan_gap(start=0.0, end=5.0, duration=30.0, rate=Fraction(25, 1), keyframes=keyframes)
    with pytest.raises(ValueError, match="drop the tail"):
        plan_gap(start=20.0, end=30.0, duration=30.0, rate=Fraction(25, 1), keyframes=keyframes)
    with pytest.raises(ValueError, match="empty"):
        plan_gap(start=12.0, end=12.0, duration=30.0, rate=Fraction(25, 1), keyframes=keyframes)
    with pytest.raises(ValueError, match="No keyframe"):
        plan_gap(start=10.0, end=13.0, duration=30.0, rate=Fraction(25, 1), keyframes=[0.0, 2.0])


def test_keyframe_at_or_after_never_looks_backwards() -> None:
    assert keyframe_at_or_after([0.0, 2.0, 4.0], 2.0) == 2.0
    assert keyframe_at_or_after([0.0, 2.0, 4.0], 2.5) == 4.0
    assert keyframe_at_or_after([0.0, 2.0, 4.0], 5.0) is None


def test_a_piece_headed_for_a_join_carries_its_own_length() -> None:
    """`-frames:v` stops the sound with the last frame; on a join that shows.

    Measured at 16 ms short on a 25 fps PCM take, which lands straight on the
    joint. Passing the length as well lets the sound reach the end of the piece.
    """
    command = build_trim_command(
        ffmpeg="ffmpeg",
        source="in.mov",
        target="out.mov",
        overwrite=True,
        start_seconds=0.0,
        frame_count=250,
        sound_to_seconds=10.0,
        extension="mov",
    )
    assert "-frames:v" in command and command[command.index("-frames:v") + 1] == "250"
    assert "-t" in command and command[command.index("-t") + 1] == "10.000000"

    # Without it nothing changes: the ordinary cut still ends on its frame, and
    # a plain duration is still ignored when a frame count is present.
    plain = build_trim_command(
        ffmpeg="ffmpeg",
        source="in.mov",
        target="out.mov",
        overwrite=True,
        start_seconds=0.0,
        frame_count=250,
        extension="mov",
    )
    assert "-t" not in plain


def data_stream(tag: str = "gpmd", codec: str = "bin_data") -> dict[str, str]:
    return {"codec_type": "data", "codec_name": codec, "codec_tag_string": tag}


def subtitle_stream(codec: str = "mov_text") -> dict[str, str]:
    return {"codec_type": "subtitle", "codec_name": codec}


def test_telemetry_travels_where_the_container_takes_it() -> None:
    """A GoPro's telemetry is a data stream, and MOV and MP4 will carry it."""
    for container in ("mov", "mp4"):
        keep_data, _keep_subs, warnings = extra_stream_plan([data_stream()], container)
        assert keep_data is True
        assert warnings == []


def test_a_container_that_cannot_hold_it_says_so_before_the_run() -> None:
    """Measured: Matroska answers "Only audio, video, and subtitles"."""
    keep_data, _keep_subs, warnings = extra_stream_plan([data_stream()], "mkv")
    assert keep_data is False
    assert warnings and "MKV cannot hold a data stream" in warnings[0]
    assert "gpmd" in warnings[0], "the stream is named, so the operator knows what stayed behind"


def test_a_timecode_track_is_left_behind_on_purpose() -> None:
    """It reads as an unnameable codec, and it travels as a value instead.

    MP4 stops outright on such a stream - "Could not find tag for codec none" -
    so carrying it is not merely pointless but fatal.
    """
    timecode_track = {"codec_type": "data", "codec_name": "unknown", "codec_tag_string": "tmcd"}
    keep_data, _keep_subs, warnings = extra_stream_plan([timecode_track], "mov")
    assert keep_data is False
    assert warnings and "tmcd" in warnings[0]
    assert "written as a value" in warnings[0]


def test_subtitles_travel_unless_the_container_refuses() -> None:
    """A DJI writes flight data as subtitles; losing them loses the flight log."""
    _keep_data, keep_subs, warnings = extra_stream_plan([subtitle_stream()], "mkv")
    assert keep_subs is True and warnings == []

    _keep_data, keep_subs, warnings = extra_stream_plan([subtitle_stream()], "mxf")
    assert keep_subs is False
    assert warnings and "MXF cannot hold subtitles" in warnings[0]


def test_turning_a_checkbox_off_is_still_said_out_loud() -> None:
    """Dropping a stream silently is what this whole thing was fixing."""
    keep_data, keep_subs, warnings = extra_stream_plan(
        [data_stream(), subtitle_stream()], "mov", want_data=False, want_subtitles=False
    )
    assert keep_data is False and keep_subs is False
    assert len(warnings) == 2
    assert all("checkbox is off" in warning for warning in warnings)


def test_a_file_with_nothing_extra_says_nothing() -> None:
    video_and_sound = [{"codec_type": "video", "codec_name": "h264"}, {"codec_type": "audio", "codec_name": "pcm_s16le"}]
    assert extra_stream_plan(video_and_sound, "mov") == (False, False, [])


def test_the_command_maps_them_only_when_asked() -> None:
    """`-copy_unknown` has to ride along, or a data stream is dropped anyway."""
    kept = build_trim_command(
        ffmpeg="ffmpeg",
        source="in.mov",
        target="out.mov",
        overwrite=True,
        start_seconds=0.0,
        frame_count=100,
        extension="mov",
        keep_data=True,
        keep_subtitles=True,
    )
    assert "-dn" not in kept and "-sn" not in kept
    assert "-copy_unknown" in kept
    assert "0:d?" in kept and "0:s?" in kept

    dropped = build_trim_command(
        ffmpeg="ffmpeg",
        source="in.mov",
        target="out.mov",
        overwrite=True,
        start_seconds=0.0,
        frame_count=100,
        extension="mov",
    )
    assert "-dn" in dropped and "-sn" in dropped
    assert "0:d?" not in dropped


def test_a_data_stream_travels_home_and_nowhere_else() -> None:
    """Measured on a broadcast MXF, and it cost a failed run to learn.

    A SMPTE 436M ancillary track goes straight back into MXF. MOV holds data
    streams in general and refuses this one outright - the cut died with exit
    4294967274 and no useful message. So the question is not only what the
    target takes, but what the stream was written for.
    """
    anc = {"codec_type": "data", "codec_name": "smpte_436m_anc", "codec_tag_string": "[0][0][0][0]"}

    keep_data, _subs, warnings = extra_stream_plan([anc], "mxf", source_container=".mxf")
    assert keep_data is True and warnings == []

    keep_data, _subs, warnings = extra_stream_plan([anc], "mov", source_container=".mxf")
    assert keep_data is False
    assert "written for MXF" in warnings[0]
    assert "smpte_436m_anc" in warnings[0], "the empty MXF tag must not be printed as [0][0][0][0]"


def test_the_tag_names_the_stream_when_there_is_one() -> None:
    """`gpmd` and `tmcd` mean something; `[0][0][0][0]` means nothing."""
    assert stream_display_name({"codec_tag_string": "gpmd", "codec_name": "bin_data"}) == "gpmd"
    assert stream_display_name({"codec_tag_string": "[0][0][0][0]", "codec_name": "smpte_436m_anc"}) == "smpte_436m_anc"
    assert stream_display_name({"codec_name": "bin_data"}) == "bin_data"
    assert stream_display_name({}) == "data"


def test_mxf_holds_a_data_stream_after_all() -> None:
    """It was assumed not to, on no evidence, until a real file said otherwise."""
    assert "mxf" in DATA_STREAM_CONTAINERS
    assert "mkv" not in DATA_STREAM_CONTAINERS
