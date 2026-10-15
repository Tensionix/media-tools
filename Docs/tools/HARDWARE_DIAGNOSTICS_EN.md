# Hardware And Diagnostics

[Русский](HARDWARE_DIAGNOSTICS_RU.md)

## Why Diagnostics Are Needed

The media pipeline depends not only on the Python code but also on:

- the FFmpeg build;
- ffprobe;
- yt-dlp;
- Deno;
- the GPU drivers;
- the availability of CUDA/NVENC, QuickSync, AMF/D3D11VA;
- the presence of SVT-AV1 and dav1d;
- a valid manifest/profile map.

Diagnostics separate “the profile is not supported on this machine” from “the program is broken”. All checks are in the
SERVICE menu of the window header and in the console command (`media_cli.cmd run --operation selftest` and so on).

## Inventory

Counts the files of the working folders:

- the Source (`input`);
- the Target (`output`);
- `LUTs`.

This is a quick check: does the program see the expected folders, and how many files are in them.

## Selftest

Checks:

- FFmpeg;
- ffprobe;
- yt-dlp;
- Deno.

If Selftest fails, first repair the portable tools through the builder/installers.

## Profile Doctor

Compares:

- the manifest of the operations (`config\tool_manifest.yaml`);
- the 95 wrappers `Scripts\*.cmd`;
- the profile catalog `config\script_profiles.yaml`; the COLOR presets refer to it (`script_preset`);
- the bindings of the services.

It is needed after presets are added or renamed. If the window shows a profile and the wrapper does not know it,
Profile Doctor must catch this.

## Hardware Capabilities

Checks the availability of the backends:

- CPU H.264/HEVC;
- CUDA/NVENC - H.264, HEVC and AV1;
- Intel QuickSync/QSV - H.264, HEVC and AV1;
- AMD AMF/D3D11VA - H.264, HEVC and AV1;
- SVT-AV1;
- dav1d AV1 decode.

If there is no hardware or driver, the result must be `MISS`, not a project failure. This also covers the case when a GPU is present but a given codec is not available to it: old Intel graphics answer `av1_qsv` with the line `Current codec type is unsupported`, and this is `MISS`.

Decoding is checked by separate smoke tests: `CUDA decode`, `QuickSync decode`, `AMD/D3D11VA decode` and `dav1d AV1 decode`. This is essential: decode and encode are different stacks, and on a machine without NVENC or AMF the hardware decode can work fully. The guard for `Decoder` looks only at the matching decode test.

If the cache was made by an old version and has no decode lines, the preflight gives `WARN` and suggests running `Hardware capabilities` again, instead of blocking the work.

The window and the preflight use the hardware check cache to stop an unavailable hardware path before a long encode starts. SETTINGS → SYSTEM shows which FFmpeg encoders passed the check.

## Preset Test Matrix

Runs a set of presets on a short fixture file. The point is to:

- check how the commands are built;
- check the availability of the codecs;
- tell `MISS` from `FAIL`;
- not spend time on long real source files.

The categories usually cover:

- CPU encode;
- hardware encode;
- hardware backend;
- audio;
- remux;
- FPS;
- LUT;
- storage;
- delivery.

The `hardware backend` category exists on its own because all presets of the manifest are built for the CPU: without it the NVENC/QSV/AMF branches of the command builders would never run. It runs the matrix `backend × target` (cuda/qsv/amd × H.264/HEVC/AV1) straight through the working command builder. On a machine without the matching hardware this is `MISS`.

## Tool Installation

The SERVICE menu has the installers:

- Install 7-Zip;
- Install FFmpeg;
- Install yt-dlp (together with Deno);
- Install mpv - the player of the CUT section.

Before downloading, each one names the files, the source and the size. Versions and updates are in SETTINGS → COMPONENTS.

For a full first build this is still convenient:

```cmd
builder_main.cmd
```

But an installer from SERVICE is convenient for a targeted repair of a damaged tool.

## How To Diagnose A Problem

### FFmpeg Not Found

1. Selftest.
2. Check `Tools\ffmpeg\bin\ffmpeg.exe`.
3. Reinstall FFmpeg through builder/install.
4. Run Selftest again.

### Hardware Profile Blocked

1. Run Hardware capabilities.
2. Check the driver/GPU.
3. If the backend is `MISS`, choose CPU or another hardware backend.
4. Do not count `MISS` as a project error.

### LUT Profile Fails

1. Check `LUTs\`.
2. Choose the LUT explicitly.
3. Press `COMMAND`.
4. Check the escaping of the path in the dry run.
5. Run with `Test on first file`.

### YouTube Broke

1. Selftest yt-dlp.
2. Update yt-dlp.
3. Try Safe Safari.
4. Turn on IPv4/retries.
5. Check the cookies if a sign-in is needed.

## Minimal Health Check

After the environment is repaired:

```cmd
install\verify_portable_env.cmd
```

In the window, in the SERVICE menu:

1. Selftest.
2. Hardware capabilities.
3. Profile Doctor.
4. Preset Test Matrix.

If these items are green or give the expected `MISS`, you can move on to the real material.
