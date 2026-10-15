"""The parameter model against the record of the former window.

tests\\former_window_parameters.json holds 1206 states of the forms of 18 operations as the window on
NiceGUI of 2.6.1 made them: each state with the clicks that led to it, and the parameters it handed the
service or the refusal it gave. Here the same clicks go through system_core\\core\\operation_model.py on a
stand like the one the record was taken on; the parameters and the refusal must be the same. The record
is not written anew; what 3.0.0 changes on purpose is changed here, one line each, with its reason.
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

import pytest

from system_core.core import operation_model as model
from system_core.core.manifest import load_manifest

PROJECT = Path(__file__).resolve().parent.parent
RECORD: list[dict[str, Any]] = json.loads((Path(__file__).resolve().parent / "former_window_parameters.json").read_text(encoding="utf-8"))
FORMS = [entry for entry in RECORD if entry["state"] != "maintenance"]

# Changed on purpose in 3.0.0 (the owner, 15.10.2026: "Source -> Transcoded на input -> output"): the working folders
# are input and output, and Download leaves the root - the list of links lies in the Source, the cookies of a
# browser with the program's state.
CHANGED = [
    ("<ROOT>\\Source", "<ROOT>\\input"),
    ("<ROOT>\\Transcoded", "<ROOT>\\output"),
]
# Defaults of fields, changed as whole values: a path a person typed stays as typed.
CHANGED_DEFAULTS = {"Download\\urls.txt": "input\\urls.txt", "Download\\cookies.txt": "config\\cookies.txt"}
# Fields 3.0.0 adds, with the value an untouched form gives them: what the wrappers of Scripts\ could do and the
# window could not (the owner, 15.10.2026: the wrappers become doors of the console command) - a section of a video,
# the downmix of audio-downmix-51-to-20 and the timestamps evened of audio-resample-*_sync; and the range of a playlist,
# which Media Downloader 5.6.6 has, and where the cookies come from - File by default, the file the former window read.
NEW_FIELDS = {"youtube_run": {"youtube_sections": "", "youtube_playlist_items": "", "cookies_source": "file"},
              "audio_run": {"downmix_formula": "ffmpeg", "audio_resync": False},
              # The scan of an interlaced source (the owner, 16.10.2026: "чересстрочная дрянь в 2026 году выглядит
              # несмешно"): progressive, a frame of each field, by default. A progressive source is not touched.
              **dict.fromkeys(("editing_run", "storage_run", "delivery_run", "grading_run"), {"scan_mode": "double"})}


# Defaults 3.0.0 changes on purpose, where the record never touched the field: the cut of a sound file is lossless (the
# owner, 15.10.2026) - an AAC cut exactly was encoded once more.
NEW_DEFAULTS = {"trim_run": {"trim_exact": False}}


def changed(parameters: dict[str, Any], operation: str = "") -> dict[str, Any]:
    moved = swap(parameters, CHANGED)
    told = {key: CHANGED_DEFAULTS.get(value, value) if isinstance(value, str) else value for key, value in moved.items()}
    for key, value in NEW_FIELDS.get(operation, {}).items():
        told.setdefault(key, value)
    told.update(NEW_DEFAULTS.get(operation, {}))
    return told


@pytest.fixture(scope="module")
def stand(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A project folder like the one the record was taken on: its configuration, its LUTs, two takes staged."""
    root = tmp_path_factory.mktemp("model")
    shutil.copytree(PROJECT / "config", root / "config", ignore=shutil.ignore_patterns("gui_lut_cache.json"))
    shutil.copytree(PROJECT / "LUTs", root / "LUTs")
    first = sorted((root / "LUTs").glob("*.cube"))[0]
    shutil.copy2(first, root / "LUTs" / "Second sample.cube")
    for name in ("input", "output"):
        (root / name).mkdir()
    for name in ("clip.mp4", "song.wav"):
        (root / "input" / name).write_bytes(b"")
    return root


@pytest.fixture(scope="module")
def manifest():
    return load_manifest(PROJECT / "config" / "tool_manifest.yaml")


def swap(value: Any, pairs: list[tuple[str, str]]) -> Any:
    if isinstance(value, str):
        for old, new in pairs:
            value = value.replace(old, new)
        return value
    if isinstance(value, list):
        return [swap(item, pairs) for item in value]
    if isinstance(value, dict):
        return {key: swap(item, pairs) for key, item in value.items()}
    return value


def test_the_record_is_whole() -> None:
    assert len(RECORD) == 1206
    assert {entry["operation"] for entry in FORMS} >= {"youtube_run", "audio_run", "archive_run", "editing_run", "storage_run",
                                                        "delivery_run", "remux_run", "trim_run", "fps_run", "grading_run"}


@pytest.mark.parametrize("entry", FORMS, ids=[f"{entry['operation']}:{entry['state']}" for entry in FORMS])
def test_a_form_becomes_what_the_former_window_made_of_it(entry: dict, stand: Path, manifest) -> None:
    there = [("<ROOT>", str(stand))]
    node = model.find_node(manifest, entry["operation"])
    assert node is not None, entry["operation"]
    form = model.Form(node, stand).open()
    for step in swap(entry["steps"], there):
        form.click(step["action"], step["field"], step["value"])
    assert swap(form.parameters(), [(str(stand), "<ROOT>")]) == changed(entry["parameters"], entry["operation"])
    assert form.refusal("en") == entry.get("refused", "")


def test_the_service_operations_run_with_their_own_parameters(manifest) -> None:
    for entry in RECORD:
        if entry["state"] == "maintenance":
            operation = model.find_node(manifest, entry["operation"])
            assert operation is not None and operation.parameters == entry["parameters"], entry["operation"]
