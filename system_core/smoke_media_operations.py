from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from system_core.core.jobs import JobContext
from system_core.core.manifest import Operation
from system_core.core.paths import ensure_project_dirs, get_project_paths
from system_core.services.media_service import preset_test_matrix


def run_backend_matrix(*, clean: bool = True) -> dict[str, object]:
    paths = get_project_paths(ROOT)
    ensure_project_dirs(paths)
    report_dir = paths.report / "refactor_media_smoke"
    if clean and report_dir.exists():
        shutil.rmtree(report_dir)
    report_dir.mkdir(parents=True, exist_ok=True)
    log_file = report_dir / "backend_matrix.log"
    operation = Operation(
        id="preset_test_matrix",
        title="Preset Test Matrix",
        description="Refactor acceptance matrix",
        service="system_core.services.media_service:preset_test_matrix",
        parameters={},
    )
    context = JobContext(
        paths=paths,
        operation=operation,
        log_file=log_file,
        report_dir=report_dir,
        log_callback=lambda line: print(line, flush=True),
    )
    return preset_test_matrix(context)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run real short-file Media Tools acceptance smoke.")
    parser.add_argument("--keep", action="store_true", help="Keep an existing report directory before the run.")
    args = parser.parse_args(argv)
    result = run_backend_matrix(clean=not args.keep)
    summary = result.get("summary", {})
    print("SMOKE_SUMMARY=" + json.dumps(summary, ensure_ascii=False, sort_keys=True))
    print(f"SMOKE_REPORT={result.get('preset_matrix_md', '')}")
    return 0 if bool(result.get("ok")) else 1


if __name__ == "__main__":
    raise SystemExit(main())
