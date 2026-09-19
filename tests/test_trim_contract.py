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
    plan_split,
    AudioPiece,
    audio_join_graph,
    audio_sample_depth,
    audio_trim_encoding,
    audio_trim_filter,
    audio_trim_metadata,
    build_audio_trim_command,
    plan_audio_trim,
    seconds_to_sample,
    PACKET_COPY_RULES,
    PacketPiece,
    build_packet_copy_command,
    build_packet_join_command,
    plan_packet_copy,
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


KEYS_EVERY_SECOND = [float(second) for second in range(31)]


def test_one_point_splits_in_two_and_the_parts_add_up() -> None:
    """The joint is one keyframe: the first part ends just before it, the second starts on it."""
    split = plan_split(points=["00:00:10,000", ""], duration=30.0, rate=Fraction(25), keyframes=KEYS_EVERY_SECOND)
    assert split.boundaries == (10.0,)
    assert [part.frames for part in split.parts] == [250, None]
    assert split.parts[1].start == 10.0
    assert split.parts[0].frames + round(split.parts[1].seconds * 25) == 750


def test_two_points_split_in_three() -> None:
    split = plan_split(points=[12.0, 20.0], duration=30.0, rate=Fraction(25), keyframes=KEYS_EVERY_SECOND)
    assert split.boundaries == (12.0, 20.0)
    assert [part.index for part in split.parts] == [1, 2, 3]
    assert [part.start for part in split.parts] == [0.0, 12.0, 20.0]
    assert [part.frames for part in split.parts] == [300, 200, None]
    assert sum(part.frames or round(part.seconds * 25) for part in split.parts) == 750


def test_a_point_between_keyframes_moves_to_the_nearest_and_both_parts_follow() -> None:
    """Measured on the old split: at 10.7 s the tail snapped to 11.0 while the head
    still ended at 10.7, and 7 frames belonged to neither file; at 10.2 s, 5 frames
    landed in both."""
    split = plan_split(points=[10.7], duration=30.0, rate=Fraction(25), keyframes=KEYS_EVERY_SECOND)
    assert split.boundaries == (11.0,)
    assert split.offsets[0] == pytest.approx(0.3)
    assert split.parts[0].frames == 275
    assert split.parts[1].start == 11.0


def test_the_joint_is_counted_by_rounding_not_by_ceiling() -> None:
    """A keyframe timestamp is a frame boundary already. At 23.976 the keyframe of
    frame 240 reads 10.010010 s, which is 240.00024 frames: ceil would put frame 240
    into both parts."""
    keyframe = 10.010010
    split = plan_split(points=[10.0], duration=30.0, rate=NTSC_24, keyframes=[0.0, keyframe, 20.02])
    assert split.parts[0].frames == 240


def test_points_arrive_in_any_order() -> None:
    split = plan_split(points=[20.0, 12.0], duration=30.0, rate=Fraction(25), keyframes=KEYS_EVERY_SECOND)
    assert split.requested == (12.0, 20.0)


def test_a_split_that_would_leave_nothing_says_so() -> None:
    with pytest.raises(ValueError, match="needs a point"):
        plan_split(points=["", None], duration=30.0, rate=Fraction(25), keyframes=KEYS_EVERY_SECOND)
    with pytest.raises(ValueError, match="middle part would be empty"):
        plan_split(points=[10.2, 10.4], duration=30.0, rate=Fraction(25), keyframes=KEYS_EVERY_SECOND)
    with pytest.raises(ValueError, match="edge of the file"):
        plan_split(points=[0.3], duration=30.0, rate=Fraction(25), keyframes=KEYS_EVERY_SECOND)
    with pytest.raises(ValueError, match="outside the file"):
        plan_split(points=[31.0], duration=30.0, rate=Fraction(25), keyframes=KEYS_EVERY_SECOND)


def test_a_variable_rate_split_travels_by_time() -> None:
    split = plan_split(points=[10.0], duration=30.0, rate=Fraction(30), keyframes=KEYS_EVERY_SECOND, frame_exact=False)
    assert split.parts[0].frames is None
    assert split.parts[0].seconds == pytest.approx(10.0)


# Sound files. The numbers come from the measured take: 30 s of stereo noise at
# 48 kHz, 1 440 000 samples, cut at 10.2345 s and 20.0001 s.


