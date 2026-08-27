from __future__ import annotations

from pathlib import Path
from typing import Any
import json
import os
import platform
import re
import shutil
import subprocess

from .ansi_terminal import ansi_status
from .encoder_backends import (
    AUTO_PIX_FMTS,
    HARDWARE_ENCODE_BACKENDS,
    decode_backend_from_params as _decode_backend,
    hardware_pix_fmt as _hardware_pix_fmt,
    is_hardware_encoder,
    encode_backend_from_params as _encode_backend,
    encoder_for_target as _encoder_for_target,
    normalize_target as _normalize_target,
    target_for_backend as _target_for_backend,
)
from .path_cache import cached_output_path, cached_source_path
from .script_profiles import script_profile


VIDEO_CONTAINER_EXTENSIONS = {"mp4", "m4v", "mov", "mkv", "mxf", "avi", "webm", "mpg", "mpeg", "mts", "m2ts", "ts", "3gp"}
PURE_AUDIO_EXTENSIONS = {
    "wav",
    "w64",
    "flac",
    "m4a",
    "m4b",
    "aac",
    "mp3",
    "opus",
    "oga",
    "ogg",
    "aif",
    "aiff",
    "caf",
    "au",
    "snd",
    "ac3",
    "eac3",
    "dts",
    "mka",
    "ape",
    "wv",
    "tak",
    "tta",
    "mpc",
    "mpc8",
    "amr",
    "awb",
    "spx",
    "dsf",
    "dff",
}
MEDIA_EXTENSIONS = VIDEO_CONTAINER_EXTENSIONS | PURE_AUDIO_EXTENSIONS
AUDIO_MEDIA_EXTENSIONS = VIDEO_CONTAINER_EXTENSIONS | PURE_AUDIO_EXTENSIONS
SKIP_SERVICES = {
    "inventory",
    "selftest",
    "profile_doctor",
    "hardware_capabilities",
    "probe_source",
    "source_info",
    "cleanup_source",
    "cleanup_transcoded",
    "cleanup_workspace",
}
MEDIA_SERVICES = {"encode_targets", "audio_process", "remux_media", "fps_convert", "run_color_grade"}
REMUX_COMPATIBILITY = {
    "mp4": {"mov", "mkv"},
    "mov": {"mp4", "mkv", "mxf"},
    "mkv": {"mp4", "mov"},
    "mxf": {"mov", "mkv"},
    "avi": {"mkv"},
    "webm": {"mkv"},
    "mts": {"mp4", "mkv"},
    "m2ts": {"mp4", "mkv"},
}
HARDWARE_ENCODERS = {
    "h264_nvenc": ("CUDA/NVENC", "NVENC H.264 encode"),
    "hevc_nvenc": ("CUDA/NVENC", "NVENC HEVC encode"),
    "av1_nvenc": ("CUDA/NVENC", "NVENC AV1 encode"),
    "h264_qsv": ("QuickSync/QSV", "QSV H.264 encode"),
    "hevc_qsv": ("QuickSync/QSV", "QSV HEVC encode"),
    "av1_qsv": ("QuickSync/QSV", "QSV AV1 encode"),
    "h264_amf": ("AMD/AMF", "AMF H.264 encode"),
    "hevc_amf": ("AMD/AMF", "AMF HEVC encode"),
    "av1_amf": ("AMD/AMF", "AMF AV1 encode"),
}
# Decode stacks are guarded by their own smoke result. Using an encoder smoke as
# a proxy would block, for example, a ProRes master decoded through CUDA on a
# machine whose NVENC encoder is unavailable.
HARDWARE_DECODERS = {
    "cuda": ("CUDA decode", "CUDA decode"),
    "qsv": ("QuickSync decode", "QuickSync decode"),
    "amd": ("AMD/D3D11VA decode", "AMD/D3D11VA decode"),
    "dav1d": ("dav1d AV1 decode", "dav1d AV1 decode"),
}


def _as_list(value: Any) -> list[str]:
    if isinstance(value, (list, tuple)):
        return [str(item).strip() for item in value if str(item).strip()]
    if value in (None, ""):
        return []
    return [str(value).strip()]


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "y", "on", "да"}


