"""The layout of the window against the manifest: every operation stands once, every mode is a real choice."""
from __future__ import annotations

from pathlib import Path

from system_core.core import window_layout
from system_core.core.manifest import load_manifest

PROJECT = Path(__file__).resolve().parent.parent


def test_every_operation_stands_once_and_every_mode_is_a_choice() -> None:
    manifest = load_manifest(PROJECT / "config" / "tool_manifest.yaml")
    layout = window_layout.load(PROJECT / "config")
    assert window_layout.problems(layout, manifest) == []


def test_the_ribbon_is_the_owners() -> None:
    """Seven sections, DOWNLOAD at the right end (the owner, 15.10.2026)."""
    layout = window_layout.describe(window_layout.load(PROJECT / "config"))
    assert [section["title_ru"] for section in layout["sections"]] == [
        "АУДИО", "КОДИРОВАНИЕ", "УПАКОВКА", "НАРЕЗКА", "ЧАСТОТА", "ЦВЕТ", "СКАЧАТЬ"]


def test_the_window_gets_a_title_for_every_mode() -> None:
    manifest = load_manifest(PROJECT / "config" / "tool_manifest.yaml")
    told = window_layout.for_window(window_layout.load(PROJECT / "config"), manifest)
    for section in told["sections"]:
        for mode in section["modes"]:
            assert mode["title"] and mode["title_ru"], (section["id"], mode)


def test_the_filter_of_the_source_stands_last_in_audio() -> None:
    """The filter of 42 kinds of sound file is seldom wanted and pushed the fields in use out of sight (the owner, 15.10.2026):
    AUDIO draws it at the very end. A block no form of the section has is a mistake of the layout."""
    manifest = load_manifest(PROJECT / "config" / "tool_manifest.yaml")
    layout = window_layout.load(PROJECT / "config")
    told = {section["id"]: section for section in window_layout.for_window(layout, manifest)["sections"]}
    assert told["audio"]["blocks_last"] == ["source"]
    wrong = {**layout, "sections": [{**section, "blocks_last": ["nothing"]} if section["id"] == "audio" else section
                                    for section in layout["sections"]]}
    assert window_layout.problems(wrong, manifest) == ["the section audio: no form of it has the block 'nothing' of blocks_last"]


def test_paste_stands_beside_links_and_paths_and_formats_is_a_sign() -> None:
    """PASTE at the right of the link, the file of links and the cookies file; FORMATS of a link is the sign [i] alone and
    TAKE UNDER DPAPI the shield (the owner, 15.10.2026). PASTE beside a field that is no text or path is a mistake of the layout."""
    manifest = load_manifest(PROJECT / "config" / "tool_manifest.yaml")
    layout = window_layout.load(PROJECT / "config")
    told = window_layout.for_window(layout, manifest)
    assert told["paste"] == ["youtube_url", "batch_file", "cookies_path"]
    formats = next(button for button in told["buttons"] if button["op"] == "youtube_formats")
    assert (formats["icon"], formats["words"]) == ("info", False)
    dpapi = next(button for button in told["buttons"] if button["op"] == "youtube_cookies_import")
    assert (dpapi["icon"], dpapi["words"]) == ("shield-check", False)
    assert window_layout.problems({**layout, "paste": ["youtube_profile"]}, manifest) == [
        "PASTE stands beside no field of a text or a path: 'youtube_profile'"]
