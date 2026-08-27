"""Turning a clip without touching a pixel.

A camera on its side writes an ordinary landscape file and says nothing about
it. This section writes the turn into the container, so the editor opens the
clip upright - measured: 6 085 307 bytes in, 6 085 304 out, frame hashes
identical, decoder returns 540x960 where the stream is 960x540.

The two things worth pinning down here are the ones that were wrong first time
round: the direction of the angle, and the shape of the flip options.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from system_core.services.media_service import (  # noqa: E402
    REMUX_ORIENTATIONS,
    _remux_orientation,
    _remux_orientation_args,
)


def test_clockwise_is_a_negative_angle() -> None:
    """`-display_rotation` counts counter-clockwise; the labels do not.

    Getting this backwards turns every vertical clip the wrong way, and the file
    looks plausible either way until someone opens it.
    """
    assert _remux_orientation_args({"remux_orientation": "cw90"}) == ["-display_rotation:v", "-90"]
    assert _remux_orientation_args({"remux_orientation": "ccw90"}) == ["-display_rotation:v", "90"]
    assert _remux_orientation_args({"remux_orientation": "turn180"}) == ["-display_rotation:v", "180"]


def test_the_flips_take_no_value() -> None:
    """`-display_hflip 1` sends the 1 on as an output filename and the run dies.

    Measured, on the first attempt at this: "Option display_hflip cannot be
    applied to output url 1". The flags stand alone.
    """
    for name in ("hflip", "vflip"):
        args = _remux_orientation_args({"remux_orientation": name})
        assert len(args) == 1
        assert args[0] == f"-display_{name}"


def test_an_unknown_or_absent_choice_turns_nothing() -> None:
    for value in ("", None, "none", "sideways", "90"):
        assert _remux_orientation({"remux_orientation": value}) == "none"
        assert _remux_orientation_args({"remux_orientation": value}) == []


def test_every_choice_the_panel_offers_is_implemented() -> None:
    """The manifest and the table have to agree, or a button does nothing."""
    import yaml

    manifest = yaml.safe_load((ROOT / "config" / "tool_manifest.yaml").read_text(encoding="utf-8"))

    def find_field(nodes) -> dict | None:
        for node in nodes or []:
            for field in node.get("fields", []) or []:
                if field.get("id") == "remux_orientation":
                    return field
            found = find_field(node.get("children"))
            if found is not None:
                return found
        return None

    # The panel's sections live under `operation_groups`; `operations` holds
    # the two standalone entries.
    field = find_field(manifest.get("operation_groups"))
    assert field is not None, "the remux group has no orientation field"
    offered = [str(option["value"]) for option in field["options"]]
    assert offered[0] == "none", "the first choice must be the one that changes nothing"
    assert set(offered[1:]) == set(REMUX_ORIENTATIONS), "the panel and the service disagree"

    # Both languages, on every button: a label without its pair is a bug report
    # waiting to happen.
    for option in field["options"]:
        assert option.get("label") and option.get("label_ru")
        assert option.get("tooltip") and option.get("tooltip_ru")


@pytest.mark.parametrize("codec, allowed", [("h264", True), ("hevc", True), ("prores", False), ("dnxhd", False)])
def test_turning_is_offered_for_camera_originals_only(codec: str, allowed: bool) -> None:
    """A scope decision, not a technical limit - the matrix works with any codec.

    Turning an unturned file is a camera-original problem, and those arrive as
    H.264 or HEVC. A mezzanine that already went through an NLE is not this
    section's business.
    """
    from system_core.services.media_service import REMUX_ORIENTATION_CODECS

    assert (codec in REMUX_ORIENTATION_CODECS) is allowed
