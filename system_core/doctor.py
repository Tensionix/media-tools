from __future__ import annotations

from pathlib import Path
import importlib
import os
import platform
import sys

# What the engine imports (3.0.0): PyYAML reads the manifest and the layout. The window on NiceGUI and the packages it
# lived on (nicegui, pywebview, rich, pydantic, markdown-it-py) are gone; tqdm drew the bar of a template service.
REQUIRED_MODULES = [
    ("yaml", "PyYAML"),
]

# The tests of the program: without pytest the program runs, its checks do not.
OPTIONAL_MODULES = [
    ("pytest", "pytest"),
]

# The tools the program calls, as the builder installs them (steps 10-14): without FFmpeg nothing is converted; the
# others are wanted by one section each - the player of CUT, DOWNLOAD, the release archive.
TOOLS = [
    ("FFmpeg", ("Tools", "ffmpeg", "bin", "ffmpeg.exe"), True),
    ("FFprobe", ("Tools", "ffmpeg", "bin", "ffprobe.exe"), True),
    ("mpv", ("Tools", "mpv", "bin", "mpv.exe"), False),
    ("yt-dlp", ("Tools", "yt-dlp", "bin", "yt-dlp.exe"), False),
    ("Deno", ("Tools", "deno", "deno.exe"), False),
    ("7-Zip", ("Tools", "7zip", "bin", "7za.exe"), False),
]


def ansi_enabled() -> bool:
    return (
        'NO_COLOR' not in os.environ
        and (
            os.environ.get('AUDION_GUI_TERMINAL') == '1'
            or os.environ.get('FORCE_COLOR') == '1'
            or os.environ.get('CLICOLOR_FORCE') == '1'
            or sys.stdout.isatty()
        )
    )


def color(text: str, code: str) -> str:
    if not ansi_enabled():
        return text
    return f'\033[{code}m{text}\033[0m'


def info(label: str, value: object) -> None:
    print(f"{color('[INFO]', '36;1')} {label:<12}: {value}")


def check_module(import_name: str) -> tuple[bool, str]:
    try:
        mod = importlib.import_module(import_name)
        version = getattr(mod, "__version__", "unknown")
        return True, str(version)
    except Exception as exc:
        return False, f"{exc.__class__.__name__}: {exc}"


def detect_python_mode(root: Path) -> str:
    if (root / "runtime" / "python.exe").exists():
        return "portable-runtime"
    if (root / "runtime" / "python" / "python.exe").exists():
        return "portable-runtime"
    return "system-python"


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

    from system_core.core import operation_model as model  # noqa: WPS433

    # Every operation that runs: the leaves of the tree of the sections and the service operations.
    every_operation = [node for node in model.all_nodes(manifest) if node.service and not node.children]
    every_operation += [*manifest.operations, *manifest.maintenance_operations]
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


def main() -> int:
    root = Path(__file__).resolve().parents[1]

    print(color("======================================================================", "36;1"))
    print(color("AUDION MEDIA TOOLS - DOCTOR", "36;1"))
    print(color("======================================================================", "36;1"))
    info("Project root", root)
    info("Executable", sys.executable)
    info("Python", sys.version.split()[0])
    info("Python mode", detect_python_mode(root))
    info("Platform", platform.platform())
    print()

    failed = False

    print(color("[Required modules]", "35;1"))
    for import_name, package_name in REQUIRED_MODULES:
        ok, detail = check_module(import_name)
        status = color("[OK]", "32;1") if ok else color("[FAIL]", "31;1")
        print(f"  - {package_name:<18} : {status} {detail}")
        if not ok:
            failed = True

    print()
    print(color("[Optional modules]", "35;1"))
    for import_name, package_name in OPTIONAL_MODULES:
        ok, detail = check_module(import_name)
        status = color("[OK]", "32;1") if ok else color("[MISS]", "33;1")
        print(f"  - {package_name:<18} : {status} {detail}")

    print()
    print(color("[Tools]", "35;1"))
    for name, parts, needed in TOOLS:
        path = root.joinpath(*parts)
        ok = path.is_file()
        status = color("[OK]", "32;1") if ok else color("[MISS]", "33;1")
        print(f"  - {name:<18} : {status} {path.relative_to(root) if ok else 'not installed: builder_main.cmd, steps 10-14'}")
    # The tools are installed by steps of their own, not by a build of the environment: a missing one is said, not failed.

    print()
    print(color("[Manifest operations]", "35;1"))
    manifest_ok, rows = check_manifest_operations(root)
    if not rows:
        print("  (no operations found)")
    else:
        for op_id, status, detail in rows:
            mark = color(status, "32;1") if status == "OK" else color(status, "31;1")
            print(f"  - {op_id:<22} : {mark:<13} {detail}")
    if not manifest_ok:
        failed = True

    print()
    print(color("[CMD encoding]", "35;1"))
    cmd_ok, cmd_rows = check_cmd_encoding(root)
    if not cmd_rows:
        print("  (no CMD files found)")
    else:
        for relative, result_ok, detail in cmd_rows:
            status = color("[OK]", "32;1") if result_ok else color("[FAIL]", "31;1")
            print(f"  - {relative:<58} : {status} {detail}")
    if not cmd_ok:
        failed = True

    print()
    if failed:
        print(color("[RESULT] One or more checks failed.", "31;1"))
        return 1

    print(color("[RESULT] Required environment looks good.", "32;1"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
