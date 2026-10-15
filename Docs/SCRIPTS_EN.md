# Audion Media Tools - Wrappers of Scripts

[Русский](SCRIPTS_RU.md) · [Operations](OPERATIONS_EN.md)

> Made from the data of the program by `media_cli.cmd map --docs`: the manifest of the operations (`config\tool_manifest.yaml`), the layout of the window (`config\window_layout.yaml`) and the table of the wrappers (`config\wrappers.yaml`). It is not edited by hand: a text is changed there and the command is run again.

Every wrapper is a door of `media_cli.cmd wrapper NAME`: a file of its own name that runs one or more operations of the program with the values written for it. The environment variables of the table at the end are read by the wrappers as they always were.

| Wrapper | What it is | Takes | The same through the console command |
|---|---|---|---|
| `audio-downmix-51-to-20` | 5.1 down to stereo, WAV 24-bit | - | `media_cli.cmd run --operation audio_run --set audio_workflow=extract --set audio_format=wav --set audio_bit_depth=24 --set audio_sample_rate=source --set audio_channel_mode=stereo --set downmix_formula=surround_6db`<br>`media_cli.cmd run --operation audio_run --set audio_workflow=audio_files --set audio_format=wav --set audio_bit_depth=24 --set audio_sample_rate=source --set audio_channel_mode=stereo --set downmix_formula=surround_6db` |
| `audio-extract-audio-copy` | The first sound stream as it is, in a container of its codec | - | `media_cli.cmd run --operation audio_run --set audio_workflow=extract --set audio_format=copy --set audio_copy_container=auto` |
| `audio-extract-audio-wav` | The sound to WAV 24-bit at its own rate | - | `media_cli.cmd run --operation audio_run --set audio_workflow=extract --set audio_format=wav --set audio_bit_depth=24 --set audio_sample_rate=source`<br>`media_cli.cmd run --operation audio_run --set audio_workflow=audio_files --set audio_format=wav --set audio_bit_depth=24 --set audio_sample_rate=source` |
| `audio-extract-audio-wav-32` | The sound to WAV 32-bit float at its own rate | - | `media_cli.cmd run --operation audio_run --set audio_workflow=extract --set audio_format=wav --set audio_bit_depth=32f --set audio_sample_rate=source`<br>`media_cli.cmd run --operation audio_run --set audio_workflow=audio_files --set audio_format=wav --set audio_bit_depth=32f --set audio_sample_rate=source` |
| `audio-lufs-14` | Loudness -14 LUFS (streaming), WAV 24-bit | - | `media_cli.cmd run --operation audio_run --set audio_workflow=extract --set audio_format=wav --set audio_bit_depth=24 --set audio_sample_rate=source --set audio_lufs=-14 --set audio_lufs_mode=one_pass`<br>`media_cli.cmd run --operation audio_run --set audio_workflow=audio_files --set audio_format=wav --set audio_bit_depth=24 --set audio_sample_rate=source --set audio_lufs=-14 --set audio_lufs_mode=one_pass` |
| `audio-lufs-23` | Loudness -23 LUFS (EBU R128), WAV 24-bit | - | `media_cli.cmd run --operation audio_run --set audio_workflow=extract --set audio_format=wav --set audio_bit_depth=24 --set audio_sample_rate=source --set audio_lufs=-23 --set audio_lufs_mode=one_pass`<br>`media_cli.cmd run --operation audio_run --set audio_workflow=audio_files --set audio_format=wav --set audio_bit_depth=24 --set audio_sample_rate=source --set audio_lufs=-23 --set audio_lufs_mode=one_pass` |
| `audio-resample-to-44100` | The sound to 44.1 kHz, WAV 24-bit | - | `media_cli.cmd run --operation audio_run --set audio_workflow=extract --set audio_format=wav --set audio_bit_depth=24 --set audio_sample_rate=44100`<br>`media_cli.cmd run --operation audio_run --set audio_workflow=audio_files --set audio_format=wav --set audio_bit_depth=24 --set audio_sample_rate=44100` |
| `audio-resample-to-44100-32f` | The sound to 44.1 kHz, WAV 32-bit float | - | `media_cli.cmd run --operation audio_run --set audio_workflow=extract --set audio_format=wav --set audio_bit_depth=32f --set audio_sample_rate=44100`<br>`media_cli.cmd run --operation audio_run --set audio_workflow=audio_files --set audio_format=wav --set audio_bit_depth=32f --set audio_sample_rate=44100` |
| `audio-resample-to-44100-32f_sync` | The sound to 44.1 kHz, WAV 32-bit float, timestamps evened | - | `media_cli.cmd run --operation audio_run --set audio_workflow=extract --set audio_format=wav --set audio_bit_depth=32f --set audio_sample_rate=44100 --set audio_resync=true`<br>`media_cli.cmd run --operation audio_run --set audio_workflow=audio_files --set audio_format=wav --set audio_bit_depth=32f --set audio_sample_rate=44100 --set audio_resync=true` |
| `audio-resample-to-44100_sync` | The sound to 44.1 kHz, WAV 24-bit, timestamps evened | - | `media_cli.cmd run --operation audio_run --set audio_workflow=extract --set audio_format=wav --set audio_bit_depth=24 --set audio_sample_rate=44100 --set audio_resync=true`<br>`media_cli.cmd run --operation audio_run --set audio_workflow=audio_files --set audio_format=wav --set audio_bit_depth=24 --set audio_sample_rate=44100 --set audio_resync=true` |
| `audio-resample-to-48000` | The sound to 48 kHz, WAV 24-bit | - | `media_cli.cmd run --operation audio_run --set audio_workflow=extract --set audio_format=wav --set audio_bit_depth=24 --set audio_sample_rate=48000`<br>`media_cli.cmd run --operation audio_run --set audio_workflow=audio_files --set audio_format=wav --set audio_bit_depth=24 --set audio_sample_rate=48000` |
| `audio-resample-to-48000-32f` | The sound to 48 kHz, WAV 32-bit float | - | `media_cli.cmd run --operation audio_run --set audio_workflow=extract --set audio_format=wav --set audio_bit_depth=32f --set audio_sample_rate=48000`<br>`media_cli.cmd run --operation audio_run --set audio_workflow=audio_files --set audio_format=wav --set audio_bit_depth=32f --set audio_sample_rate=48000` |
| `audio-resample-to-48000-32f_sync` | The sound to 48 kHz, WAV 32-bit float, timestamps evened | - | `media_cli.cmd run --operation audio_run --set audio_workflow=extract --set audio_format=wav --set audio_bit_depth=32f --set audio_sample_rate=48000 --set audio_resync=true`<br>`media_cli.cmd run --operation audio_run --set audio_workflow=audio_files --set audio_format=wav --set audio_bit_depth=32f --set audio_sample_rate=48000 --set audio_resync=true` |
| `audio-resample-to-48000_sync` | The sound to 48 kHz, WAV 24-bit, timestamps evened | - | `media_cli.cmd run --operation audio_run --set audio_workflow=extract --set audio_format=wav --set audio_bit_depth=24 --set audio_sample_rate=48000 --set audio_resync=true`<br>`media_cli.cmd run --operation audio_run --set audio_workflow=audio_files --set audio_format=wav --set audio_bit_depth=24 --set audio_sample_rate=48000 --set audio_resync=true` |
| `audio-to-flac` | The sound to FLAC at its own rate | - | `media_cli.cmd run --operation audio_run --set audio_workflow=extract --set audio_format=flac --set audio_bit_depth=source --set audio_sample_rate=source`<br>`media_cli.cmd run --operation audio_run --set audio_workflow=audio_files --set audio_format=flac --set audio_bit_depth=source --set audio_sample_rate=source` |
| `audio-to-flac-48k` | The sound to FLAC 48 kHz | - | `media_cli.cmd run --operation audio_run --set audio_workflow=extract --set audio_format=flac --set audio_bit_depth=source --set audio_sample_rate=48000`<br>`media_cli.cmd run --operation audio_run --set audio_workflow=audio_files --set audio_format=flac --set audio_bit_depth=source --set audio_sample_rate=48000` |
| `audio-to-flac-96k` | The sound to FLAC 96 kHz | - | `media_cli.cmd run --operation audio_run --set audio_workflow=extract --set audio_format=flac --set audio_bit_depth=source --set audio_sample_rate=96000`<br>`media_cli.cmd run --operation audio_run --set audio_workflow=audio_files --set audio_format=flac --set audio_bit_depth=source --set audio_sample_rate=96000` |
| `audio-to-m4a-256` | The sound to AAC 256 kbps in M4A | - | `media_cli.cmd run --operation audio_run --set audio_workflow=extract --set audio_profile=m4a256`<br>`media_cli.cmd run --operation audio_run --set audio_workflow=audio_files --set audio_profile=m4a256` |
| `audio-to-m4a-384` | The sound to AAC 384 kbps in M4A | - | `media_cli.cmd run --operation audio_run --set audio_workflow=extract --set audio_profile=m4a384`<br>`media_cli.cmd run --operation audio_run --set audio_workflow=audio_files --set audio_profile=m4a384` |
| `ff-100to23976-conform` | 100 fps to 23.976, conform | - | `media_cli.cmd run --operation fps_run --set fps_mode=conform --set fps_target=24000/1001` |
| `ff-100to23976-varispeed` | 100 fps to 23.976, varispeed | - | `media_cli.cmd run --operation fps_run --set fps_mode=varispeed --set fps_target=24000/1001` |
| `ff-11988to23976-conform` | 119.88 fps to 23.976, conform | - | `media_cli.cmd run --operation fps_run --set fps_mode=conform --set fps_target=24000/1001` |
| `ff-11988to23976-varispeed` | 119.88 fps to 23.976, varispeed | - | `media_cli.cmd run --operation fps_run --set fps_mode=varispeed --set fps_target=24000/1001` |
| `ff-17982to23976-conform` | 179.82 fps to 23.976, conform | - | `media_cli.cmd run --operation fps_run --set fps_mode=conform --set fps_target=24000/1001` |
| `ff-17982to23976-varispeed` | 179.82 fps to 23.976, varispeed | - | `media_cli.cmd run --operation fps_run --set fps_mode=varispeed --set fps_target=24000/1001` |
| `ff-24to23976-varispeed` | 24 fps to 23.976, varispeed | - | `media_cli.cmd run --operation fps_run --set fps_mode=varispeed --set fps_target=24000/1001` |
| `ff-25to23976-conform` | 25 fps to 23.976, conform | - | `media_cli.cmd run --operation fps_run --set fps_mode=conform --set fps_target=24000/1001` |
| `ff-25to23976-varispeed` | 25 fps to 23.976, varispeed | - | `media_cli.cmd run --operation fps_run --set fps_mode=varispeed --set fps_target=24000/1001` |
| `ff-2997to23976-conform` | 29.97 fps to 23.976, conform | - | `media_cli.cmd run --operation fps_run --set fps_mode=conform --set fps_target=24000/1001` |
| `ff-2997to23976-varispeed` | 29.97 fps to 23.976, varispeed | - | `media_cli.cmd run --operation fps_run --set fps_mode=varispeed --set fps_target=24000/1001` |
| `ff-50to23976-conform` | 50 fps to 23.976, conform | - | `media_cli.cmd run --operation fps_run --set fps_mode=conform --set fps_target=24000/1001` |
| `ff-50to23976-varispeed` | 50 fps to 23.976, varispeed | - | `media_cli.cmd run --operation fps_run --set fps_mode=varispeed --set fps_target=24000/1001` |
| `ff-5994to23976-conform` | 59.94 fps to 23.976, conform | - | `media_cli.cmd run --operation fps_run --set fps_mode=conform --set fps_target=24000/1001` |
| `ff-5994to23976-varispeed` | 59.94 fps to 23.976, varispeed | - | `media_cli.cmd run --operation fps_run --set fps_mode=varispeed --set fps_target=24000/1001` |
| `ff-av1-crf14` | AV1 (SVT), CRF 14, MKV | - | `media_cli.cmd run --operation storage_run --set storage_profile=svt_av1_crf14 --set audio_mode=aac_320` |
| `ff-av1-fast-crf14` | AV1 (SVT), fast preset, CRF 14, MP4 | - | `media_cli.cmd run --operation storage_run --set storage_profile=svt_av1_crf14 --set av1_preset=8 --set output_container=mp4 --set audio_mode=aac_320` |
| `ff-dnxhr-hq-mov` | DNxHR HQ in MOV, PCM 24-bit | - | `media_cli.cmd run --operation editing_run --set editing_profile=dnxhr_hq_mov` |
| `ff-dnxhr-hq-mxf` | DNxHR HQ in MXF, PCM 24-bit | - | `media_cli.cmd run --operation editing_run --set editing_profile=dnxhr_hq_mxf` |
| `ff-dnxhr-hqx-mov` | DNxHR HQX 10-bit in MOV, PCM 24-bit | - | `media_cli.cmd run --operation editing_run --set editing_profile=dnxhr_hqx_mov` |
| `ff-dnxhr-hqx-mxf` | DNxHR HQX 10-bit in MXF, PCM 24-bit | - | `media_cli.cmd run --operation editing_run --set editing_profile=dnxhr_hqx_mxf` |
| `ff-extract-audio` | The first sound stream as it is, in a container of its codec | - | `media_cli.cmd run --operation audio_run --set audio_workflow=extract --set audio_format=copy --set audio_copy_container=auto` |
| `ff-extract-subs` | The subtitle streams as they are, to MKS | - | `media_cli.cmd run --operation subtitles_extract` |
| `ff-grade-lut-only-hevc10` | The LUT, HEVC Main10 | - | `media_cli.cmd run --operation grading_run --set grading_profile=lut_hevc10 --set audio_mode=aac_320 --set cpu_encoder_preset=medium` |
| `ff-grade-lut-only-prores422` | The LUT, ProRes 422 | - | `media_cli.cmd run --operation grading_run --set grading_profile=lut_prores422 --set audio_mode=aac_320` |
| `ff-grade-lut-only-proresLT` | The LUT, ProRes LT | - | `media_cli.cmd run --operation grading_run --set grading_profile=lut_prores422 --set audio_mode=aac_320 --set target_codecs=prores_lt` |
| `ff-grade-lut-only-x264` | The LUT, H.264 | - | `media_cli.cmd run --operation grading_run --set grading_profile=lut_x264 --set audio_mode=aac_320 --set cpu_encoder_preset=medium` |
| `ff-grade-preexpose-lut-x264` | A gamma of 1.15 before the LUT, H.264 | - | `media_cli.cmd run --operation grading_run --set grading_profile=preexpose_x264 --set audio_mode=aac_320 --set cpu_encoder_preset=medium` |
| `ff-grade-pregamma-lut-hevc10` | A gamma of 0.85 before the LUT, HEVC Main10 | - | `media_cli.cmd run --operation grading_run --set grading_profile=pregamma_hevc10 --set audio_mode=aac_320 --set cpu_encoder_preset=medium` |
| `ff-grade-pregamma-lut-prores422` | A gamma of 0.85 before the LUT, ProRes 422 | - | `media_cli.cmd run --operation grading_run --set script_preset=ff-grade-pregamma-lut-prores422.cmd --set output_container=mov --set pix_fmt=yuv422p10le --set audio_mode=aac_320` |
| `ff-grade-pregamma-lut-x264` | A gamma of 0.85 before the LUT, H.264 | - | `media_cli.cmd run --operation grading_run --set script_preset=ff-grade-pregamma-lut-x264.cmd --set output_container=mp4 --set pix_fmt=yuv420p --set audio_mode=aac_320 --set cpu_encoder_preset=medium` |
| `ff-hdr2sdr-hable-hevc10` | HDR to SDR (Hable), HEVC Main10 | - | `media_cli.cmd run --operation grading_run --set grading_profile=hdr_hable_x264 --set target_codecs=hevc_x265 --set pix_fmt=yuv420p10le --set audio_mode=aac_320 --set cpu_encoder_preset=medium` |
| `ff-hdr2sdr-hable-x264` | HDR to SDR (Hable), H.264 | - | `media_cli.cmd run --operation grading_run --set grading_profile=hdr_hable_x264 --set audio_mode=aac_320 --set cpu_encoder_preset=medium` |
| `ff-hevc10-crf14` | HEVC Main10, CRF 14 | - | `media_cli.cmd run --operation storage_run --set storage_profile=hevc10_crf14 --set audio_mode=aac_320 --set cpu_encoder_preset=medium` |
| `ff-prores-422-mov` | ProRes 422 in MOV, PCM 24-bit | - | `media_cli.cmd run --operation editing_run --set editing_profile=prores_422_mov` |
| `ff-prores-422-mxf` | ProRes 422 in MXF, PCM 24-bit | - | `media_cli.cmd run --operation editing_run --set editing_profile=prores_422_mxf` |
| `ff-prores-lt-mov` | ProRes LT in MOV, PCM 24-bit | - | `media_cli.cmd run --operation editing_run --set editing_profile=prores_lt_mov` |
| `ff-prores-lt-mxf` | ProRes LT in MXF, PCM 24-bit | - | `media_cli.cmd run --operation editing_run --set editing_profile=prores_lt_mxf` |
| `ff-prores-proxy-mov` | ProRes Proxy in MOV, PCM 24-bit | - | `media_cli.cmd run --operation editing_run --set editing_profile=prores_proxy_mov --set audio_mode=pcm_s24` |
| `ff-prores-proxy-mxf` | ProRes Proxy in MXF, PCM 24-bit | - | `media_cli.cmd run --operation editing_run --set editing_profile=prores_proxy_mxf --set audio_mode=pcm_s24` |
| `ff-remux-mkv-to-mp4` | MKV to MP4 without re-encoding | - | `media_cli.cmd run --operation remux_run --set remux_stream_mode=video_audio --set remux_target_format=mp4 --only mkv` |
| `ff-remux-mkv-to-mp4-faststart` | MKV to MP4 without re-encoding, for the web | - | `media_cli.cmd run --operation remux_run --set remux_stream_mode=video_audio --set remux_target_format=mp4 --only mkv` |
| `ff-remux-mov-to-mxf-copy` | MOV to MXF without re-encoding | - | `media_cli.cmd run --operation remux_run --set remux_stream_mode=video_audio --set remux_target_format=mxf --only mov` |
| `ff-remux-mp4-to-mkv` | MP4 to MKV without re-encoding | - | `media_cli.cmd run --operation remux_run --set remux_stream_mode=video_audio --set remux_target_format=mkv --only mp4` |
| `ff-remux-mp4-to-mkv-copy` | MP4 to MKV without re-encoding | - | `media_cli.cmd run --operation remux_run --set remux_stream_mode=video_audio --set remux_target_format=mkv --only mp4` |
| `ff-remux-mxf-to-mov-copy` | MXF to MOV without re-encoding | - | `media_cli.cmd run --operation remux_run --set remux_stream_mode=video_audio --set remux_target_format=mov --only mxf` |
| `ff-selftest` | Versions of FFmpeg, ffprobe, yt-dlp and deno | - | `media_cli.cmd run --operation selftest` |
| `ff-trim-both` | Keep what lies between IN and OUT | - | `media_cli.cmd run --operation trim_run --set trim_action=keep` |
| `ff-trim-end` | Cut the tail off: keep up to OUT | - | `media_cli.cmd run --operation trim_run --set trim_action=keep --set "trim_start="` |
| `ff-trim-middle` | Cut out what lies between IN and OUT | - | `media_cli.cmd run --operation trim_run --set trim_action=cut` |
| `ff-trim-start` | Cut the head off: keep from IN | - | `media_cli.cmd run --operation trim_run --set trim_action=keep --set "trim_end="` |
| `ff-x264-4k-to-1080-crf14` | H.264 1080p from 4K, CRF 14 | - | `media_cli.cmd run --operation storage_run --set storage_profile=x264_1080_crf14 --set audio_mode=aac_320 --set cpu_encoder_preset=medium` |
| `ff-x264-4k-to-1080-crf17` | H.264 1080p from 4K, CRF 17 | - | `media_cli.cmd run --operation storage_run --set storage_profile=x264_1080_crf14 --set crf=17 --set audio_mode=aac_320 --set cpu_encoder_preset=medium` |
| `ff-x264-4k-to-1080-crf21` | H.264 1080p from 4K, CRF 21 | - | `media_cli.cmd run --operation storage_run --set storage_profile=x264_1080_crf14 --set crf=21 --set audio_mode=aac_320 --set cpu_encoder_preset=medium` |
| `ff-x264-crf14` | H.264, CRF 14 | - | `media_cli.cmd run --operation storage_run --set storage_profile=x264_crf14 --set audio_mode=aac_320 --set cpu_encoder_preset=medium` |
| `ff-x264-crf17` | H.264, CRF 17 | - | `media_cli.cmd run --operation storage_run --set storage_profile=x264_crf14 --set crf=17 --set audio_mode=aac_320 --set cpu_encoder_preset=medium` |
| `ff-x264-crf21` | H.264, CRF 21 | - | `media_cli.cmd run --operation storage_run --set storage_profile=x264_crf14 --set crf=21 --set audio_mode=aac_320 --set cpu_encoder_preset=medium` |
| `yt-1080p-avc-mp4` | 1080p H.264 with AAC in MP4 | urls | `media_cli.cmd run --operation youtube_run --set youtube_profile=upload_ready --set youtube_resolution=1080 --set youtube_video_codec=avc --set youtube_container=mp4 --set "youtube_options="` |
| `yt-480p-aac` | 480p with AAC in MP4 | urls | `media_cli.cmd run --operation youtube_run --set youtube_profile=video_custom --set youtube_resolution=480 --set youtube_container=mp4 --set "youtube_options="` |
| `yt-batch-480p-aac` | 480p from the links of input\urls.txt | - | `media_cli.cmd run --operation youtube_run --set youtube_source_mode=batch --set youtube_profile=video_custom --set youtube_resolution=480 --set youtube_container=mp4 --set "youtube_options="` |
| `yt-batch-best-mp4` | The best MP4 from the links of input\urls.txt | - | `media_cli.cmd run --operation youtube_run --set youtube_source_mode=batch --set youtube_profile=best_mp4 --set "youtube_options="` |
| `yt-best-av1` | The best AV1 in MP4 | urls | `media_cli.cmd run --operation youtube_run --set youtube_profile=video_custom --set youtube_video_codec=av1 --set youtube_container=mp4 --set "youtube_options="` |
| `yt-best-m4a` | The sound alone, M4A, with cover and tags | urls | `media_cli.cmd run --operation youtube_run --set youtube_profile=audio_custom --set youtube_audio_format=m4a --set youtube_options=embed_metadata` |
| `yt-best-mp4` | The best picture in MP4 | urls | `media_cli.cmd run --operation youtube_run --set youtube_profile=best_mp4 --set "youtube_options="` |
| `yt-best-mp4-safari` | The best MP4 as Safari asks for it | urls | `media_cli.cmd run --operation youtube_run --set youtube_profile=best_mp4 --set youtube_client=safari --set "youtube_options="` |
| `yt-best-mp4-safe` | The best MP4, slowly and with retries | urls | `media_cli.cmd run --operation youtube_run --set youtube_profile=safe_mp4` |
| `yt-clip-sections` | A section of a video: the first argument is *00:01:00-00:02:00 | sections | `media_cli.cmd run --operation youtube_run --set youtube_profile=best_mp4 --set "youtube_options="` |
| `yt-embed-subs` | The best MP4 with subtitles inside | urls | `media_cli.cmd run --operation youtube_run --set youtube_profile=best_mp4 --set "youtube_options=" --set subtitle_options=write_subs,embed_subs --set "subtitle_languages=ru,en.*"` |
| `yt-mp3` | The sound alone, MP3, with cover and tags | urls | `media_cli.cmd run --operation youtube_run --set youtube_profile=audio_custom --set youtube_audio_format=mp3 --set youtube_options=embed_metadata` |
| `yt-opus` | The sound alone, Opus, with cover and tags | urls | `media_cli.cmd run --operation youtube_run --set youtube_profile=audio_custom --set youtube_audio_format=opus --set youtube_options=embed_metadata` |
| `yt-playlist-1080p-avc` | A whole playlist, 1080p H.264, numbered | urls | `media_cli.cmd run --operation youtube_run --set youtube_source_mode=playlist --set youtube_profile=upload_ready --set youtube_resolution=1080 --set youtube_video_codec=avc --set youtube_container=mp4 --set "youtube_options="` |
| `yt-playlist-best` | A whole playlist, the best MP4, numbered | urls | `media_cli.cmd run --operation youtube_run --set youtube_source_mode=playlist --set youtube_profile=best_mp4 --set "youtube_options="` |
| `yt-selftest` | Versions of FFmpeg, ffprobe, yt-dlp and deno | - | `media_cli.cmd run --operation selftest` |
| `yt-subs-only` | The subtitles alone | urls | `media_cli.cmd run --operation youtube_run --set youtube_profile=subs_only --set "youtube_options=" --set subtitle_options=write_subs --set "subtitle_languages=ru,en.*"` |
| `yt-update` | Update yt-dlp | - | `media_cli.cmd run --operation install_ytdlp` |
| `yt-webm-vp9` | VP9 in WebM | urls | `media_cli.cmd run --operation youtube_run --set youtube_profile=video_custom --set youtube_video_codec=vp9 --set youtube_container=webm --set "youtube_options="` |

