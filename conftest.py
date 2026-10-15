"""Pytest, for every test of the project: the journals and the reports of the runs the tests start go to a folder of
the session (core\\paths.py: AUDION_LOGS, AUDION_REPORT), not to logs\\ and report\\ of the program - those stay the
person's. The folder goes when the session ends."""
from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path

_RUNS = Path(tempfile.mkdtemp(prefix="audion-test-runs-"))
os.environ.setdefault("AUDION_LOGS", str(_RUNS / "logs"))
os.environ.setdefault("AUDION_REPORT", str(_RUNS / "report"))


def pytest_sessionfinish(session, exitstatus) -> None:
    shutil.rmtree(_RUNS, ignore_errors=True)
