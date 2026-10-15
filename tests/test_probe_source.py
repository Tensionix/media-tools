"""SOURCE INFO says what the files are (media_service.py: _probe_row, _probe_summary, probe_source).

On the owner's material (WINDOW_INVENTORY, 12) it said 25p of a 25i file, 28.875p of a phone's variable rate, "?" in the
video column of a sound file, nothing clear of an ARRIRAW, "ERROR ... Permission denied" of a file being copied - and it
spoke for the whole folder by its first file.
"""
from __future__ import annotations

from pathlib import Path

from system_core.services import media_service as media

PRORES_LT = {"codec_type": "video", "codec_name": "prores", "width": 4096, "height": 2160, "r_frame_rate": "24000/1001",
             "avg_frame_rate": "7188000/299299", "pix_fmt": "yuv422p10le"}
SOUND = {"codec_type": "audio", "codec_name": "pcm_s24le", "sample_rate": "48000", "channels": 2, "channel_layout": "stereo",
         "bits_per_sample": 24}


def row(*streams: dict, name: str = "clip.mov") -> dict[str, str]:
    return media._probe_row(Path(name), {"streams": list(streams), "format": {"duration": "24.94"}})


def test_a_steady_rate_is_the_stated_one() -> None:
    assert "23.976p" in row(PRORES_LT, SOUND)["video"]


def test_two_fields_are_said_as_such() -> None:
    video = {"codec_type": "video", "codec_name": "dvvideo", "width": 720, "height": 576, "r_frame_rate": "25/1",
             "avg_frame_rate": "25/1", "field_order": "bb", "pix_fmt": "yuv420p"}
    assert row(video)["video"] == "DVVIDEO 720x576 25i yuv420p"
    assert "25p" in row({**video, "field_order": "progressive"})["video"]


def test_a_variable_rate_says_both_rates() -> None:
    phone = {"codec_type": "video", "codec_name": "hevc", "width": 1920, "height": 1080, "r_frame_rate": "30/1",
             "avg_frame_rate": "231/8", "pix_fmt": "yuv420p"}
    assert "VFR 30 (avg 28.875)" in row(phone)["video"]


def test_a_sound_file_has_no_video() -> None:
    sound = row(SOUND, name="take.wav")
    assert sound["video"] == "-" and sound["audio"] == "PCM_S24LE 48000 Hz 24 stereo"


def test_camera_raw_is_named_not_guessed() -> None:
    arriraw = row({"codec_type": "video", "codec_name": "", "width": 0, "height": 0, "r_frame_rate": "24/1",
                   "avg_frame_rate": "24/1"}, name="ARRI.mxf")
    assert arriraw["video"] == media.PROBE_UNREADABLE_VIDEO and arriraw["kind"] == "unreadable"


def test_the_folder_is_said_by_most_of_the_files_read() -> None:
    sound = row(SOUND, name="first.wav")
    clips = [row(PRORES_LT, SOUND, name=f"clip{index}.mov") for index in range(3)]
    raw = row({"codec_type": "video", "codec_name": "unknown", "width": 0}, name="ARRI.mxf")
    busy = {"file": "copying.mov", "video": media.PROBE_BUSY, "audio": "-", "duration": "-", "fingerprint": "busy", "kind": "busy"}
    summary = media._probe_summary([raw, sound, *clips, busy], 6)
    assert summary.startswith("6 file(s), mixed: 3 of 4 read like this, 1 busy, 1 unreadable | V: PRORES 4096x2160 23.976p")
    assert media._probe_summary([raw, busy], 2) == "2 file(s), none could be read, 1 busy, 1 unreadable"


def test_a_file_open_elsewhere_is_busy(tmp_path: Path, monkeypatch) -> None:
    clip = tmp_path / "copying.mov"
    clip.write_bytes(b"\0" * 16)

    def refused(self, *args, **kwargs):
        raise PermissionError(13, "Permission denied", str(self))

    assert not media._file_is_busy(clip)
    monkeypatch.setattr(Path, "open", refused)
    assert media._file_is_busy(clip)
