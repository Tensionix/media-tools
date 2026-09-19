# Audion Media Tools — User Guide

[Русский](USER_GUIDE_RU.md) · [About](README_EN.md) · [Measurements](MEASUREMENTS_RU.md) · [Decisions](DECISIONS_EN.md)

**Contents**

- [The Order of Work](#the-order-of-work)
- [The Workbench](#the-workbench)
- [Trimming: the Player and Its Keys](#trimming-the-player-and-its-keys)
- [The Pages](#the-pages)
- [Hardware](#hardware)
- [Terminal and Reports](#terminal-and-reports)
- [Rules for Safe Work](#rules-for-safe-work)
- [Checks After Changes](#checks-after-changes)
- [Technical Reference](#technical-reference)

How to work with it: the workbench, the order of running an operation, trimming
with the player, the pages, the reports.

## The Order of Work

1. Choose the source and the output folder.
2. Open the page you need.
3. Pick a profile.
4. Change only what needs changing.
5. Press `Command` — see exactly what will go to FFmpeg.
6. Run the first file.
7. Run the batch.

The profile sets a ready base; the fields below override it selectively.
Checkboxes never enable hidden actions the profile did not set.

**Steps 5 and 6 are not skipped on a new operation.** A wrong parameter costs
seconds on one file and an hour on a folder.

## The Workbench

The top row sets two paths for every page:

| button | what it does |
|---|---|
| Source | the folder with the originals |
| Add file… | a single file as the source |
| Target | the output folder |
| Reset | restore the project `Source\` and `Transcoded\`, touching no files |
| Delete | clear the current source and target after confirmation |
| List | print the names of the current source files to the terminal |

Path fields remember history; a pinned path moves to the top. Clearing requires
confirmation.

The source is walked recursively and the output mirrors its structure:

```
Target\<operation>\<profile>\<as in source>\<filename>.<ext>
```

`Source\Day1\clip.mov` and `Source\Day2\clip.mov` do not collapse into one flat
folder and fight over a name.

## Trimming: the Player and Its Keys

Cut points are found in the mpv player — opened by a button in the section — and
carried into the fields by `Take A and B`. The keys work **in the player window**,
not in the program panel.

The dozen keys that do the whole job:

| key | what it does |
|---|---|
| `Space` | play or pause |
| `,` `.` | step exactly one frame back or forward |
| `←` `→` | seek 5 seconds |
| `Shift+←` `Shift+→` | **exactly** one second back or forward |
| `Shift+↓` `Shift+↑` | **exactly** five seconds |
| `↓` `↑` | one minute back or forward |
| `Home` | to the start of the file |
| `l` | set point **A**; press again for **B**; the piece between them loops |
| `Ctrl+l` | clear A and B |
| `b` | play **backwards** |
| `n` | return to playing forwards |
| `[` `]` | 10% slower or faster — at 0.25 every syllable is audible |
| `Backspace` | back to normal speed |
| `s` | a frame grab next to the source file |

`l` *is* the cut: set A and B, listen to the loop, and if a point is wrong nudge
it with `,` and `.` and press `l` again.

**The difference between `←` and `Shift+←` matters.** An ordinary seek jumps five
seconds and shows the nearest frame; `Shift` is exact, precisely one second, and
lands on the frame. Finding a cut point needs the second one.

`b` and `n` were added by this build: in stock mpv `b` is debanding, overridden
here.

The full list — all 197 bindings with their player commands — is in
`tools\MPV_HOTKEYS_RU.md`. It was taken from the player itself through
`input-bindings`, not copied from a web page.

Trimming in detail — the working cycle, the three actions, accuracy, refusals — is
in `tools\TRIM_RU.md`; what is compatible with what when cutting is in
`tools\TRIM_MATRIX_RU.md`. Both are Russian.

## The Pages

| page | about | in detail |
|---|---|---|
| Download | a link or a list, format profiles, resolution, subtitles, threads | `tools\YOUTUBE_DOWNLOAD_RU.md` |
| Audio streams | extraction, resampling, loudness, packaging; audio into video without re-encoding the picture | `tools\AUDIO_WORKFLOWS_RU.md` |
| Trimming | frame-accurate and keyframe cuts, marks remembered per file; sound files on the sample | `tools\TRIM_RU.md` |
| Remux, frame rate, colour | container changes, frame rate, lookup tables, HDR to SDR | `tools\REMUX_FPS_LUT_RU.md` |
| Archive, editing, storage, delivery | lossless FFV1 and x264, ProRes and DNxHR, x264/x265/AV1, upload profiles | `tools\ENCODING_PIPELINES_RU.md` |
| Diagnostics | what hardware is present, what it can do, profile checks | `tools\HARDWARE_DIAGNOSTICS_RU.md` |

Section documents are Russian only.

## Hardware

The program can choose between the NVIDIA, Intel, and AMD hardware paths, separate
AV1 encoder and decoder, and the plain processor.

**Run "Hardware Capabilities" before the first run on a new machine.** The result
is cached and hardware profiles are checked against it. A missing path is a normal
answer, not a fault: it means the driver or the hardware is absent.

## Terminal and Reports

On the right: operation status, progress, the log, a `Command` button for a dry
run, links to logs, reports, and settings, a terminal expander, and a manual
command line with history.

Every operation writes `batch_report.md` and `.json`. Audio adds
`audio_report.md` and `.json`: the source stream, input parameters, processing
mode, loudness, output path.

The workbench, the path cache, the terminal, and the reports are covered in
`tools\WORKSPACE_REPORTS_TERMINAL_RU.md`.

## Rules for Safe Work

* A new operation: `Command` first, then the run.
* A large folder: the first file first.
* Do not enable overwriting unless you are sure of the target folder.
* A hardware path: check the hardware capabilities first.
* A colour table: look at which `.cube` is selected.
* A download batch: check the list of links first.
* Cleanup: look carefully at the selected folders.
* Never run two operations at once in one window.

## Checks After Changes

```cmd
runtime\python.exe -m py_compile system_core\ui_nicegui\app.py system_core\services\media_service.py Scripts\Common\script_runner.py
runtime\python.exe system_core\ui_nicegui\app.py --smoke
```

What is actually run before a release: the [checklist](SMOKE_TEST_RU.md)
(Russian).

---

## Technical Reference

### Running

```bat
launcher_gui.cmd
```

If the environment is not built:

```bat
builder_main.cmd
```

The window opens at `http://127.0.0.1:8080/`.

### Tooltips

They appear after 1500 ms, hide in 100 ms, background `RGB(23, 33, 43)`. If a
field is unclear, hold the cursor on it for about a second and a half.

Tooltips cover audio modes, stream selection, loudness, the resampler, hardware
encoding, remux pairs, colour tables, and operations with side effects. File
extensions and obvious buttons such as "Back" and "Run" are not duplicated by
them.

For the outermost buttons in a group the tooltip aligns to the edge so long text
is not clipped.

### Workbench Naming

One shared vocabulary across all Audion projects. In Russian: **Источник**,
**Добавить файл…**, **Назначение**, **Сбросить**, **Удалить**, **Список**. The
words `Destination`, `Clear`, «Цель», and «Очистить» are not used for these
controls.
