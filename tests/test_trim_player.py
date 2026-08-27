"""The player buttons: on screen, and writing what the player found.

Two things are worth a test and nothing else is. That the five buttons actually
reach the trim panel - a widget that exists only in a `type:` string is easy to
get wrong and impossible to notice from `--smoke`, which never opens a section.
And that the two positions the player hands over land in the timecode fields in
the form the cutting engine parses back.

The player itself is not started here: mpv is a payload under `Tools\\`, absent
from a fresh clone, and a test that needs a window is a test nobody runs. What
matters is the handover, and that is pure arithmetic.
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("bs4", reason="NiceGUI's user fixture needs beautifulsoup4")

from nicegui import ui  # noqa: E402
from nicegui.testing import User  # noqa: E402

pytest_plugins = ["nicegui.testing.user_plugin"]


def gui_module():
    from system_core.ui_nicegui import app

    return app


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
def fresh_gui():
    gui = gui_module()
    targets = getattr(getattr(gui, "command_tree", None), "targets", None)
    if targets is not None:
        targets.clear()
    state = getattr(gui, "state", None)
    if isinstance(state, dict):
        state["field_values"] = {}
        state["command_path"] = []
        state["pending_command"] = None

    def page() -> None:
        gui.build_ui()

    page.__module__ = "tests.trim_player_page"
    ui.page("/")(page)
    return gui


def trim_node(gui):
    """The trim command, wherever it sits in the tree."""

    def walk(nodes):
        for node in nodes:
            if "trim" in str(node.id or "").lower():
                return node
            found = walk(node.children)
            if found is not None:
                return found
        return None

    return walk(gui.root_command_nodes())


def test_the_player_field_is_declared_in_the_trim_group() -> None:
    """The widget exists in the manifest, with all five actions."""
    gui = gui_module()
    node = trim_node(gui)
    assert node is not None, "the manifest declares no trim command"
    field = next((item for item in node.fields if gui.field_id(item) == "trim_player"), None)
    assert field is not None, "the trim group has no player field"
    assert str(field.get("type")) == "mpv_transport"
    actions = [str(option.get("value")) for option in gui.field_options(field)]
    assert actions == ["open", "both", "mark_in", "mark_out", "close"]


def test_points_from_the_player_land_in_the_timecode_fields() -> None:
    """What mpv reports as A and B is what the fields must hold afterwards.

    Written the way the cutting engine reads it back - which is checked here by
    parsing it, rather than by comparing strings and hoping.
    """
    from system_core.core.trim_contract import parse_seconds

    gui = gui_module()
    gui.state["field_values"] = {}
    gui.mpv_points_to_fields(9.0, 21.04)

    values = gui.state["field_values"]
    assert values["trim_start"] == "00:00:09,000"
    assert values["trim_end"] == "00:00:21,040"
    assert parse_seconds(values["trim_start"]) == pytest.approx(9.0)
    assert parse_seconds(values["trim_end"]) == pytest.approx(21.04)

    # Only one point set is a normal state: the operator has found the start and
    # is still looking for the end.
    gui.state["field_values"] = {"trim_end": "00:00:30,000"}
    gui.mpv_points_to_fields(3.5, None)
    assert gui.state["field_values"]["trim_start"] == "00:00:03,500"
    assert gui.state["field_values"]["trim_end"] == "00:00:30,000"


def test_the_service_finds_a_staged_file_by_its_name(tmp_path: Path) -> None:
    """The panel hands the player a path; the name comes from the same list."""
    from system_core.services.media_service import trim_source_path

    source = tmp_path / "Source"
    source.mkdir()
    (source / "take.mov").write_bytes(b"not really a movie")

    assert trim_source_path("take.mov", tmp_path) == source / "take.mov"
    assert trim_source_path("missing.mov", tmp_path) is None
    assert trim_source_path("", tmp_path) is None


@pytest.mark.anyio
async def test_the_player_buttons_reach_the_trim_panel(user: User, fresh_gui) -> None:
    """Open the section the way an operator does, and look for the buttons."""
    gui = fresh_gui
    node = trim_node(gui)
    assert node is not None

    language = getattr(getattr(gui, "settings", None), "language", "ru") or "ru"
    await user.open("/")
    user.find(node.display_title(language)).click()

    field = next((item for item in node.fields if gui.field_id(item) == "trim_player"), None)
    assert field is not None
    for option in gui.field_options(field):
        await user.should_see(str(gui.option_label(option)))
