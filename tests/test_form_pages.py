"""The forms the window holds (`media_cli.cmd form`, core\\form_pages.py).

The window shows what the form server answers and runs what it holds. So: the clicks of the record of the former
window, put through the server, give what that window gave; a page sent to `run` as its values gives the same
parameters it showed; the machine's fields are one for every page; and the process answers a line for a line.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from system_core.core import form_pages
from system_core.core import operation_model as model
from system_core.core import window_layout
from system_core.core.manifest import load_manifest

PROJECT = Path(__file__).resolve().parent.parent
RECORD: list[dict[str, Any]] = json.loads((Path(__file__).resolve().parent / "former_window_parameters.json").read_text(encoding="utf-8"))
FORMS = [entry for entry in RECORD if entry["state"] != "maintenance"]

from test_operation_model import changed, swap  # noqa: E402  - the same reading of the record


@pytest.fixture(scope="module")
def stand(tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = tmp_path_factory.mktemp("pages")
    shutil.copytree(PROJECT / "config", root / "config", ignore=shutil.ignore_patterns("gui_lut_cache.json"))
    shutil.copytree(PROJECT / "LUTs", root / "LUTs")
    shutil.copy2(sorted((root / "LUTs").glob("*.cube"))[0], root / "LUTs" / "Second sample.cube")
    for name in ("input", "output"):
        (root / name).mkdir()
    for name in ("clip.mp4", "song.wav"):
        (root / "input" / name).write_bytes(b"")
    return root


@pytest.fixture(autouse=True)
def no_lut_memory(stand: Path):
    """A LUT chosen is remembered in config\\gui_lut_cache.json, as the former window remembered it, and a fresh form takes
    it: every test starts without that memory, or the LUT of one record would be the default of the next."""
    (stand / "config" / "gui_lut_cache.json").unlink(missing_ok=True)
    yield


@pytest.fixture(scope="module")
def manifest():
    return load_manifest(PROJECT / "config" / "tool_manifest.yaml")


@pytest.mark.parametrize("entry", FORMS, ids=[f"{entry['operation']}:{entry['state']}" for entry in FORMS])
def test_the_clicks_of_the_record_through_the_server(entry: dict, stand: Path, manifest) -> None:
    pages = form_pages.Pages(stand, manifest)
    pages.open("page", entry["operation"], None, None)
    for step in swap(entry["steps"], [("<ROOT>", str(stand))]):
        pages.click("page", step["action"], step["field"], step["value"])
    form = pages.pages["page"].form
    assert swap(form.parameters(), [(str(stand), "<ROOT>")]) == changed(entry["parameters"], entry["operation"])
    assert pages.state("page")["refusal"] == entry.get("refused", "")


def layout_pages(manifest) -> list[tuple[str, str, dict[str, Any] | None]]:
    told = window_layout.for_window(window_layout.load(PROJECT / "config"), manifest)
    found = []
    for section in told["sections"]:
        for mode in section["modes"]:
            key = f"{section['id']}/{mode['value'] if mode['field'] else mode['op']}"
            found.append((key, mode["op"], {"field": mode["field"], "value": mode["value"]} if mode["field"] else None))
    return found


def test_every_page_runs_what_it_shows(stand: Path, manifest) -> None:
    """The values of a page, given to a run, fill a form to the same parameters: what the window shows is what runs."""
    pages = form_pages.Pages(stand, manifest)
    for key, operation, mode in layout_pages(manifest):
        state = pages.open(key, operation, mode, None)
        shown = pages.pages[key].form.parameters()
        node = model.find_node(manifest, operation)
        run = model.Form(node, stand).open().fill(state["values"])
        assert run.parameters() == shown, key
        if mode:
            assert state["values"][mode["field"]] == mode["value"] and mode["field"] not in state["shown"], key
            assert state["set"] == {mode["field"]: form_pages.as_text(mode["value"])}, key
        else:
            assert state["set"] == {}, key


def test_a_form_is_remembered_and_the_machine_is_one(stand: Path, manifest) -> None:
    pages = form_pages.Pages(stand, manifest)
    pages.open("encode/delivery_run", "delivery_run", None, None)
    pages.open("encode/storage_run", "storage_run", None, None)
    state = pages.click("encode/storage_run", "preset", "storage_profile", "hevc10_crf14")
    assert state["presets"]["storage_profile"] == "hevc10_crf14" and "storage_profile" in state["set"]
    # The encoder set on one page is the encoder of every page.
    pages.click("encode/storage_run", "choose", "encode_backend", "cuda")
    assert pages.state("encode/delivery_run")["values"]["encode_backend"] == "cuda"
    # A page opened again with what it held: the same form.
    held = pages.state("encode/storage_run")["values"]
    again = form_pages.Pages(stand, manifest).open("encode/storage_run", "storage_run", None, held)
    assert again["values"] == held
    # Back to its start; the machine stays.
    reset = pages.reset("encode/storage_run")
    assert reset["presets"]["storage_profile"] != "hevc10_crf14" and reset["values"]["encode_backend"] == "cuda"


def test_a_choice_that_is_off_is_told(stand: Path, manifest) -> None:
    pages = form_pages.Pages(stand, manifest)
    pages.open("audio/extract", "audio_run", {"field": "audio_workflow", "value": "extract"}, None)
    pages.click("audio/extract", "select", "audio_format", "mp3")
    # The bitrate is in sight for MP3 when its LAME preset is "by bitrate"; 384k is AAC's, MP3 stops at 320.
    state = pages.click("audio/extract", "choose", "mp3_lame_preset", "bitrate")
    rates = dict((value, off) for value, off, *_ in state["choices"]["audio_bitrate"])
    assert rates["384k"] is True and state["values"]["audio_bitrate"] != "384k"


def test_a_trim_page_tells_its_take_and_a_new_take_clears_the_points(stand: Path, manifest, monkeypatch: pytest.MonkeyPatch) -> None:
    """The window draws the rows of a trim and hands its take to the player by what `take` says; the points of a take
    describe that take only - another one starts clean, the same one keeps them (the window on NiceGUI, app.py: step)."""
    monkeypatch.setenv(form_pages.SOURCE_ENV, str(stand / "input"))
    pages = form_pages.Pages(stand, manifest)
    pages.open("cut/keep", "trim_run", {"field": "trim_action", "value": "keep"}, None)
    take = pages.handle({"do": "take", "page": "cut/keep"})["take"]
    assert take["names"] == ["clip.mp4", "song.wav"]
    assert (take["name"], take["kind"], Path(take["path"])) == ("clip.mp4", "video", stand / "input" / "clip.mp4")
    pages.click("cut/keep", "point", "trim_rows", [0, "start", "00:00:01,000"])
    pages.click("cut/keep", "add_row", "trim_rows", None)
    pages.click("cut/keep", "point", "trim_rows", [1, "end", "00:00:02,000"])
    values = pages.state("cut/keep")["values"]
    assert (values["trim_start"], values["trim_rows"]) == ("00:00:01,000", [{"start": "", "end": "00:00:02,000"}])
    pages.click("cut/keep", "take", "trim_file", "song.wav")
    values = pages.state("cut/keep")["values"]
    assert (values["trim_file"], values["trim_start"], values["trim_rows"], values["trim_points"]) == ("song.wav", "", [], [])
    assert pages.handle({"do": "take", "page": "cut/keep"})["take"]["kind"] == "audio"
    pages.click("cut/keep", "point", "trim_rows", [0, "end", "00:00:01,500"])
    pages.click("cut/keep", "take", "trim_file", "song.wav")
    assert pages.state("cut/keep")["values"]["trim_end"] == "00:00:01,500"
    # An empty file is no media: ffprobe's refusal comes back as words, not as a failed request.
    probe = pages.handle({"do": "probe", "page": "cut/keep"})["probe"]
    assert probe["ok"] is False and probe["error"]


def test_luts_are_added_pinned_and_listed_in_the_order_of_the_former_window(stand: Path, manifest, tmp_path: Path) -> None:
    """A LUT field lists the pinned first, then the chosen one, the recent ones and the rest of LUTs\\; files added are
    copied into LUTs\\ and the first of them is chosen; what is not a LUT is passed over."""
    pages = form_pages.Pages(stand, manifest)
    pages.open("color", "grading_run", None, None)
    field = next(model.field_id(item) for item in model.form_fields(pages.pages["color"].node) if model.field_kind(item) in model.LUT_PICKS)
    (tmp_path / "Look B.cube").write_text("LUT_3D_SIZE 2\n", encoding="utf-8")
    (tmp_path / "notes.txt").write_text("not a LUT", encoding="utf-8")
    added = pages.handle({"do": "lut_add", "page": "color", "field": field, "files": [str(tmp_path / "Look B.cube"), str(tmp_path / "notes.txt")]})
    copy = stand / "LUTs" / "Look B.cube"
    # The stand is one for the module: the copy goes when the test is over.
    try:
        check_luts(pages, field, added, copy)
    finally:
        copy.unlink(missing_ok=True)


def check_luts(pages: form_pages.Pages, field: str, added: dict, copy: Path) -> None:
    stand = copy.parent.parent
    assert added["added"] == 1
    assert copy.is_file() and not (stand / "LUTs" / "notes.txt").exists()
    assert Path(added["values"][field]) == copy.resolve()
    assert added["choices"][field][0][:3] == [str(copy.resolve()), False, "Look B.cube"]
    last = added["choices"][field][-1][0]
    pinned = pages.handle({"do": "lut_pin", "page": "color", "value": last, "pinned": True})
    assert pinned["choices"][field][0][0] == last and pinned["pinned"][field] == [last]
    # A pin is no choice: the form keeps the LUT it held.
    assert Path(pinned["values"][field]) == copy.resolve()
    let_go = pages.handle({"do": "lut_pin", "page": "color", "value": last, "pinned": False})
    assert let_go["pinned"][field] == [] and let_go["choices"][field][0][0] == str(copy.resolve())


def test_the_process_answers_a_line_for_a_line(tmp_path: Path) -> None:
    requests = [
        {"id": 1, "do": "open", "page": "rate/conform", "operation": "fps_run", "mode": {"field": "fps_mode", "value": "conform"}},
        {"id": 2, "do": "click", "page": "rate/conform", "action": "choose", "field": "fps_target", "value": "25"},
        {"id": 3, "do": "click", "page": "nowhere", "action": "choose", "field": "x", "value": 1},
        {"id": 4, "do": "state", "page": "rate/conform", "language": "ru"},
    ]
    done = subprocess.run([sys.executable, "-u", str(PROJECT / "system_core" / "cli.py"), "form"], input="\n".join(json.dumps(r) for r in requests) + "\n",
                          capture_output=True, text=True, encoding="utf-8", errors="replace", cwd=str(PROJECT), timeout=300)
    assert done.returncode == 0, done.stderr[-800:]
    answers = [json.loads(line) for line in done.stdout.splitlines() if line.strip()]
    assert [answer["id"] for answer in answers] == [1, 2, 3, 4]
    assert answers[0]["ok"] and answers[0]["values"]["fps_mode"] == "conform"
    assert answers[1]["set"] == {"fps_mode": "conform", "fps_target": "25"}
    assert not answers[2]["ok"] and "no page" in answers[2]["error"]
    assert answers[3]["ok"] and answers[3]["values"]["fps_target"] == "25"