def test_a_sound_point_is_the_nearest_sample() -> None:
    assert seconds_to_sample(10.2345, 48000) == 491256
    assert seconds_to_sample(20.0001, 48000) == 960005
    assert seconds_to_sample(10.0, 44100) == 441000


def test_sound_keeps_what_lies_between_the_points() -> None:
    trim = plan_audio_trim(pattern="both", start="00:00:10,000", end="00:00:20,000", duration=30.0, sample_rate=48000)
    assert trim.pieces == (AudioPiece(480000, 960000),)
    assert trim.kept == 480000
    assert not trim.joined


def test_sound_in_alone_drops_the_head_and_out_alone_the_tail() -> None:
    head = plan_audio_trim(pattern="start", start=10.0, end="", duration=30.0, sample_rate=44100)
    assert head.pieces == (AudioPiece(441000, None),)
    assert head.kept == 1323000 - 441000
    tail = plan_audio_trim(pattern="end", start="", end=10.0, duration=30.0, sample_rate=44100)
    assert tail.pieces == (AudioPiece(0, 441000),)


def test_the_sample_count_a_file_states_wins_over_its_duration() -> None:
    trim = plan_audio_trim(pattern="start", start=1.0, end="", duration=30.0, sample_rate=48000, total_samples=1440768)
    assert trim.total == 1440768
    assert trim.kept == 1440768 - 48000


def test_sound_cut_out_joins_the_two_ends() -> None:
    """Measured bit for bit on WAV and FLAC: 971 251 samples remain."""
    trim = plan_audio_trim(pattern="middle", start=10.2345, end=20.0001, duration=30.0, sample_rate=48000)
    assert trim.joined
    assert trim.pieces == (AudioPiece(0, 491256), AudioPiece(960005, None))
    assert trim.kept == 971251


def test_sound_split_gives_two_or_three_parts_that_add_up() -> None:
    two = plan_audio_trim(pattern="split", start=10.0, end="", duration=30.0, sample_rate=48000)
    assert two.pieces == (AudioPiece(0, 480000), AudioPiece(480000, None))
    three = plan_audio_trim(pattern="split", start=20.0001, end=10.2345, duration=30.0, sample_rate=48000)
    assert three.pieces == (AudioPiece(0, 491256), AudioPiece(491256, 960005), AudioPiece(960005, None))
    assert [three.length(piece) for piece in three.pieces] == [491256, 468749, 479995]
    assert three.kept == 1440000


def test_sound_refuses_what_the_picture_refuses() -> None:
    with pytest.raises(ValueError, match="no cut point"):
        plan_audio_trim(pattern="both", start="", end="", duration=30.0, sample_rate=48000)
    with pytest.raises(ValueError, match="kept piece is empty"):
        plan_audio_trim(pattern="both", start=20.0, end=10.0, duration=30.0, sample_rate=48000)
    with pytest.raises(ValueError, match="needs both IN and OUT"):
        plan_audio_trim(pattern="middle", start=10.0, end="", duration=30.0, sample_rate=48000)
    with pytest.raises(ValueError, match="starts at zero"):
        plan_audio_trim(pattern="middle", start=0.0, end=10.0, duration=30.0, sample_rate=48000)
    with pytest.raises(ValueError, match="reaches the end"):
        plan_audio_trim(pattern="middle", start=10.0, end=31.0, duration=30.0, sample_rate=48000)
    with pytest.raises(ValueError, match="needs a point"):
        plan_audio_trim(pattern="split", start="", end=None, duration=30.0, sample_rate=48000)
    with pytest.raises(ValueError, match="outside the file"):
        plan_audio_trim(pattern="split", start=30.0, end="", duration=30.0, sample_rate=48000)
    with pytest.raises(ValueError, match="middle part would be empty"):
        plan_audio_trim(pattern="split", start=10.000001, end=10.000002, duration=30.0, sample_rate=48000)
    with pytest.raises(ValueError, match="sample rate"):
        plan_audio_trim(pattern="both", start=1.0, end=2.0, duration=30.0, sample_rate=0)


