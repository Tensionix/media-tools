# Audion Media Tools — changelog

[Русский](CHANGELOG_RU.md) · [About](README_EN.md) · [User guide](USER_GUIDE_EN.md)

## 3.2.1 — 23 October 2026

**Equal parts.** CUT → SPLIT has an Equal parts preset: the part length is a timecode, as the points are -
`01:29:00,000`; the console command takes minutes (`89`) too. Parts are numbered from the start,
with the remainder last; By points keeps manual entry available. Video is copied at
keyframes; sound follows the selected cut mode.

**Copy extraction.** The Copy preset's `auto` resampler value now passes parameter
validation, so the window can extract audio without encoding or resampling.

**The headings of the blocks in Russian.** CUT, METADATA, STREAMS, CHANNELS, MASTERING and MP3 / LAME are named
in Russian again in the Russian window, not by the words of the manifest.

## 3.1.2 — 22 October 2026

**The sources of the icon.** `system_core\icons` holds the original vector of the icon again, `app.svg` - a yellow
film reel with three openings on a red rounded tile; `source.png` and `app.png` are rendered from it at 1024×1024. The
icon of the program, `app.ico`, is the same: all ten of its frames match them pixel for pixel. How the icon was made -
`prompt.txt`.

## 3.1.1 — 21 October 2026

**The licence of winpthreads named right.** The record `Tools\cineraw\cineraw-source.json` the installer of cineraw
writes names it as its text does: MIT and, for the parts from Lockless Inc., BSD-3-Clause; it was "ZPL-2.1 and MIT".

**The texts on cineraw.** The README, the guide and the tooltip of cineraw in the header of the window say that
cineraw comes with the program - built from its sources when the program is built - and SERVICE → "Install ProRes RAW
development" builds it again.

## 3.1.0 — 18 October 2026

**FFmpeg by the NVIDIA driver.** Without an NVIDIA card and with the LTS driver 610.88 and newer the newest stable Gyan
build is installed, 9.0.2 at least; a newer one that fails the NVENC test goes back to 9.0.2. Below 610.88 an older
branch (8.0.1 or 7.1) keeps NVENC working, and the installer, the window before the download and the amber dot of
FFmpeg in the header say that not every operation is possible. The sources of a former FFmpeg build are removed once
the new build's are in place.

**Camera RAW.** The program says what opens it instead of a flat green frame or an error of FFmpeg. ProRes RAW ENCODE,
FRAME RATE and COLOR refuse — FFmpeg gives the signal of the sensor without the white balance and the matrix of the
camera — and CUT, PACKAGE and AUDIO take it as it is. ARRIRAW, Sony RAW and X-OCN (known by the header of the MXF), RED
R3D, Nikon N-RAW, Blackmagic RAW and Canon Cinema RAW FFmpeg does not read: CUT and PACKAGE refuse them too, and their
files, which no operation takes, are named in the preflight. A Source of RAW alone is refused before the run, among other
videos such a file fails by itself. The line names the program and its download page (DaVinci Resolve, Final Cut Pro,
ARRI Reference Tool, REDCINE-X PRO, Blackmagic RAW Player, Sony RAW Viewer, Canon Cinema RAW Development); the table is
`config\camera_raw.yaml`.

**ProRes RAW on the video card.** cineraw comes with the program: it is built from the sources of libcraw when the
program is built, and SERVICE → "Install ProRes RAW development" builds it again (about 185 MB downloaded, 5 minutes;
MSYS2 only for the build). ProRes RAW is developed as it was shot — the white balance and the colour matrix of the
camera — on a card with Vulkan 1.4 (NVIDIA RTX). ENCODE → RAW writes it into ProRes 4444, DNxHR 444, H.264 or H.265 with
the sound, the timecode and BT.709; ENCODE, FRAME RATE and COLOR take ProRes RAW, developing it first. The pieces of a
clip develop side by side, no frame touches the disk, the joins are exact to the frame; 4.2K on an RTX 5070 — about 5
frames a second.

**The header.** A newer FFmpeg is marked, as yt-dlp, Deno and mpv are; SETTINGS → COMPONENTS updates it.

## 3.0.0 — 15 October 2026

**A new window.** The window is a program of its own — C# on Avalonia, `App\AudionMediaTools.exe`, started by
`Start.exe`. The engine runs for the time of an operation and is gone after it; nothing stays in the background.

**The window is the face of the console command.** Every button is an operation of `media_cli.cmd`, and a run opens in
the journal with the command that repeats it. The command does everything the window does:

- `describe` — the operations, their fields, choices, presets;
- `run --operation ID --set NAME=VALUE` with `--source`, `--target`, `--result` (the outcome as JSON), `--dry-run`
  (the commands it would start), `--cancel-file`, `--only`;
- `wrapper NAME`, `map`, `components`, `plan`, `version`;
- exit codes 0 done, 1 failed, 2 a wrong call or a run refused before it began, 130 stopped.

**An interlaced source becomes progressive.** EDITING, STORAGE, DELIVERY and COLOR turn a source of two fields into
progressive frames by bwdif - by default a frame of each field, 50i to 50p; a frame of each frame, or the fields kept,
are choices in Advanced. A progressive source is not touched, ARCHIVE keeps the fields.

**Sections and modes.** The ribbon holds AUDIO, ENCODE (archive, editing, storage, delivery), PACKAGE, CUT, FRAME RATE,
COLOR and DOWNLOAD, each with its modes. DETAILS tells what the files of the Source are; SERVICE holds the checks and the
installers. Every section and mode keeps its own form, remembered between launches; only the encoder and the decoder are
shared. ↺ brings a mode back to its preset; COMMAND shows the commands of the run without running them.

