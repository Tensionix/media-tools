from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from system_core.core.script_profiles import load_script_profiles


REPORT_ROOT = ROOT / "report" / "refactor_media_smoke"
BACKEND_INPUTS = REPORT_ROOT / "preset_matrix" / "inputs"
CLI_ROOT = REPORT_ROOT / "cli_profiles"
FFMPEG = ROOT / "Tools" / "ffmpeg" / "bin" / "ffmpeg.exe"
FFPROBE = ROOT / "Tools" / "ffmpeg" / "bin" / "ffprobe.exe"
PYTHON = ROOT / "runtime" / "python.exe"
RUNNER = ROOT / "Scripts" / "Common" / "script_runner.py"
MEDIA_SUFFIXES = {
    ".aac", ".flac", ".m4a", ".mka", ".mkv", ".mov", ".mp3", ".mp4", ".mxf",
    ".opus", ".wav", ".webm",
}


def _run(command: list[str], *, env: dict[str, str], timeout: int = 180) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=ROOT,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        check=False,
    )


def _create_audio_fixture(path: Path, rate: int, channels: int = 2) -> None:
    layout = "5.1" if channels == 6 else "stereo"
    command = [
        str(FFMPEG), "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i",
        f"anoisesrc=color=pink:sample_rate={rate}:duration=0.25", "-ac", str(channels),
        "-channel_layout", layout, "-c:a", "pcm_s24le", str(path),
    ]
    result = subprocess.run(command, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace")
    if result.returncode != 0:
        raise RuntimeError(f"Could not create {path.name}: {result.stderr.strip()}")


def _fixtures() -> dict[str, Path]:
    if not BACKEND_INPUTS.exists():
        raise RuntimeError("Run smoke_media_operations.py before the CLI profile matrix.")
    fixtures = {
        "mp4": BACKEND_INPUTS / "matrix_input.mp4",
        "mkv": BACKEND_INPUTS / "matrix_input.mkv",
        "mov": BACKEND_INPUTS / "matrix_input.mov",
        "mov_edit": BACKEND_INPUTS / "matrix_edit.mov",
        "hdr": BACKEND_INPUTS / "matrix_hdr_pq.mp4",
        "wav": BACKEND_INPUTS / "matrix_audio.wav",
        "lut": BACKEND_INPUTS / "identity.cube",
    }
    mxf = next((REPORT_ROOT / "preset_matrix" / "outputs" / "editing").rglob("*.mxf"), None)
    if not mxf:
        raise RuntimeError("The backend matrix did not produce an MXF fixture.")
    fixtures["mxf"] = mxf
    fixture_dir = CLI_ROOT / "fixtures"
    fixture_dir.mkdir(parents=True, exist_ok=True)
    fixtures["wav441"] = fixture_dir / "matrix_audio_44100.wav"
    fixtures["wav48"] = fixture_dir / "matrix_audio_48000.wav"
    fixtures["wav51"] = fixture_dir / "matrix_audio_51_48000.wav"
    _create_audio_fixture(fixtures["wav441"], 44100)
    _create_audio_fixture(fixtures["wav48"], 48000)
    _create_audio_fixture(fixtures["wav51"], 48000, channels=6)
    return fixtures


def _source_fixture(profile_id: str, profile: dict[str, Any], fixtures: dict[str, Path]) -> Path | None:
    kind = str(profile.get("kind", "")).lower()
    if kind == "ff_selftest" or kind == "youtube":
        return None
    if kind == "remux":
        source = str(profile.get("source", "mp4")).lower()
        if source == "mov" and str(profile.get("target", "")).lower() == "mxf":
            return fixtures["mov_edit"]
        return fixtures.get(source, fixtures["mp4"])
    if kind == "audio":
        if str(profile.get("action", "")).lower() == "downmix":
            return fixtures["wav51"]
        target_rate = str(profile.get("sample_rate", ""))
        if target_rate == "48000":
            return fixtures["wav441"]
        if target_rate == "44100":
            return fixtures["wav48"]
        return fixtures["wav"]
    if kind == "color" and str(profile.get("color_filter", "")).lower() == "hdr2sdr_hable":
        return fixtures["hdr"]
    return fixtures["mp4"]


def _probe_outputs(output_dir: Path) -> tuple[list[str], list[str]]:
    outputs = sorted(path for path in output_dir.rglob("*") if path.is_file() and path.suffix.lower() in MEDIA_SUFFIXES)
    errors: list[str] = []
    for output in outputs:
        result = subprocess.run(
            [str(FFPROBE), "-v", "error", "-show_entries", "format=duration:stream=codec_type,codec_name,sample_rate,bits_per_raw_sample", "-of", "json", str(output)],
            cwd=ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        if result.returncode != 0:
            errors.append(f"{output.name}: {result.stderr.strip() or 'ffprobe failed'}")
            continue
        try:
            payload = json.loads(result.stdout)
        except json.JSONDecodeError:
            errors.append(f"{output.name}: invalid ffprobe JSON")
            continue
        if not payload.get("streams"):
            errors.append(f"{output.name}: no streams")
    return [str(path.relative_to(output_dir)) for path in outputs], errors


def _base_env(source_dir: Path, output_dir: Path, fixtures: dict[str, Path]) -> dict[str, str]:
    env = os.environ.copy()
    env.update(
        {
            "PYTHONUTF8": "1",
            "PYTHONIOENCODING": "utf-8",
            "AUDION_SOURCE": str(source_dir),
            "AUDION_OUTPUT": str(output_dir),
            "AUDION_DOWNLOAD": str(CLI_ROOT / "Download"),
            "AUDION_LUT_FILE": str(fixtures["lut"]),
            "AUDION_LIMIT_FIRST_FILE": "1",
            "AUDION_RECURSIVE": "0",
            "AUDION_OVERWRITE": "1",
            "AUDION_DRY_RUN": "0",
            "AUDION_ENCODE_BACKEND": "cpu",
            "AUDION_CPU_ENCODER_PRESET": "fast",
        }
    )
    return env


def _run_local_profile(profile_id: str, profile: dict[str, Any], fixtures: dict[str, Path]) -> dict[str, Any]:
    case_dir = CLI_ROOT / "actual" / profile_id
    source_dir = case_dir / "Source"
    output_dir = case_dir / "OUT"
    source_dir.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)
    fixture = _source_fixture(profile_id, profile, fixtures)
    if fixture:
        shutil.copy2(fixture, source_dir / fixture.name)
    env = _base_env(source_dir, output_dir, fixtures)
    wrapper = ROOT / "Scripts" / f"{profile_id}.cmd"
    command = ["cmd.exe", "/d", "/c", str(wrapper)]
    result = _run(command, env=env)
    outputs, probe_errors = _probe_outputs(output_dir)
    output_required = str(profile.get("kind", "")).lower() not in {"ff_selftest", "subtitles"}
    ok = result.returncode == 0 and not probe_errors and (bool(outputs) or not output_required)
    return {
        "profile": profile_id,
        "mode": "actual",
        "status": "OK" if ok else "FAIL",
        "exit_code": result.returncode,
        "outputs": outputs,
        "probe_errors": probe_errors,
        "tail": result.stdout.splitlines()[-8:],
    }


def _run_youtube_preview(profile_id: str, profile: dict[str, Any], fixtures: dict[str, Path]) -> dict[str, Any]:
    case_dir = CLI_ROOT / "youtube" / profile_id
    source_dir = case_dir / "Source"
    output_dir = case_dir / "OUT"
    source_dir.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)
    env = _base_env(source_dir, output_dir, fixtures)
    mode = str(profile.get("mode", "download")).lower()
    env["AUDION_DRY_RUN"] = "0" if mode == "selftest" else "1"
    env["AUDION_YOUTUBE_URL"] = "https://example.invalid/audion-smoke"
    download_dir = Path(env["AUDION_DOWNLOAD"])
    download_dir.mkdir(parents=True, exist_ok=True)
    (download_dir / "urls.txt").write_text("https://example.invalid/audion-smoke\n", encoding="utf-8")
    args: list[str] = []
    if mode == "clip":
        args = ["*00:00:00-00:00:01", "https://example.invalid/audion-smoke"]
    command = [str(PYTHON), str(RUNNER), profile_id, *args]
    result = _run(command, env=env)
    ok = result.returncode == 0 and "[CMD]" in result.stdout
    return {
        "profile": profile_id,
        "mode": "actual-selftest" if mode == "selftest" else "network-preview",
        "status": "OK" if ok else "FAIL",
        "exit_code": result.returncode,
        "outputs": [],
        "probe_errors": [],
        "tail": result.stdout.splitlines()[-8:],
    }


