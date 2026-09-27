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
    # Five for a keep or a cut; a split swaps the three loop buttons for two point buttons.
    assert actions == ["open", "both", "mark_in", "mark_out", "take_a", "mark_point", "close"]


def visible_actions(gui, action: str) -> list[str]:
    gui.state["field_values"] = {"trim_action": action}
    field = next(item for item in trim_node(gui).fields if gui.field_id(item) == "trim_player")
    return [str(item["value"]) for item in gui.choice_option_items(field)]


def test_a_split_shows_its_own_player_buttons() -> None:
    gui = gui_module()
    assert visible_actions(gui, "keep") == ["open", "both", "mark_in", "mark_out", "close"]
    assert visible_actions(gui, "cut") == ["open", "both", "mark_in", "mark_out", "close"]
    assert visible_actions(gui, "split") == ["open", "take_a", "mark_point", "close"]


def test_the_player_writes_into_the_last_row() -> None:
    """Row 1 is IN and OUT; after a + the player fills the new row, not the old one."""
    gui = gui_module()
    gui.state["field_values"] = {"trim_action": "keep"}
    gui.mpv_points_to_fields(9.0, 21.04)
    assert gui.trim_add_row()
    written = gui.mpv_points_to_fields(15.0, 40.0)

    values = gui.state["field_values"]
    assert values["trim_start"] == "00:00:09,000"
    assert values["trim_end"] == "00:00:21,040"
    assert values["trim_rows"] == [{"start": "00:00:15,000", "end": "00:00:40,000"}]
    assert written == ["2: IN 00:00:15,000", "2: OUT 00:00:40,000"]


def test_the_plus_waits_for_what_the_action_needs() -> None:
    gui = gui_module()
    # A keep row with IN alone is a whole variant already: the head goes.
    gui.state["field_values"] = {"trim_action": "keep", "trim_start": "00:00:05,000"}
    assert gui.trim_can_add()
    # A cut needs both points, or there is nothing between them to cut out.
    gui.state["field_values"] = {"trim_action": "cut", "trim_start": "00:00:05,000"}
    assert not gui.trim_can_add()
    assert not gui.trim_add_row()
    gui.state["field_values"]["trim_end"] = "00:00:08,000"
    assert gui.trim_add_row()
    # The new, empty row greys the + again.
    assert not gui.trim_can_add()


def test_split_points_are_taken_only_walking_forward() -> None:
    gui = gui_module()
    gui.state["field_values"] = {"trim_action": "split"}
    assert gui.trim_split_take(10.0) == "00:00:10,000"
    assert gui.trim_add_row()
    # The slider went back by accident: nothing is written.
    assert gui.trim_split_take(8.0) is None
    assert gui.trim_split_take(10.0) is None
    assert gui.trim_split_points() == ["00:00:10,000", ""]
    assert gui.trim_split_take(12.5) == "00:00:12,500"
    # The last point itself may be retaken, as long as it stays past the one before.
    assert gui.trim_split_take(11.0) == "00:00:11,000"
    assert gui.state["field_values"]["trim_points"] == ["00:00:10,000", "00:00:11,000"]


def test_the_length_of_a_piece_follows_the_action() -> None:
    gui = gui_module()
    assert gui.trim_piece_seconds("00:00:05,000", "00:00:09,500", "keep") == pytest.approx(4.5)
    assert gui.trim_piece_seconds("00:00:05,000", "00:00:09,500", "cut") == pytest.approx(4.5)
    # IN alone keeps the rest of the file; OUT alone keeps the start of it.
    assert gui.trim_piece_seconds("00:00:05,000", "", "keep", 30.0) == pytest.approx(25.0)
    assert gui.trim_piece_seconds("", "00:00:09,500", "keep") == pytest.approx(9.5)
    # A cut with one point cuts nothing, and a reversed or unreadable row has no length.
    assert gui.trim_piece_seconds("00:00:05,000", "", "cut", 30.0) is None
    assert gui.trim_piece_seconds("00:00:09,000", "00:00:05,000", "keep") is None
    assert gui.trim_piece_seconds("soon", "00:00:05,000", "keep") is None


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


@pytest.mark.anyio
async def test_the_points_of_another_file_are_not_taken(user: User, fresh_gui, tmp_path: Path, monkeypatch) -> None:
    """Found by the 2.6.0 audit: the arrows changed the file in the panel, not in
    the player, and `Take A and B` wrote the old take's loop into the new one."""
    from system_core.services import mpv_service

    gui = fresh_gui
    (tmp_path / "Source").mkdir()
    for name in ("A.mp4", "B.mp4"):
        (tmp_path / "Source" / name).write_bytes(b"not really a movie")
    monkeypatch.setattr(gui, "ROOT", tmp_path)

    class Player:
        shown = tmp_path / "Source" / "A.mp4"

        def is_running(self) -> bool:
            return True

        def ab_loop(self):
            return 1.0, 3.0

        def send(self, *command):
            # What mpv itself answers: the file it shows, not what the panel remembers.
            return str(self.shown) if command == ("get_property", "path") else None

    player = Player()
    monkeypatch.setattr(mpv_service, "player", lambda *args: player)

    node = trim_node(gui)
    await user.open("/")
    user.find(node.display_title(gui.settings.language)).click()
    await user.should_see("A.mp4")
    step = next(item for item in user.find(ui.button).elements if item.props.get("icon") == "chevron_right")
    step.mark("next_take")
    user.find("next_take").click()
    await user.should_see("B.mp4")

    field = next(item for item in node.fields if gui.field_id(item) == "trim_player")
    take = next(item for item in gui.choice_option_items(field) if item["value"] == "both")
    user.find(take["label"]).click()
    values = gui.state["field_values"]
    assert values.get("trim_start", "") == "" and values.get("trim_end", "") == ""

    # Once the player shows B, its points are B's and they are taken.
    player.shown = tmp_path / "Source" / "B.mp4"
    user.find(take["label"]).click()
    assert values["trim_start"] == "00:00:01,000" and values["trim_end"] == "00:00:03,000"


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
    for item in gui.choice_option_items(field):
        await user.should_see(str(item["label"]))

    # Each point field carries its ▲▼: IN and OUT of row 1, up and down each.
    spinners = [element for element in user.find(ui.button).elements if element.props.get("data-audion-spin")]
    assert sorted(str(element.props["data-audion-spin"]) for element in spinners) == ["-1", "-1", "1", "1"]
