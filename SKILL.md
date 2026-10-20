---
name: audion-media-tools
description: Process video and sound with Audion Media Tools - transcode for an archive, for editing (ProRes, DNxHR), for storage or for delivery (x264, HEVC 10-bit, SVT-AV1, on the CPU or a GPU), repackage into another container without re-encoding, extract sound, convert it inside a video or as sound files (WAV, FLAC, ALAC, AAC, MP3, Opus, loudness to LUFS), cut a camera file without loss (keep a piece, cut a piece out, split), conform or varispeed a frame rate to 23.976, apply a LUT with a gamma before it or tone-map HDR to SDR, download a video or its sound by a link (yt-dlp), and tell what the files of a folder are (ffprobe). Run its operations through the console command media_cli.cmd and read their outcome. Use when asked to transcode, re-encode, convert or compress a video, make editing proxies, remux or change a container, extract or convert audio, normalise loudness, trim or cut a video, change its frame rate, grade it with a LUT, convert HDR to SDR, download from YouTube or another site, inspect media files, or to change and check the program itself.
---

# Audion Media Tools

A portable program for media work by FFmpeg. `Start.exe` opens the window (`App\AudionMediaTools.exe`, C# on Avalonia);
every button of the window is an operation of the console command `media_cli.cmd` (Python 3.12 of `runtime\`, the engine in
`system_core\`), and the window runs nothing the command cannot. The tools the engine calls lie in `Tools\`: FFmpeg and
ffprobe, mpv (the player of a trim), yt-dlp with Deno, 7-Zip.

Paths below are relative to the project root. Sibling projects are resolved from the parent folder; never hardcode the
drive. Why things are as they are is in `MEMORY.md`; the rules of the workshop are in `CLAUDE.md`. The person's guide is
`Docs\USER_GUIDE_RU.md` / `_EN.md`, the command line `Docs\CLI_RU.md` / `_EN.md`. Every operation with every field,
choice and preset is in `Docs\OPERATIONS_EN.md`, every wrapper of `Scripts\` in `Docs\SCRIPTS_EN.md` - both are made from
the data of the program (`media_cli.cmd map --docs`).

## The folders

| Folder | What it holds |
|---|---|
| `input\` | the Source: the files an operation takes (all of the folder, its subfolders too, or one file named by `--source`) |
| `output\` | the Target: every result, in a folder of the operation - `Storage\x264_crf14_slow\clip.mp4`, `Remux\...`, `Trim\...`, `Download\...` |
| `LUTs\` | the LUTs of COLOR (`.cube`, `.3dl`, `.lut`), subfolders too |
| `logs\`, `report\` | the journal of every run, and its report (`batch_report.md`, `batch_report.json`) |
| `config\` | `tool_manifest.yaml` - the operations and their fields; `window_layout.yaml` - where each stands in the window; `wrappers.yaml` - the 95 wrappers; the state of the window (settings, path history, caches) |
| `Scripts\` | 95 wrappers `*.cmd`, one action each, every one a door of `media_cli.cmd wrapper NAME` |
| `cli\`, `launcher_project.cmd`, `launcher_tools.cmd` | the console menus on FZF over the wrappers |
| `builder_main.cmd`, `install\` | the builder on FZF: the Python environment, the tools, the window, the checks |
| `Source\` | the window (C#); `install\Build-App.cmd` builds it into `App\` |
| `workspace\` | the engine's scratch (the pieces of a trim before they are joined); empty between runs |

## The console command

```
media_cli.cmd describe                                    the operations, their fields, the layout (JSON)
media_cli.cmd run --operation ID [--set NAME=VALUE ...]   an operation; the Source is input\, the Target output\
media_cli.cmd run ... --source FILE_OR_FOLDER --target FOLDER --result OUTCOME.json
media_cli.cmd run ... --dry-run                           the commands it would start, nothing started
media_cli.cmd wrapper NAME [ARGUMENTS]                    a wrapper of Scripts\ by its name
media_cli.cmd map [--out MAP.json] [--docs]               the map of the program; --docs writes the reference documents
media_cli.cmd components [--latest]                       the versions of yt-dlp, Deno, mpv, FFmpeg, 7-Zip and the GPU driver
media_cli.cmd plan --operation install_ffmpeg             what an installer would download: files, source, size
media_cli.cmd version
```

Exit codes: `0` done, `1` failed, `2` a wrong call or a run refused before it began (nothing was run), `130` stopped. A
wrong call is a field the operation has not, a value that is none of its choices, a form that may not run as it stands, or
`--dry-run` of an operation that cannot only say its commands. A refused run is one its preflight stopped - no file of its
kind in the Source, no FFmpeg; its `[PREFLIGHT]` lines say why.

- `--set NAME=VALUE` sets a field; a row of ticks is `a,b`, the rows of a trim are JSON. A preset field sets the fields it
  names when it is named (`--set storage_profile=hevc10_crf14`), and the other `--set` are laid over it. Left unnamed,
  every field keeps its own default - the preset a form shows first is not applied by itself; name it to have its values.
- `--result FILE` - the outcome as JSON: `operation`, `outcome` (`done`, `failed`, `refused`, `stopped`), `ok`,
  `message`, `parameters` (every value the run went with), `source`, `target`, `seconds`, and `data` - what the operation
  tells: a media operation `processed` (the files written), `skipped` (passed by, the reason in the journal), `files` (the
  files of the Source), `failed` where it goes on past a failed file and `refused` where it turned a file down (an
  archive that would not keep it, a point a cut cannot take) - either makes the outcome `failed`, exit 1; a download
  `processed`, `downloaded` (the paths written) and `existing` (found there already). Every outcome names `log_file` and
  `batch_report_md`. Read it rather than the journal. `--result` is a `.json` file outside the Source and outside
  `config\`: anything else is a wrong call. Give it a full path, or call the command from the program folder: a relative
  one counts from the folder of the caller.
- `--only mkv` or `--only mov,mxf` narrows the kinds of file taken from the Source.
- `--cancel-file FILE` stops the run when the file appears: the engine ends FFmpeg, a half-written file is taken away.
- The journal: plain lines, `[OK]`, `[WARN]`, `[ERR]`, `[CMD]` (the FFmpeg command), `[PROGRESS] name [####----] 42% ...`
  with FFmpeg's own line `frame= ... speed=` under it. A caller that reads by a pipe gets service lines `::media::{...}`
  (`started`, `progress`, `activity`, `finished`) too; a console does not.
- A relative `--source`/`--target` counts from the project root; relative `--result`, `--params`, `--cancel-file` from the
  folder of the caller.
- `cleanup_source`, `cleanup_transcoded`, `cleanup_workspace` delete for good and are not run from the command: the window
  clears the folders through the Recycle Bin. Never clear `input\` - it is the person's material.

## Sections and operations

The ribbon of the window, each mode with the call that does the same:

<!-- map:sections -->
| Section | Mode | Call |
|---|---|---|
| AUDIO | EXTRACT | `media_cli.cmd run --operation audio_run --set audio_workflow=extract` |
| AUDIO | SOUND IN VIDEO | `media_cli.cmd run --operation audio_run --set audio_workflow=in_video` |
| AUDIO | CONVERT | `media_cli.cmd run --operation audio_run --set audio_workflow=audio_files` |
| ENCODE | ARCHIVE | `media_cli.cmd run --operation archive_run` |
| ENCODE | EDITING | `media_cli.cmd run --operation editing_run` |
| ENCODE | STORAGE | `media_cli.cmd run --operation storage_run` |
| ENCODE | DELIVERY | `media_cli.cmd run --operation delivery_run` |
| ENCODE | RAW | `media_cli.cmd run --operation raw_develop_run` |
| PACKAGE | VIDEO | `media_cli.cmd run --operation remux_run --set remux_stream_mode=video` |
| PACKAGE | AUDIO | `media_cli.cmd run --operation remux_run --set remux_stream_mode=audio` |
| PACKAGE | VIDEO AND AUDIO | `media_cli.cmd run --operation remux_run --set remux_stream_mode=video_audio` |
| PACKAGE | SUBTITLES | `media_cli.cmd run --operation subtitles_extract` |
| CUT | KEEP | `media_cli.cmd run --operation trim_run --set trim_action=keep` |
| CUT | CUT OUT | `media_cli.cmd run --operation trim_run --set trim_action=cut` |
| CUT | SPLIT | `media_cli.cmd run --operation trim_run --set trim_action=split` |
| FRAME RATE | VARISPEED | `media_cli.cmd run --operation fps_run --set fps_mode=varispeed` |
| FRAME RATE | CONFORM | `media_cli.cmd run --operation fps_run --set fps_mode=conform` |
| COLOR | LUT | `media_cli.cmd run --operation grading_run` |
| DOWNLOAD | BEST MP4 | `media_cli.cmd run --operation youtube_run --set youtube_profile=best_mp4` |
| DOWNLOAD | SAFE MP4 | `media_cli.cmd run --operation youtube_run --set youtube_profile=safe_mp4` |
| DOWNLOAD | OWN VIDEO | `media_cli.cmd run --operation youtube_run --set youtube_profile=video_custom` |
| DOWNLOAD | FOR UPLOAD | `media_cli.cmd run --operation youtube_run --set youtube_profile=upload_ready` |
| DOWNLOAD | OWN AUDIO | `media_cli.cmd run --operation youtube_run --set youtube_profile=audio_custom` |
| DOWNLOAD | SUBTITLES | `media_cli.cmd run --operation youtube_run --set youtube_profile=subs_only` |
<!-- /map -->

SOURCE INFO, SERVICE and the buttons beside a field:

<!-- map:service -->
| Operation | What it is |
|---|---|
| `probe_source` | Probe Source: Run ffprobe once for Source, print a compact table and update the media status line. |
| `source_info` | Source Info: Run ffprobe for Source and print every audio stream: codec, sample format, sample rate, bit depth, channels, bitrate and tags. |
| `inventory` | Inventory: Count project folders. |
| `selftest` | Selftest: Check ffmpeg, ffprobe, yt-dlp and Deno. |
| `profile_doctor` | Profile Doctor: Validate GUI operations, script wrappers and the shared preset catalog. |
| `hardware_capabilities` | Hardware capabilities: Run short FFmpeg smoke tests for CPU, QSV/NVENC/AMF H.264 and HEVC, SVT-AV1 and dav1d. |
| `preset_test_matrix` | Preset Test Matrix: Run portable 1-second smoke tests across audio, remux, FPS, LUT, archive, editing, storage and delivery presets. |
| `install_7zip` | Install 7-Zip: Install or refresh portable 7-Zip; required before FFmpeg 7z payloads. |
| `install_ffmpeg` | Install FFmpeg: Install or refresh the portable FFmpeg of Gyan (GPL) in Tools\ffmpeg by the NVIDIA driver: the newest stable, 9.0.2 at least, without an NVIDIA card and from the LTS driver 610.88; below it 8.0.1 (570-610.87) or 7.1 so that NVENC works, and not every operation is possible. |
| `install_ytdlp` | Install yt-dlp: Install or refresh portable yt-dlp and Deno into Tools. |
| `install_mpv` | Install mpv: Install or refresh portable mpv into Tools/mpv: the player of the trim. |
| `install_cineraw` | Install ProRes RAW development: Build cineraw of libcraw into Tools/cineraw from its sources: a portable MSYS2 for the build (about 185 MB downloaded, 5 minutes), removed afterwards; cineraw develops ProRes RAW on a video card with Vulkan 1.4 (NVIDIA RTX). |
| `youtube_formats` | Formats of the link: What formats the link offers - resolution, codecs, size - listed in the journal, nothing downloaded. One of them is taken with the profile Own video. |
| `youtube_cookies_import` | Take under DPAPI: The cookies file of the field Cookies file sealed with DPAPI for this account of Windows into config\cookies.dpapi: downloads with Cookies - File take this copy, and the open file is no longer needed. |
<!-- /map -->

What each section is for, and the preset to begin with (all of them: `Docs\OPERATIONS_EN.md`):

| Section | For | Begin with |
|---|---|---|
| ENCODE → ARCHIVE `archive_run` | a master without loss | `archive_profile=ffv1_mkv` (FFV1 in MKV), `x264_lossless_mkv` |
| ENCODE → EDITING `editing_run` | files an editor cuts smoothly | `editing_profile=prores_422_mov`; `prores_lt_mov`, `prores_proxy_mov` for proxies; `dnxhr_hq_mov`; `*_mxf` for Avid |
| ENCODE → STORAGE `storage_run` | compact files to keep | `storage_profile=x264_crf14`; `hevc10_crf14` (HEVC 10-bit), `svt_av1_crf14`, `x264_1080_crf14` (down to 1080) |
| ENCODE → DELIVERY `delivery_run` | files to send or upload | `delivery_profile=review_h264`, `upload_h264`, `upload_hevc10`, `svt_av1_delivery` |
| PACKAGE `remux_run` | another container, streams copied | `remux_stream_mode=video_audio`, `remux_target_format=mp4|mov|mkv|mxf`; `remux_orientation` turns a sideways camera without re-encoding |
| PACKAGE → SUBTITLES `subtitles_extract` | the subtitle streams to `.mks` | - |
| AUDIO `audio_run` | sound out of a video (`extract`), converted inside it with the picture copied (`in_video`), or sound files converted (`audio_files`) | `audio_profile=copy_auto` (as it is), `wav_24_48`, `flac_24_48`, `m4a384`, `lufs14_m4a` (loudness -14), `lufs_report` (measure only) |
| CUT `trim_run` | keep a piece, cut one out, split - without loss | `trim_file=NAME`, `trim_action=keep|cut|split`, `trim_start`, `trim_end` (`00:00:05,000` or seconds); the start lands on a keyframe, the end on the exact frame |
| FRAME RATE `fps_run` | to 23.976 | `fps_mode=varispeed` (every frame kept, the sound follows the speed and its pitch moves) or `conform` (every frame kept, the sound stretched and its pitch kept), `fps_target=24000/1001` |
| COLOR `grading_run` | a LUT, a gamma before it, HDR to SDR | `lut_file=LUTs\NAME.cube`, `grading_profile=lut_x264`; `preexpose_x264`, `pregamma_hevc10`, `hdr_hable_x264` |
| DOWNLOAD `youtube_run` | a video or its sound by a link | `youtube_url=LINK`, `youtube_profile=best_mp4`; `safe_mp4` for a link that breaks off; `audio_custom` + `youtube_audio_format=m4a`; `youtube_source_mode=batch` takes `input\urls.txt` |

An interlaced source (25i, 29.97i, 50i) becomes progressive in EDITING, STORAGE, DELIVERY and COLOR by default:
`scan_mode=double` - bwdif, a frame of each field, 50i to 50p; `progressive` - a frame of each frame, the rate kept; `keep`
- the fields and their order stay. The folder of the settings tells it (`x264_crf14_slow_progressive_2x`); a progressive
source is not touched; ARCHIVE keeps the fields.

The encoder of ENCODE, FRAME RATE and COLOR is `encode_backend=cpu|cuda|amd|qsv`, the decoder `decode_backend=auto|...`;
`hardware_capabilities` (SERVICE) tells what this machine's FFmpeg can use. The sound of an encode follows `audio_mode`
(`source` copies it).

## Procedures

### Process a file

1. Find the file: in `input\`, or a path the person gives - pass it with `--source`. Never move or change the person's file.
2. `media_cli.cmd run --operation probe_source --source FILE` (a file or a folder) - what it is: codec, size, frame rate
   (`25i`, `VFR 30 (avg 28.875)`), sound; `source_info` tells every sound stream in detail.
3. Choose the operation and its preset by the table above; `describe` gives every field and choice, `--dry-run` the exact
   FFmpeg command.
4. `media_cli.cmd run --operation ID --set PRESET_FIELD=PRESET [--set ...] --source FILE --result outcome.json`.
5. Read `outcome.json`: `outcome` `done` and `data.processed` > 0. The file is under `output\<Operation>\<settings>\`,
   the subfolders of the Source kept: `Editing\prores422\`, `Storage\x264_crf14_slow\`, `Remux\remux_mkv_to_mp4_video_audio\`.
   The folder of the settings is not the name of the preset; `--dry-run` prints the exact path in the FFmpeg command.
6. Check it with `Tools\ffmpeg\bin\ffprobe.exe -v error -show_streams -show_format FILE`: codec, size, frame rate, duration
   against the source; for a trim - the number of frames.

A file already in the Target is passed by unless `--set overwrite=true`: the journal says `[SKIP] NAME already exists and
Overwrite is off`, FFmpeg is not started for it, and the outcome counts it in `skipped`, not in `processed` - a second run
into the same Target reads `done` with `processed` 0. A file of a kind the operation does not take is skipped with its
reason in the journal too. ProRes RAW is developed on the video card by cineraw once `install_cineraw` has built it into
`Tools\cineraw` (`system_core\services\raw_develop.py`): `raw_develop_run --set raw_target=prores4444|dnxhr444|h264|h265`
writes it as it was shot, and ENCODE, FRAME RATE and COLOR develop it first into a ProRes 4444 master they read
(`[RAW] ... developed first`); a machine without a Vulkan 1.4 card that reads storage images without a format (NVIDIA RTX)
gets the reason in a `[FAIL]` line. Without cineraw ProRes RAW is refused by ENCODE, FRAME RATE and COLOR and copied by
CUT and PACKAGE. Other camera RAW is not developed (`system_core\core\camera_raw.py`, the table `config\camera_raw.yaml`):
ARRIRAW, Sony RAW / X-OCN, R3D, N-RAW, BRAW and Canon Cinema RAW are read by no operation - the `[PREFLIGHT] ... camera
RAW` line names the program that opens the file and its page; tell the person that, do not look for a way round. Two
sources of one name in one run - `take.flac` and `take.wav` to M4A - write two files: the
second gets the extension of its own (`take_wav.m4a`), and the journal says so. A result that would be one of its own
sources is refused before FFmpeg starts, Overwrite or not.

### Download by a link

1. `media_cli.cmd run --operation youtube_formats --set youtube_url=LINK` - what the link offers, nothing downloaded.
2. `media_cli.cmd run --operation youtube_run --set youtube_url=LINK [--set youtube_profile=...] --result outcome.json`.
   A link to a video in a playlist takes the video alone; the whole playlist is `--set youtube_source_mode=playlist`.
3. `data.downloaded` names the file: `output\Download\<uploader>\<date> - <title> [<id>].<ext>` (a playlist:
   `output\Download\<number> - <title> [<id>].<ext>`). `best_mp4` takes the best picture that fits MP4, which may be AV1;
   H.264 with AAC is `youtube_profile=upload_ready`.
4. Cookies: by default (`cookies_source=file`) the person's sealed copy `config\cookies.dpapi`, or else `config\cookies.txt`,
   goes with the call when there is one, as in the window. A public link needs none - `--set cookies_source=none`; a link
   that wants a sign-in - `--set cookies_source=chrome` (or `edge`, `firefox`, `brave`: the browser's cookies at the call).
   Never read or print a cookies file.

### Add an operation or a field

1. The field or the operation goes into `config\tool_manifest.yaml` with its texts in both languages (`label`/`label_ru`,
   `tooltip`/`tooltip_ru`, `description`/`description_ru`); a new operation names its service `module:function`.
2. Its service in `system_core\services\media_service.py` reads `context.operation.parameters`, runs FFmpeg through
   `run_process` (the journal, the progress, STOP and the whole-file rule come with it) and returns a dict. It tells
   `context.units(count)` before its loop and `context.progress(done / count)` after each unit - the share then follows
   FFmpeg inside a unit - and passes a target already there by `_kept_in_place` before FFmpeg is asked.
3. Its place in the window: a mode of a section or a button beside a field in `config\window_layout.yaml`. An operation
   that stands nowhere fails `tests\test_window_layout.py`; the window draws it without a line of C#.
4. A rule of the form (what a choice turns off, what a preset sets) goes into `system_core\core\operation_model.py` - one
   copy for the window and the console.
5. A test in `tests\`; then `media_cli.cmd map --docs` for the documents.

### Check the program

- The engine: `runtime\python.exe -m pytest -q -p no:cacheprovider tests system_core\tests` (about five minutes; the
  wrappers and the trims run the real FFmpeg).
- The window: `install\Build-App.cmd` runs the checks of the window, builds `App\` and lets the built window check itself;
  `pwsh -File Source\Tools\release-walk.ps1 -Stand <empty folder>` presses its buttons by UI Automation on a copy, off the
  screen (an installed PowerShell 7: `App\AudionPs.exe` has no WindowsDesktop assemblies);
  `Source\Tools\shots.ps1` walks a Debug build by steps and pictures it. Never the real mouse.
- The environment: `install\verify_portable_env.cmd` (the builder's step 71).
- The download pages of the programs that open camera RAW: `runtime\python.exe tests\probe_raw_pages.py` (on the
  network, now and then; MOVED - put the new address into `config\camera_raw.yaml`).

### Build

- The window: `install\Build-App.cmd` - after a change in `Source\` only; then `Source\bin`, `Source\obj`, `Source\Ps\bin`,
  `Source\Ps\obj` go (the builder's step 70 takes them).
- `Start.exe`: `install\Build-StartLauncher.cmd`.
- The Python environment and the tools: `builder_main.cmd` (FZF): 01/02 Python, 03 FZF, 10-14 7-Zip, FFmpeg, yt-dlp with Deno,
  mpv. Every installer names its files, their source and size before it downloads.
- The version is `config\version.json` alone.