def test_a_sound_piece_is_numbered_cut_and_restarted() -> None:
    assert audio_trim_filter(AudioPiece(491256, 960005)) == (
        "asetpts=N/SR/TB,atrim=start_sample=491256:end_sample=960005,asetpts=PTS-STARTPTS"
    )
    assert audio_trim_filter(AudioPiece(0, 480000)) == "asetpts=N/SR/TB,atrim=end_sample=480000,asetpts=PTS-STARTPTS"
    assert audio_trim_filter(AudioPiece(480000, None), "aresample=48000") == (
        "asetpts=N/SR/TB,atrim=start_sample=480000,asetpts=PTS-STARTPTS,aresample=48000"
    )


def test_a_sound_cut_is_one_graph_with_a_concat() -> None:
    assert audio_join_graph((AudioPiece(0, 491256), AudioPiece(960005, None))) == (
        "[0:a:0]asetpts=N/SR/TB,asplit=2[s0][s1];"
        "[s0]atrim=end_sample=491256,asetpts=PTS-STARTPTS[p0];"
        "[s1]atrim=start_sample=960005,asetpts=PTS-STARTPTS[p1];"
        "[p0][p1]concat=n=2:v=0:a=1[out]"
    )


def test_the_sound_command_maps_a_cover_only_when_asked() -> None:
    common = dict(ffmpeg="ffmpeg", source="in.flac", overwrite=True, codec_args=("-c:a", "flac"))
    plain = build_audio_trim_command(target="out.wav", pieces=(AudioPiece(0, 100),), muxer_args=("-rf64", "auto"), **common)
    assert plain[plain.index("-af") + 1].startswith("asetpts=N/SR/TB,")
    assert "-vn" in plain and "0:v?" not in plain
    assert plain[-3:] == ["-rf64", "auto", "out.wav"]
    covered = build_audio_trim_command(target="out.flac", pieces=(AudioPiece(0, 100),), keep_cover=True, **common)
    at = covered.index("0:v?")
    assert covered[at + 1:at + 5] == ["-c:v", "copy", "-disposition:v:0", "attached_pic"]
    assert "-vn" not in covered
    joined = build_audio_trim_command(target="out.flac", pieces=(AudioPiece(0, 10), AudioPiece(20, None)), **common)
    assert "-filter_complex" in joined and joined[joined.index("-map") + 1] == "[out]"
    with pytest.raises(ValueError):
        build_audio_trim_command(target="out.flac", pieces=(), **common)


def test_lossless_sound_is_written_back_as_itself() -> None:
    wav = audio_trim_encoding(choice="source", codec="pcm_s24le", extension="wav", sample_rate=48000, channels=2, sample_fmt="s32", bits=24)
    assert wav.codec_args == ("-c:a", "pcm_s24le") and wav.extension == "wav" and wav.lossless
    assert wav.muxer_args == ("-rf64", "auto")
    flac = audio_trim_encoding(choice="source", codec="flac", extension="flac", sample_rate=96000, channels=2, sample_fmt="s32", bits=24)
    assert flac.codec_args[:2] == ("-c:a", "flac") and flac.lossless and not flac.warnings
    aiff = audio_trim_encoding(choice="source", codec="pcm_s24be", extension="aif", sample_rate=48000, channels=2)
    assert aiff.codec_args == ("-c:a", "pcm_s24be") and aiff.extension == "aif"
    snd = audio_trim_encoding(choice="source", codec="pcm_s16be", extension="snd", sample_rate=8000, channels=1)
    assert snd.muxer_args == ("-f", "au")


def test_compressed_sound_as_is_spends_a_generation_and_says_so() -> None:
    mp3 = audio_trim_encoding(choice="source", codec="mp3", extension="mp3", sample_rate=44100, channels=2, bit_rate="245000")
    assert mp3.codec_args == ("-c:a", "libmp3lame", "-b:a", "256k")
    assert not mp3.lossless and "one generation" in mp3.warnings[0]
    aac = audio_trim_encoding(choice="source", codec="aac", extension="m4a", sample_rate=48000, channels=2, bit_rate="N/A")
    assert aac.codec_args == ("-c:a", "aac", "-b:a", "256k")


