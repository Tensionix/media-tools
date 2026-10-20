"""The components the program carries and the machine it runs on: their versions, and which of them has a newer release.

    media_cli.cmd components            the versions on this machine, the newest releases as last remembered
    media_cli.cmd components --latest   the newest releases asked of GitHub when the remembered ones are a day old
    media_cli.cmd components --refresh  asked of GitHub now

One line of JSON: {"components": [...], "checked": "<when GitHub was asked>"}. A component:

  id, name     yt-dlp, deno, mpv, ffmpeg, 7zip, gpu
  version      as the component says it of itself ("" - it is not there)
  latest       the tag of its newest release ("" - not compared, or not known)
  state        fresh / old - compared; own - not compared on purpose (the driver is the user's); limited - FFmpeg of an
               NVIDIA driver below the LTS 610.88: the older branch that keeps NVENC working, not every operation possible
               (`driver` says which); missing - not installed; unknown - GitHub did not answer
  source       where the newest release is read: https://github.com/<repo>/releases/latest
  brand        the maker of a GPU: nvidia, intel, amd

The newest release is read from the tag that github.com/<repo>/releases/latest sends the browser to - no API and no limit
of requests, the way install\\Install-Portable-mpv.ps1 and Audion Sync Tools (Get-GithubTag) read it. The answers are kept in
config\\components_cache.json; without a network the program works as it did, and the state is unknown.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
import urllib.error
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

CACHE = Path("config") / "components_cache.json"
FRESH_FOR = timedelta(days=1)
TIMEOUT = 8

# What is compared with its newest release, and where that release is read.
RELEASES = {
    "yt-dlp": "yt-dlp/yt-dlp",
    "deno": "denoland/deno",
    "mpv": "shinchiro/mpv-winbuild-cmake",
    "7zip": "ip7z/7zip",
    "ffmpeg": "GyanD/codexffmpeg",
}

# FFmpeg by the NVIDIA driver (install\Install-Portable-FFmpeg-Gyan.ps1 holds the same, 18.10.2026): the newest Gyan stable,
# FFMPEG_FLOOR at least, without an NVIDIA card and from the LTS driver GOLDEN_DRIVER; below it the branch that keeps NVENC
# working - and not every operation is possible. The owner: "600-я серия драйверов уже окрепла и 610.88 стала LTS golden
# версией... собирать на основе драйвера, предупреждая, что при отсутствии минимально допустимого драйвера 610.88 для
# всех возможностей, будут возможны не все операции"; "Закреплять не стоит. Если выйдет 9.1.0 - надо его ставить?"
FFMPEG_FLOOR = "9.0.2"
GOLDEN_DRIVER = "610.88"


def driver_below_golden(driver: str) -> bool:
    """An NVIDIA driver below the LTS one: its FFmpeg is an older branch, not every operation is possible."""
    return bool(driver) and _plain(driver) < _plain(GOLDEN_DRIVER)


def _quiet(command: list[str], timeout: float = 15) -> str:
    """What a program prints of itself; "" when it is not there or does not answer."""
    try:
        creation = getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0
        done = subprocess.run(command, capture_output=True, timeout=timeout, creationflags=creation)
    except (OSError, subprocess.SubprocessError):
        return ""
    return (done.stdout or b"").decode("utf-8", errors="replace") + (done.stderr or b"").decode("utf-8", errors="replace")


def _first(pattern: str, text: str) -> str:
    found = re.search(pattern, text, re.MULTILINE)
    return found.group(1) if found else ""


def own_versions(root: Path) -> list[dict[str, Any]]:
    tools = root / "Tools"
    found: list[dict[str, Any]] = []

    ytdlp = tools / "yt-dlp" / "bin" / "yt-dlp.exe"
    found.append({"id": "yt-dlp", "name": "yt-dlp", "version": _first(r"^(\d{4}\.\d{2}\.\d{2}(?:\.\d+)?)", _quiet([str(ytdlp), "--version"])) if ytdlp.exists() else ""})

    deno = tools / "deno" / "deno.exe"
    found.append({"id": "deno", "name": "deno", "version": _first(r"^deno (\S+)", _quiet([str(deno), "--version"])) if deno.exists() else ""})

    mpv = ""
    try:
        told = json.loads((tools / "mpv" / "mpv-source.json").read_text(encoding="utf-8"))
        mpv = str(told.get("release_tag") or "")
        version = str(told.get("version") or "").removeprefix("mpv ").strip()
    except (OSError, ValueError):
        version = ""
    if not (tools / "mpv" / "bin" / "mpv.exe").exists():
        mpv = version = ""
    found.append({"id": "mpv", "name": "mpv", "version": mpv, "detail": version})

    ffmpeg = tools / "ffmpeg" / "bin" / "ffmpeg.exe"
    # "8.0.1-full_build-www.gyan.dev": the number is the version, the rest is whose build it is.
    build = _first(r"^ffmpeg version (\S+)", _quiet([str(ffmpeg), "-version"])) if ffmpeg.exists() else ""
    found.append({"id": "ffmpeg", "name": "FFmpeg", "version": build.split("-", 1)[0], "detail": build})

    seven = next((path for path in (tools / "7zip" / "bin" / "7za.exe", tools / "7zip" / "bin" / "7z.exe", tools / "7zip" / "7z.exe") if path.exists()), None)
    found.append({"id": "7zip", "name": "7-Zip", "version": _first(r"7-Zip(?: \(\w\))? (\d+\.\d+)", _quiet([str(seven)])) if seven else ""})

    # cineraw comes with the program: step 15 of the builder builds it from libcraw (install\Install-Cineraw.ps1), no video
    # card needed for that; SERVICE - Install ProRes RAW development builds it again, for another commit of libcraw. Said
    # when it is there - a machine without a card for it has no use of a red dot. Its version is the commit of libcraw.
    cineraw = tools / "cineraw"
    if (cineraw / "cineraw.exe").exists():
        try:
            told = json.loads((cineraw / "cineraw-source.json").read_text(encoding="utf-8-sig"))
        except (OSError, ValueError):
            told = {}
        commit = str(told.get("upstream_commit") or "")[:7]
        found.append({"id": "cineraw", "name": "cineraw", "version": commit or "built",
                      "detail": f"libcraw {commit}, FFmpeg {told.get('ffmpeg_version') or '?'}: ProRes RAW developed on the video card"})

    found.extend(gpus())
    return found


def gpus() -> list[dict[str, Any]]:
    """Every video card with its driver: NVIDIA by nvidia-smi, the others as Windows knows them."""
    cards: list[dict[str, Any]] = []
    smi = _quiet(["nvidia-smi", "--query-gpu=name,driver_version", "--format=csv,noheader"], timeout=10)
    nvidia = [line.split(",") for line in smi.splitlines() if line.count(",") == 1 and "NVIDIA" in line.upper()]
    for name, driver in nvidia:
        cards.append({"id": "gpu", "name": name.strip(), "version": driver.strip(), "brand": "nvidia"})
    if sys.platform != "win32":
        return cards
    listed = _quiet(["powershell", "-NoLogo", "-NoProfile", "-Command",
                     "Get-CimInstance Win32_VideoController | Select-Object Name, DriverVersion | ConvertTo-Json -Compress"], timeout=20)
    try:
        controllers = json.loads(listed[listed.find("["):] if listed.lstrip().startswith("[") else listed[listed.find("{"):])
    except ValueError:
        controllers = []
    for controller in controllers if isinstance(controllers, list) else [controllers]:
        if not isinstance(controller, dict):
            continue
        name = str(controller.get("Name") or "").strip()
        lowered = name.lower()
        if not name or "nvidia" in lowered and nvidia or "basic display" in lowered or "remote" in lowered:
            continue
        brand = "nvidia" if "nvidia" in lowered else "intel" if "intel" in lowered else "amd" if "amd" in lowered or "radeon" in lowered else ""
        cards.append({"id": "gpu", "name": name, "version": str(controller.get("DriverVersion") or ""), "brand": brand})
    return cards


def latest_tag(repo: str) -> str:
    """The tag github.com/<repo>/releases/latest sends to; "" when GitHub does not answer."""

    class Stay(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *args: Any, **kwargs: Any) -> None:  # noqa: D401 - the place is read, not followed
            return None

    opener = urllib.request.build_opener(Stay)
    request = urllib.request.Request(f"https://github.com/{repo}/releases/latest", method="HEAD", headers={"User-Agent": "Audion-Media-Tools"})
    try:
        opener.open(request, timeout=TIMEOUT)
        return ""
    except urllib.error.HTTPError as answer:
        place = answer.headers.get("Location", "") if answer.code in {301, 302, 303, 307, 308} else ""
    except (urllib.error.URLError, OSError, ValueError):
        return ""
    return place.rstrip("/").rsplit("/tag/", 1)[-1] if "/tag/" in place else ""


def _load(root: Path) -> dict[str, Any]:
    try:
        cache = json.loads((root / CACHE).read_text(encoding="utf-8"))
        return cache if isinstance(cache, dict) else {}
    except (OSError, ValueError):
        return {}


def _plain(version: str) -> tuple[int, ...]:
    return tuple(int(part) for part in re.findall(r"\d+", version))


def report(root: Path, latest: bool = False, refresh: bool = False, now: datetime | None = None) -> dict[str, Any]:
    now = now or datetime.now()
    cache = _load(root)
    known: dict[str, str] = dict(cache.get("latest") or {})
    checked = str(cache.get("checked") or "")
    try:
        stale = not checked or now - datetime.fromisoformat(checked) >= FRESH_FOR
    except ValueError:
        stale = True
    if refresh or (latest and stale):
        asked = {name: latest_tag(repo) for name, repo in RELEASES.items()}
        if any(asked.values()):
            known.update({name: tag for name, tag in asked.items() if tag})
            checked = now.isoformat(timespec="seconds")
            (root / CACHE).parent.mkdir(parents=True, exist_ok=True)
            (root / CACHE).write_text(json.dumps({"checked": checked, "latest": known}, ensure_ascii=False, indent=2), encoding="utf-8")

    components = own_versions(root)
    nvidia = next((card.get("version", "") for card in components if card["id"] == "gpu" and card.get("brand") == "nvidia"), "")
    for component in components:
        name = component["id"]
        component["latest"] = known.get(name, "")
        component["source"] = f"https://github.com/{RELEASES[name]}/releases/latest" if name in RELEASES else ""
        if not component["version"]:
            component["state"] = "missing"
        elif name not in RELEASES:
            component["state"] = "own"
        elif name == "ffmpeg" and driver_below_golden(nvidia):
            component["state"], component["driver"] = "limited", nvidia
        elif not component["latest"]:
            component["state"] = "unknown"
        else:
            component["state"] = "old" if _plain(component["version"]) < _plain(component["latest"]) else "fresh"
    return {"components": components, "checked": checked}