def _issue(level: str, subject: str, detail: str) -> dict[str, str]:
    return {"level": level, "subject": subject, "detail": detail}


def _service_name(service: str) -> str:
    return service.rsplit(":", 1)[-1].strip()


def _tool_path_env(root: Path) -> str:
    parts = [
        root / "Tools" / "ffmpeg" / "bin",
        root / "Tools" / "yt-dlp" / "bin",
        root / "Tools" / "deno",
        root / "Tools" / "deno" / "bin",
        root / "Tools" / "7zip" / "bin",
    ]
    existing = [str(path) for path in parts if path.exists()]
    return os.pathsep.join([*existing, os.environ.get("PATH", "")])


def _tool(root: Path, relative: str, fallback: str) -> tuple[str, bool]:
    local = root / relative
    if local.exists():
        return str(local), True
    resolved = shutil.which(fallback, path=_tool_path_env(root))
    return (resolved or fallback), bool(resolved)


def _hidden_subprocess_kwargs() -> dict[str, Any]:
    if os.name != "nt" or not hasattr(subprocess, "STARTUPINFO"):
        return {}
    startupinfo = subprocess.STARTUPINFO()
    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startupinfo.wShowWindow = 0
    return {
        "startupinfo": startupinfo,
        "creationflags": int(getattr(subprocess, "CREATE_NO_WINDOW", 0)),
    }


def _capture_tool(command: list[str], root: Path) -> str:
    try:
        result = subprocess.run(
            command,
            cwd=str(root),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            env={**os.environ, "PATH": _tool_path_env(root), "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"},
            check=False,
            **_hidden_subprocess_kwargs(),
        )
    except OSError:
        return ""
    return result.stdout or ""


def _normalize_extensions(values: list[str], fallback: set[str]) -> set[str]:
    result = {item.strip().lower().lstrip(".") for item in values if item.strip()}
    return result or set(fallback)


def _media_files(source: Path, extensions: set[str]) -> list[Path]:
    if not source.exists():
        return []
    if source.is_file():
        return [source] if source.suffix.lower().lstrip(".") in extensions else []
    return sorted(path for path in source.rglob("*") if path.is_file() and path.suffix.lower().lstrip(".") in extensions)


def _encoder_listed(listing: str, encoder: str) -> bool:
    return bool(re.search(rf"\s{re.escape(encoder)}\s", listing))


def _audio_workflow(params: dict[str, Any]) -> str:
    value = str(params.get("audio_workflow", "extract") or "extract").strip().lower()
    if value in {"in_video", "video", "inside_video", "container"}:
        return "in_video"
    if value in {"audio_files", "files", "audio_only"}:
        return "audio_files"
    return "extract"


def _fps_profile_target(params: dict[str, Any]) -> str:
    """Map the FPS output profile to the same target vocabulary encode pages use."""
    profile = str(params.get("fps_output_profile", "h264")).strip().lower()
    if profile in {"prores", "prores_mov", "prores_mxf"}:
        return "prores_422"
    if profile in {"dnxhr", "dnxhr_mov", "dnxhr_mxf"}:
        return "dnxhr_hqx"
    if profile in {"hevc", "h265", "x265"}:
        return "hevc_x265"
    return "x264"


def _required_encoders(service_name: str, params: dict[str, Any], root: Path) -> list[str]:
    if service_name == "remux_media":
        return []
    if service_name == "audio_process":
        lufs_mode = str(params.get("audio_lufs_mode", "") or "").strip().lower()
        if lufs_mode in {"report", "report_only", "analyze"}:
            return []
        audio_format = str(params.get("audio_format", "")).strip().lower()
        if audio_format == "mp3":
            return ["libmp3lame"]
        if audio_format == "opus":
            return ["libopus"]
        if audio_format in {"m4a", "aac"}:
            return ["aac"]
        if audio_format == "alac":
            return ["alac"]
        if audio_format == "flac":
            return ["flac"]
        return []
    if service_name == "fps_convert":
        target = _fps_profile_target(params)
        if target in {"prores_422", "dnxhr_hqx"}:
            return [_encoder_for_target(target)]
        encoder = _encoder_for_target(_target_for_backend(target, _encode_backend(params)))
        return [encoder, "aac"] if encoder else ["aac"]
    targets = _as_list(params.get("target_codecs"))
    if service_name == "run_color_grade" and not targets:
        script = str(params.get("script_preset", "")).strip()
        try:
            targets = _as_list(script_profile(root, script).get("targets"))
        except Exception:
            targets = []
        if not targets:
            targets = ["x264"]
    encoders: list[str] = []
    for target in targets:
        encoder = _encoder_for_target(_target_for_backend(_normalize_target(target), _encode_backend(params)))
        if encoder and encoder not in encoders:
            encoders.append(encoder)
    return encoders