def test_what_cannot_be_written_back_as_it_is_says_what_can() -> None:
    with pytest.raises(ValueError, match="Choose FLAC or WAV"):
        audio_trim_encoding(choice="source", codec="ape", extension="ape", sample_rate=44100, channels=2)
    with pytest.raises(ValueError, match="DSD"):
        audio_trim_encoding(choice="source", codec="dsd_lsbf_planar", extension="dsf", sample_rate=352800, channels=2)
    with pytest.raises(ValueError, match="one or two channels"):
        audio_trim_encoding(choice="mp3", codec="pcm_s24le", extension="wav", sample_rate=48000, channels=6)
    with pytest.raises(ValueError, match="Unknown format"):
        audio_trim_encoding(choice="wma", codec="pcm_s24le", extension="wav", sample_rate=48000, channels=2)


def test_wav_keeps_the_depth_the_samples_really_have() -> None:
    assert audio_sample_depth("flac", "s32", 24) == "s24"
    assert audio_sample_depth("pcm_f32le") == "f32"
    assert audio_trim_encoding(choice="wav", codec="flac", extension="flac", sample_rate=44100, channels=2, sample_fmt="s16").codec_args == ("-c:a", "pcm_s16le")
    assert audio_trim_encoding(choice="wav", codec="flac", extension="flac", sample_rate=48000, channels=2, sample_fmt="s32", bits=24).codec_args == ("-c:a", "pcm_s24le")
    # A compressed source decodes to float, and float is what is kept: measured bit for bit.
    from_mp3 = audio_trim_encoding(choice="wav", codec="mp3", extension="mp3", sample_rate=44100, channels=2, sample_fmt="fltp")
    assert from_mp3.codec_args == ("-c:a", "pcm_f32le") and from_mp3.lossless


def test_flac_and_alac_say_when_24_bits_are_not_enough() -> None:
    flac = audio_trim_encoding(choice="flac", codec="pcm_f32le", extension="wav", sample_rate=48000, channels=2)
    assert not flac.lossless and "24 bits at most" in flac.warnings[0]
    alac = audio_trim_encoding(choice="alac", codec="pcm_s24le", extension="wav", sample_rate=48000, channels=2)
    assert alac.extension == "m4a" and alac.lossless and not alac.warnings


def test_encoders_get_a_rate_they_take() -> None:
    opus = audio_trim_encoding(choice="opus", codec="pcm_s24le", extension="wav", sample_rate=44100, channels=2, bitrate="320k")
    assert opus.codec_args == ("-c:a", "libopus", "-b:a", "256k")
    assert "soxr" in opus.tail_filter and opus.output_rate == 48000
    mp3 = audio_trim_encoding(choice="mp3", codec="pcm_s24le", extension="wav", sample_rate=96000, channels=2, mp3_preset="insane")
    assert mp3.output_rate == 48000 and mp3.codec_args == ("-c:a", "libmp3lame", "-b:a", "320k")
    native = audio_trim_encoding(choice="mp3", codec="pcm_s16le", extension="wav", sample_rate=44100, channels=2)
    assert native.tail_filter == "" and native.output_rate == 44100 and native.label == "MP3 VBR V0"


def test_the_time_reference_moves_with_the_piece() -> None:
    tags = {
        "time_reference": "172800000",
        "comment": "Scene 12 take 3",
        "encoded_by": "ZOOM F8n",
        "date": "2026-09-14",
        "creation_time": "10:00:00",
    }
    metadata, muxer, moved = audio_trim_metadata(tags, start_sample=491256, extension="wav", broadcast_wav=True)
    assert moved == (172800000, 173291256)
    assert muxer == ["-write_bext", "1"]
    assert metadata == [
        "-metadata", "time_reference=173291256",
        "-metadata", "description=Scene 12 take 3",
        "-metadata", "originator=ZOOM F8n",
        "-metadata", "origination_date=2026-09-14",
        "-metadata", "origination_time=10:00:00",
    ]


def test_a_piece_from_the_start_keeps_its_reference_and_flac_takes_it_as_a_tag() -> None:
    metadata, muxer, moved = audio_trim_metadata({"TIME_REFERENCE": "5"}, start_sample=0, extension="flac", broadcast_wav=True)
    assert moved == (5, 5) and metadata == [] and muxer == []


# Packet copy. The packet positions are the measured files': MP3 frames of 1 152
# samples behind 1 105 of encoder delay, AAC frames of 1 024 behind one priming
# frame, Vorbis blocks of 1 024.

