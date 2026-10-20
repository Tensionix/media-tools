# Audion Media Tools - Operations

[Русский](OPERATIONS_RU.md) · [Wrappers of Scripts](SCRIPTS_EN.md)

**Contents**

- [AUDIO - Extract, put back, convert](#audio---extract-put-back-convert)
- [ENCODE - Archive, editing, storage, delivery, RAW](#encode---archive-editing-storage-delivery-raw)
- [PACKAGE - Another container, no re-encoding](#package---another-container-no-re-encoding)
- [CUT - Keep, cut out, split](#cut---keep-cut-out-split)
- [FRAME RATE - Varispeed and conform to 23.976](#frame-rate---varispeed-and-conform-to-23976)
- [COLOR - LUT, gamma before it, HDR to SDR](#color---lut-gamma-before-it-hdr-to-sdr)
- [DOWNLOAD - A video or its sound by a link](#download---a-video-or-its-sound-by-a-link)
- [SOURCE INFO](#source-info)
- [SERVICE: checks and installers](#service-checks-and-installers)
- [Buttons beside a field](#buttons-beside-a-field)
- [What the window does itself](#what-the-window-does-itself)

> Made from the data of the program by `media_cli.cmd map --docs`: the manifest of the operations (`config\tool_manifest.yaml`), the layout of the window (`config\window_layout.yaml`) and the table of the wrappers (`config\wrappers.yaml`). It is not edited by hand: a text is changed there and the command is run again.

*rare* - a field of the block «Additional», at the end of the form.

## AUDIO - Extract, put back, convert

### Run audio - `audio_run`

Process audio with the selected preset.

Call: `media_cli.cmd run --operation audio_run`

Modes of the ribbon: EXTRACT `audio_workflow=extract`, SOUND IN VIDEO `audio_workflow=in_video`, CONVERT `audio_workflow=audio_files`.

Wrappers: `audio-downmix-51-to-20`, `audio-extract-audio-copy`, `audio-extract-audio-wav`, `audio-extract-audio-wav-32`, `audio-lufs-14`, `audio-lufs-23`, `audio-resample-to-44100`, `audio-resample-to-44100-32f`, `audio-resample-to-44100-32f_sync`, `audio-resample-to-44100_sync`, `audio-resample-to-48000`, `audio-resample-to-48000-32f`, `audio-resample-to-48000-32f_sync`, `audio-resample-to-48000_sync`, `audio-to-flac`, `audio-to-flac-48k`, `audio-to-flac-96k`, `audio-to-m4a-256`, `audio-to-m4a-384`, `ff-extract-audio`.

**Presets** - Audio mode `audio_profile`

| Preset | What it is | What it sets |
|---|---|---|
| `copy_auto` Copy | Copy the selected audio stream without re-encoding; Auto chooses M4A/MKA/native codec file from codec and channels. | audio_stream_mode=first, audio_format=copy, audio_sample_rate=source, audio_bit_depth=source, audio_bitrate=384k, audio_resampler=auto, audio_copy_container=auto, audio_video_container=source, audio_channel_mode=keep, audio_lufs_mode=off, audio_lufs=off |
| `remux_container` Remux | Copy audio into a chosen audio container without re-encoding; useful for AAC to M4A or multichannel to MKA. | audio_stream_mode=first, audio_format=copy, audio_sample_rate=source, audio_bit_depth=source, audio_bitrate=384k, audio_resampler=auto, audio_copy_container=mka, audio_video_container=source, audio_channel_mode=keep, audio_lufs_mode=off, audio_lufs=off |
| `wav_24_48` WAV 24/48 | Editing-safe PCM WAV. | audio_stream_mode=first, audio_format=wav, audio_sample_rate=48000, audio_bit_depth=24, audio_bitrate=384k, audio_resampler=soxr, audio_video_container=mov, audio_channel_mode=keep, audio_lufs_mode=off, audio_lufs=off |
| `wav_32f_48` WAV 32f/48 | 32-bit float WAV for restoration or further processing. | audio_stream_mode=first, audio_format=wav, audio_sample_rate=48000, audio_bit_depth=32f, audio_bitrate=384k, audio_resampler=soxr, audio_video_container=mov, audio_channel_mode=keep, audio_lufs_mode=off, audio_lufs=off |
| `flac_24_48` FLAC 24/48 | Lossless archive audio. | audio_stream_mode=first, audio_format=flac, audio_sample_rate=48000, audio_bit_depth=24, audio_bitrate=384k, audio_resampler=soxr, audio_video_container=mkv, audio_channel_mode=keep, audio_lufs_mode=off, audio_lufs=off |
| `alac_m4a` ALAC M4A | Apple Lossless inside M4A for lossless delivery without WAV size. | audio_stream_mode=first, audio_format=alac, audio_sample_rate=source, audio_bit_depth=source, audio_bitrate=384k, audio_resampler=auto, audio_video_container=source, audio_channel_mode=keep, audio_lufs_mode=off, audio_lufs=off |
| `m4a384` M4A 384k | AAC 384k for review or delivery. | audio_stream_mode=first, audio_format=m4a, audio_sample_rate=source, audio_bit_depth=source, audio_bitrate=384k, audio_resampler=soxr, audio_video_container=source, audio_channel_mode=keep, audio_lufs_mode=off, audio_lufs=off |
| `m4a256` M4A 256k | Compact AAC 256k for upload and portable listening. | audio_stream_mode=first, audio_format=m4a, audio_sample_rate=source, audio_bit_depth=source, audio_bitrate=256k, audio_resampler=soxr, audio_video_container=source, audio_channel_mode=keep, audio_lufs_mode=off, audio_lufs=off |
| `video_pcm24_48_soxr` Video PCM | Keep video stream untouched, resample audio inside MOV. | audio_workflow=in_video, audio_stream_mode=first, audio_format=wav, audio_sample_rate=48000, audio_bit_depth=24, audio_bitrate=384k, audio_resampler=soxr, audio_video_container=mov, audio_channel_mode=keep, audio_lufs_mode=off, audio_lufs=off |
| `video_aac384_48_soxr` Video AAC | Keep video stream untouched, transcode audio in-container. | audio_workflow=in_video, audio_stream_mode=first, audio_format=m4a, audio_sample_rate=48000, audio_bit_depth=source, audio_bitrate=384k, audio_resampler=soxr, audio_video_container=source, audio_channel_mode=keep, audio_lufs_mode=off, audio_lufs=off |
| `mp3_v0` MP3 V0 | Highest quality LAME VBR profile, around 245 kbps. | audio_stream_mode=first, audio_format=mp3, audio_sample_rate=48000, audio_bit_depth=source, audio_bitrate=320k, audio_resampler=soxr, audio_video_container=source, mp3_lame_preset=v0, audio_channel_mode=keep, audio_lufs_mode=off, audio_lufs=off |
| `mp3_insane` MP3 320 | LAME CBR 320 kbps. | audio_stream_mode=first, audio_format=mp3, audio_sample_rate=48000, audio_bit_depth=source, audio_bitrate=320k, audio_resampler=soxr, audio_video_container=source, mp3_lame_preset=insane, audio_channel_mode=keep, audio_lufs_mode=off, audio_lufs=off |
| `opus192` Opus 192k | Modern compact speech/music delivery. | audio_stream_mode=first, audio_format=opus, audio_sample_rate=48000, audio_bit_depth=source, audio_bitrate=192k, audio_resampler=soxr, audio_video_container=source, audio_channel_mode=keep, audio_lufs_mode=off, audio_lufs=off |
| `lufs14_m4a` LUFS -14 M4A | Two-pass loudnorm to a common streaming loudness target. | audio_stream_mode=first, audio_format=m4a, audio_sample_rate=48000, audio_bit_depth=source, audio_bitrate=384k, audio_resampler=soxr, audio_video_container=source, audio_channel_mode=keep, audio_lufs_mode=two_pass, audio_lufs=-14 |
| `downmix_wav` Stereo WAV | Downmix the first audio stream to stereo. | audio_stream_mode=first, audio_format=wav, audio_sample_rate=48000, audio_bit_depth=24, audio_bitrate=384k, audio_resampler=soxr, audio_video_container=mov, audio_channel_mode=stereo, audio_lufs_mode=off, audio_lufs=off |
| `matrix51_wav` Matrix 5.1 | Stereo-compatible DPLII matrix downmix. | audio_stream_mode=first, audio_format=wav, audio_sample_rate=48000, audio_bit_depth=24, audio_bitrate=384k, audio_resampler=soxr, audio_video_container=mov, audio_channel_mode=stereo, audio_lufs_mode=off, audio_lufs=off, matrix_51=true |
| `copy_all_audio` Copy all | Extract every audio stream without re-encoding. | audio_stream_mode=all, audio_format=copy, audio_sample_rate=source, audio_bit_depth=source, audio_bitrate=384k, audio_resampler=auto, audio_copy_container=auto, audio_video_container=source, audio_channel_mode=keep, audio_lufs_mode=off, audio_lufs=off |
| `lufs_report` LUFS report | Analyze loudness and write report without encoding. | audio_stream_mode=first, audio_format=m4a, audio_sample_rate=source, audio_bit_depth=source, audio_bitrate=384k, audio_resampler=auto, audio_video_container=source, audio_channel_mode=keep, audio_lufs_mode=report, audio_lufs=-23 |

**Fields**

| Field | Kind | Default | Choices | When | What it is |
|---|---|---|---|---|---|
| Source file filter `input_formats` | ticks | - | `wav` WAV; `w64` W64; `flac` FLAC; `m4a` M4A; `m4b` M4B; `mp3` MP3; `aac` AAC; `ac3` AC3; `eac3` E-AC3; `dts` DTS; `opus` Opus; `oga` OGA; `ogg` OGG; `aif` AIF; `aiff` AIFF; `caf` CAF; `au` AU; `snd` SND; `mka` MKA; `ape` APE; `wv` WV; `tak` TAK; `tta` TTA; `mpc` MPC; `amr` AMR; `awb` AWB; `spx` SPX; `dsf` DSF; `dff` DFF; `mp4` MP4; `m4v` M4V; `mov` MOV; `mkv` MKV; `mxf` MXF; `avi` AVI; `webm` WEBM; `mpg` MPG; `mpeg` MPEG; `mts` MTS; `m2ts` M2TS; `ts` TS; `3gp` 3GP | - | The Source is scanned recursively; the Target keeps the same subfolder structure. |
| Format `audio_format` | choice | `wav` | `copy` Copy; `wav` WAV; `flac` FLAC; `alac` ALAC; `m4a` M4A / AAC; `mp3` MP3; `opus` Opus | - | Output audio codec/container. Copy preserves the selected audio stream without re-encoding; ALAC writes Apple Lossless into M4A. |
| Copy container `audio_copy_container` | choice | `auto` | `auto` Auto; `m4a` M4A; `mka` MKA; `elementary` Codec file | shown when all of (audio_format is copy; audio_workflow is one of extract, audio_files) | Container policy for extracted Copy files: Auto chooses by codec and channel count; MKA/M4A/codec file force a specific wrapping policy. |
| Sample rate `audio_sample_rate` | choice | `48000` | `source` COPY; `44100` 44.1 kHz; `48000` 48 kHz; `88200` 88.2 kHz; `96000` 96 kHz; `176400` 176.4 kHz; `192000` 192 kHz | hidden when audio_format is copy | Target sample rate. Source keeps the original rate. |
| Bit depth `audio_bit_depth` | choice | `24` | `source` COPY; `16` 16-bit; `24` 24-bit; `32f` 32-bit float | hidden when audio_format is copy | PCM/FLAC bit depth. Source keeps the original depth where the codec supports it. |
| Resampler `audio_resampler` | choice | `soxr` | `soxr` SoX 100% quality | hidden when audio_format is copy | Resampling engine used when changing sample rate. |
| Even the timestamps (rare) `audio_resync` | tick | `false` | - | hidden when audio_format is copy | Fills the gaps of the sound and trims its overlaps by the timestamps, from zero (aresample=async=1:first_pts=0): a recording with broken timestamps keeps in step with its picture. |
| Video container `audio_video_container` | choice | `source` | `source` Source; `mov` MOV (not offered when audio_format is one of flac, opus); `mkv` MKV; `mp4` MP4 (not offered when audio_format is one of wav, flac); `mxf` MXF (not offered when audio_format is one of flac, alac, m4a, mp3, opus) | shown when audio_workflow is in_video | Container for video-copy mode. Some audio codecs are disabled for unsafe container pairs. |
| Audio bitrate `audio_bitrate` | choice | `384k` | `192k` 192 kbps; `256k` 256 kbps; `320k` 320 kbps; `384k` 384 kbps (not offered when any of (audio_mode is mp3; audio_format is mp3)) | shown when any of (audio_format is one of m4a, opus; all of (audio_format is mp3; mp3_lame_preset is bitrate)) | The bitrate of a lossy sound: AAC, Opus (at most 256 kbps), and MP3 when its LAME preset is By bitrate (at most 320 kbps). |
| Audio streams `audio_stream_mode` | choice | `first` | `first` First stream; `all` All streams; `index` By index; `language` By language | - | Which audio stream(s) to process from each source file. |
| Stream index `audio_stream_index` | number | `0` | - | shown when audio_stream_mode is index | Zero-based audio stream index: a0 is the first audio stream. |
| Language tag `audio_language` | choice | - | `""` Not selected; `eng` English (eng); `ara` Arabic (ara); `spa` Spanish (spa); `ita` Italian (ita); `zho` Chinese (zho); `kor` Korean (kor); `deu` German (deu); `pol` Polish (pol); `por` Portuguese (por); `rus` Russian (rus); `ukr` Ukrainian (ukr); `fra` French (fra); `jpn` Japanese (jpn) | shown when audio_stream_mode is language | Match streams by container language tag such as eng, rus or ukr. |
| LUFS `audio_lufs` | choice | `off` | `off` Off; `-14` -14; `-16` -16; `-23` -23 | shown when all of (audio_lufs_mode is one of report, one_pass, two_pass; not (audio_format is copy)) | Target integrated loudness for loudnorm. |
| LUFS mode `audio_lufs_mode` | choice | `off` | `off` Off; `report` Report only; `one_pass` One pass; `two_pass` Two pass | hidden when audio_format is copy | Report analyzes loudness only; one-pass is quick; two-pass is more accurate. |
| Channels `audio_channel_mode` | choice | `keep` | `keep` Keep; `stereo` Stereo; `mono` Mono; `dual_mono` Dual mono | hidden when audio_format is copy | Channel layout operation: keep original channels, downmix to stereo/mono, or make dual mono. |
| 5.1 Matrix `matrix_51` | tick | `false` | - | shown when all of (audio_channel_mode is stereo; not (audio_format is copy)) | Adds DPLII-style matrix encoding while downmixing to stereo. |
| Downmix `downmix_formula` | choice | `ffmpeg` | `ffmpeg` FFmpeg; `surround_6db` Surround -6 dB | shown when all of (audio_channel_mode is stereo; matrix_51 is off; not (audio_format is copy)) | How 5.1 becomes stereo. A stereo source stays as it is either way. |
| MP3 / LAME `mp3_lame_preset` | choice | `v0` | `v0` VBR V0; `insane` Insane 320; `bitrate` By bitrate | shown when audio_format is mp3 | LAME quality mode for MP3 output. |
| Overwrite `overwrite` | tick | `false` | - | - | Allow FFmpeg to replace existing output files. |
| Test on first file `limit_first_file` | tick | `false` | - | - | Process only the first matching file, useful for checking a preset before a full batch. |
| Dry run `dry_run` | tick | `false` | - | - | Print commands without processing media. |

## ENCODE - Archive, editing, storage, delivery, RAW

### Create archive - `archive_run`

Encode selected archive targets.

Call: `media_cli.cmd run --operation archive_run`

**Presets** - Archive preset `archive_profile`

| Preset | What it is | What it sets |
|---|---|---|
| `ffv1_mkv` FFV1 MKV + FLAC | Archive master with all streams mapped and FLAC audio; float PCM, which FLAC cannot hold, is copied as it is. A pixel format FFV1 cannot keep is refused. | target_codecs=ffv1, audio_mode=flac, output_container=mkv, pix_fmt=auto |
| `x264_lossless_mkv` x264 lossless MKV | CRF 0 x264 archive variant, useful when FFV1 is too heavy. Keeps YUV of 8 and 10 bits; a 12-bit, RGB or alpha source is refused - FFV1 keeps it. | target_codecs=x264_lossless, audio_mode=source, output_container=mkv, pix_fmt=auto |
| `dual_archive` FFV1 + x264 lossless | Create both archive formats sequentially. | target_codecs=ffv1,x264_lossless, audio_mode=flac, output_container=mkv, pix_fmt=auto |

**Fields**

| Field | Kind | Default | Choices | When | What it is |
|---|---|---|---|---|---|
| Source file filter `input_formats` | ticks | - | `mp4` MP4; `mov` MOV; `mkv` MKV; `mxf` MXF; `avi` AVI; `webm` WEBM; `mts` MTS; `m2ts` M2TS | - | Empty means the operation uses its own supported source file types. |
| Archive formats `target_codecs` | ticks | - | `ffv1` FFV1; `x264_lossless` x264 lossless | - | One or more output targets. Multiple targets are written separately for each Source file. |
| Decoder `decode_backend` | choice | `auto` | `auto` CPU/Auto; `cuda` CUDA; `qsv` QuickSync; `amd` AMD/D3D11VA; `dav1d` dav1d AV1 | - | Hardware/software decode preference before encoding. |
| Audio `audio_mode` | choice | `source` | `source` COPY; `aac_320` AAC override; `mp3` MP3; `flac` FLAC; `pcm_s16` PCM 16-bit; `pcm_s24` PCM 24-bit; `pcm_f32` PCM float; `none` No audio | - | Audio policy for the output: stream copy, lossy/lossless encode, PCM depth, or no audio. MXF permits only compatible PCM modes. |
| Sample rate `audio_sample_rate` | choice | `source` | `source` COPY; `44100` 44.1 kHz; `48000` 48 kHz; `88200` 88.2 kHz; `96000` 96 kHz; `176400` 176.4 kHz; `192000` 192 kHz | shown when audio_mode is one of aac_320, mp3, flac, pcm_s16, pcm_s24, pcm_f32 | Target sample rate. Source keeps the original rate. |
| MP3 / LAME `mp3_lame_preset` | choice | `v0` | `v0` VBR V0; `insane` Insane 320; `bitrate` By bitrate | shown when audio_mode is mp3 | LAME quality mode for MP3 output. |
| Audio bitrate `audio_bitrate` | choice | `384k` | `192k` 192 kbps; `256k` 256 kbps; `320k` 320 kbps; `384k` 384 kbps (not offered when any of (audio_mode is mp3; audio_format is mp3)) | shown when any of (audio_mode is aac_320; all of (audio_mode is mp3; mp3_lame_preset is bitrate)) | The bitrate of a lossy sound: AAC, Opus (at most 256 kbps), and MP3 when its LAME preset is By bitrate (at most 320 kbps). |
| CPU preset `cpu_encoder_preset` | choice | `medium` | `fast` fast; `medium` medium; `slow` slow; `slower` slower; `veryslow` veryslow | hidden when encode_backend is one of cuda, qsv, amd | Software x264/x265 speed-compression preset. Slower presets spend more CPU searching for a cleaner/smaller encode at the same CRF. |
| Pixel format `pix_fmt` | choice | `auto` | `auto` auto; `yuv420p` yuv420p; `yuv420p10le` yuv420p10le; `yuv422p` yuv422p; `yuv422p10le` yuv422p10le | - | Output pixel format and bit depth. Keep it compatible with the selected codec and delivery/editing workflow. |
| Encode tuning `encode_tuning` | ticks | - | `grain` Grain; `film` Film; `animation` Animation; `fastdecode` Fast decode; `zerolatency` Zero latency | hidden when encode_backend is one of cuda, qsv, amd | x264/x265 tune values. Hardware encoders use their own quality controls and ignore this list, so it stays CPU-only. |
| Overwrite `overwrite` | tick | `false` | - | - | Allow FFmpeg to replace existing output files. |
| Test on first file `limit_first_file` | tick | `false` | - | - | Process only the first matching file, useful for checking a preset before a full batch. |
| Dry run `dry_run` | tick | `false` | - | - | Print commands without processing media. |

### Create editing files - `editing_run`

Encode selected mezzanine targets.

Call: `media_cli.cmd run --operation editing_run`

Wrappers: `ff-dnxhr-hq-mov`, `ff-dnxhr-hq-mxf`, `ff-dnxhr-hqx-mov`, `ff-dnxhr-hqx-mxf`, `ff-prores-422-mov`, `ff-prores-422-mxf`, `ff-prores-lt-mov`, `ff-prores-lt-mxf`, `ff-prores-proxy-mov`, `ff-prores-proxy-mxf`.

**Presets** - Editing preset `editing_profile`

| Preset | What it is | What it sets |
|---|---|---|
| `prores_proxy_mov` Proxy | A light proxy for a responsive edit. | target_codecs=prores_proxy, output_container=mov, audio_mode=pcm_s16, pix_fmt=yuv422p10le |
| `prores_lt_mov` LT | A lighter ProRes for the edit. | target_codecs=prores_lt, output_container=mov, audio_mode=pcm_s24, pix_fmt=yuv422p10le |
| `prores_422_mov` 422 | A balanced 10-bit 4:2:2 mezzanine. | target_codecs=prores_422, output_container=mov, audio_mode=pcm_s24, pix_fmt=yuv422p10le |
| `prores_hq_mov` HQ | ProRes 422 HQ at a high bitrate. | target_codecs=prores_hq, output_container=mov, audio_mode=pcm_s24, pix_fmt=yuv422p10le |
| `prores_proxy_mxf` Proxy | ProRes Proxy in MXF with PCM 16-bit. | target_codecs=prores_proxy, output_container=mxf, audio_mode=pcm_s16, pix_fmt=yuv422p10le |
| `prores_lt_mxf` LT | ProRes LT in MXF with PCM 24-bit. | target_codecs=prores_lt, output_container=mxf, audio_mode=pcm_s24, pix_fmt=yuv422p10le |
| `prores_422_mxf` 422 | ProRes 422 in MXF with PCM 24-bit. | target_codecs=prores_422, output_container=mxf, audio_mode=pcm_s24, pix_fmt=yuv422p10le |
| `prores_hq_mxf` HQ | ProRes 422 HQ in MXF with PCM 24-bit. | target_codecs=prores_hq, output_container=mxf, audio_mode=pcm_s24, pix_fmt=yuv422p10le |
| `dnxhr_hq_mov` HQ | DNxHR HQ 8-bit in MOV. | target_codecs=dnxhr_hq, output_container=mov, audio_mode=pcm_s24, pix_fmt=yuv422p |
| `dnxhr_hqx_mov` HQX | DNxHR HQX 10-bit in MOV. | target_codecs=dnxhr_hqx, output_container=mov, audio_mode=pcm_s24, pix_fmt=yuv422p10le |
| `dnxhr_hq_mxf` HQ | DNxHR HQ 8-bit in MXF with PCM 24-bit. | target_codecs=dnxhr_hq, output_container=mxf, audio_mode=pcm_s24, pix_fmt=yuv422p |
| `dnxhr_hqx_mxf` HQX | DNxHR HQX 10-bit in MXF with PCM 24-bit. | target_codecs=dnxhr_hqx, output_container=mxf, audio_mode=pcm_s24, pix_fmt=yuv422p10le |

**Fields**

| Field | Kind | Default | Choices | When | What it is |
|---|---|---|---|---|---|
| Source file filter `input_formats` | ticks | - | `mp4` MP4; `mov` MOV; `mkv` MKV; `mxf` MXF; `avi` AVI; `webm` WEBM; `mts` MTS; `m2ts` M2TS | - | Empty means the operation uses its own supported source file types. |
| Editing targets `target_codecs` | ticks | - | `prores_proxy` ProRes Proxy; `prores_lt` ProRes LT; `prores_422` ProRes 422; `prores_hq` ProRes HQ; `dnxhr_hq` DNxHR HQ; `dnxhr_hqx` DNxHR HQX | - | One or more output targets. Multiple targets are written separately for each Source file. |
| Decoder `decode_backend` | choice | `auto` | `auto` CPU/Auto; `cuda` CUDA; `qsv` QuickSync; `amd` AMD/D3D11VA; `dav1d` dav1d AV1 | - | Hardware/software decode preference before encoding. |
| Audio `audio_mode` | choice | `source` | `source` COPY (not offered when output_container is mxf); `aac_320` AAC override (not offered when output_container is mxf); `mp3` MP3 (not offered when output_container is mxf); `flac` FLAC (not offered when output_container is one of mxf, mov); `pcm_s16` PCM 16-bit; `pcm_s24` PCM 24-bit; `pcm_f32` PCM float (not offered when output_container is mxf); `none` No audio | - | Audio policy for the output: stream copy, lossy/lossless encode, PCM depth, or no audio. MXF permits only compatible PCM modes. |
| Sample rate `audio_sample_rate` | choice | `source` | `source` COPY; `44100` 44.1 kHz; `48000` 48 kHz; `88200` 88.2 kHz; `96000` 96 kHz; `176400` 176.4 kHz; `192000` 192 kHz | shown when audio_mode is one of aac_320, mp3, flac, pcm_s16, pcm_s24, pcm_f32 | Target sample rate. Source keeps the original rate. |
| MP3 / LAME `mp3_lame_preset` | choice | `v0` | `v0` VBR V0; `insane` Insane 320; `bitrate` By bitrate | shown when audio_mode is mp3 | LAME quality mode for MP3 output. |
| Audio bitrate `audio_bitrate` | choice | `384k` | `192k` 192 kbps; `256k` 256 kbps; `320k` 320 kbps; `384k` 384 kbps (not offered when any of (audio_mode is mp3; audio_format is mp3)) | shown when any of (audio_mode is aac_320; all of (audio_mode is mp3; mp3_lame_preset is bitrate)) | The bitrate of a lossy sound: AAC, Opus (at most 256 kbps), and MP3 when its LAME preset is By bitrate (at most 320 kbps). |
| Container `output_container` | choice | `mov` | `mov` MOV; `mxf` MXF | - | Container for encoded output when the selected codec family allows it. |
| Resolution `output_resolution` | choice | `source` | `source` Source; `2160` 2160p; `1440` 1440p; `1080` 1080p; `720` 720p; `480` 480p | - | Optional scaling target. Source keeps the original frame size. |
| Interlaced source (rare) `scan_mode` | choice | `double` | `keep` Keep fields; `progressive` Progressive; `double` Progressive x2 | - | What becomes of a source of two fields (25i, 29.97i, 50i). Progressive x2, the default: bwdif makes a frame of each field, the rate doubled and the motion whole - 50i becomes 50p. Progressive: a whole frame of each frame, the rate kept. Keep fields: the fields and their order stay, for an interlaced broadcast. A progressive source is not touched. |
| Overwrite `overwrite` | tick | `false` | - | - | Allow FFmpeg to replace existing output files. |
| Test on first file `limit_first_file` | tick | `false` | - | - | Process only the first matching file, useful for checking a preset before a full batch. |
| Dry run `dry_run` | tick | `false` | - | - | Print commands without processing media. |

### Encode storage files - `storage_run`

Encode selected storage targets.

Call: `media_cli.cmd run --operation storage_run`

Wrappers: `ff-av1-crf14`, `ff-av1-fast-crf14`, `ff-hevc10-crf14`, `ff-x264-4k-to-1080-crf14`, `ff-x264-4k-to-1080-crf17`, `ff-x264-4k-to-1080-crf21`, `ff-x264-crf14`, `ff-x264-crf17`, `ff-x264-crf21`.

**Presets** - Storage preset `storage_profile`

| Preset | What it is | What it sets |
|---|---|---|
| `x264_crf14` x264 CRF 14 | Strong general-purpose H.264 storage encode. | target_codecs=x264, encode_backend=cpu, decode_backend=auto, output_container=mp4, output_resolution=source, audio_mode=source, audio_bitrate=384k, crf=14, cpu_encoder_preset=slow, pix_fmt=yuv420p |
| `x264_1080_crf14` x264 1080p CRF 14 | Downscale 4K sources to high-quality 1080p. | target_codecs=x264, encode_backend=cpu, decode_backend=auto, output_container=mp4, output_resolution=1080, audio_mode=aac_320, audio_bitrate=384k, crf=14, cpu_encoder_preset=slow, pix_fmt=yuv420p |
| `hevc10_crf14` HEVC Main10 CRF 14 | 10-bit HEVC storage with smaller files. | target_codecs=hevc_x265, encode_backend=cpu, decode_backend=auto, output_container=mp4, output_resolution=source, audio_mode=source, audio_bitrate=384k, crf=14, cpu_encoder_preset=slow, pix_fmt=yuv420p10le |
| `svt_av1_crf14` SVT-AV1 CRF 14 | Modern long-term storage codec when decode support is acceptable. | target_codecs=svt_av1, encode_backend=cpu, decode_backend=auto, output_container=mkv, output_resolution=source, audio_mode=source, audio_bitrate=384k, crf=14, av1_preset=6, pix_fmt=yuv420p10le |

**Fields**

| Field | Kind | Default | Choices | When | What it is |
|---|---|---|---|---|---|
| Source file filter `input_formats` | ticks | - | `mp4` MP4; `mov` MOV; `mkv` MKV; `mxf` MXF; `avi` AVI; `webm` WEBM; `mts` MTS; `m2ts` M2TS | - | Empty means the operation uses its own supported source file types. |
| Storage codecs `target_codecs` | ticks | - | `x264` x264 / H.264; `hevc_x265` x265 / HEVC; `svt_av1` AV1 | - | One or more output targets. Multiple targets are written separately for each Source file. |
| Encoder `encode_backend` | choice | `cpu` | `cpu` CPU; `cuda` NVENC; `amd` AMF; `qsv` QSV | - | Select the encoder backend. Each backend exposes its own native preset/quality controls below. |
| Decoder `decode_backend` | choice | `auto` | `auto` CPU/Auto; `cuda` CUDA; `qsv` QuickSync; `amd` AMD/D3D11VA; `dav1d` dav1d AV1 | - | Hardware/software decode preference before encoding. |
| Audio `audio_mode` | choice | `source` | `source` COPY; `aac_320` AAC override; `mp3` MP3; `flac` FLAC; `pcm_s16` PCM 16-bit; `pcm_s24` PCM 24-bit; `pcm_f32` PCM float; `none` No audio | - | Audio policy for the output: stream copy, lossy/lossless encode, PCM depth, or no audio. MXF permits only compatible PCM modes. |
| Sample rate `audio_sample_rate` | choice | `source` | `source` COPY; `44100` 44.1 kHz; `48000` 48 kHz; `88200` 88.2 kHz; `96000` 96 kHz; `176400` 176.4 kHz; `192000` 192 kHz | shown when audio_mode is one of aac_320, mp3, flac, pcm_s16, pcm_s24, pcm_f32 | Target sample rate. Source keeps the original rate. |
| MP3 / LAME `mp3_lame_preset` | choice | `v0` | `v0` VBR V0; `insane` Insane 320; `bitrate` By bitrate | shown when audio_mode is mp3 | LAME quality mode for MP3 output. |
| Audio bitrate `audio_bitrate` | choice | `384k` | `192k` 192 kbps; `256k` 256 kbps; `320k` 320 kbps; `384k` 384 kbps (not offered when any of (audio_mode is mp3; audio_format is mp3)) | shown when any of (audio_mode is aac_320; all of (audio_mode is mp3; mp3_lame_preset is bitrate)) | The bitrate of a lossy sound: AAC, Opus (at most 256 kbps), and MP3 when its LAME preset is By bitrate (at most 320 kbps). |
| Container `output_container` | choice | `mp4` | `mp4` MP4; `mkv` MKV; `mov` MOV | - | Container for encoded output when the selected codec family allows it. |
| CPU preset `cpu_encoder_preset` | choice | `medium` | `fast` fast; `medium` medium; `slow` slow; `slower` slower; `veryslow` veryslow | hidden when encode_backend is one of cuda, qsv, amd | Software x264/x265 speed-compression preset. Slower presets spend more CPU searching for a cleaner/smaller encode at the same CRF. |
| NVENC preset `nvenc_preset` | choice | `p6` | `p5` NVENC p5; `p6` NVENC p6; `p7` NVENC p7 | shown when encode_backend is cuda | NVIDIA NVENC P-preset. This is a hardware encoder scale, not an equivalent of CPU slow/slower/veryslow. |
| QSV preset `qsv_encoder_preset` | choice | `medium` | `veryfast` veryfast; `faster` faster; `fast` fast; `medium` medium; `slow` slow; `slower` slower; `veryslow` veryslow | shown when encode_backend is qsv | Intel QuickSync preset. QSV has its own preset line exposed by FFmpeg: veryfast, faster, fast, medium, slow, slower, veryslow. |
| AMF quality `amf_quality` | choice | `quality` | `speed` speed; `balanced` balanced; `quality` quality | shown when encode_backend is amd | AMD AMF quality preset. This controls AMF's speed/balanced/quality mode; CQ/QP still controls quantization level. |
| Resolution `output_resolution` | choice | `source` | `source` Source; `2160` 2160p; `1440` 1440p; `1080` 1080p; `720` 720p; `480` 480p | - | Optional scaling target. Source keeps the original frame size. |
| Interlaced source (rare) `scan_mode` | choice | `double` | `keep` Keep fields; `progressive` Progressive; `double` Progressive x2 | - | What becomes of a source of two fields (25i, 29.97i, 50i). Progressive x2, the default: bwdif makes a frame of each field, the rate doubled and the motion whole - 50i becomes 50p. Progressive: a whole frame of each frame, the rate kept. Keep fields: the fields and their order stay, for an interlaced broadcast. A progressive source is not touched. |
| SVT-AV1 preset `av1_preset` | choice | `6` | `4` 4 quality; `6` 6 balanced; `8` 8 fast | shown when target_codecs is one of svt_av1; hidden when encode_backend is one of cuda, qsv, amd | Software SVT-AV1 speed/quality preset. Hardware AV1 encoders use their own NVENC/QSV/AMF scales instead. |
| Pixel format `pix_fmt` | choice | `auto` | `auto` auto; `yuv420p` yuv420p; `yuv420p10le` yuv420p10le; `yuv422p` yuv422p; `yuv422p10le` yuv422p10le | - | Output pixel format and bit depth. Keep it compatible with the selected codec and delivery/editing workflow. |
| CRF `crf` | number | `14` | - | hidden when encode_backend is one of cuda, qsv, amd | Quality target for software encoders: lower means larger and cleaner. |
| CQ/QP `cq` | number | `14` | - | shown when encode_backend is one of cuda, qsv, amd | Constant-quality value for hardware encoders. |
| Encode tuning `encode_tuning` | ticks | - | `grain` Grain; `film` Film; `animation` Animation; `fastdecode` Fast decode; `zerolatency` Zero latency | hidden when encode_backend is one of cuda, qsv, amd | x264/x265 tune values. Hardware encoders use their own quality controls and ignore this list, so it stays CPU-only. |
| Overwrite `overwrite` | tick | `false` | - | - | Allow FFmpeg to replace existing output files. |
| Test on first file `limit_first_file` | tick | `false` | - | - | Process only the first matching file, useful for checking a preset before a full batch. |
| Dry run `dry_run` | tick | `false` | - | - | Print commands without processing media. |

### Encode delivery files - `delivery_run`

Encode selected delivery targets.

Call: `media_cli.cmd run --operation delivery_run`

**Presets** - Delivery preset `delivery_profile`

| Preset | What it is | What it sets |
|---|---|---|
| `review_h264` Review H.264 | Fast MP4 review encode, good enough to send around. | target_codecs=x264, encode_backend=cpu, decode_backend=auto, output_container=mp4, output_resolution=1080, audio_mode=aac_320, audio_bitrate=384k, crf=14, cpu_encoder_preset=fast, pix_fmt=yuv420p |
| `upload_h264` Upload H.264 | Cleaner H.264 MP4 for video platforms. | target_codecs=x264, encode_backend=cpu, decode_backend=auto, output_container=mp4, output_resolution=source, audio_mode=aac_320, audio_bitrate=384k, crf=14, cpu_encoder_preset=slow, pix_fmt=yuv420p |
| `upload_hevc10` Upload HEVC 10-bit | HEVC Main10 for platforms that accept it. | target_codecs=hevc_x265, encode_backend=cpu, decode_backend=auto, output_container=mp4, output_resolution=source, audio_mode=aac_320, audio_bitrate=384k, crf=14, cpu_encoder_preset=slow, pix_fmt=yuv420p10le |
| `svt_av1_delivery` SVT-AV1 delivery | AV1 encode for modern delivery tests. | target_codecs=svt_av1, encode_backend=cpu, decode_backend=auto, output_container=mp4, output_resolution=1080, audio_mode=aac_320, audio_bitrate=384k, crf=14, av1_preset=8, pix_fmt=yuv420p10le |

**Fields**

| Field | Kind | Default | Choices | When | What it is |
|---|---|---|---|---|---|
| Source file filter `input_formats` | ticks | - | `mp4` MP4; `mov` MOV; `mkv` MKV; `mxf` MXF; `avi` AVI; `webm` WEBM; `mts` MTS; `m2ts` M2TS | - | Empty means the operation uses its own supported source file types. |
| Delivery codecs `target_codecs` | ticks | - | `x264` x264 / H.264; `hevc_x265` x265 / HEVC; `svt_av1` AV1 | - | One or more output targets. Multiple targets are written separately for each Source file. |
| Encoder `encode_backend` | choice | `cpu` | `cpu` CPU; `cuda` NVENC; `amd` AMF; `qsv` QSV | - | Select the encoder backend. Each backend exposes its own native preset/quality controls below. |
| Decoder `decode_backend` | choice | `auto` | `auto` CPU/Auto; `cuda` CUDA; `qsv` QuickSync; `amd` AMD/D3D11VA; `dav1d` dav1d AV1 | - | Hardware/software decode preference before encoding. |
| Audio `audio_mode` | choice | `source` | `source` COPY; `aac_320` AAC override; `mp3` MP3; `flac` FLAC; `pcm_s16` PCM 16-bit; `pcm_s24` PCM 24-bit; `pcm_f32` PCM float; `none` No audio | - | Audio policy for the output: stream copy, lossy/lossless encode, PCM depth, or no audio. MXF permits only compatible PCM modes. |
| Sample rate `audio_sample_rate` | choice | `source` | `source` COPY; `44100` 44.1 kHz; `48000` 48 kHz; `88200` 88.2 kHz; `96000` 96 kHz; `176400` 176.4 kHz; `192000` 192 kHz | shown when audio_mode is one of aac_320, mp3, flac, pcm_s16, pcm_s24, pcm_f32 | Target sample rate. Source keeps the original rate. |
| MP3 / LAME `mp3_lame_preset` | choice | `v0` | `v0` VBR V0; `insane` Insane 320; `bitrate` By bitrate | shown when audio_mode is mp3 | LAME quality mode for MP3 output. |
| Audio bitrate `audio_bitrate` | choice | `384k` | `192k` 192 kbps; `256k` 256 kbps; `320k` 320 kbps; `384k` 384 kbps (not offered when any of (audio_mode is mp3; audio_format is mp3)) | shown when any of (audio_mode is aac_320; all of (audio_mode is mp3; mp3_lame_preset is bitrate)) | The bitrate of a lossy sound: AAC, Opus (at most 256 kbps), and MP3 when its LAME preset is By bitrate (at most 320 kbps). |
| Container `output_container` | choice | `mp4` | `mp4` MP4; `mkv` MKV; `mov` MOV | - | Container for encoded output when the selected codec family allows it. |
| CPU preset `cpu_encoder_preset` | choice | `medium` | `fast` fast; `medium` medium; `slow` slow; `slower` slower; `veryslow` veryslow | hidden when encode_backend is one of cuda, qsv, amd | Software x264/x265 speed-compression preset. Slower presets spend more CPU searching for a cleaner/smaller encode at the same CRF. |
| NVENC preset `nvenc_preset` | choice | `p6` | `p5` NVENC p5; `p6` NVENC p6; `p7` NVENC p7 | shown when encode_backend is cuda | NVIDIA NVENC P-preset. This is a hardware encoder scale, not an equivalent of CPU slow/slower/veryslow. |
| QSV preset `qsv_encoder_preset` | choice | `medium` | `veryfast` veryfast; `faster` faster; `fast` fast; `medium` medium; `slow` slow; `slower` slower; `veryslow` veryslow | shown when encode_backend is qsv | Intel QuickSync preset. QSV has its own preset line exposed by FFmpeg: veryfast, faster, fast, medium, slow, slower, veryslow. |
| AMF quality `amf_quality` | choice | `quality` | `speed` speed; `balanced` balanced; `quality` quality | shown when encode_backend is amd | AMD AMF quality preset. This controls AMF's speed/balanced/quality mode; CQ/QP still controls quantization level. |
| Resolution `output_resolution` | choice | `source` | `source` Source; `2160` 2160p; `1440` 1440p; `1080` 1080p; `720` 720p; `480` 480p | - | Optional scaling target. Source keeps the original frame size. |
| Interlaced source (rare) `scan_mode` | choice | `double` | `keep` Keep fields; `progressive` Progressive; `double` Progressive x2 | - | What becomes of a source of two fields (25i, 29.97i, 50i). Progressive x2, the default: bwdif makes a frame of each field, the rate doubled and the motion whole - 50i becomes 50p. Progressive: a whole frame of each frame, the rate kept. Keep fields: the fields and their order stay, for an interlaced broadcast. A progressive source is not touched. |
| SVT-AV1 preset `av1_preset` | choice | `6` | `4` 4 quality; `6` 6 balanced; `8` 8 fast | shown when target_codecs is one of svt_av1; hidden when encode_backend is one of cuda, qsv, amd | Software SVT-AV1 speed/quality preset. Hardware AV1 encoders use their own NVENC/QSV/AMF scales instead. |
| Pixel format `pix_fmt` | choice | `auto` | `auto` auto; `yuv420p` yuv420p; `yuv420p10le` yuv420p10le; `yuv422p` yuv422p; `yuv422p10le` yuv422p10le | - | Output pixel format and bit depth. Keep it compatible with the selected codec and delivery/editing workflow. |
| CRF `crf` | number | `14` | - | hidden when encode_backend is one of cuda, qsv, amd | Quality target for software encoders: lower means larger and cleaner. |
| CQ/QP `cq` | number | `14` | - | shown when encode_backend is one of cuda, qsv, amd | Constant-quality value for hardware encoders. |
| Encode tuning `encode_tuning` | ticks | - | `grain` Grain; `film` Film; `animation` Animation; `fastdecode` Fast decode; `zerolatency` Zero latency | hidden when encode_backend is one of cuda, qsv, amd | x264/x265 tune values. Hardware encoders use their own quality controls and ignore this list, so it stays CPU-only. |
| Overwrite `overwrite` | tick | `false` | - | - | Allow FFmpeg to replace existing output files. |
| Test on first file `limit_first_file` | tick | `false` | - | - | Process only the first matching file, useful for checking a preset before a full batch. |
| Dry run `dry_run` | tick | `false` | - | - | Print commands without processing media. |

### Develop ProRes RAW - `raw_develop_run`

Develop every ProRes RAW of the Source on the video card into the chosen format.

Call: `media_cli.cmd run --operation raw_develop_run`

**Fields**

| Field | Kind | Default | Choices | When | What it is |
|---|---|---|---|---|---|
| Develop into `raw_target` | choice | `prores4444` | `prores4444` ProRes 4444; `dnxhr444` DNxHR 444; `h264` H.264; `h265` H.265 10-bit | - | What the developed clip is written into. ProRes 4444 and DNxHR 444 - 10-bit 4:4:4 for an editor, with the PCM sound of the source; H.264 and H.265 10-bit - a file to look at and send, AAC sound. |
| Encoder `raw_encoder` | choice | `cpu` | `cpu` CPU; `nvenc` NVENC | shown when raw_target is one of h264, h265 | The encoder of H.264 and H.265: the processor (x264, x265, CRF 16) or NVENC of an NVIDIA card (p6, CQ 16). |
| Pieces at once `raw_workers` | choice | `auto` | `auto` Auto; `2` 2; `4` 4; `8` 8; `12` 12 | - | How many pieces of a clip develop side by side, each by its own cineraw: the decode of ProRes RAW takes one core a piece, the video card develops a frame in milliseconds. Auto - half the cores, eight at most. |
| Overwrite `overwrite` | tick | `false` | - | - | Allow FFmpeg to replace existing output files. |
| Test on first file `limit_first_file` | tick | `false` | - | - | Process only the first matching file, useful for checking a preset before a full batch. |
| Dry run `dry_run` | tick | `false` | - | - | Print commands without processing media. |

## PACKAGE - Another container, no re-encoding

### Run remux - `remux_run`

Run selected packaging operation.

Call: `media_cli.cmd run --operation remux_run`

Modes of the ribbon: VIDEO `remux_stream_mode=video`, AUDIO `remux_stream_mode=audio`, VIDEO AND AUDIO `remux_stream_mode=video_audio`.

Wrappers: `ff-remux-mkv-to-mp4`, `ff-remux-mkv-to-mp4-faststart`, `ff-remux-mov-to-mxf-copy`, `ff-remux-mp4-to-mkv`, `ff-remux-mp4-to-mkv-copy`, `ff-remux-mxf-to-mov-copy`.

**Fields**

| Field | Kind | Default | Choices | When | What it is |
|---|---|---|---|---|---|
| Output container `remux_target_format` | container | `mp4` | `mp4` MP4; `mov` MOV; `mkv` MKV; `mxf` MXF | shown when remux_stream_mode is one of video, video_audio | The new container. A file whose codec the container cannot hold is passed over with the reason - the check reads the codec, not the container alone. |
| Which way up `remux_orientation` | choice | `none` | `none` As shot; `cw90` 90 clockwise; `ccw90` 90 counter-cw; `turn180` Upside down; `hflip` Mirror left-right; `vflip` Mirror top-bottom | shown when remux_stream_mode is one of video, video_audio | Writes into the container how the picture should be shown. Nothing is decoded and nothing is re-encoded - the pixels are copied and one header field changes. Offered for H.264 and HEVC camera originals; MP4, MOV and MKV keep it, MXF does not, and the section refuses rather than writing an unturned file. |
| Audio output container `remux_audio_target_format` | container | `mka` | `m4a` M4A; `alac` ALAC; `mka` MKA; `aac` AAC; `ac3` AC3; `eac3` EAC3; `dts` DTS; `flac` FLAC; `wav` WAV; `mp3` MP3; `opus` OPUS; `ogg` OGG | shown when remux_stream_mode is audio | The file the sound goes into, without re-encoding. MKA takes any sound; the others their own codecs - M4A AAC and ALAC, WAV PCM. |
| Overwrite `overwrite` | tick | `false` | - | - | Allow FFmpeg to replace existing output files. |
| Test on first file `limit_first_file` | tick | `false` | - | - | Process only the first matching file, useful for checking a preset before a full batch. |
| Dry run `dry_run` | tick | `false` | - | - | Print commands without processing media. |

### Take subtitles out - `subtitles_extract`

Every subtitle stream of a video, copied as it is into an MKS file beside its name; a video without subtitles is passed over.

Call: `media_cli.cmd run --operation subtitles_extract`

Wrappers: `ff-extract-subs`.

**Fields**

| Field | Kind | Default | Choices | When | What it is |
|---|---|---|---|---|---|
| Overwrite `overwrite` | tick | `false` | - | - | Allow FFmpeg to replace existing output files. |
| Test on first file `limit_first_file` | tick | `false` | - | - | Process only the first matching file, useful for checking a preset before a full batch. |
| Dry run `dry_run` | tick | `false` | - | - | Print commands without processing media. |

## CUT - Keep, cut out, split

### Trim the file - `trim_run`

Cut on the nearest keyframe, copy the streams, shift the timecode; sound on the sample.

Call: `media_cli.cmd run --operation trim_run`

Modes of the ribbon: KEEP `trim_action=keep`, CUT OUT `trim_action=cut`, SPLIT `trim_action=split`.

Wrappers: `ff-trim-both`, `ff-trim-end`, `ff-trim-middle`, `ff-trim-start`.

**Fields**

| Field | Kind | Default | Choices | When | What it is |
|---|---|---|---|---|---|
| File to trim `trim_file` | trim_file_pick | - | - | - | The video and sound files staged in Source, alphabetically. One file is trimmed at a time: takes rarely share a keyframe, let alone a cut point. |
| Points `trim_rows` | trim_rows | - | - | - | The points, in hours, minutes, seconds and milliseconds: 00:01:02,500. Each row added with + is written to a file of its own. |
| Player - find the points `trim_player` | mpv_transport | `open` | `open` Open in the player; `both` Take A and B (hidden when trim_action is split); `mark_in` Mark IN (hidden when trim_action is split); `mark_out` Mark OUT (hidden when trim_action is split); `take_a` Take A (shown when trim_action is split); `mark_point` Mark here (shown when trim_action is split); `close` Close the player | - | Opens the take in mpv. There, `l` sets the A point and `l` again sets B; the piece between them plays in a loop, so the cut is heard before it is written. `,` and `.` step one frame, `b` plays backwards. Then bring A and B here. |
| Output container `trim_container` | choice | `source` | `source` As is; `mp4` MP4; `mov` MOV; `mkv` MKV; `mxf` MXF | hidden when trim_media_kind is audio | The container of the piece. As is keeps the camera's own. |
| Audio `trim_audio` | choice | `copy` | `copy` Copy; `none` Drop | hidden when trim_media_kind is audio | The sound of the piece: copied as it is, or dropped. |
| Audio channel `trim_audio_channel` | choice | `both` | `both` Both; `first` First; `second` Second; `mono` Fold to mono | shown when trim_audio is copy; hidden when trim_media_kind is audio | Which channels of the sound go into the piece: both, one of the two, or both folded to mono. |
| Cut `trim_exact` | choice | `false` | `true` Exact; `false` Lossless | shown when trim_media_kind is audio | How a sound file is cut: exactly on the sample, a compressed sound encoded once more, or without loss, the compressed packets copied as they are and the points moved to packet boundaries. |
| Format of the piece `trim_audio_format` | choice | `source` | `source` As is; `wav` WAV; `flac` FLAC; `alac` ALAC; `m4a` M4A / AAC; `mp3` MP3; `opus` Opus | shown when all of (trim_media_kind is audio; trim_exact is on) | The format a piece of a sound file is written in. As is keeps the source's, sample for sample where it is lossless. |
| MP3 / LAME `trim_mp3_preset` | choice | `v0` | `v0` VBR V0; `insane` Insane 320; `bitrate` By bitrate | shown when all of (trim_media_kind is audio; trim_exact is on; trim_audio_format is mp3) | The LAME quality of a piece written as MP3. |
| Bitrate `trim_audio_bitrate` | choice | `320k` | `192k` 192 kbps; `256k` 256 kbps; `320k` 320 kbps; `384k` 384 kbps (not offered when trim_audio_format is one of mp3, opus) | shown when all of (trim_media_kind is audio; trim_exact is on; any of (trim_audio_format is one of m4a, opus; all of (trim_audio_format is mp3; trim_mp3_preset is bitrate))) | The bitrate of a piece written as AAC, Opus (at most 256 kbps) or MP3 by bitrate (at most 320 kbps). |
| Telemetry `trim_data` | tick | `true` | - | hidden when trim_media_kind is audio | Carries the file's data stream into the result - a GoPro writes its telemetry there, and it would otherwise vanish without a word. MOV and MP4 can hold one; MKV and MXF cannot, and the log says so before the run. A timecode track is left behind on purpose: it travels as a value instead. Cut it out does not carry the data stream through its join, and says so. |
| Subtitles `trim_subtitles` | tick | `true` | - | hidden when trim_media_kind is audio | Carries subtitle streams over. Camera files rarely have them, but a DJI writes its flight data as subtitles, and dropping them loses the flight log. The lines are rebuilt for the cut rather than copied: each is trimmed to the piece kept and moved onto its timeline, so a line across IN or OUT keeps its part inside, and after Cut it out the lines sit where the join puts them. MP4 and MOV write them as mov_text, MKV as SRT; picture subtitles stay behind, and the log says so. |
| Timecode `trim_timecode` | choice | `shift` | `shift` Shift; `zero` Zero | hidden when trim_media_kind is audio | The timecode of the piece: shifted by what was cut away - the edit syncs cameras by it - or from zero. |
| faststart `trim_faststart` | tick | `true` | - | hidden when trim_media_kind is audio | Move the header to the front so an MP4 or MOV starts playing before it is fully downloaded. |
| Overwrite `overwrite` | tick | `false` | - | - | Allow FFmpeg to replace existing output files. |
| Test on first file `limit_first_file` | tick | `false` | - | - | Process only the first matching file, useful for checking a preset before a full batch. |
| Dry run `dry_run` | tick | `false` | - | - | Print commands without processing media. |

## FRAME RATE - Varispeed and conform to 23.976

### Convert FPS - `fps_run`

Probe source FPS and render the selected target cadence.

Call: `media_cli.cmd run --operation fps_run`

Modes of the ribbon: VARISPEED `fps_mode=varispeed`, CONFORM `fps_mode=conform`.

Wrappers: `ff-100to23976-conform`, `ff-100to23976-varispeed`, `ff-11988to23976-conform`, `ff-11988to23976-varispeed`, `ff-17982to23976-conform`, `ff-17982to23976-varispeed`, `ff-24to23976-varispeed`, `ff-25to23976-conform`, `ff-25to23976-varispeed`, `ff-2997to23976-conform`, `ff-2997to23976-varispeed`, `ff-50to23976-conform`, `ff-50to23976-varispeed`, `ff-5994to23976-conform`, `ff-5994to23976-varispeed`.

**Presets** - Output profile `fps_output_profile`

| Preset | What it is | What it sets |
|---|---|---|
| `h264` H.264 MP4 | MP4 with H.264 and AAC. The bitrate of the sound is chosen below. | fps_output_profile=h264, encode_backend=cpu, audio_bitrate=384k, fps_audio_pcm_depth=s24, fps_audio_oversample=x1, crf=14, cq=19, cpu_encoder_preset=medium |
| `hevc` H.265 MP4 | MP4 with H.265/HEVC and AAC. The bitrate of the sound is chosen below. | fps_output_profile=hevc, encode_backend=cpu, audio_bitrate=384k, fps_audio_pcm_depth=s24, fps_audio_oversample=x1, crf=16, cq=19, cpu_encoder_preset=medium |
| `prores` ProRes MOV | ProRes 422 in Apple MOV with 16/24/32-float PCM; the selected internal rate can remain 96/192 kHz. | fps_output_profile=prores, fps_audio_pcm_depth=s24, fps_audio_oversample=x2 |
| `prores_mxf` ProRes MXF | ProRes 422 in MXF with 16/24-bit PCM at the FFmpeg MXF output rate of 48 kHz. | fps_output_profile=prores_mxf, fps_audio_pcm_depth=s24, fps_audio_oversample=x2 |
| `dnxhr` DNxHR MOV | DNxHR HQX in Apple MOV with 16/24/32-float PCM; the selected internal rate can remain 96/192 kHz. | fps_output_profile=dnxhr, fps_audio_pcm_depth=s24, fps_audio_oversample=x2 |
| `dnxhr_mxf` DNxHR MXF | DNxHR HQX in MXF with 16/24-bit PCM at the FFmpeg MXF output rate of 48 kHz. | fps_output_profile=dnxhr_mxf, fps_audio_pcm_depth=s24, fps_audio_oversample=x2 |

**Fields**

| Field | Kind | Default | Choices | When | What it is |
|---|---|---|---|---|---|
| Source file filter `input_formats` | ticks | - | `mp4` MP4; `mov` MOV; `mkv` MKV; `mxf` MXF; `avi` AVI; `webm` WEBM; `mts` MTS; `m2ts` M2TS | - | Empty means the operation uses its own supported source file types. |
| Target FPS `fps_target` | choice | `24000/1001` | `16` 16; `18` 18; `24000/1001` 23.976; `24` 24; `25` 25; `30000/1001` 29.97; `30` 30; `48` 48; `50` 50; `60000/1001` 59.94; `60` 60 | - | The frame rate the file is played at. Every frame stays: the duration changes, not the picture. |
| Audio bitrate `audio_bitrate` | choice | `384k` | `192k` 192 kbps; `256k` 256 kbps; `320k` 320 kbps; `384k` 384 kbps (not offered when any of (audio_mode is mp3; audio_format is mp3)) | shown when fps_output_profile is one of h264, hevc | The bitrate of a lossy sound: AAC, Opus (at most 256 kbps), and MP3 when its LAME preset is By bitrate (at most 320 kbps). |
| Encoder `encode_backend` | choice | `cpu` | `cpu` CPU; `cuda` NVENC; `amd` AMF; `qsv` QSV | shown when fps_output_profile is one of h264, hevc | Select the encoder backend. Each backend exposes its own native preset/quality controls below. |
| Decoder `decode_backend` | choice | `auto` | `auto` CPU/Auto; `cuda` CUDA; `qsv` QuickSync; `amd` AMD/D3D11VA; `dav1d` dav1d AV1 | - | Hardware/software decode preference before encoding. |
| CPU preset `cpu_encoder_preset` | choice | `medium` | `fast` fast; `medium` medium; `slow` slow; `slower` slower; `veryslow` veryslow | shown when fps_output_profile is one of h264, hevc; hidden when encode_backend is one of cuda, qsv, amd | Software x264/x265 speed-compression preset. Slower presets spend more CPU searching for a cleaner/smaller encode at the same CRF. |
| NVENC preset `nvenc_preset` | choice | `p6` | `p5` NVENC p5; `p6` NVENC p6; `p7` NVENC p7 | shown when fps_output_profile is one of h264, hevc and encode_backend is cuda | NVIDIA NVENC P-preset. This is a hardware encoder scale, not an equivalent of CPU slow/slower/veryslow. |
| QSV preset `qsv_encoder_preset` | choice | `medium` | `veryfast` veryfast; `faster` faster; `fast` fast; `medium` medium; `slow` slow; `slower` slower; `veryslow` veryslow | shown when fps_output_profile is one of h264, hevc and encode_backend is qsv | Intel QuickSync preset. QSV has its own preset line exposed by FFmpeg: veryfast, faster, fast, medium, slow, slower, veryslow. |
| AMF quality `amf_quality` | choice | `quality` | `speed` speed; `balanced` balanced; `quality` quality | shown when fps_output_profile is one of h264, hevc and encode_backend is amd | AMD AMF quality preset. This controls AMF's speed/balanced/quality mode; CQ/QP still controls quantization level. |
| CRF `crf` | number | `14` | - | shown when fps_output_profile is one of h264, hevc; hidden when encode_backend is one of cuda, qsv, amd | Quality target for software encoders: lower means larger and cleaner. |
| CQ/QP `cq` | number | `14` | - | shown when fps_output_profile is one of h264, hevc and encode_backend is one of cuda, qsv, amd | Constant-quality value for hardware encoders. |
| PCM depth `fps_audio_pcm_depth` | choice | `s24` | `s16` PCM 16-bit; `s24` PCM 24-bit; `f32` PCM 32-float (offered only when fps_output_profile is one of prores, dnxhr) | shown when fps_output_profile is one of prores, prores_mxf, dnxhr, dnxhr_mxf | The bit depth of the PCM sound of ProRes and DNxHR. MXF takes 16 or 24 bits. |
| Audio oversampling `fps_audio_oversample` | choice | `x2` | `x1` COPY; `x2` 2x 88.2/96; `x4` 4x 176.4/192 | shown when fps_output_profile is one of prores, prores_mxf, dnxhr, dnxhr_mxf | Internal processing rate. MXF output is finalized at 48 kHz by the FFmpeg MXF muxer. |
| Overwrite `overwrite` | tick | `false` | - | - | Allow FFmpeg to replace existing output files. |
| Dry run `dry_run` | tick | `false` | - | - | Print commands without processing media. |

## COLOR - LUT, gamma before it, HDR to SDR

### Run color - `grading_run`

Apply selected color operation with the current overrides.

Call: `media_cli.cmd run --operation grading_run`

Wrappers: `ff-grade-lut-only-hevc10`, `ff-grade-lut-only-prores422`, `ff-grade-lut-only-proresLT`, `ff-grade-lut-only-x264`, `ff-grade-preexpose-lut-x264`, `ff-grade-pregamma-lut-hevc10`, `ff-grade-pregamma-lut-prores422`, `ff-grade-pregamma-lut-x264`, `ff-hdr2sdr-hable-hevc10`, `ff-hdr2sdr-hable-x264`.

**Presets** - Color preset `grading_profile`

| Preset | What it is | What it sets |
|---|---|---|
| `lut_x264` LUT x264 | Apply the selected LUT without pre-gamma and encode an H.264 MP4 production default. | script_preset=ff-grade-lut-only-x264.cmd, output_container=mp4, pix_fmt=yuv420p, encode_backend=cpu, decode_backend=auto, crf=14, cq=14 |
| `lut_hevc10` LUT HEVC Main10 | Apply the selected LUT without pre-gamma and encode 10-bit HEVC Main10. | script_preset=ff-grade-lut-only-hevc10.cmd, output_container=mp4, pix_fmt=yuv420p10le, encode_backend=cpu, decode_backend=auto, crf=14, cq=14 |
| `lut_prores422` LUT ProRes 422 | Apply the selected LUT and create a 10-bit 4:2:2 ProRes editing intermediate. | script_preset=ff-grade-lut-only-prores422.cmd, output_container=mov, pix_fmt=yuv422p10le, encode_backend=cpu, decode_backend=auto |
| `preexpose_x264` Pre-expose LUT x264 | Apply gamma 1.15 before the LUT, lifting 18% gray to about 22.5%, then encode x264. | script_preset=ff-grade-preexpose-lut-x264.cmd, pre_gamma=1.15, output_container=mp4, pix_fmt=yuv420p, encode_backend=cpu, decode_backend=auto, crf=14, cq=14 |
| `pregamma_hevc10` Pregamma HEVC Main10 | Apply gamma 0.85 before the LUT, lowering 18% gray to about 13.3%, then encode HEVC Main10. | script_preset=ff-grade-pregamma-lut-hevc10.cmd, pre_gamma=0.85, output_container=mp4, pix_fmt=yuv420p10le, encode_backend=cpu, decode_backend=auto, crf=14, cq=14 |
| `hdr_hable_x264` HDR to SDR x264 | Convert BT.2020/PQ HDR to BT.709 SDR with Hable tonemapping and encode x264. | script_preset=ff-hdr2sdr-hable-x264.cmd, output_container=mp4, pix_fmt=yuv420p, encode_backend=cpu, decode_backend=auto, crf=14, cq=14 |

**Fields**

| Field | Kind | Default | Choices | When | What it is |
|---|---|---|---|---|---|
| LUT `lut_file` | LUT | - | - | - | Defaults to LUTs\active.cube or the first LUT file in LUTs. |
| Source file filter `input_formats` | ticks | - | `mp4` MP4; `mov` MOV; `mkv` MKV; `mxf` MXF; `avi` AVI; `webm` WEBM; `mts` MTS; `m2ts` M2TS | - | Empty means the operation uses its own supported source file types. |
| Pre-LUT gamma `pre_gamma` | number | - | - | shown when script_preset is one of ff-grade-preexpose-lut-x264.cmd, ff-grade-pregamma-lut-x264.cmd, ff-grade-pregamma-lut-hevc10.cmd, ff-grade-pregamma-lut-prores422.cmd | Gamma applied before the LUT. Values above 1 lift 18% gray; values below 1 lower it. The preview is a pre-LUT technical reference. |
| Color output targets `target_codecs` | ticks | - | `x264` x264 / H.264; `hevc_x265` x265 / HEVC; `svt_av1` AV1; `prores_422` ProRes 422; `prores_lt` ProRes LT | - | One or more output targets. Multiple targets are written separately for each Source file. |
| Encoder `encode_backend` | choice | `cpu` | `cpu` CPU; `cuda` NVENC; `amd` AMF; `qsv` QSV | - | Select the encoder backend. Each backend exposes its own native preset/quality controls below. |
| Decoder `decode_backend` | choice | `auto` | `auto` CPU/Auto; `cuda` CUDA; `qsv` QuickSync; `amd` AMD/D3D11VA; `dav1d` dav1d AV1 | - | Hardware/software decode preference before encoding. |
| Audio `audio_mode` | choice | `source` | `source` COPY (not offered when output_container is mxf); `aac_320` AAC override (not offered when output_container is mxf); `mp3` MP3 (not offered when output_container is mxf); `flac` FLAC (not offered when output_container is one of mxf, mov); `pcm_s16` PCM 16-bit; `pcm_s24` PCM 24-bit; `pcm_f32` PCM float (not offered when output_container is mxf); `none` No audio | - | Audio policy for the output: stream copy, lossy/lossless encode, PCM depth, or no audio. MXF permits only compatible PCM modes. |
| Sample rate `audio_sample_rate` | choice | `source` | `source` COPY; `44100` 44.1 kHz; `48000` 48 kHz; `88200` 88.2 kHz; `96000` 96 kHz; `176400` 176.4 kHz; `192000` 192 kHz | shown when audio_mode is one of aac_320, mp3, flac, pcm_s16, pcm_s24, pcm_f32 | Target sample rate. Source keeps the original rate. |
| MP3 / LAME `mp3_lame_preset` | choice | `v0` | `v0` VBR V0; `insane` Insane 320; `bitrate` By bitrate | shown when audio_mode is mp3 | LAME quality mode for MP3 output. |
| Audio bitrate `audio_bitrate` | choice | `384k` | `192k` 192 kbps; `256k` 256 kbps; `320k` 320 kbps; `384k` 384 kbps (not offered when any of (audio_mode is mp3; audio_format is mp3)) | shown when any of (audio_mode is aac_320; all of (audio_mode is mp3; mp3_lame_preset is bitrate)) | The bitrate of a lossy sound: AAC, Opus (at most 256 kbps), and MP3 when its LAME preset is By bitrate (at most 320 kbps). |
| Container `output_container` | choice | `mp4` | `mp4` MP4; `mkv` MKV; `mov` MOV | - | Container for encoded output when the selected codec family allows it. |
| CPU preset `cpu_encoder_preset` | choice | `medium` | `fast` fast; `medium` medium; `slow` slow; `slower` slower; `veryslow` veryslow | hidden when encode_backend is one of cuda, qsv, amd | Software x264/x265 speed-compression preset. Slower presets spend more CPU searching for a cleaner/smaller encode at the same CRF. |
| NVENC preset `nvenc_preset` | choice | `p6` | `p5` NVENC p5; `p6` NVENC p6; `p7` NVENC p7 | shown when encode_backend is cuda | NVIDIA NVENC P-preset. This is a hardware encoder scale, not an equivalent of CPU slow/slower/veryslow. |
| QSV preset `qsv_encoder_preset` | choice | `medium` | `veryfast` veryfast; `faster` faster; `fast` fast; `medium` medium; `slow` slow; `slower` slower; `veryslow` veryslow | shown when encode_backend is qsv | Intel QuickSync preset. QSV has its own preset line exposed by FFmpeg: veryfast, faster, fast, medium, slow, slower, veryslow. |
| AMF quality `amf_quality` | choice | `quality` | `speed` speed; `balanced` balanced; `quality` quality | shown when encode_backend is amd | AMD AMF quality preset. This controls AMF's speed/balanced/quality mode; CQ/QP still controls quantization level. |
| Resolution `output_resolution` | choice | `source` | `source` Source; `2160` 2160p; `1440` 1440p; `1080` 1080p; `720` 720p; `480` 480p | - | Optional scaling target. Source keeps the original frame size. |
| Interlaced source (rare) `scan_mode` | choice | `double` | `keep` Keep fields; `progressive` Progressive; `double` Progressive x2 | - | What becomes of a source of two fields (25i, 29.97i, 50i). Progressive x2, the default: bwdif makes a frame of each field, the rate doubled and the motion whole - 50i becomes 50p. Progressive: a whole frame of each frame, the rate kept. Keep fields: the fields and their order stay, for an interlaced broadcast. A progressive source is not touched. |
| SVT-AV1 preset `av1_preset` | choice | `6` | `4` 4 quality; `6` 6 balanced; `8` 8 fast | shown when target_codecs is one of svt_av1; hidden when encode_backend is one of cuda, qsv, amd | Software SVT-AV1 speed/quality preset. Hardware AV1 encoders use their own NVENC/QSV/AMF scales instead. |
| Pixel format `pix_fmt` | choice | `auto` | `auto` auto; `yuv420p` yuv420p; `yuv420p10le` yuv420p10le; `yuv422p` yuv422p; `yuv422p10le` yuv422p10le | - | Output pixel format and bit depth. Keep it compatible with the selected codec and delivery/editing workflow. |
| CRF `crf` | number | `14` | - | hidden when encode_backend is one of cuda, qsv, amd | Quality target for software encoders: lower means larger and cleaner. |
| CQ/QP `cq` | number | `14` | - | shown when encode_backend is one of cuda, qsv, amd | Constant-quality value for hardware encoders. |
| Overwrite `overwrite` | tick | `false` | - | - | Allow FFmpeg to replace existing output files. |
| Test on first file `limit_first_file` | tick | `false` | - | - | Process only the first matching file, useful for checking a preset before a full batch. |
| Dry run `dry_run` | tick | `false` | - | - | Print commands without processing media. |

## DOWNLOAD - A video or its sound by a link

### Download - `youtube_run`

Run the selected yt-dlp profile.

Call: `media_cli.cmd run --operation youtube_run`

Modes of the ribbon: BEST MP4 `youtube_profile=best_mp4`, SAFE MP4 `youtube_profile=safe_mp4`, OWN VIDEO `youtube_profile=video_custom`, FOR UPLOAD `youtube_profile=upload_ready`, OWN AUDIO `youtube_profile=audio_custom`, SUBTITLES `youtube_profile=subs_only`.

Wrappers: `yt-1080p-avc-mp4`, `yt-480p-aac`, `yt-batch-480p-aac`, `yt-batch-best-mp4`, `yt-best-av1`, `yt-best-m4a`, `yt-best-mp4`, `yt-best-mp4-safari`, `yt-best-mp4-safe`, `yt-clip-sections`, `yt-embed-subs`, `yt-mp3`, `yt-opus`, `yt-playlist-1080p-avc`, `yt-playlist-best`, `yt-subs-only`, `yt-webm-vp9`.

**Presets** - Download profile `youtube_preset`

| Preset | What it is | What it sets |
|---|---|---|
| `best_video` Best MP4 video | Best available MP4/M4A merge for general use. | youtube_profile=best_mp4, youtube_source_mode=single, youtube_resolution=best, youtube_video_codec=auto, youtube_audio_format=source, youtube_container=mp4, youtube_client=default, youtube_options=safe_retries,embed_metadata,no_playlist, subtitle_options=, parallel_fragments=8, download_archive=false |
| `upload_1080_avc` 1080p AVC MP4 | YouTube-friendly 1080p AVC preference. | youtube_profile=upload_ready, youtube_source_mode=single, youtube_resolution=1080, youtube_video_codec=avc, youtube_audio_format=source, youtube_container=mp4, youtube_options=safe_retries,embed_metadata,no_playlist, subtitle_options=, parallel_fragments=8, download_archive=false |
| `safe_safari` Safe Safari | Slower Safari client, retries and IPv4 for fragile downloads. | youtube_profile=safe_mp4, youtube_source_mode=single, youtube_resolution=best, youtube_video_codec=auto, youtube_audio_format=source, youtube_container=mp4, youtube_client=safari, youtube_options=safe_retries,force_ipv4,embed_metadata,no_playlist, subtitle_options=, parallel_fragments=1, download_archive=false |
| `av1_if_available` AV1 if available | Prefer AV1 video while keeping MP4 output. | youtube_profile=video_custom, youtube_source_mode=single, youtube_resolution=best, youtube_video_codec=av1, youtube_audio_format=source, youtube_container=mp4, youtube_options=safe_retries,embed_metadata,no_playlist, subtitle_options=, parallel_fragments=8, download_archive=false |
| `audio_mp3` Audio MP3 | Audio-only MP3 extraction. | youtube_profile=audio_custom, youtube_source_mode=single, youtube_audio_format=mp3, youtube_options=safe_retries,embed_metadata,no_playlist, subtitle_options=, parallel_fragments=8, download_archive=false |
| `batch_best` Batch from urls.txt | Read links from input\urls.txt. | youtube_profile=best_mp4, youtube_source_mode=batch, youtube_resolution=best, youtube_video_codec=auto, youtube_audio_format=source, youtube_container=mp4, youtube_options=safe_retries,embed_metadata, subtitle_options=, parallel_fragments=8, download_archive=false |

**Fields**

| Field | Kind | Default | Choices | When | What it is |
|---|---|---|---|---|---|
| URL `youtube_url` | text | - | - | - | The link of a video - or of a playlist when Source is Playlist. yt-dlp takes YouTube and most video sites. |
| Section (rare) `youtube_sections` | text | - | - | - | A part of the video only, as yt-dlp writes it: *start-end. Empty - the whole video. |
| Playlist items (rare) `youtube_playlist_items` | text | - | - | shown when youtube_source_mode is playlist | Which videos of the playlist, by their numbers in it: 1-10,15, or -5: for the last five. Empty - the whole playlist. |
| Batch file `batch_file` | file | `input\urls.txt` | - | - | A text file of links, one a line. The default input\urls.txt is urls.txt of the Source, wherever the Source is. |
| Resolution `youtube_resolution` | choice | `best` | `best` Best; `2160` 2160p; `1440` 1440p; `1080` 1080p; `720` 720p; `480` 480p | - | The limit of the resolution: the best one up to it. Best - the highest the site has. |
| Video codec `youtube_video_codec` | choice | `auto` | `auto` Auto; `avc` AVC / H.264; `av1` AV1; `vp9` VP9 | - | The codec to prefer, not to demand: without it the best other one comes. H.264 in MP4 comes with AAC sound, for editors and upload forms that take no Opus. |
| Audio format `youtube_audio_format` | choice | `source` | `source` Source / native; `m4a` M4A; `opus` Opus; `mp3` MP3 | - | The sound of Custom audio. Source: the best sound as the site keeps it, not re-encoded. M4A: the AAC of the site where it has one, else converted. Opus and MP3 (VBR V0): the sound in that codec, converted by FFmpeg where the site keeps another. |
| Container `youtube_container` | choice | `mp4` | `mp4` MP4; `mkv` MKV; `webm` WEBM | - | The container the picture and the sound are merged into. |
| Source `youtube_source_mode` | choice | `single` | `single` Single URL; `batch` input\urls.txt; `playlist` Playlist | - | Where the links come from: one link, the list of input\urls.txt, or a whole playlist. |
| Download tuning `youtube_options` | ticks | - | `safe_retries` Retries; `force_ipv4` IPv4; `embed_metadata` Metadata + thumbnail; `no_playlist` No playlist | - | Retries: ten tries for a request and for a fragment, two seconds apart. IPv4: IPv4 connections only. Metadata + thumbnail: the tags and the cover into the file. No playlist: for the links of input\urls.txt - of a link to a video in a playlist, the video alone; one link always takes its video alone, Playlist takes the whole list. |
| Subtitles `subtitle_options` | ticks | - | `write_subs` Manual; `write_auto_subs` Auto; `embed_subs` Embed | - | Manual: the subtitles people wrote, as files beside the video. Auto: the ones the site made itself. Embed: the subtitles inside the video file. |
| Parallel `parallel_fragments` | number | `8` | - | - | How many fragments of one video are downloaded at once (yt-dlp -N). More is faster on a good line; a site that limits may answer with errors. |
| Client (rare) `youtube_client` | choice | `default` | `default` Default; `safari` Safari; `android` Android | - | Which YouTube player yt-dlp presents itself as. Default suits most links; Safari or Android when formats are missing or the speed is cut. |
| Subtitle languages (rare) `subtitle_languages` | text | `ru,en.*` | - | - | The languages of the subtitles, comma-separated; a pattern is allowed: en.* takes en, en-US, en-GB. |
| Cookies (rare) `cookies_source` | choice | `file` | `none` None; `chrome` Chrome; `edge` Edge; `firefox` Firefox; `brave` Brave; `file` File | - | Where yt-dlp takes the cookies of a link that wants a sign-in. A browser: yt-dlp reads its profile at the download and the program keeps nothing; Chrome and Edge seal their cookies with their own encryption, and yt-dlp may fail to read them - Firefox is the sure one. File: the copy taken with TAKE UNDER DPAPI, kept sealed for this account of Windows; without it, the file of the field Cookies file when it is there. None: no cookies. |
| Cookies file (rare) `cookies_path` | file | `config\cookies.txt` | - | - | A cookies file of a browser (Netscape format, cookies.txt) for a link that wants a sign-in. TAKE UNDER DPAPI keeps a sealed copy of it, and the open file is no longer needed; without the copy the file is read as it is, when it is there. |
| Use download archive (rare) `download_archive` | tick | `false` | - | - | Remembers what was downloaded in config\download-archive.txt; a link already there is passed over. |
| Dry run `youtube_dry_run` | tick | `false` | - | - | Says the yt-dlp command and runs nothing. |

## SOURCE INFO

### Probe Source - `probe_source`

Run ffprobe once for Source, print a compact table and update the media status line.

Call: `media_cli.cmd run --operation probe_source`

### Source Info - `source_info`

Run ffprobe for Source and print every audio stream: codec, sample format, sample rate, bit depth, channels, bitrate and tags.

Call: `media_cli.cmd run --operation source_info`

## SERVICE: checks and installers

### Inventory - `inventory`

Count project folders.

Call: `media_cli.cmd run --operation inventory`

### Selftest - `selftest`

Check ffmpeg, ffprobe, yt-dlp and Deno.

Call: `media_cli.cmd run --operation selftest`

Wrappers: `ff-selftest`, `yt-selftest`.

### Profile Doctor - `profile_doctor`

Validate GUI operations, script wrappers and the shared preset catalog.

Call: `media_cli.cmd run --operation profile_doctor`

### Hardware capabilities - `hardware_capabilities`

Run short FFmpeg smoke tests for CPU, QSV/NVENC/AMF H.264 and HEVC, SVT-AV1 and dav1d.

Call: `media_cli.cmd run --operation hardware_capabilities`

### Preset Test Matrix - `preset_test_matrix`

Run portable 1-second smoke tests across audio, remux, FPS, LUT, archive, editing, storage and delivery presets.

Call: `media_cli.cmd run --operation preset_test_matrix`

### Install 7-Zip - `install_7zip`

Install or refresh portable 7-Zip; required before FFmpeg 7z payloads.

Call: `media_cli.cmd run --operation install_7zip`

### Install FFmpeg - `install_ffmpeg`

Install or refresh the portable FFmpeg of Gyan (GPL) in Tools\ffmpeg by the NVIDIA driver: the newest stable, 9.0.2 at least, without an NVIDIA card and from the LTS driver 610.88; below it 8.0.1 (570-610.87) or 7.1 so that NVENC works, and not every operation is possible.

Call: `media_cli.cmd run --operation install_ffmpeg`

### Install yt-dlp - `install_ytdlp`

Install or refresh portable yt-dlp and Deno into Tools.

Call: `media_cli.cmd run --operation install_ytdlp`

Wrappers: `yt-update`.

### Install mpv - `install_mpv`

Install or refresh portable mpv into Tools/mpv: the player of the trim.

Call: `media_cli.cmd run --operation install_mpv`

### Install ProRes RAW development - `install_cineraw`

Build cineraw of libcraw into Tools/cineraw from its sources: a portable MSYS2 for the build (about 185 MB downloaded, 5 minutes), removed afterwards; cineraw develops ProRes RAW on a video card with Vulkan 1.4 (NVIDIA RTX).

Call: `media_cli.cmd run --operation install_cineraw`

## Buttons beside a field

### Formats of the link - `youtube_formats`

What formats the link offers - resolution, codecs, size - listed in the journal, nothing downloaded. One of them is taken with the profile Own video.

Beside: `youtube_url`. Call: `media_cli.cmd run --operation youtube_formats`.

### Take under DPAPI - `youtube_cookies_import`

The cookies file of the field Cookies file sealed with DPAPI for this account of Windows into config\cookies.dpapi: downloads with Cookies - File take this copy, and the open file is no longer needed.

Beside: `cookies_path`. Call: `media_cli.cmd run --operation youtube_cookies_import`.

## What the window does itself

The window clears the working folders through the Recycle Bin; the console command does not run these operations, they delete for good.

- Clear Source - `cleanup_source`
- Clear Target - `cleanup_transcoded`
- Clear GUI workspace - `cleanup_workspace`