def _probe_video_codec(root: Path, source: Path) -> str:
    ffprobe, ffprobe_ok = _tool(root, "Tools/ffmpeg/bin/ffprobe.exe", "ffprobe")
    if not ffprobe_ok:
        return ""
    output = _capture_tool(
        [ffprobe, "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=codec_name", "-of", "default=nw=1:nk=1", str(source)],
        root,
    )
    return output.strip().splitlines()[0].strip().lower() if output.strip() else ""


def _append_dav1d_source_check(root: Path, params: dict[str, Any], files: list[Path], checks: list[dict[str, str]]) -> None:
    """libdav1d is forced with -c:v, so a non-AV1 source fails inside FFmpeg."""
    if _decode_backend(params) != "dav1d" or not files:
        return
    first = files[0]
    codec = _probe_video_codec(root, first)
    if not codec:
        checks.append(_issue("WARN", "dav1d decode", f"Could not probe the video codec of {first.name}. dav1d only decodes AV1."))
        return
    if codec == "av1":
        checks.append(_issue("OK", "dav1d decode", f"{first.name}: AV1 source (first file checked)."))
    else:
        checks.append(
            _issue(
                "ERROR",
                "dav1d decode",
                f"{first.name} is {codec}, not AV1. The dav1d decoder is forced with -c:v libdav1d and cannot read it. Choose CPU/Auto decode.",
            )
        )


def _append_pixel_format_checks(service_name: str, params: dict[str, Any], checks: list[dict[str, str]]) -> None:
    """Report pixel formats the selected hardware encoder cannot produce."""
    if service_name not in {"encode_targets", "run_color_grade"}:
        return
    pix_fmt = str(params.get("pix_fmt", "") or "").strip().lower()
    if not pix_fmt or pix_fmt in AUTO_PIX_FMTS:
        return
    backend = _encode_backend(params)
    if backend not in HARDWARE_ENCODE_BACKENDS:
        return
    for target in _as_list(params.get("target_codecs")):
        encoder = _target_for_backend(_normalize_target(target), backend)
        if not is_hardware_encoder(encoder):
            continue
        try:
            native = _hardware_pix_fmt(encoder, pix_fmt)
        except RuntimeError as exc:
            checks.append(_issue("ERROR", "pixel format", str(exc)))
            continue
        detail = f"{encoder}: {pix_fmt}" if native == pix_fmt else f"{encoder}: {pix_fmt} -> {native}"
        checks.append(_issue("OK", "pixel format", detail))


def _hardware_cache_path(root: Path) -> Path:
    return root / "config" / "hardware_capabilities_cache.json"


def _load_hardware_cache(root: Path) -> tuple[dict[str, Any] | None, str]:
    path = _hardware_cache_path(root)
    if not path.exists():
        return None, f"Hardware Capabilities cache not found: {path}"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return None, f"Hardware Capabilities cache is unreadable: {exc}"
    if not isinstance(data, dict):
        return None, f"Hardware Capabilities cache has invalid shape: {path}"
    cached_machine = str(data.get("machine") or "").strip()
    current_machine = platform.node()
    if cached_machine and current_machine and cached_machine.lower() != current_machine.lower():
        return None, f"Hardware Capabilities cache belongs to {cached_machine}, current machine is {current_machine}."
    return data, ""


def _hardware_cache_status(cache: dict[str, Any], label: str) -> dict[str, Any] | None:
    statuses = cache.get("statuses", [])
    if not isinstance(statuses, list):
        return None
    for item in statuses:
        if isinstance(item, dict) and str(item.get("label", "")).strip().lower() == label.lower():
            return item
    return None