def _run_fps_frontend_variants(fixtures: dict[str, Path]) -> list[dict[str, Any]]:
    variants = [
        ("h264", "", "x1"),
        ("hevc", "", "x1"),
        ("prores", "s16", "x1"),
        ("prores", "s24", "x2"),
        ("prores", "f32", "x4"),
        ("prores_mxf", "s24", "x4"),
        ("dnxhr", "s16", "x1"),
        ("dnxhr", "s24", "x2"),
        ("dnxhr", "f32", "x4"),
        ("dnxhr_mxf", "s24", "x4"),
    ]
    rows: list[dict[str, Any]] = []
    for profile, depth, oversample in variants:
        case_id = f"fps_frontend_{profile}_{depth or 'aac'}_{oversample}"
        case_dir = CLI_ROOT / "fps_frontend" / case_id
        source_dir = case_dir / "Source"
        output_dir = case_dir / "OUT"
        source_dir.mkdir(parents=True, exist_ok=True)
        output_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(fixtures["mp4"], source_dir / fixtures["mp4"].name)
        env = _base_env(source_dir, output_dir, fixtures)
        env["AUDION_FPS_OUTPUT_PROFILE"] = profile
        env["AUDION_FPS_AUDIO_PCM_DEPTH"] = depth
        env["AUDION_FPS_AUDIO_OVERSAMPLE"] = oversample
        result = _run(["cmd.exe", "/d", "/c", str(ROOT / "Scripts" / "ff-25to23976-conform.cmd")], env=env)
        outputs, probe_errors = _probe_outputs(output_dir)
        ok = result.returncode == 0 and bool(outputs) and not probe_errors
        rows.append(
            {
                "profile": case_id,
                "mode": "actual-cli-gui-contract",
                "status": "OK" if ok else "FAIL",
                "exit_code": result.returncode,
                "outputs": outputs,
                "probe_errors": probe_errors,
                "tail": result.stdout.splitlines()[-8:],
            }
        )
    return rows


