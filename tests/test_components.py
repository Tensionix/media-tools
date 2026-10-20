"""The versions the window shows in its header (`media_cli.cmd components`, core\\components.py).

A component compared with its newest release is fresh or old; the driver is shown, never compared - it is the user's;
FFmpeg under an NVIDIA driver below the LTS 610.88 is limited; one not installed is missing; GitHub not answering leaves it
unknown. GitHub is asked once a day at most, and at once when asked to refresh.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from system_core.core import components

MINE = [
    {"id": "yt-dlp", "name": "yt-dlp", "version": "2026.08.19"},
    {"id": "deno", "name": "deno", "version": "2.9.7"},
    {"id": "mpv", "name": "mpv", "version": "20260927"},
    {"id": "ffmpeg", "name": "FFmpeg", "version": "8.0.1"},
    {"id": "7zip", "name": "7-Zip", "version": "26.03"},
    {"id": "gpu", "name": "Intel(R) Iris(R) Xe Graphics", "version": "32.0.101.7085", "brand": "intel"},
]


@pytest.fixture()
def asked(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    calls: list[str] = []
    tags = {"yt-dlp/yt-dlp": "2026.10.01", "denoland/deno": "v2.9.7", "shinchiro/mpv-winbuild-cmake": "20261015", "ip7z/7zip": "26.04",
            "GyanD/codexffmpeg": "9.0.2"}

    def latest(repo: str) -> str:
        calls.append(repo)
        return tags[repo]

    monkeypatch.setattr(components, "latest_tag", latest)
    monkeypatch.setattr(components, "own_versions", lambda root: [dict(item) for item in MINE])
    return calls


def states(told: dict) -> dict[str, str]:
    return {item["name"]: item["state"] for item in told["components"]}


def test_without_a_question_nothing_is_compared(tmp_path: Path, asked: list[str]) -> None:
    told = components.report(tmp_path)
    assert asked == []
    assert states(told) == {"yt-dlp": "unknown", "deno": "unknown", "mpv": "unknown", "FFmpeg": "unknown", "7-Zip": "unknown",
                            "Intel(R) Iris(R) Xe Graphics": "own"}


def test_a_component_that_is_not_there_is_missing(tmp_path: Path, asked: list[str], monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(components, "own_versions", lambda root: [{"id": "7zip", "name": "7-Zip", "version": ""}])
    assert states(components.report(tmp_path, latest=True, now=datetime(2026, 10, 15))) == {"7-Zip": "missing"}


def test_the_newest_releases_are_compared_and_kept_for_a_day(tmp_path: Path, asked: list[str]) -> None:
    now = datetime(2026, 10, 15, 16, 0)
    told = components.report(tmp_path, latest=True, now=now)
    assert states(told)["yt-dlp"] == "old" and states(told)["deno"] == "fresh" and states(told)["mpv"] == "old"
    assert states(told)["7-Zip"] == "old" and states(told)["FFmpeg"] == "old"
    assert next(item for item in told["components"] if item["id"] == "deno")["source"] == "https://github.com/denoland/deno/releases/latest"
    kept = json.loads((tmp_path / "config" / "components_cache.json").read_text(encoding="utf-8"))
    assert kept["latest"]["mpv"] == "20261015"
    asked.clear()
    # Within a day the remembered answer stands; a day later GitHub is asked again; a refresh asks at once.
    assert states(components.report(tmp_path, latest=True, now=now + timedelta(hours=23)))["yt-dlp"] == "old" and asked == []
    components.report(tmp_path, latest=True, now=now + timedelta(days=1))
    assert len(asked) == 5
    components.report(tmp_path, refresh=True, now=now + timedelta(days=1, minutes=1))
    assert len(asked) == 10


@pytest.mark.parametrize("driver, build, state", [
    ("", "9.0.2", "fresh"),            # no NVIDIA card: the newest stable
    ("610.88", "9.0.2", "fresh"),      # the LTS driver
    ("610.88", "8.0.1", "old"),        # the LTS driver and an older build: the newest is due
    ("610.50", "8.0.1", "limited"),    # below the LTS driver: the older branch, not every operation
    ("566.36", "7.1", "limited"),
])
def test_ffmpeg_follows_the_nvidia_driver(tmp_path: Path, asked: list[str], monkeypatch: pytest.MonkeyPatch,
                                          driver: str, build: str, state: str) -> None:
    mine = [{"id": "ffmpeg", "name": "FFmpeg", "version": build}]
    if driver:
        mine.append({"id": "gpu", "name": "NVIDIA GeForce RTX 4070", "version": driver, "brand": "nvidia"})
    monkeypatch.setattr(components, "own_versions", lambda root: [dict(item) for item in mine])
    ffmpeg = next(item for item in components.report(tmp_path, latest=True, now=datetime(2026, 10, 18))["components"]
                  if item["id"] == "ffmpeg")
    assert ffmpeg["state"] == state
    assert ffmpeg.get("driver", "") == (driver if state == "limited" else "")


def test_github_not_answering_keeps_what_was_known(tmp_path: Path, asked: list[str], monkeypatch: pytest.MonkeyPatch) -> None:
    components.report(tmp_path, latest=True, now=datetime(2026, 10, 15))
    monkeypatch.setattr(components, "latest_tag", lambda repo: "")
    told = components.report(tmp_path, refresh=True, now=datetime(2026, 10, 17))
    assert states(told)["mpv"] == "old"
    assert told["checked"] == "2026-10-15T00:00:00"