**The header and SETTINGS.** The versions of yt-dlp, Deno, mpv, FFmpeg and the video card driver stand in the header; a
newer yt-dlp, Deno or mpv is marked. SETTINGS: four looks, the fonts of the window and of the terminal, the components with
UPDATE and INSTALL, the system — processor, video card and driver, memory, the FFmpeg coders that passed the check, the
disk. ABOUT names the version, the folders, the author and the licence of every part.

**The journal.** The lines of a run come in the colours of the program that writes them. FFmpeg's own progress line
`frame= … speed=` stands under the `[PROGRESS]` bar, in the window and in a console, and its last word `Lsize=` ends
the file. The journal widens, and its width is remembered. The COMMAND line at the bottom runs a command of your own in
the PowerShell 7 of the program (`App\AudionPs.exe`) or in `cmd.exe`.

**The folders are `input` and `output`.** The Source by default is `input\`, the Target `output\`; downloads go to
`output\Download`, the list of links is `input\urls.txt`. Beside the paths: history, pin, RESET, LIST, TO SOURCE (the
result becomes the next Source) and CLEAR — through the Recycle Bin, after a question that names the folders.

**CUT.** The window drives mpv itself: open, take A and B, mark IN or OUT, a split point taken only forward, the points
only of the file chosen. A timecode is typed through a mask — digits one after another, the separators come by
themselves. A sound file is cut without loss by default.

**DOWNLOAD.** PASTE beside the link, the list file and the cookies file; ⓘ shows the formats a link offers without
downloading; cookies come from a browser or from a file sealed with DPAPI (the shield). A link to a video in a playlist
takes the video alone unless the playlist is asked for.

**The 95 wrappers of `Scripts\`** keep their names and run through `media_cli.cmd wrapper`. Each has its description in
both languages, and [the list of wrappers](SCRIPTS_EN.md) gives the same call through `run`.

**Documents made from the program.** [Operations](OPERATIONS_EN.md) — every field, choice and preset with its tooltip —
and [Wrappers](SCRIPTS_EN.md) are written by `media_cli.cmd map --docs` from the data of the program. New: the
[console command](CLI_EN.md) and the [guide for an AI agent](AI_AGENT_GUIDE_EN.md).

**Fixed.**

- FRAME RATE and CUT take the declared rate of a constant-rate file: a ProRes LT averaging 24.016 at 23.976 was
  slowed by 0.17 %, and a cut missed the frame grid.
- "1080p H.264 with AAC" and "for upload" downloads took Opus sound; they take AAC now.
- The 5.1 downmix of the wrappers (front whole, centre −3, rear −6 dB, no LFE) is a field of AUDIO
  (`downmix_formula`); the plain `-ac 2` of FFmpeg is 7.6 dB quieter on full 5.1.
- The `_sync` wrappers even the timestamps again (`audio_resync`); the ProRes wrappers of COLOR encode the sound to AAC
  384k.
- A wrapper of two runs (the sound of videos, then sound files) no longer fails on a folder of one kind: a run without
  files of its own is passed by.
- A file stopped halfway is never left under its final name: a file is written under `name.writing.ext` and takes its
  name only whole.
- Empty folders a run made in the Target are taken away after it.
- DETAILS tells an interlaced rate (`25i`) and a variable one (`VFR 30 (avg 28.875)`), and names a file it cannot read
  or that another program holds.
- `--dry-run` of an operation that cannot only say its commands is refused instead of running for real; a dry run
  sets only the dry-run field of its own operation.
- A second run into the same Target with Overwrite off no longer reads as written: a file already there is passed by
  before FFmpeg is started (`[SKIP] … already exists and Overwrite is off`) and counted in `skipped`, in ENCODE, AUDIO,
  PACKAGE, FRAME RATE and COLOR as in CUT.
- The bar of a run follows FFmpeg's own progress inside a file; it stood near 8 % through a one-file encode.
- Profile Doctor knows the wrappers of CUT: four `ff-trim-*` were reported as errors.
- The outcome of a download names the files it wrote (`downloaded`) and their count (`processed`).
- CUT keeps the frames asked for in a file whose timeline does not start at zero (MPEG-TS, an MP4 with an offset, ARRI
  MOV): the start of the file was added to the seek twice. The top-up of a short tail works with Overwrite off.
- A result that would be one of its own sources - by its path, a link or a hard link - is refused before FFmpeg starts.
- A file is written under a draft name of its own run: a file that only looks like a draft is never deleted, and a
  name with "%" is written whole like any other.
- `--result` is a `.json` file outside the Source and the settings; its draft is the run's own.
- `cleanup_project.cmd` refuses a folder that is a link and never walks through one.
- A lossless archive keeps the bits or refuses: x264 lossless turns down a 12-bit, RGB or alpha source (FFV1 keeps it),
  float PCM is copied instead of going to FLAC.
- A run with a failed file is a failure, a run stopped before its first file is a stop; STOP ends a child that prints
  nothing, together with what it started.
- Two sources of one stem write two files (`take.m4a`, `take_wav.m4a`).
- CUT takes a Source of one file.
- The loudness report of sound in a video measures every track.
- A copy of big-endian PCM goes to MKA: WAV does not hold it.
- A download repeated at once counts nothing as written; what was there is listed as `existing`.
- x264 keeps the fields and their order of an interlaced source.

**The environment.** Python carries only what the engine needs — PyYAML, pytest, pip-tools (59 MB). The scripts and the installers
run in the PowerShell 7 of the program. The builder menu (`builder_main.cmd`) and the console menus on FZF stay.