## Environment variables the wrappers read

| Field | Variables |
|---|---|
| `amf_quality` | `AUDION_AMF_QUALITY` |
| `audio_bitrate` | `AUDION_AUDIO_BITRATE`, `AUDIO_BITRATE` |
| `audio_copy_container` | `AUDION_AUDIO_COPY_CONTAINER`, `AUDIO_COPY_CONTAINER` |
| `audio_mode` | `AUDION_AUDIO_MODE`, `AUDIO_MODE` |
| `audio_sample_rate` | `AUDION_AUDIO_SAMPLE_RATE`, `AUDIO_SAMPLE_RATE` |
| `av1_preset` | `AUDION_AV1_PRESET`, `AV1_PRESET` |
| `batch_file` | `AUDION_URLS_FILE`, `URLS_FILE`, `LIST` |
| `cpu_encoder_preset` | `AUDION_CPU_ENCODER_PRESET`, `AUDION_ENCODER_PRESET`, `ENCODER_PRESET`, `PRESET` |
| `cq` | `AUDION_CQ`, `AUDION_QP`, `CQ`, `QP` |
| `crf` | `AUDION_CRF`, `CRF` |
| `decode_backend` | `AUDION_DECODE_BACKEND`, `DECODE_BACKEND` |
| `encode_backend` | `AUDION_ENCODE_BACKEND`, `AUDION_BACKEND`, `ENCODE_BACKEND` |
| `encode_tuning` | `AUDION_ENCODE_TUNING`, `ENCODE_TUNING` |
| `fps_audio_oversample` | `AUDION_FPS_AUDIO_OVERSAMPLE` |
| `fps_audio_pcm_depth` | `AUDION_FPS_AUDIO_PCM_DEPTH` |
| `fps_output_profile` | `AUDION_FPS_OUTPUT_PROFILE`, `OUT_MODE` |
| `input_formats` | `AUDION_INPUT_FORMATS`, `INPUT_FORMATS` |
| `limit_first_file` | `AUDION_LIMIT_FIRST_FILE`, `AUDION_FIRST_FILE`, `FIRST_FILE` |
| `lut_file` | `AUDION_LUT_FILE`, `LUT_FILE`, `ACTIVE_LUT` |
| `mp3_lame_preset` | `AUDION_MP3_LAME_PRESET`, `MP3_LAME_PRESET` |
| `nvenc_preset` | `AUDION_NVENC_PRESET` |
| `overwrite` | `AUDION_OVERWRITE`, `OVERWRITE` |
| `pix_fmt` | `AUDION_PIX_FMT`, `PIX_FMT` |
| `pre_gamma` | `AUDION_PRE_GAMMA`, `PRE_GAMMA` |
| `qsv_encoder_preset` | `AUDION_QSV_ENCODER_PRESET` |
| `target_codecs` | `AUDION_TARGET_CODECS`, `TARGET_CODECS` |
| `trim_audio` | `AUDION_TRIM_AUDIO` |
| `trim_audio_channel` | `AUDION_TRIM_AUDIO_CHANNEL` |
| `trim_container` | `AUDION_TRIM_CONTAINER` |
| `trim_data` | `AUDION_TRIM_DATA` |
| `trim_end` | `AUDION_TRIM_END`, `TRIM_END` |
| `trim_faststart` | `AUDION_TRIM_FASTSTART` |
| `trim_file` | `AUDION_TRIM_FILE`, `TRIM_FILE` |
| `trim_start` | `AUDION_TRIM_START`, `TRIM_START` |
| `trim_subtitles` | `AUDION_TRIM_SUBTITLES` |
| `trim_timecode` | `AUDION_TRIM_TIMECODE` |
| `youtube_url` | `AUDION_YOUTUBE_URL`, `YOUTUBE_URL`, `URL` |
