from __future__ import annotations

from pathlib import Path
import importlib
import platform
import shutil
import sys

REQUIRED_MODULES = [
    ("tqdm", "tqdm"),
    ("rich", "rich"),
    ("pydantic", "pydantic"),
    ("nicegui", "nicegui"),
    ("webview", "pywebview"),
    ("yaml", "pyyaml"),
    ("markdown_it", "markdown-it-py"),
]

OPTIONAL_MODULES = [
    ("requests", "requests"),
    ("docx", "python-docx"),
    ("openai", "openai"),
    ("google.genai", "google-genai"),
    ("pandas", "pandas"),
    ("openpyxl", "openpyxl"),
    ("fitz", "pymupdf"),
    ("pptx", "python-pptx"),
]


def check_module(import_name: str) -> tuple[bool, str]:
    try:
        mod = importlib.import_module(import_name)
        version = getattr(mod, "__version__", "unknown")
        return True, str(version)
    except Exception as exc:
        return False, exc.__class__.__name__


def detect_python_mode(root: Path) -> str:
    if (root / "runtime" / "python.exe").exists():
        return "portable-runtime"
    if (root / "runtime" / "python" / "python.exe").exists():
        return "portable-runtime"
    return "system-python"


def check_picker_powershell(root: Path) -> tuple[bool, list[tuple[str, bool, str]]]:
    candidates = [
        ("portable pwsh", root / "system_core" / "powershell" / "pwsh.exe"),
        ("PATH pwsh", "pwsh.exe"),
        ("Windows PowerShell", "powershell.exe"),
    ]
    rows: list[tuple[str, bool, str]] = []
    any_ok = False
    for label, candidate in candidates:
        if isinstance(candidate, Path):
            ok = candidate.exists()
            detail = str(candidate)
        else:
            resolved = shutil.which(candidate)
            ok = bool(resolved)
            detail = resolved or "not found"
        rows.append((label, ok, detail))
        any_ok = any_ok or ok
    return any_ok, rows


def check_manifest_operations(root: Path) -> tuple[bool, list[tuple[str, str, str]]]:
    """Validate every operation declared in config/tool_manifest.yaml.

    For each operation tries to import the module and resolve the function.
    Returns (all_ok, [(operation_id, status, detail), ...]).

    Status codes:
      OK              — module imports and function is callable
      MANIFEST_FAIL   — manifest file missing or unparseable (emitted once)
      BAD_SYNTAX      — service string does not match module:function
      IMPORT_FAIL     — importlib.import_module raised
      MISSING_FUNC    — module imports, attribute does not exist
      NOT_CALLABLE    — attribute exists but is not callable
    """
    # Make sure system_core is importable when running doctor as
    # `python -m system_core.doctor` from the project root.
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))

    try:
        from system_core.core.manifest import load_manifest  # noqa: WPS433
    except Exception as exc:
        return False, [("(loader)", "MANIFEST_FAIL", f"{exc.__class__.__name__}: {exc}")]

    manifest_path = root / "config" / "tool_manifest.yaml"
    if not manifest_path.exists():
        return False, [("(loader)", "MANIFEST_FAIL", f"Not found: {manifest_path}")]

    try:
        manifest = load_manifest(manifest_path)
    except Exception as exc:
        return False, [("(loader)", "MANIFEST_FAIL", f"{exc.__class__.__name__}: {exc}")]

    rows: list[tuple[str, str, str]] = []
    all_ok = True

    every_operation = [*manifest.operations, *manifest.maintenance_operations]
    for op in every_operation:
        if ":" not in op.service:
            rows.append((op.id, "BAD_SYNTAX", op.service))
            all_ok = False
            continue

        module_name, function_name = op.service.split(":", 1)
        try:
            mod = importlib.import_module(module_name)
        except Exception as exc:
            rows.append((op.id, "IMPORT_FAIL", f"{module_name} ({exc.__class__.__name__})"))
            all_ok = False
            continue

        if not hasattr(mod, function_name):
            rows.append((op.id, "MISSING_FUNC", f"{module_name}:{function_name}"))
            all_ok = False
            continue

        if not callable(getattr(mod, function_name)):
            rows.append((op.id, "NOT_CALLABLE", f"{module_name}:{function_name}"))
            all_ok = False
            continue

        rows.append((op.id, "OK", op.service))

    return all_ok, rows