MP3_STARTS = [1152 * index - 1105 for index in range(1251)]


def test_packet_copy_lands_on_the_nearest_packet_and_mp3_keeps_its_header_only_at_the_start() -> None:
    trim = plan_audio_trim(pattern="split", start=10.2345, end=20.0001, duration=30.0, sample_rate=48000, total_samples=1440000)
    copy = plan_packet_copy(trim=trim, rule=PACKET_COPY_RULES["mp3"], packet_starts=MP3_STARTS)
    assert copy.moves == ((491256, 490799), (960005, 959663))
    assert [piece.packet for piece in copy.pieces] == [0, 427, 834]
    assert [piece.header for piece in copy.pieces] == [True, False, False]
    assert copy.pieces[0].copy_from is None and copy.pieces[2].copy_to is None
    assert copy.pieces[1].copy_from == pytest.approx((490799 + 489647) / 96000)
    assert copy.kept == 1440000


def test_vorbis_pieces_start_one_packet_early_but_a_join_does_not() -> None:
    starts = [1024 * index for index in range(1407)]
    split = plan_audio_trim(pattern="split", start=10.2345, end="", duration=30.0, sample_rate=48000, total_samples=1440000)
    copy = plan_packet_copy(trim=split, rule=PACKET_COPY_RULES["vorbis"], packet_starts=starts)
    assert copy.pieces[1].packet == 480
    assert copy.pieces[1].start_sample == 491520
    assert copy.pieces[1].copy_from == pytest.approx((490496 + 489472) / 96000)
    cut = plan_audio_trim(pattern="middle", start=10.2345, end=20.0001, duration=30.0, sample_rate=48000, total_samples=1440000)
    joined = plan_packet_copy(trim=cut, rule=PACKET_COPY_RULES["vorbis"], packet_starts=starts)
    assert joined.pieces[1].packet == 938
    assert joined.pieces[1].copy_from == pytest.approx((960512 + 959488) / 96000)
    assert all(piece.header for piece in joined.pieces)


def test_a_packet_copy_that_would_leave_nothing_says_so() -> None:
    starts = [1024 * (index - 1) for index in range(1408)]
    assert PACKET_COPY_RULES["aac"].join_clock_back
    cut = plan_audio_trim(pattern="middle", start=10.0, end=10.01, duration=30.0, sample_rate=48000, total_samples=1440768)
    with pytest.raises(ValueError, match="shorter than a packet"):
        plan_packet_copy(trim=cut, rule=PACKET_COPY_RULES["aac"], packet_starts=starts)
    keep = plan_audio_trim(pattern="both", start=10.0, end=10.01, duration=30.0, sample_rate=48000, total_samples=1440768)
    with pytest.raises(ValueError, match="would be empty"):
        plan_packet_copy(trim=keep, rule=PACKET_COPY_RULES["aac"], packet_starts=starts)
    with pytest.raises(ValueError, match="could not be read"):
        plan_packet_copy(trim=keep, rule=PACKET_COPY_RULES["aac"], packet_starts=[0])


def test_packet_copy_commands_seek_on_the_output_and_join_from_the_source() -> None:
    piece = PacketPiece(packet=427, end_packet=834, start_sample=490799, end_sample=959663, copy_from=10.2, copy_to=19.97, header=False)
    command = build_packet_copy_command(ffmpeg="ffmpeg", source="in.mp3", target="out.mp3", overwrite=True, piece=piece)
    assert command[-7:] == ["-write_xing", "0", "-ss", "10.200000", "-to", "19.970000", "out.mp3"]
    assert command[command.index("-c:a") + 1] == "copy"
    assert command.index("-i") < command.index("-ss")
    join = build_packet_join_command(ffmpeg="ffmpeg", list_file="parts.txt", source="in.m4a", target="out.m4a", overwrite=True, clock_back=1024 / 48000)
    assert join[join.index("-output_ts_offset") + 1] == "-0.021333"
    assert join[join.index("-map_metadata") + 1] == "1"
    plain = build_packet_join_command(ffmpeg="ffmpeg", list_file="parts.txt", source="in.mp3", target="out.mp3", overwrite=True)
    assert "-output_ts_offset" not in plain
