# Download

[Русский](YOUTUBE_DOWNLOAD_RU.md)

## Purpose

The DOWNLOAD section uses yt-dlp from the program folder (`Tools\yt-dlp`; for YouTube, Deno is needed next to it, and it is
installed together with yt-dlp). The modes of the section are format profiles: BEST MP4, SAFE MP4, OWN VIDEO, FOR UPLOAD,
OWN AUDIO, SUBTITLES. What is downloaded goes into `output\Download` (or into `Download` of the selected Target); the
progress of the download is shown as `[download]` lines in the journal. A file is named
`<uploader>\<date> - <title> [<id>].<ext>`, in a playlist `<number> - <title> [<id>].<ext>`; at the end the journal
names every file written in an `[OK]` line, and the outcome of the console command lists them in `downloaded`.

## Sources

The `Source` field of the section:

- `Single URL` - the `URL` field. The `PASTE` button on the right takes the link from the clipboard; ⓘ shows in the
  journal which formats the link offers (resolution, codecs, size), without downloading anything. A link to a video
  inside a playlist takes this one video.
- `input\urls.txt` - a list of links, one per line. Another file can be chosen (`Batch file`, with the same `PASTE`
  button for the path).
- `Playlist` - the whole playlist by the link; `Playlist items` takes a part of it, for example `1-10` or `3,5,7`.

`Section` downloads a piece by time, not the whole video.

## Format profiles

| mode | what it takes |
|---|---|
| BEST MP4 | the best video and sound, merged into MP4/M4A; a general profile without special requirements. The picture may come in AV1, which not every program plays |
| SAFE MP4 | for fragile links that break off: another client, retries, IPv4 |
| OWN VIDEO | the resolution, codec, sound and container are set by the fields below |
| FOR UPLOAD | H.264 with AAC sound in MP4: what any platform and program accepts |
| OWN AUDIO | only the sound, in the selected format |
| SUBTITLES | only the subtitles, without media |

The presets above the fields (`Download profile`) are ready combinations: Best MP4 video, 1080p AVC MP4, Safe Safari, AV1
if available, Audio MP3, Batch from urls.txt.

## Video and sound

Fields:

- `Resolution`: Best, 2160p, 1440p, 1080p, 720p, 480p.
- `Video codec`: Auto, AVC/H.264, AV1, VP9.
- `Audio format`: Source / native, M4A, Opus, MP3.
- `Container`: MP4, MKV, WEBM.

Recommendations:

- For maximum compatibility: FOR UPLOAD or the 1080p AVC MP4 preset.
- For an ordinary download without strict requirements: BEST MP4.
- Sound only: OWN AUDIO (for example, `Audio format` = M4A) or the Audio MP3 preset.
- Subtitles without media: SUBTITLES.

## Download tuning

Ticks:

- `Retries` - useful on an unstable network.
- `IPv4` - sometimes helps if the IPv6 route breaks the download.
- `Metadata + thumbnail` - embeds the metadata and the cover where possible.
- `No playlist` - for links from `input\urls.txt`: a playlist is not expanded by accident. A single link never expands a
  playlist.

`Parallel` - how many fragments are downloaded at once; `Client` - which client yt-dlp presents itself as to YouTube
(Default, Safari, Android).

## Subtitles

Fields:

- `Manual`;
- `Auto`;
- `Embed`;
- `Subtitle languages`.

It is better to give the languages explicitly, for example:

```text
ru,en
```

or:

```text
en.*,ru.*
```

depending on the yt-dlp format and the source.

## Cookies

Links where yt-dlp must see a sign-in to an account need cookies. The `Cookies` field:

- `None`;
- `Chrome`, `Edge`, `Firefox`, `Brave` - the cookies of the browser are taken at the moment of the download;
- `File` - a cookies file (`Cookies file`, by default `config\cookies.txt`; the `PASTE` button takes a path from the
  clipboard).

The shield next to the file seals it with DPAPI for this Windows account into `config\cookies.dpapi`: a download with
`File` takes this copy, and the open file is no longer needed; it can be deleted.

`File` is the default: the sealed copy, or without it the file of the field, goes with every download when there is one.
A public link needs no cookies - choose `None` for it.

Rules:

- do not keep cookies in a public repository;
- do not send cookies together with reports;
- on errors, first check the path and the format of the cookies file.

## Download archive

`Use download archive` turns on the yt-dlp archive (`config\download-archive.txt`). It is off by default, so that the
user decides explicitly whether links that were already downloaded are skipped.

Turn the archive on if a batch repeats regularly and it matters not to download the same thing twice.

## Dry run

`Dry run` and the COMMAND button show the real yt-dlp call before the run.

Check it when you change:

- the client;
- the cookies;
- the subtitles;
- the container;
- the source of the links;
- the download archive.

## Typical errors

### A playlist was downloaded instead of one video

These are links from `input\urls.txt`: turn on `No playlist`.

### The link works in the browser but not in yt-dlp

Try:

1. SAFE MP4 or the Safe Safari preset;
2. `IPv4`;
3. the browser cookies;
4. update yt-dlp: SETTINGS → COMPONENTS → UPDATE, or SERVICE → «Install yt-dlp».

### Wrong subtitles

Check `Subtitle languages` and separate the manual and the automatic ones. Some sources have only automatic ones.

### MP4 did not come out

Reasons:

- the source gives only VP9/AV1/WebM;
- an incompatible combination of codec and container is selected;
- yt-dlp cannot merge the streams without re-encoding.

For compatibility choose FOR UPLOAD.
