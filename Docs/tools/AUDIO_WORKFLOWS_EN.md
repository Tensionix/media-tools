# Audio

[Русский](AUDIO_WORKFLOWS_RU.md)

## The Main Idea

The AUDIO section covers three different tasks that are easy to confuse:

- EXTRACT;
- SOUND IN VIDEO;
- CONVERT.

These are the modes of the section: a row of buttons under the ribbon. Each one has a tooltip that explains it. If in doubt, hold the cursor over a mode for a second.

## Mode: Extract Audio

Makes separate audio files from video containers. The video is not copied into the result.

Use it to:

- take WAV out of MOV/MP4/MKV/MXF;
- get FLAC/M4A/MP3/Opus from a video;
- extract all audio streams;
- make a LUFS report or a normalized audio delivery.

The Target keeps the structure of the Source.

## Mode: Sound In Video

Makes a new video file: the video streams are copied, and the selected audio streams are changed inside the container.

Technically this is `-c:v copy` plus processing of the audio stream.

Use it when you need to:

- change the sample rate of the audio in a video;
- change PCM/AAC parameters without re-encoding the picture;
- normalize the sound without touching the picture;
- make a MOV/MKV/MP4 with a new audio stream.

Container advice:

- PCM/FLAC is safer in MOV or MKV.
- AAC/MP3 usually suit MP4.
- The `Source` container is good when the source file is already compatible with the selected audio format.

## Mode: Convert Audio

Processes separate sound files from the Source:

- WAV;
- FLAC;
- M4A;
- MP3;
- AAC;
- Opus.

Use it for:

- resampling of libraries;
- normalization of music/speech;
- batch conversion WAV -> FLAC/M4A/MP3/Opus;
- downmix to mono/stereo.

## Profiles

The main presets:

- `WAV 24/48` - PCM WAV for editing.
- `WAV float 48 kHz` - 32-bit float for restoration.
- `FLAC 24-bit 48 kHz` - lossless archive audio.
- `M4A 384k` - AAC for review/delivery.
- `M4A 256k` - compact AAC.
- `Video copy + PCM 24/48 SoX` - the sound inside MOV, the video is not touched.
- `Video copy + AAC 384/48 SoX` - AAC inside the container.
- `MP3 LAME V0` - high-quality VBR.
- `MP3 Insane 320` - CBR 320.
- `Opus 192k` - modern compact audio delivery.
- `M4A 384k LUFS -14` - two-pass loudnorm.
- `WAV stereo downmix` - downmix.
- `5.1 Matrix WAV` - matrix-compatible stereo.
- `Copy all audio streams` - extract all streams without re-encoding.
- `LUFS report` - loudness analysis without encoding.

The audio presets are shown as buttons. A button does not only choose the name of the mode: it also changes the parameters below at once: workflow, format, Copy container, bitrate, LUFS, channels and other related fields. Colors of the groups: Copy/remux - dark green, lossless/PCM - dark teal, lossy delivery - dark orange.

## Source Filter

The `Source file filter` field limits the extensions. If it is empty, the operation takes its own supported types.

On the audio page these are available:

```text
WAV W64 FLAC M4A M4B AAC MP3 Opus OGA OGG AIF AIFF CAF AU SND
AC3 E-AC3 DTS MKA APE WV TAK TTA MPC AMR AWB SPX DSF DFF
MP4 M4V MOV MKV MXF AVI WEBM MPG MPEG MTS M2TS TS 3GP
```

The Source is scanned recursively; the Target repeats the structure of the subfolders.

## Format

Available:

- `Copy` - the selected audio stream is not re-encoded.
- `WAV` - PCM.
- `FLAC` - lossless, `-compression_level 8`. The same level is used for FLAC inside video (for example in the archive FFV1) and in the CLI profiles, so that one format is not encoded in different ways.
- `ALAC` - Apple Lossless in M4A.
- `M4A / AAC` - AAC delivery.
- `MP3` - LAME.
- `Opus` - modern compact audio.

`Copy` is not compatible with every change. If the sample rate, bit depth, LUFS or channels change, a re-encode is needed.

For `Copy` there is a container policy:

- `Auto` - picks a practical container by codec and channels: AAC stereo/mono -> M4A, AC3/E-AC3/DTS -> the codec's own file, unknown or multichannel AAC -> MKA.
- `M4A` - forces M4A for compatible streams, otherwise falls back to MKA.
- `MKA` - always Matroska Audio.
- `Codec file` - writes an elementary file where possible: AAC, AC3, E-AC3, DTS, FLAC, MP3 and so on.

## Sample Rate, Bit Depth And Resampler

Sample rate:

- `COPY`;
- `44.1 kHz`;
- `48 kHz`;
- `96 kHz`.

Bit depth:

- `COPY`;
- `16-bit`;
- `24-bit`;
- `32-bit float`.

Resampler:

- `SoX 100% quality` - every change of the rate goes through libsoxr with `precision=33`.

The available rates are grouped by multiples: Copy/source, 44.1/88.2/176.4 kHz and 48/96/192 kHz.

## Streams

Modes:

- `First stream`;
- `All streams`;
- `By index`;
- `By language`.

The audio stream index counts from zero: `a0` is the first audio stream.

Selection by language uses the container tags: `eng`, `rus`, `ukr` and others.

## LUFS

Fields:

- `LUFS`: off, -14, -16, -23.
- `LUFS mode`: off, report, one-pass, two-pass.

Recommendations:

- `Report only` - measure the material first.
- `One pass` - fast.
- `Two pass` - more accurate and better for the final normalization.
- `-14` - often used for streaming-style loudness.
- `-23` - a broadcast-style target.

## Channels

Choices:

- `Keep`;
- `Stereo`;
- `Mono`;
- `Dual mono`;
- `5.1 Matrix`.

`5.1 Matrix` adds DPLII matrix compatibility when the sound is downmixed to stereo.

## MP3 / LAME

Choices:

- `VBR V0` (about 245 kbps);
- `Insane 320`;
- `By bitrate`.

For music V0 is usually better. For strict systems that need CBR, choose 320.

The same scale works in the ENCODE (ARCHIVE, EDITING, STORAGE, DELIVERY) and COLOR sections when `Audio = MP3`, and in the CLI through `AUDION_MP3_LAME_PRESET`. The default is `v0` everywhere.

`By bitrate` is limited to 320 kbps: MPEG-1 Layer III cannot go higher, and LAME lowers a bigger value silently, so the file name would promise a bitrate that the file does not have.

## Audio Report

After processing, these files are written:

```text
audio_report.md
audio_report.json
```

The report contains:

- the source file;
- the stream selection;
- the input audio parameters;
- the output path;
- the codec/format;
- the LUFS data, if it was measured;
- the errors per file.

## Common Solutions

### Need To Take WAV Out For Editing

Profile `WAV 24/48`, mode `EXTRACT`, stream `First stream` or `All streams`.

### Need To Change The Sound In A Video Without Re-encoding The Picture

Profile `Video copy + PCM 24/48 SoX` or `Video copy + AAC 384/48 SoX`, mode `SOUND IN VIDEO`.

### Need To Process Folders With The Same File Names

Just use a Source with subfolders: the Target keeps the structure.

### Need Only To Know The Loudness

Profile `LUFS report`, LUFS mode `Report only`, no overwrite.

### Need To Cut A Piece Out Of A Sound File

This is not done here but in the CUT section: WAV, FLAC, MP3 and the others are cut there
exactly on the sample, and the piece is written as it was or in a format from the same set
as in this section. Details: `TRIM_EN.md`.
