# Scripts Layer

`Scripts\*.cmd` keeps the old CLI preset names stable for launchers and direct use.

AV1 presets (`ff-av1-crf14`, `ff-av1-fast-crf14`) were added later than the original professional-delivery set; they mirror the GUI AV1 target and follow the same encoder backend selection.

Each preset is now a thin wrapper around:

```bat
Scripts\Common\run-profile.cmd
```

The declarative profile catalog lives in:

```text
config\script_profiles.yaml
```

The portable command engine lives in:

```text
Scripts\Common\script_runner.py
```

Encoder/decoder backend names, aliases, preset scales and the target-to-encoder map are shared with the GUI through:

```text
system_core\core\encoder_backends.py
```

Audio sample rate handling is shared through:

```text
system_core\core\audio_contract.py
```

## Override Contract

The GUI and CLI can override script behavior through environment variables:

- `AUDION_SOURCE` - input folder, default `Source\`.
- `AUDION_OUTPUT` - output folder, default `Transcoded\`.
- `AUDION_DOWNLOAD` - yt-dlp output folder, default `Download\`.
- `AUDION_INPUT_FORMATS` - comma-separated input extensions.
- `AUDION_AUDIO_BITRATE` - `192k`, `256k`, `320k` or `384k`. `384k` applies to AAC only; MP3 is capped at the LAME ceiling of `320k`.
- `AUDION_MP3_LAME_PRESET` - `v0` (default), `insane` or `bitrate`. Same scale as the GUI `MP3 / LAME` field: `v0` encodes `-q:a 0`, `insane` encodes `-b:a 320k`, and `bitrate` uses `AUDION_AUDIO_BITRATE`.
- `AUDION_AUDIO_SAMPLE_RATE` - `source` (default), `44100`, `48000`, `88200`, `96000`, `176400` or `192000`. Matches the GUI `Sample rate` field: `source` keeps the input rate and any other value resamples through SoX/libsoxr, never a plain `-ar`. Copy and no-audio modes are never resampled.
- `AUDION_CRF` - CPU encoder CRF, default profile-dependent or `14`.
- `AUDION_CQ` - hardware encoder quality value, default `14`.
- `AUDION_ENCODER_PRESET` - encoder preset.
- `AUDION_PIX_FMT` - pixel format.
- `AUDION_AV1_PRESET` - SVT-AV1 speed/quality preset for AV1 profiles on CPU. Hardware AV1 uses the NVENC/QSV/AMF scales instead.
- `AUDION_ENCODE_BACKEND` - `cpu`, `cuda`, `qsv` or `amd`. Aliases accepted by the GUI are accepted here too: `auto`/`software` mean `cpu`, `nvenc`/`nvidia`/`cuda/nvenc` mean `cuda`, `quicksync`/`intel` mean `qsv`, `amf`/`amd/amf` mean `amd`.
- `AUDION_DECODE_BACKEND` - `auto`, `cuda`, `qsv`, `amd` or `dav1d`. Aliases: `cpu`/`none`/`software` mean `auto`, `nvenc`/`nvidia` mean `cuda`, `quicksync`/`intel` mean `qsv`, `d3d11va`/`dxva2`/`amd/d3d11va` mean `amd`.
- `AUDION_DRY_RUN` - print commands without executing.
- `AUDION_OVERWRITE` - `1`/`0`, default `1`.
- `AUDION_LIMIT_FIRST_FILE` - process only the first matching file.
- `AUDION_RECURSIVE` - `1`/`0`, default `1`; output keeps the same relative subfolder structure under `AUDION_OUTPUT`.
- `AUDION_LUT_FILE` - explicit `.cube` LUT path.
- `AUDION_TARGET_CODECS` - comma-separated color output targets.
- `AUDION_YTDLP_JS_RUNTIMES` - explicit yt-dlp `--js-runtimes` value when portable Deno is not used.
- `AUDION_YTDLP_COOKIES_BROWSER` - browser name/profile for yt-dlp `--cookies-from-browser`.
- `AUDION_YTDLP_COOKIES` - cookies file path for yt-dlp.
- `AUDION_YTDLP_SPONSORBLOCK` - SponsorBlock categories to remove for video downloads.

Example:

```bat
set AUDION_SOURCE=E:\Media\Source
set AUDION_OUTPUT=E:\Media\Out
set AUDION_CRF=14
set AUDION_AUDIO_BITRATE=384k
Scripts\ff-x264-crf14.cmd
```

The wrappers intentionally stay tiny: old launchers keep working, while `config\script_profiles.yaml` keeps the preset map readable and one runner keeps path resolution, portable tools and GUI overrides consistent.
