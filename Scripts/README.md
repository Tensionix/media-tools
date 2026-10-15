# Scripts Layer

`Scripts\*.cmd` keeps the old CLI preset names stable for launchers and direct use.

Each preset is a one-line door:

```bat
call "%~dp0Common\run-profile.cmd" "%~n0" %*
```

`Scripts\Common\run-profile.cmd` hands the name and the arguments to the console command:

```bat
media_cli.cmd wrapper <name> [arguments]
```

What every wrapper runs - the operation of the manifest, the values it sets, what it is for - lives in:

```text
config\wrappers.yaml
```

The work is the engine's, the same a button of the window does: one engine for the window, the console command and the wrappers. `tests\test_wrappers.py` holds every wrapper to its recorded FFmpeg and yt-dlp commands and names every deliberate difference with its reason.

Arguments: a download wrapper takes links (none - the links of `input\urls.txt`); `yt-clip-sections` takes a section first, `*00:01:00-00:02:00`, then the link; `--dry-run` says what would run and runs nothing.

## Override Contract

The wrappers read these environment variables and hand them to the fields of their operation:

- `AUDION_SOURCE` - input folder, default `input\`.
- `AUDION_OUTPUT` - output folder, default `output\`.
- `AUDION_DOWNLOAD` - yt-dlp output folder, default `output\Download\`.
- `AUDION_INPUT_FORMATS` - comma-separated input extensions.
- `AUDION_AUDIO_BITRATE` - `192k`, `256k`, `320k` or `384k`. `384k` applies to AAC only; MP3 is capped at the LAME ceiling of `320k`.
- `AUDION_MP3_LAME_PRESET` - `v0` (default), `insane` or `bitrate`. Same scale as the `MP3 / LAME` field of the window: `v0` encodes `-q:a 0`, `insane` encodes `-b:a 320k`, and `bitrate` uses `AUDION_AUDIO_BITRATE`.
- `AUDION_AUDIO_SAMPLE_RATE` - `source` (default), `44100`, `48000`, `88200`, `96000`, `176400` or `192000`. Matches the `Sample rate` field of the window: `source` keeps the input rate and any other value resamples through SoX/libsoxr, never a plain `-ar`. Copy and no-audio modes are never resampled.
- `AUDION_AUDIO_COPY_CONTAINER` - the container of a sound taken out as it is.
- `AUDION_CRF` - CPU encoder CRF, default profile-dependent or `14`.
- `AUDION_CQ` - hardware encoder quality value, default `14`.
- `AUDION_CPU_ENCODER_PRESET` (or `AUDION_ENCODER_PRESET`) - CPU encoder preset.
- `AUDION_NVENC_PRESET`, `AUDION_QSV_ENCODER_PRESET`, `AUDION_AMF_QUALITY` - hardware encoder scales.
- `AUDION_PIX_FMT` - pixel format.
- `AUDION_AV1_PRESET` - SVT-AV1 speed/quality preset for AV1 profiles on CPU. Hardware AV1 uses the NVENC/QSV/AMF scales instead.
- `AUDION_ENCODE_BACKEND` - `cpu`, `cuda`, `qsv` or `amd`. Aliases accepted by the window are accepted here too: `auto`/`software` mean `cpu`, `nvenc`/`nvidia`/`cuda/nvenc` mean `cuda`, `quicksync`/`intel` mean `qsv`, `amf`/`amd/amf` mean `amd`.
- `AUDION_DECODE_BACKEND` - `auto`, `cuda`, `qsv`, `amd` or `dav1d`. Aliases: `cpu`/`none`/`software` mean `auto`, `nvenc`/`nvidia` mean `cuda`, `quicksync`/`intel` mean `qsv`, `d3d11va`/`dxva2`/`amd/d3d11va` mean `amd`.
- `AUDION_FPS_OUTPUT_PROFILE`, `AUDION_FPS_AUDIO_PCM_DEPTH`, `AUDION_FPS_AUDIO_OVERSAMPLE` - the output of a frame-rate wrapper, as `cli\launcher-select-fps-speed.cmd` chooses it.
- `AUDION_TRIM_FILE`, `AUDION_TRIM_START`, `AUDION_TRIM_END` - the file and the points of a trim wrapper.
- `AUDION_DRY_RUN` - print commands without executing.
- `AUDION_OVERWRITE` - `1`/`0`.
- `AUDION_LIMIT_FIRST_FILE` - process only the first matching file.
- `AUDION_LUT_FILE` - explicit `.cube` LUT path.
- `AUDION_TARGET_CODECS` - comma-separated color output targets.
- `AUDION_YTDLP_JS_RUNTIMES` - explicit yt-dlp `--js-runtimes` value when portable Deno is not used.
- `AUDION_YTDLP_COOKIES_BROWSER` - browser name/profile for yt-dlp `--cookies-from-browser`.
- `AUDION_YTDLP_COOKIES` - cookies file path for yt-dlp.
- `AUDION_YTDLP_SPONSORBLOCK` - SponsorBlock categories to remove for video downloads.

The full table, field by field: `WRAPPER_ENVIRONMENT` in `system_core\cli.py`.

Example:

```bat
set AUDION_SOURCE=E:\Media\Footage
set AUDION_OUTPUT=E:\Media\Out
set AUDION_CRF=14
set AUDION_AUDIO_BITRATE=384k
Scripts\ff-x264-crf14.cmd
```

The wrappers intentionally stay tiny: old launchers keep working, while `config\wrappers.yaml` keeps the preset map readable and the engine keeps path resolution, portable tools and overrides consistent.
