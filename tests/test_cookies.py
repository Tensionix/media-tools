"""The cookies of a download (media_service: _ytdlp_cookies, seal_cookies_file; core\\secret_store.py).

A browser is read by yt-dlp at the call and nothing is kept; a file is taken into a copy sealed with DPAPI, opened for a
call into a file of its own and sealed again after it - with what yt-dlp renewed - the open file gone; without the copy
the file of the field is read as it always was; the environment stands over the form.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

from system_core.services import media_service as media

COOKIES = b"# Netscape HTTP Cookie File\n.example.com\tTRUE\t/\tTRUE\t0\tSID\tsecret-value\n#HttpOnly_.example.com\tTRUE\t/\tTRUE\t0\tHSID\tother\n"
windows_only = pytest.mark.skipif(sys.platform != "win32", reason="DPAPI is a part of Windows")


class Context:
    def __init__(self) -> None:
        self.said: list[str] = []

    def log(self, text: str) -> None:
        self.said.append(text)


@pytest.fixture(autouse=True)
def no_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("AUDION_YTDLP_COOKIES_BROWSER", "YTDLP_COOKIES_BROWSER", "AUDION_YTDLP_COOKIES", "YTDLP_COOKIES", "COOKIES"):
        monkeypatch.delenv(name, raising=False)


def test_a_browser_is_read_by_yt_dlp_and_nothing_is_kept(tmp_path: Path) -> None:
    for browser in media.COOKIE_BROWSERS:
        args, done = media._ytdlp_cookies(Context(), tmp_path, {"cookies_source": browser})
        done()
        assert args == ["--cookies-from-browser", browser]
    assert list(tmp_path.iterdir()) == []


def test_none_is_no_cookies_even_with_a_file_there(tmp_path: Path) -> None:
    (tmp_path / "cookies.txt").write_bytes(COOKIES)
    assert media._ytdlp_cookies(Context(), tmp_path, {"cookies_source": "none", "cookies_path": "cookies.txt"})[0] == []


def test_without_a_sealed_copy_the_file_of_the_field_is_read_as_before(tmp_path: Path) -> None:
    assert media._ytdlp_cookies(Context(), tmp_path, {"cookies_path": "config\\cookies.txt"})[0] == []
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "cookies.txt").write_bytes(COOKIES)
    args, _ = media._ytdlp_cookies(Context(), tmp_path, {"cookies_path": "config\\cookies.txt"})
    assert args == ["--cookies", str(tmp_path / "config" / "cookies.txt")]


def test_the_environment_stands_over_the_form(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AUDION_YTDLP_COOKIES_BROWSER", "vivaldi")
    assert media._ytdlp_cookies(Context(), tmp_path, {"cookies_source": "none"})[0] == ["--cookies-from-browser", "vivaldi"]


@windows_only
def test_a_file_is_sealed_opened_for_a_call_and_sealed_again(tmp_path: Path) -> None:
    given = tmp_path / "exported.txt"
    given.write_bytes(COOKIES)
    assert media.seal_cookies_file(tmp_path, given) == 2
    sealed = tmp_path / media.SEALED_COOKIES
    assert sealed.is_file() and b"secret-value" not in sealed.read_bytes()

    context = Context()
    args, done = media._ytdlp_cookies(context, tmp_path, {"cookies_source": "file", "cookies_path": str(given)})
    opened = Path(args[1])
    assert args[0] == "--cookies" and opened != given and opened.read_bytes() == COOKIES
    assert not any("secret-value" in line for line in context.said)
    # yt-dlp writes back the cookies it was given, renewed: they are sealed again, and the open file goes.
    opened.write_bytes(COOKIES + b".example.com\tTRUE\t/\tTRUE\t0\tNEW\tfresh\n")
    done()
    assert not opened.exists()
    from system_core.core.secret_store import open_sealed

    assert b"\tNEW\tfresh" in open_sealed(sealed.read_bytes())
    # A dry run opens nothing.
    args, _ = media._ytdlp_cookies(context, tmp_path, {"cookies_source": "file"}, opened=False)
    assert args[0] == "--cookies" and "cookies.dpapi" in args[1] and not Path(args[1]).exists()


@windows_only
def test_what_is_no_cookies_file_is_refused(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError, match="no cookies file"):
        media.seal_cookies_file(tmp_path, tmp_path / "missing.txt")
    other = tmp_path / "notes.txt"
    other.write_text("a word\nanother\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="Netscape"):
        media.seal_cookies_file(tmp_path, other)
    assert not (tmp_path / media.SEALED_COOKIES).exists()
