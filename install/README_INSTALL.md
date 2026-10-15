# Audion Media Tools - install notes

## The builder

```bat
builder_main.cmd
```

A menu on FZF with fixed numbers:

```text
[01] PYTHON ENV CMD
[02] PYTHON ENV PS
[03] FZF
[09] PORTABLE OFFLINE
[10] 7-ZIP
[11] FFMPEG BTBN AUTO-FALLBACK
[12] FFMPEG GYAN
[13] YT-DLP
[14] MPV
[70] CLEAN INSTALL CACHE
[71] VERIFY / DOCTOR
[72] CMD ENCODING CHECK
[90] PROJECT LAUNCHER
[95] OPEN install
[96] OPEN runtime
[97] OPEN wheelhouse
[98] OPEN licenses
[00] EXIT
```

## The Python environment

`[01]` runs `install\Build_Portable_Env_Build.cmd`, the main build; `[02]` runs `install\Build_Portable_Env.cmd`, a thin
wrapper of `Build_Portable_Env.ps1` in the PowerShell 7 of the program (`App\AudionPs.exe`; `pwsh.exe` from `PATH` when
the window is not built yet).

1. Create the folders (`install\init_folders.cmd`).
2. Resolve and download the latest Python Embedded `3.12.x` ZIP.
3. Extract it to `runtime\`; enable `import site` in the active `python3<minor>._pth`.
4. Download `get-pip.py`, build the local `wheelhouse\` and install the packages: PyYAML, pytest, pip-tools
   (`install\requirements_full.in`).
5. Verify with `install\verify_portable_env.cmd`.

With `runtime\` and `wheelhouse\` already filled, `[09]` (`install\install_portable_offline.cmd`) installs without the
network.

## The media tools

`[10]`-`[14]`, or directly:

```bat
install\Install-Portable-7Zip.cmd
install\Install-Portable-FFmpeg-BtbN.cmd
install\Install-Portable-FFmpeg-Gyan.cmd
install\Install-Portable-yt-dlp.cmd
install\Install-Portable-mpv.cmd
```

The same installers stand in the SERVICE menu of the window and behind `media_cli.cmd run --operation install_ffmpeg`
(`install_7zip`, `install_ytdlp`, `install_mpv`); SETTINGS of the window shows their versions with UPDATE or INSTALL.
Before downloading, each names its files, their source and size - `media_cli.cmd plan --operation install_ffmpeg` says
the same without downloading. Every installer takes `/NOPAUSE`.

They write to:

```text
Tools\ffmpeg\bin\
Tools\yt-dlp\bin\
Tools\deno\
Tools\mpv\
Tools\7zip\bin\
```

and always replace their payload cleanly:

- FFmpeg Gyan requires 7-Zip and downloads the Gyan FULL build (`ffmpeg-release-full.7z`, then
  `ffmpeg-release-full-shared.7z`). Which version - by the NVIDIA driver: `install\FFmpeg-Driver-Fallback-Policy.md`.
- FFmpeg BtbN bootstraps 7-Zip through `install\Ensure-7zip.ps1` and downloads the newest BtbN win64 `gpl`
  release-branch build, never master or nightly; when BtbN changes its layout or the download fails, it falls back
  to Gyan. `/V gpl-shared` asks for the shared build.
- yt-dlp also installs Deno into `Tools\deno\`: without it yt-dlp does not take the formats of YouTube.
- mpv is the player of CUT; its key bindings are `config\mpv\input.conf`.
- Every installer resets its `Tools\` folder and creates it anew: no stale EXE, DLL or document survives an upgrade.
  These folders are reproducible payloads, not user data. The GPL builds keep their sources beside them.

Downloads are cached in `install\download\`.

## Cleaning

- `[70]` `install\Clean-Install-Cache.cmd` - the install cache: the transient files of `install\download\`, the staging
  folders of the installers, Python bytecode outside `runtime\` and `wheelhouse\`, and what a build of the window leaves
  (`Source\bin`, `Source\obj`, `Source\Ps\bin`, `Source\Ps\obj`).
- `cleanup_project.cmd` in the root is a separate tool for a lean source state: it clears `input`, `output` (all but
  `output\Download`), logs, reports, the runtime, the wheelhouse, the tool payloads, the state of the window and the
  cookies, after a confirmation. It is not part of any install flow. A folder to clear that is itself a link (a
  junction, a symbolic link) is refused - what lies there is not the project's; a link inside a folder being cleared is
  taken away as a link, never walked through.

## Rules

- Python Embedded tracks the latest `3.12.x`; no concrete patch version in docs or scripts.
- The bootstrap installs `setuptools`, `wheel` and `packaging` before building or installing the wheels.
- `runtime\`, `wheelhouse\` and the `Tools\` folders are reproducible payloads; an installer replaces only its own.
- GPL and other external tools are explicit install payloads, never bundled silently into the source.
- Licences of a release are collected by Audion Build Licenses from the staged release, not during a build.