def _hardware_needs(service_name: str, params: dict[str, Any], encoders: list[str]) -> list[tuple[str, str]]:
    needs: list[tuple[str, str]] = []
    for encoder in encoders:
        need = HARDWARE_ENCODERS.get(encoder)
        if need and need not in needs:
            needs.append(need)
    if service_name in MEDIA_SERVICES:
        decode_need = HARDWARE_DECODERS.get(_decode_backend(params))
        if decode_need and decode_need not in needs:
            needs.append(decode_need)
    return needs


def _append_hardware_guard_checks(root: Path, checks: list[dict[str, str]], needs: list[tuple[str, str]]) -> None:
    if not needs:
        return
    cache, cache_warning = _load_hardware_cache(root)
    if cache is None:
        checks.append(_issue("WARN", "hardware guard", f"{cache_warning} Run Diagnostics -> Hardware Capabilities."))
        return
    updated_at = str(cache.get("updated_at") or "").strip()
    for stack_label, smoke_label in needs:
        status_row = _hardware_cache_status(cache, smoke_label)
        if status_row is None:
            checks.append(_issue("WARN", "hardware guard", f"{stack_label}: no smoke result named '{smoke_label}' in current cache."))
            continue
        status = str(status_row.get("status") or "").strip().upper()
        detail = str(status_row.get("detail") or "").strip()
        suffix = f" ({updated_at})" if updated_at else ""
        if status == "OK":
            checks.append(_issue("OK", "hardware guard", f"{stack_label}: {smoke_label} passed{suffix}."))
        else:
            checks.append(_issue("ERROR", "hardware guard", f"{stack_label}: {smoke_label} is {status}{suffix}. {detail}"))


def _media_extensions_for(service_name: str, params: dict[str, Any]) -> set[str]:
    raw = _as_list(params.get("input_formats"))
    if service_name == "audio_process":
        if raw:
            return _normalize_extensions(raw, AUDIO_MEDIA_EXTENSIONS)
        if _audio_workflow(params) == "audio_files":
            return set(PURE_AUDIO_EXTENSIONS)
        return set(VIDEO_CONTAINER_EXTENSIONS)
    if service_name == "remux_media":
        source_format = str(params.get("remux_source_format", "") or "").strip().lower()
        if not source_format:
            legacy = str(params.get("remux_task", "") or "").strip().lower()
            source_format = {
                "mp4_to_mkv": "mp4",
                "mkv_to_mp4": "mkv",
                "mkv_to_mp4_faststart": "mkv",
                "mov_to_mxf": "mov",
                "mxf_to_mov": "mxf",
            }.get(legacy, "")
        return {source_format} if source_format else _normalize_extensions(raw, MEDIA_EXTENSIONS)
    return _normalize_extensions(raw, MEDIA_EXTENSIONS)


def _remux_pair(params: dict[str, Any]) -> tuple[str, str]:
    source_format = str(params.get("remux_source_format", "") or "").strip().lower()
    target_format = str(params.get("remux_target_format", "") or "").strip().lower()
    if source_format and target_format:
        return source_format, target_format
    legacy = str(params.get("remux_task", "") or "").strip().lower()
    return {
        "mp4_to_mkv": ("mp4", "mkv"),
        "mkv_to_mp4": ("mkv", "mp4"),
        "mkv_to_mp4_faststart": ("mkv", "mp4"),
        "mov_to_mxf": ("mov", "mxf"),
        "mxf_to_mov": ("mxf", "mov"),
    }.get(legacy, (source_format, target_format or "mp4"))


