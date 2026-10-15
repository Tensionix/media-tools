"""The console command: what it describes, what it refuses before a run, and a run of the engine end to end.

The runs make their own short clip with the FFmpeg of the program and are skipped where there is none.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

PROJECT = Path(__file__).resolve().parent.parent
CLI = PROJECT / "system_core" / "cli.py"
FFMPEG = PROJECT / "Tools" / "ffmpeg" / "bin" / "ffmpeg.exe"
CONTROL = "::media::"


def run(*args: str, timeout: float = 300) -> subprocess.CompletedProcess:
    env = dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
    env.pop("AUDION_SOURCE", None)
    env.pop("AUDION_OUTPUT", None)
    return subprocess.run([sys.executable, "-u", str(CLI), *args], capture_output=True, text=True, encoding="utf-8",
                          timeout=timeout, env=env)


def told(output: str) -> list[dict]:
    return [json.loads(line[len(CONTROL):]) for line in output.splitlines() if line.startswith(CONTROL)]


@pytest.fixture(scope="module")
def clip(tmp_path_factory: pytest.TempPathFactory) -> Path:
    if not FFMPEG.is_file():
        pytest.skip("no FFmpeg of the program in Tools")
    folder = tmp_path_factory.mktemp("clip") / "in"
    folder.mkdir()
    subprocess.run([str(FFMPEG), "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc2=size=640x360:rate=25:duration=4",
                    "-f", "lavfi", "-i", "sine=frequency=440:duration=4", "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac",
                    "-shortest", str(folder / "clip.mov")], check=True, timeout=120)
    return folder


def test_describe_tells_the_operations_and_the_ribbon() -> None:
    done = run("describe")
    assert done.returncode == 0, done.stderr
    payload = json.loads(done.stdout)
    assert len(payload["operations"]) >= 20
    assert [section["id"] for section in payload["layout"]["sections"]] == ["audio", "encode", "package", "cut", "rate", "color", "download"]
    tones = {option["tone"] for field in payload["operations"]["editing_run"]["fields"] for option in field.get("options", [])}
    assert {"lossless", "lossy", "uncompressed"} <= tones


@pytest.mark.parametrize("arguments, said", [
    (["--operation", "nothing_run"], "has no operation"),
    (["--operation", "storage_run", "--set", "nothing=1"], "has no field"),
    (["--operation", "storage_run", "--set", "storage_profile=nope"], "no such choice"),
    (["--operation", "storage_run", "--set", "target_codecs="], "Select at least one item"),
    (["--operation", "cleanup_source"], "deletes for good"),
    # A service without the field of a dry run does not read it: --dry-run would run it for real.
    (["--operation", "hardware_capabilities", "--dry-run"], "has no dry run"),
])
def test_a_wrong_call_runs_nothing(arguments: list[str], said: str) -> None:
    done = run("run", *arguments)
    assert done.returncode == 2
    assert said in done.stderr
    assert CONTROL not in done.stdout


def test_a_run_the_preflight_refuses_is_a_refusal_without_a_trace(tmp_path: Path) -> None:
    """An empty Source is no failure of the program: the [PREFLIGHT] lines say why, one line [REFUSED], exit code 2."""
    (tmp_path / "in").mkdir()
    done = run("run", "--operation", "remux_run", "--source", str(tmp_path / "in"), "--target", str(tmp_path / "out"))
    assert done.returncode == 2, done.stdout[-500:]
    assert told(done.stdout)[-1]["finished"]["outcome"] == "refused"
    assert "[REFUSED]" in done.stdout and "Traceback" not in done.stdout + done.stderr


def test_every_operation_is_told_whether_a_dry_run_suits_it() -> None:
    """--dry-run is taken by an operation with the field of it or one of DRY_RUN_TOO; a new operation is neither until it is
    looked at, and only the two named here would run for real."""
    from system_core import cli
    from system_core.core import operation_model as model
    from system_core.core.manifest import load_manifest

    manifest = load_manifest(PROJECT / "config" / "tool_manifest.yaml")
    nodes = {node.id: node for node in [*model.all_nodes(manifest), *manifest.operations, *manifest.maintenance_operations]
             if node.service and not getattr(node, "children", None)}
    assert cli.DRY_RUN_TOO <= set(nodes)
    refused = {node_id for node_id, node in nodes.items() if node.kind != "dangerous" and node_id not in cli.DRY_RUN_TOO
               and not {"dry_run", "youtube_dry_run"} & {model.field_id(field) for field in model.form_fields(node)}}
    assert refused == {"hardware_capabilities", "preset_test_matrix"}


def test_a_run_is_told_as_service_lines_and_writes_its_result(clip: Path, tmp_path: Path) -> None:
    result = tmp_path / "result.json"
    done = run("run", "--operation", "remux_run", "--source", str(clip), "--target", str(tmp_path / "out"),
               "--set", "remux_target_format=mkv", "--live", "--result", str(result))
    assert done.returncode == 0, done.stdout[-2000:] + done.stderr
    lines = told(done.stdout)
    assert "started" in lines[0] and "finished" in lines[-1]
    assert lines[-1]["finished"]["outcome"] == "done"
    assert any("activity" in line and "100%" in line["activity"] for line in lines)
    assert not any(line.startswith("[PROGRESS]") for line in done.stdout.splitlines())
    assert list((tmp_path / "out").rglob("clip.mkv"))
    assert json.loads(result.read_text(encoding="utf-8"))["outcome"] == "done"


def test_a_link_of_the_form_is_said(clip: Path, tmp_path: Path) -> None:
    done = run("run", "--operation", "editing_run", "--source", str(clip), "--target", str(tmp_path / "out"),
               "--set", "audio_mode=aac_320", "--set", "output_container=mxf", "--dry-run")
    assert done.returncode == 0, done.stderr
    assert "[NOTE] audio_mode: 'aac_320' became 'pcm_s24'" in done.stdout
    assert not (tmp_path / "out").exists() or not list((tmp_path / "out").rglob("*.mxf"))


def test_a_command_only_said_leaves_no_folder_behind(clip: Path, tmp_path: Path) -> None:
    """A dry run plans the folders of its results and writes nothing into them: they go when the run ends. A folder that
    was in the Target before stays, empty as it is (the owner, 15.10.2026: "паразитные файлы после кодирования")."""
    target = tmp_path / "out"
    (target / "mine").mkdir(parents=True)
    done = run("run", "--operation", "storage_run", "--source", str(clip), "--target", str(target), "--dry-run")
    assert done.returncode == 0, done.stderr
    assert "[DRY RUN]" in done.stdout
    assert sorted(path.name for path in target.rglob("*")) == ["mine"]


def test_the_cancel_file_stops_the_run(tmp_path: Path) -> None:
    if not FFMPEG.is_file():
        pytest.skip("no FFmpeg of the program in Tools")
    source = tmp_path / "in"
    source.mkdir()
    subprocess.run([str(FFMPEG), "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc2=size=1920x1080:rate=25:duration=30",
                    "-c:v", "libx264", "-preset", "ultrafast", str(source / "long.mov")], check=True, timeout=300)
    stop = tmp_path / "stop.flag"
    threading.Timer(4.0, stop.touch).start()
    began = time.monotonic()
    done = run("run", "--operation", "storage_run", "--source", str(source), "--target", str(tmp_path / "out"),
               "--set", "storage_profile=hevc10_crf14", "--live", "--cancel-file", str(stop))
    assert done.returncode == 130, done.stdout[-2000:]
    assert told(done.stdout)[-1]["finished"]["outcome"] == "stopped"
    assert time.monotonic() - began < 60


def test_a_person_at_a_console_sees_no_service_lines(monkeypatch, capsys) -> None:
    """A wrapper started from a launcher writes to a console: "::media::{...}" is for the window, which reads a pipe;
    the lines of the run and of FFmpeg are printed as they are (the owner, 15.10.2026)."""
    from system_core import cli

    cli.control({"finished": {"outcome": "done"}})
    assert capsys.readouterr().out.startswith(CONTROL)
    monkeypatch.setattr(cli.sys.stdout, "isatty", lambda: True)
    cli.control({"finished": {"outcome": "done"}})
    cli.say("[EXIT] 0")
    assert capsys.readouterr().out == "[EXIT] 0\n"
