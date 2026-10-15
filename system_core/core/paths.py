from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os


# The working folders: what an operation reads, and where it writes.
INPUT_DIR = "input"
OUTPUT_DIR = "output"
# Where the journals and the reports of the runs go. A process may name other folders: the tests do, so that the
# program's own stay the person's.
LOGS_ENV = "AUDION_LOGS"
REPORT_ENV = "AUDION_REPORT"


def _named_or(name: str, fallback: Path) -> Path:
    given = os.environ.get(name, "").strip().strip('"')
    return Path(given) if given else fallback


@dataclass(frozen=True)
class ProjectPaths:
    root: Path
    input: Path
    output: Path
    logs: Path
    report: Path
    workspace: Path
    config: Path
    system_core: Path


def find_project_root(start: Path | None = None) -> Path:
    current = (start or Path(__file__)).resolve()
    if current.is_file():
        current = current.parent

    for parent in [current, *current.parents]:
        if (parent / "system_core").exists() and (parent / "config").exists():
            return parent

    return Path(__file__).resolve().parents[2]


def get_project_paths(root: Path | None = None) -> ProjectPaths:
    project_root = (root or find_project_root()).resolve()
    return ProjectPaths(
        root=project_root,
        input=project_root / INPUT_DIR,
        output=project_root / OUTPUT_DIR,
        logs=_named_or(LOGS_ENV, project_root / "logs"),
        report=_named_or(REPORT_ENV, project_root / "report"),
        workspace=project_root / "workspace",
        config=project_root / "config",
        system_core=project_root / "system_core",
    )


def ensure_project_dirs(paths: ProjectPaths) -> None:
    for directory in [paths.input, paths.output, paths.logs, paths.report, paths.workspace, paths.config]:
        directory.mkdir(parents=True, exist_ok=True)