def run_preflight(context: Any) -> dict[str, Any]:
    root = context.paths.root
    params = dict(context.operation.parameters)
    service_name = _service_name(context.operation.service)
    report: dict[str, Any] = {
        "operation": context.operation.id,
        "service": service_name,
        "ok": True,
        "skipped": False,
        "checks": [],
        "source": "",
        "output": "",
        "input_files": None,
        "planned_items": None,
    }
    checks: list[dict[str, str]] = report["checks"]

    if service_name in SKIP_SERVICES:
        report["skipped"] = True
        checks.append(_issue("OK", "preflight", "Skipped for diagnostic/maintenance operation."))
        context.log(f"{ansi_status('PREFLIGHT')} skipped")
        return report

    context.log("\x1b[1;36mPreflight\x1b[0m")

    if service_name == "download_youtube":
        yt_dlp, yt_ok = _tool(root, "Tools/yt-dlp/bin/yt-dlp.exe", "yt-dlp")
        checks.append(_issue("OK" if yt_ok else "ERROR", "yt-dlp", yt_dlp if yt_ok else "yt-dlp was not found."))
        deno, deno_ok = _tool(root, "Tools/deno/deno.exe", "deno")
        checks.append(_issue("OK" if deno_ok else "WARN", "Deno", deno if deno_ok else "Deno was not found. YouTube formats may be limited."))
        download_dir = root / "Download"
        report["output"] = str(download_dir)
        source_mode = str(params.get("youtube_source_mode", "single") or "single").strip()
        if source_mode == "batch":
            batch_file = Path(str(params.get("batch_file", "Download\\urls.txt")).strip().strip('"'))
            if not batch_file.is_absolute():
                batch_file = root / batch_file
            report["source"] = str(batch_file)
            if not batch_file.exists():
                checks.append(_issue("ERROR", "batch file", f"Not found: {batch_file}"))
            elif not batch_file.read_text(encoding="utf-8", errors="ignore").strip():
                checks.append(_issue("ERROR", "batch file", f"File is empty: {batch_file}"))
            else:
                checks.append(_issue("OK", "batch file", str(batch_file)))
        else:
            url = str(params.get("youtube_url", "") or "").strip()
            report["source"] = url
            checks.append(_issue("OK" if url else "ERROR", "URL", url or "YouTube URL is empty."))
    elif service_name in MEDIA_SERVICES:
        ffmpeg, ffmpeg_ok = _tool(root, "Tools/ffmpeg/bin/ffmpeg.exe", "ffmpeg")
        checks.append(_issue("OK" if ffmpeg_ok else "ERROR", "ffmpeg", ffmpeg if ffmpeg_ok else "ffmpeg was not found."))
        source = cached_source_path(root)
        output = cached_output_path(root)
        report["source"] = str(source)
        report["output"] = str(output)
        source_files: list[Path] = []
        if not source.exists():
            checks.append(_issue("ERROR", "Source", f"Source does not exist: {source}"))
        else:
            extensions = _media_extensions_for(service_name, params)
            files = _media_files(source, extensions)
            source_files = files
            planned = min(1, len(files)) if _as_bool(params.get("limit_first_file")) else len(files)
            report["input_files"] = len(files)
            report["planned_items"] = planned
            if files:
                checks.append(_issue("OK", "Source files", f"{len(files)} matching file(s); planned: {planned}; extensions: {', '.join(sorted(extensions))}"))
            else:
                checks.append(_issue("ERROR", "Source files", f"No matching file(s) in {source}; extensions: {', '.join(sorted(extensions))}"))
        _append_dav1d_source_check(root, params, source_files, checks)
        if output.exists() and not output.is_dir():
            checks.append(_issue("ERROR", "OUT", f"Output path is not a folder: {output}"))
        elif source.exists() and output.resolve() == source.resolve():
            checks.append(_issue("WARN", "OUT", "Source and OUT point to the same folder."))
        else:
            checks.append(_issue("OK", "OUT", str(output)))

        if service_name == "remux_media":
            source_format, target_format = _remux_pair(params)
            if not source_format:
                checks.append(_issue("OK", "remux", f"Source format is detected per file; target: {target_format.upper()}."))
            elif target_format not in REMUX_COMPATIBILITY.get(source_format, set()):
                checks.append(_issue("ERROR", "remux", f"{source_format.upper()} -> {target_format.upper()} is not enabled as a safe stream-copy pair."))
            else:
                checks.append(_issue("OK", "remux", f"{source_format.upper()} -> {target_format.upper()}"))

        if service_name == "run_color_grade" and "hdr2sdr" not in str(params.get("script_preset", "")).lower():
            raw_lut = str(params.get("lut_file", "") or "").strip().strip('"')
            lut = Path(raw_lut) if raw_lut else root / "LUTs" / "active.cube"
            if not lut.is_absolute():
                lut = root / lut
            fallback_luts = sorted((root / "LUTs").glob("*.cube")) if (root / "LUTs").exists() else []
            if lut.exists() or fallback_luts:
                checks.append(_issue("OK", "LUT", str(lut if lut.exists() else fallback_luts[0])))
            else:
                checks.append(_issue("ERROR", "LUT", f"No LUT file found: {lut}"))

        if service_name in {"encode_targets", "run_color_grade"} and str(params.get("output_container", "")).strip().lower() == "mxf":
            audio_mode = str(params.get("audio_mode", "source") or "source").strip().lower()
            if audio_mode in {"pcm_s16", "pcm_s24", "none"}:
                checks.append(_issue("OK", "MXF audio", audio_mode))
            else:
                checks.append(_issue("ERROR", "MXF audio", "MXF editing output requires PCM 16-bit, PCM 24-bit, or no audio."))

        _append_pixel_format_checks(service_name, params, checks)

        if ffmpeg_ok:
            listing = _capture_tool([ffmpeg, "-hide_banner", "-encoders"], root)
            required_encoders = _required_encoders(service_name, params, root)
            for encoder in required_encoders:
                if listing and _encoder_listed(listing, encoder):
                    checks.append(_issue("OK", "encoder", encoder))
                elif listing:
                    checks.append(_issue("ERROR", "encoder", f"FFmpeg encoder is not listed: {encoder}"))
                else:
                    checks.append(_issue("WARN", "encoder", f"Could not inspect FFmpeg encoders for {encoder}."))

            _append_hardware_guard_checks(root, checks, _hardware_needs(service_name, params, required_encoders))

        if service_name == "audio_process":
            workflow = _audio_workflow(params)
            stream_mode = str(params.get("audio_stream_mode", "first") or "first").strip().lower()
            if stream_mode == "language" and not str(params.get("audio_language", "") or "").strip():
                checks.append(_issue("ERROR", "audio stream", "Language mode requires a language tag such as eng, rus or jpn."))
            if stream_mode == "index":
                try:
                    index_value = int(float(str(params.get("audio_stream_index", 0)).strip()))
                except ValueError:
                    index_value = -1
                if index_value < 0:
                    checks.append(_issue("ERROR", "audio stream", "Stream index must be 0 or greater."))
            if workflow == "in_video":
                audio_format = str(params.get("audio_format", "wav") or "wav").strip().lower()
                container = str(params.get("audio_video_container", "source") or "source").strip().lower()
                if container == "mp4" and audio_format in {"wav", "flac"}:
                    checks.append(_issue("ERROR", "audio in video", "MP4 is not a safe container for PCM/FLAC audio replacement. Choose MOV or MKV."))
                if container == "source" and audio_format in {"wav", "flac"}:
                    checks.append(_issue("WARN", "audio in video", "Source container may not support PCM/FLAC. MOV or MKV is safer for in-container audio processing."))
                if container == "mxf" and audio_format in {"flac", "alac", "m4a", "mp3", "opus"}:
                    checks.append(_issue("ERROR", "audio in video", "MXF is not a safe container for this compressed audio format. Choose MOV or MKV."))
                if str(params.get("audio_lufs_mode", "") or "").strip().lower() in {"two_pass", "two-pass", "2pass"} and stream_mode == "all":
                    checks.append(_issue("ERROR", "audio in video", "Two-pass LUFS inside one video supports one selected audio stream; choose first/index/language."))
    else:
        report["skipped"] = True
        checks.append(_issue("OK", "preflight", "No preflight rules for this service."))

    errors = [item for item in checks if item["level"] == "ERROR"]
    report["ok"] = not errors
    for item in checks:
        context.log(f"{ansi_status(item['level'])} {item['subject']}: {item['detail']}")
    if errors:
        context.log(f"{ansi_status('PREFLIGHT')} failed: {len(errors)} error(s)")
    else:
        context.log(f"{ansi_status('PREFLIGHT')} OK")
    context.log("")
    return report
