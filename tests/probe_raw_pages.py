"""The download pages of the programs that open camera RAW (config\\camera_raw.yaml): does each one still answer, and
where does it lead. On the network, so apart from the tests - run it now and then:

    runtime\\python.exe tests\\probe_raw_pages.py

A line a page: OK - it answers where it is; MOVED - it answers at another address (put that one into the table); FAIL -
it does not answer, with why. Exit code 0 - every page answers where it is written, 1 - one moved or failed.
"""
from __future__ import annotations

import sys
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from system_core.core.camera_raw import table  # noqa: E402

# A browser's name: some makers' sites answer a script's with 403.
AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0 Safari/537.36"
TIMEOUT = 40


def ask(page: str) -> tuple[str, str]:
    request = urllib.request.Request(page, headers={"User-Agent": AGENT, "Accept": "text/html,*/*"})
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as answer:
            where = answer.geturl()
            return ("OK" if where.rstrip("/") == page.rstrip("/") else "MOVED"), f"{answer.status} {where}"
    except urllib.error.HTTPError as error:
        return "FAIL", f"HTTP {error.code}"
    except (urllib.error.URLError, OSError, ValueError) as error:
        return "FAIL", f"{type(error).__name__}: {getattr(error, 'reason', error)}"


def main() -> int:
    programs = table()["programs"]
    bad = 0
    for key, program in programs.items():
        state, said = ask(program["page"])
        bad += state != "OK"
        print(f"[{state}] {program['name']}: {program['page']} - {said}")
    print(f"{len(programs)} pages, {bad} moved or not answering")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
