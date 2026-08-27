# Audion Media Tools - install notes

## Main build paths

### Recommended
Run:

```bat
builder_main.cmd
```

or directly:

```bat
install\Build_Portable_Env_Build.cmd
```

This is the main CMD build script.

### Optional PowerShell route
Run:

```bat
install\Build_Portable_Env.cmd
```

This is a thin wrapper for the same-name `Build_Portable_Env.ps1`.

The wrapper looks for PowerShell in:

1. `system_core\powershell\pwsh.exe`
2. `pwsh.exe` in `PATH`
3. `powershell.exe` in `PATH`

### Optional portable PowerShell installer

Portable PowerShell is not required by the Python project core. It is useful for fully portable GUI picker dialogs and build helper scripts.

From `builder_main.cmd`, choose the fixed numeric entry:

```text
[04] POWERSHELL
```

or run directly:

```bat
install\Install-Portable-PowerShell.cmd
```

The installer downloads the latest Windows x64 PowerShell ZIP from GitHub and extracts it to:

```text
system_core\powershell\
```

GUI picker dialogs prefer this portable `pwsh.exe` when it exists, then fall back to `pwsh.exe` from `PATH`, then to built-in `powershell.exe`.

### Optional portable media tool installers

The project can install the external media tools used by the GUI into the portable `Tools\` tree.

From `builder_main.cmd`, choose the fixed numeric entry:

```text
[10] 7-ZIP
[11] FFMPEG BTBN
[12] FFMPEG GYAN
[13] YT-DLP
```

or run directly:

```bat
install\Install-Portable-7Zip.cmd
install\Install-Portable-FFmpeg-BtbN.cmd
install\Install-Portable-FFmpeg-Gyan.cmd
install\Install-Portable-yt-dlp.cmd
```

Each installer supports `/NOPAUSE`. They write tools to:

```text
Tools\ffmpeg\bin\
Tools\yt-dlp\bin\
Tools\7zip\bin\
Tools\deno\
```

The media tool installers always replace their target payloads cleanly:

- FFmpeg BtbN uses `install\Ensure-7zip.ps1` to bootstrap `system_core\7zip`, downloads the newest BtbN win64 `gpl` FFmpeg release-branch build, and never falls back to master/nightly. It resets `Tools\ffmpeg\` and then recreates `Tools\ffmpeg\bin\`. Use `/V gpl-shared` when the shared build is explicitly needed.
- FFmpeg Gyan requires 7-Zip, downloads Gyan FULL builds (`ffmpeg-release-full.7z`, then `ffmpeg-release-full-shared.7z` fallback), resets `Tools\ffmpeg\` and then recreates `Tools\ffmpeg\bin\`.
- yt-dlp resets `Tools\yt-dlp\` and then recreates `Tools\yt-dlp\bin\`; it also installs Deno into `Tools\deno\` for yt-dlp external JavaScript runtime support.
- 7-Zip resets `Tools\7zip\` and then recreates `Tools\7zip\bin\`.

This is intentional. These directories are reproducible tool payloads, not user data. Updating with a clean target prevents stale EXE/DLL/docs or legacy compatibility files from surviving after a tool upgrade.

Downloads are cached in `install\download\`.

`install\Install-Portable-PowerShell.cmd` applies the same replacement rule to `system_core\powershell\`. `install\launcher-tools-update_fzf.cmd` replaces `system_core\fzf.exe`.

For destructive source/release cleanup only, run root-level `cleanup_project.cmd` manually. It may clear portable payloads such as `runtime\`, `wheelhouse\`, tool folders, portable PowerShell/FZF, and generated logs/reports/workspace/release/output folders; it is not the install-cache cleanup path.

## Portable flow

1. Create folders
2. Resolve and download latest Python Embedded `3.12.x` ZIP
3. Extract to `runtime\`
4. Enable `import site` in `python3<minor>._pth`
5. Download `get-pip.py`
6. Build local `wheelhouse\`
7. Install packages into portable runtime
8. Verify with `system_core\doctor.py`
9. Optionally create a release ZIP in `release\`

## Offline flow

If `runtime\` and `wheelhouse\` are already populated, run:

```bat
install\install_portable_offline.cmd
```

Then verify with:

```bat
install\verify_portable_env.cmd
```

For GUI projects, see:

```text
install\README_GUI_PORTING.md
```

## Release licensing

Third-party notices and license files are generated from the finalized staged release contents during `make_release_archive.cmd`. They are no longer generated during routine environment build/install steps.

---

## Current Builder Order And Dependency Hygiene

`builder_main.cmd` uses fixed numeric entries. Keep the bootstrap order stable: `[01] PYTHON ENV CMD`, `[02] PYTHON ENV PS`, `[03] FZF`, `[04] POWERSHELL`, then project-specific payload installers and one-time maintenance/diagnostic actions below.

Current builder install/maintenance map:

```text
[01] PYTHON ENV CMD
[02] PYTHON ENV PS
[03] FZF
[04] POWERSHELL
[09] PORTABLE OFFLINE
[10] 7-ZIP
[11] FFMPEG BTBN
[12] FFMPEG GYAN
[13] YT-DLP
[70] CLEAN INSTALL CACHE
[71] VERIFY / DOCTOR
[72] CMD ENCODING CHECK
[74] COLLECT LICENSES
[75] PRUNE LICENSES
[76] DEDUP LICENSES
[77] MAKE RELEASE ARCHIVE
[90] PROJECT LAUNCHER
[95] OPEN install
[96] OPEN runtime
[97] OPEN wheelhouse
[98] OPEN licenses
[99] OPEN release
[00] EXIT
```

Project-specific payload entries before diagnostics:

[10] 7-ZIP, [11] FFMPEG BTBN, [12] FFMPEG GYAN, [13] YT-DLP

Dependency hygiene rules:

- Python Embedded tracks the latest `3.12.x`; do not pin a concrete patch version in docs or scripts.
- Use the active embedded Python `_pth` file for path edits; do not hard-code a concrete filename.
- Bootstrap installs must include `setuptools`, `wheel`, and `packaging` before building or installing project wheels.
- `runtime\`, `wheelhouse\`, `system_core\powershell\`, `system_core\fzf.exe`, browser payloads, and external tool folders are reproducible payloads. Install/update scripts may cleanly replace only their owned targets.
- GPL or unknown-license external tools are explicit install/update payloads. Prefer GUI install buttons where the project exposes them, or fixed builder entries otherwise; do not silently bundle them as default source contents.
- `install\Clean-Install-Cache.cmd` / `.ps1` is the general install-cache cleanup. It removes transient `install\download\` artifacts (preserving `.gitkeep`, `get-pip.py`, and `7z*-extra.7z`), exact installer staging dirs `system_core\_pwsh_tmp` / `system_core\_fzf_tmp` / `system_core\_ffmpeg_btbn_tmp` / `system_core\_deno_tmp`, and Python bytecode caches outside runtime, wheelhouse, and user-data zones.
- `cleanup_project.cmd` is a separate source/release cleanup tool. It can remove runtime payloads and user-output zones after explicit confirmation; do not describe it as the general install-cache cleaner and do not wire it into install flow.

Project-specific notes:

- Media Tools exposes GUI install buttons for 7-Zip, FFmpeg, and yt-dlp. Builder exposes both FFmpeg providers explicitly: BtbN above Gyan. Installers call the same local wrappers with `/NOPAUSE` and clean-replace only their owned `Tools\` payload folders.