def main() -> int:
    if CLI_ROOT.exists():
        shutil.rmtree(CLI_ROOT)
    CLI_ROOT.mkdir(parents=True)
    fixtures = _fixtures()
    catalog = load_script_profiles(ROOT).get("profiles", {})
    rows: list[dict[str, Any]] = []
    for profile_id, raw_profile in sorted(catalog.items()):
        profile = raw_profile if isinstance(raw_profile, dict) else {}
        kind = str(profile.get("kind", "")).lower()
        row = _run_youtube_preview(profile_id, profile, fixtures) if kind == "youtube" else _run_local_profile(profile_id, profile, fixtures)
        rows.append(row)
        print(f"[{row['status']}] {profile_id} ({row['mode']})", flush=True)
    for row in _run_fps_frontend_variants(fixtures):
        rows.append(row)
        print(f"[{row['status']}] {row['profile']} ({row['mode']})", flush=True)

    summary = {
        "OK": sum(row["status"] == "OK" for row in rows),
        "FAIL": sum(row["status"] == "FAIL" for row in rows),
        "actual": sum(row["mode"].startswith("actual") for row in rows),
        "network_preview": sum(row["mode"] == "network-preview" for row in rows),
    }
    payload = {"summary": summary, "items": rows}
    report_json = REPORT_ROOT / "cli_profile_matrix.json"
    report_md = REPORT_ROOT / "cli_profile_matrix.md"
    report_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = [
        "# CLI Profile Matrix", "", f"- OK: `{summary['OK']}`", f"- FAIL: `{summary['FAIL']}`",
        f"- Actual local/selftest executions: `{summary['actual']}`", f"- Network-safe command previews: `{summary['network_preview']}`",
        "", "| Status | Profile | Mode | Outputs |", "|---|---|---|---|",
    ]
    for row in rows:
        outputs = ", ".join(row["outputs"]) or "-"
        lines.append(f"| {row['status']} | `{row['profile']}` | {row['mode']} | {outputs} |")
    report_md.write_text("\n".join(lines), encoding="utf-8", newline="\n")
    print("CLI_SMOKE_SUMMARY=" + json.dumps(summary, ensure_ascii=False, sort_keys=True))
    print(f"CLI_SMOKE_REPORT={report_md}")
    if summary["FAIL"]:
        for row in rows:
            if row["status"] == "FAIL":
                print(json.dumps(row, ensure_ascii=False, indent=2))
    return 0 if summary["FAIL"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