def check_cmd_encoding(root: Path) -> tuple[bool, list[tuple[str, bool, str]]]:
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))

    try:
        from system_core.core.cmd_encoding import check_cmd_files  # noqa: WPS433
    except Exception as exc:
        return False, [("(loader)", False, f"{exc.__class__.__name__}: {exc}")]

    rows: list[tuple[str, bool, str]] = []
    all_ok = True
    for result in check_cmd_files(root):
        try:
            relative = str(result.path.resolve().relative_to(root.resolve()))
        except ValueError:
            relative = str(result.path)

        detail = result.summary()
        if result.error:
            detail = f"{detail} {result.error}"
        rows.append((relative, result.ok, detail))
        if not result.ok:
            all_ok = False

    return all_ok, rows


def check_gui_theme_catalog(root: Path) -> tuple[bool, list[tuple[str, bool, str]]]:
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))

    try:
        from system_core.core.config import load_yaml_or_json  # noqa: WPS433
        from system_core.core.ui_theme_catalog import validate_theme_catalog  # noqa: WPS433
    except Exception as exc:
        return False, [("(loader)", False, f"{exc.__class__.__name__}: {exc}")]

    try:
        data = load_yaml_or_json(root / "config" / "ui_colors.yaml")
    except Exception as exc:
        return False, [("catalog", False, f"{exc.__class__.__name__}: {exc}")]

    result = validate_theme_catalog(data)
    if not result.ok:
        return False, [("catalog", False, error) for error in result.errors]

    rows = [
        ("theme order", True, f"core prefix OK; {len(result.theme_ids)} theme(s)"),
        ("extension themes", True, ", ".join(result.extra_theme_ids) or "none"),
    ]
    return True, rows


def main() -> int:
    root = Path(__file__).resolve().parents[1]

    print("======================================================================")
    print("AUDION PYTHON GUI PORTABLE TEMPLATE - DOCTOR")
    print("======================================================================")
    print(f"Project root : {root}")
    print(f"Executable   : {sys.executable}")
    print(f"Python       : {sys.version.split()[0]}")
    print(f"Python mode  : {detect_python_mode(root)}")
    print(f"Platform     : {platform.platform()}")
    print()

    failed = False

    print("[Required modules]")
    for import_name, package_name in REQUIRED_MODULES:
        ok, detail = check_module(import_name)
        status = "OK" if ok else "FAIL"
        print(f"  - {package_name:<18} : {status:<4} {detail}")
        if not ok:
            failed = True

    print()
    print("[GUI portability]")
    picker_ok, picker_rows = check_picker_powershell(root)
    for label, ok, detail in picker_rows:
        status = "OK" if ok else "MISS"
        print(f"  - {label:<18} : {status:<4} {detail}")
    if not picker_ok:
        print("  - picker dialogs     : FAIL PowerShell was not found")
        failed = True
    else:
        print("  - picker dialogs     : OK   PowerShell-backed Windows dialogs available")

    print()
    print("[GUI themes]")
    themes_ok, theme_rows = check_gui_theme_catalog(root)
    for label, ok, detail in theme_rows:
        status = "OK" if ok else "FAIL"
        print(f"  - {label:<18} : {status:<4} {detail}")
    if not themes_ok:
        failed = True

    print()
    print("[Optional modules]")
    for import_name, package_name in OPTIONAL_MODULES:
        ok, detail = check_module(import_name)
        status = "OK" if ok else "MISS"
        print(f"  - {package_name:<18} : {status:<4} {detail}")

    print()
    print("[Manifest operations]")
    manifest_ok, rows = check_manifest_operations(root)
    if not rows:
        print("  (no operations found)")
    else:
        for op_id, status, detail in rows:
            print(f"  - {op_id:<22} : {status:<13} {detail}")
    if not manifest_ok:
        failed = True

    print()
    print("[CMD encoding]")
    cmd_ok, cmd_rows = check_cmd_encoding(root)
    if not cmd_rows:
        print("  (no CMD files found)")
    else:
        for relative, result_ok, detail in cmd_rows:
            status = "OK" if result_ok else "FAIL"
            print(f"  - {relative:<58} : {status:<4} {detail}")
    if not cmd_ok:
        failed = True

    print()
    if failed:
        print("[RESULT] One or more checks failed.")
        return 1

    print("[RESULT] Required environment looks good.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
