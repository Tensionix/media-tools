r"""The stack of short samples a live run goes over: minutes of compute, not a week.

Cut from the owner's material in `input` - a few seconds of each file, the streams copied as they are, so a
sample keeps its codec, its rates, its timecode track and its quirks - and made by FFmpeg for what the
material does not have: 5.1, 50p, 59.94p, 25i, a variable rate, HDR10, telemetry as subtitles, sound alone.

The stack lies beside the program, not in it: `..\Audion Media Tools Samples` (or AUDION_MEDIA_SAMPLES).
Part of it is other people's material - a music video, ARRI's own clips - and no archive of the program
may carry it; a folder beside the program is in none of them.

    runtime\python.exe tests\make_samples.py [--from <folder>] [--to <folder>] [--seconds 3]

samples.json in the stack names every sample, what it was made from, what it is for and what ffprobe says
of it; README.md says the same for a person.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
TOOLS = PROJECT / "Tools" / "ffmpeg" / "bin"
FFMPEG, FFPROBE = TOOLS / "ffmpeg.exe", TOOLS / "ffprobe.exe"

# What is cut from the owner's material: the file, the name of its sample, where the cut starts, what it is for.
CUTS = [
    ("ALEXA 35 Encounters – “An Ancestral Path” [pOvXh6VhQFQ].webm", "vp9_4k_24p_opus.webm", 30.0,
     "VP9 4K 24p with Opus in WebM: a download as it comes; remux to MKV, sound out of Opus"),
    ("ARRI Tech Talk - B-Mount Battery Systems [-cJbkkHvGKI].mp4", "h264_1080_24p_aac44k.mp4", 60.0,
     "H.264 1080p 24p, AAC at 44.1 kHz: resampling to 48 kHz, delivery"),
    ("Ellie Goulding - Something In The way You Move_Fragment.mov", "prores_lt_4k_23976.mov", 0.0,
     "ProRes LT 4096x2160 10-bit 23.976, AAC: editing, storage, trim on a 23.976 grid"),
    ("FullHD 120 FPS Slo-Mo Canon EOS 90D.MP4", "h264_1080_2997_slomo_noaudio.mp4", 10.0,
     "H.264 1080p 29.97 (120 fps slow motion played at 29.97), no sound: frame rate, a file without sound"),
    ("ISO_800_ARRI.mov", "prores4444_uhd_25p_pcm_tc_arri.mov", 1.0,
     "ProRes 4444 UHD 12-bit 25p, PCM, timecode track: LUT, conform 25 -> 23.976, MOV -> MXF", 2.0),
    ("ISO_800_RED.mov", "prores4444_uhd_25p_pcm_tc_red.mov", 1.0, "the same of a RED camera: LUT", 2.0),
    ("ISO_800_SONY.mov", "prores4444_uhd_25p_pcm_tc_sony.mov", 1.0, "the same of a Sony camera: LUT", 2.0),
    ("UHD Canon EOS 90D Cropped mode.MP4", "h264_uhd_23976_aac_canon90d.mp4", 5.0,
     "H.264 UHD 23.976 full range (yuvj420p), AAC: storage, delivery"),
    ("UHD Canon EOS R8.MP4", "h264_uhd_23976_pcm_be_tc_canonr8.mp4", 3.0,
     "H.264 UHD 23.976 with PCM big-endian and a timecode track in MP4: remux to MOV, sound out"),
    ("8K VIDEO.mkv", "av1_8k_30p_aac44k.mkv", 20.0, "AV1 8K 30p, AAC 44.1 kHz: decoding (dav1d, NVDEC, QSV, AMF) of the heaviest"),
]
# The whole file is the sample: what makes it a case is how it ends.
WHOLE = [
    ("Ellie Goulding - Something In The way You Move_Fragment.mov", "prores_lt_4k_23976_avg24016_whole.mov",
     "the patient: 24000/1001 stated, 24.016 averaged (599 frames in 24.94 s) - a frame grid and a conform must take 23.976. "
     "A cut of it averages 24000/1001 again, so the whole file stands here; for the decisions on its rate and a dry run, "
     "not for encoding"),
]
# The head of a file FFmpeg cannot decode: enough for a probe to see what it is.
HEADS = [
    ("ARRI_Helen_John_ALEXA_35_ARRIRAW.mxf", "arriraw_alexa35_head.mxf", 64,
     "ARRIRAW in MXF: FFmpeg sees a video stream with no codec and no size - a refusal said plainly, not a crash"),
]
# What the material does not have, made by FFmpeg.
PICTURE = "testsrc2=size=1920x1080:rate={rate}:duration={seconds}"
SYNTH = [
    ("synth_h264_1080_25p_pcm24_51.mov", "5.1 PCM 24-bit 48 kHz: downmix to stereo, channels, LUFS",
     ["-f", "lavfi", "-i", PICTURE.format(rate=25, seconds="{s}"),
      "-f", "lavfi", "-i", "sine=f=220:d={s}:sample_rate=48000", "-f", "lavfi", "-i", "sine=f=330:d={s}:sample_rate=48000", "-f", "lavfi", "-i", "sine=f=440:d={s}:sample_rate=48000",
      "-f", "lavfi", "-i", "sine=f=55:d={s}:sample_rate=48000", "-f", "lavfi", "-i", "sine=f=550:d={s}:sample_rate=48000", "-f", "lavfi", "-i", "sine=f=660:d={s}:sample_rate=48000",
      "-filter_complex", "[1][2][3][4][5][6]join=inputs=6:channel_layout=5.1[a]", "-map", "0:v", "-map", "[a]",
      "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "pcm_s24le"]),
    ("synth_h264_1080_50p_aac.mp4", "50p: frame rate to 25 and to 23.976",
     ["-f", "lavfi", "-i", PICTURE.format(rate=50, seconds="{s}"), "-f", "lavfi", "-i", "sine=f=440:d={s}:sample_rate=48000",
      "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac", "-ac", "2", "-shortest"]),
    ("synth_h264_1080_5994p_aac.mp4", "59.94p: frame rate to 29.97 and to 23.976",
     ["-f", "lavfi", "-i", PICTURE.format(rate="60000/1001", seconds="{s}"), "-f", "lavfi", "-i", "sine=f=440:d={s}:sample_rate=48000",
      "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac", "-ac", "2", "-shortest"]),
    ("synth_h264_1080_25i_tff_aac.mp4", "25i, top field first: an interlaced source - the nominal rate may read as 50",
     ["-f", "lavfi", "-i", PICTURE.format(rate=50, seconds="{s}"), "-f", "lavfi", "-i", "sine=f=440:d={s}:sample_rate=48000",
      "-vf", "interlace=scan=tff,setfield=tff", "-c:v", "libx264", "-preset", "ultrafast", "-flags", "+ildct+ilme",
      "-x264-params", "tff=1", "-pix_fmt", "yuv420p", "-c:a", "aac", "-ac", "2", "-shortest"]),
    ("synth_h264_1080_vfr_aac.mp4", "a variable rate, as a phone writes it: a trim by time, a conform from the nominal rate",
     ["-f", "lavfi", "-i", PICTURE.format(rate=30, seconds="{s}"), "-f", "lavfi", "-i", "sine=f=440:d={s}:sample_rate=48000",
      "-vf", "select='not(eq(mod(n\\,7)\\,3))',setpts=N/(30*TB)+if(gte(N\\,40)\\,0.12\\,0)/TB", "-fps_mode", "vfr",
      "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac", "-ac", "2", "-shortest"]),
    ("synth_hevc10_uhd_2398p_hdr10_pq.mkv", "HDR10: HEVC Main10, BT.2020, PQ, mastering display - HDR to SDR",
     ["-f", "lavfi", "-i", "testsrc2=size=3840x2160:rate=24000/1001:duration={s}",
      "-vf", "format=yuv420p10le", "-c:v", "libx265", "-preset", "ultrafast",
      "-x265-params", "hdr10=1:colorprim=bt2020:transfer=smpte2084:colormatrix=bt2020nc:range=limited:"
                      "master-display=G(13250,34500)B(7500,3000)R(34000,16000)WP(15635,16450)L(10000000,1):max-cll=1000,400",
      "-color_primaries", "bt2020", "-color_trc", "smpte2084", "-colorspace", "bt2020nc"]),
    ("synth_h264_1080_2997p_telemetry_subs.mp4", "flight data as subtitles, as a DJI writes it: the trim rebuilds them",
     ["-f", "lavfi", "-i", PICTURE.format(rate="30000/1001", seconds="{s}"), "-f", "lavfi", "-i", "sine=f=440:d={s}:sample_rate=48000",
      "-i", "{srt}", "-map", "0:v", "-map", "1:a", "-map", "2:s", "-c:v", "libx264", "-preset", "ultrafast",
      "-pix_fmt", "yuv420p", "-c:a", "aac", "-c:s", "mov_text", "-shortest"]),
    ("synth_wav_s24_96k_stereo.wav", "sound alone: WAV 24-bit 96 kHz", ["-f", "lavfi", "-i", "sine=f=440:d={s}:sample_rate=96000",
                                                                         "-ac", "2", "-c:a", "pcm_s24le"]),
    ("synth_flac_44k_stereo.flac", "sound alone: FLAC 44.1 kHz", ["-f", "lavfi", "-i", "sine=f=440:d={s}:sample_rate=44100",
                                                                   "-ac", "2", "-c:a", "flac"]),
    ("synth_mp3_320_stereo.mp3", "sound alone: MP3 320", ["-f", "lavfi", "-i", "sine=f=440:d={s}:sample_rate=48000", "-ac", "2", "-c:a", "libmp3lame",
                                                          "-b:a", "320k"]),
    ("synth_mxf_mpeg2_1080p25_pcm.mxf", "MXF OP1a with MPEG-2 and PCM, as broadcast cameras write it",
     ["-f", "lavfi", "-i", PICTURE.format(rate=25, seconds="{s}"), "-f", "lavfi", "-i", "sine=f=440:d={s}:sample_rate=48000",
      "-c:v", "mpeg2video", "-b:v", "35M", "-pix_fmt", "yuv422p", "-c:a", "pcm_s24le", "-ar", "48000", "-shortest"]),
]


def samples_folder(given: str) -> Path:
    if given:
        return Path(given).resolve()
    if os.environ.get("AUDION_MEDIA_SAMPLES"):
        return Path(os.environ["AUDION_MEDIA_SAMPLES"]).resolve()
    return PROJECT.parent / f"{PROJECT.name} Samples"


def probe(path: Path) -> dict:
    done = subprocess.run([str(FFPROBE), "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(path)],
                          capture_output=True, text=True, encoding="utf-8", errors="replace")
    try:
        data = json.loads(done.stdout or "{}")
    except ValueError:
        data = {}
    streams = []
    for stream in data.get("streams", []):
        told = {key: stream.get(key) for key in ("codec_type", "codec_name", "profile", "width", "height", "pix_fmt", "field_order",
                                                 "r_frame_rate", "avg_frame_rate", "color_transfer", "color_primaries",
                                                 "sample_rate", "channels", "channel_layout", "duration") if stream.get(key) not in (None, "")}
        streams.append(told)
    fmt = data.get("format", {})
    return {"format": fmt.get("format_name", ""), "seconds": round(float(fmt.get("duration", 0) or 0), 3),
            "megabytes": round(path.stat().st_size / 1048576, 1), "streams": streams, "error": done.stderr.strip()[:300]}


def ffmpeg(arguments: list[str]) -> str:
    done = subprocess.run([str(FFMPEG), "-hide_banner", "-loglevel", "error", "-y", *arguments],
                          capture_output=True, text=True, encoding="utf-8", errors="replace")
    return "" if done.returncode == 0 else (done.stderr.strip() or f"exit {done.returncode}")[-400:]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--from", dest="source", default=str(PROJECT / "input"))
    parser.add_argument("--to", dest="target", default="")
    parser.add_argument("--seconds", type=float, default=3.0)
    args = parser.parse_args()
    source, target, seconds = Path(args.source).resolve(), samples_folder(args.target), float(args.seconds)
    target.mkdir(parents=True, exist_ok=True)
    made: list[dict] = []

    def record(name: str, made_from: str, purpose: str, trouble: str) -> None:
        path = target / name
        entry = {"sample": name, "from": made_from, "for": purpose}
        if trouble or not path.is_file():
            entry["failed"] = trouble or "not made"
        else:
            entry["probe"] = probe(path)
        made.append(entry)
        print(("FAIL " if "failed" in entry else "ok   ") + name + (f"  - {entry.get('failed')}" if "failed" in entry else ""))

    for original, name, start, purpose, *own in CUTS:
        path = source / original
        if not path.is_file():
            print(f"skip {name} - no {original}")
            continue
        length = float(own[0]) if own else seconds
        # The streams as they are; a timecode or data track goes along where the container keeps it. A long-GOP
        # stream is cut at its keyframes: a VP9 or an AV1 sample comes out longer than asked.
        trouble = ffmpeg(["-ss", f"{start}", "-i", str(path), "-t", f"{length}", "-map", "0", "-c", "copy",
                          "-avoid_negative_ts", "make_zero", str(target / name)])
        if trouble:
            trouble = ffmpeg(["-ss", f"{start}", "-i", str(path), "-t", f"{length}", "-map", "0:v:0", "-map", "0:a?", "-c", "copy",
                              "-avoid_negative_ts", "make_zero", str(target / name)])
        record(name, original, purpose, trouble)
    for original, name, purpose in WHOLE:
        path = source / original
        if path.is_file():
            shutil.copy2(path, target / name)
            record(name, original, purpose, "")
    for original, name, megabytes, purpose in HEADS:
        path = source / original
        if path.is_file():
            with path.open("rb") as reader, (target / name).open("wb") as writer:
                writer.write(reader.read(megabytes * 1048576))
            record(name, original, purpose, "")
    srt = target / "_telemetry.srt"
    lines = []
    for index in range(int(seconds * 2)):
        begin, end = index * 0.5, index * 0.5 + 0.5
        stamp = lambda value: f"00:00:{int(value):02d},{int(round((value % 1) * 1000)):03d}"  # noqa: E731
        lines += [str(index + 1), f"{stamp(begin)} --> {stamp(end)}",
                  f"F/2.8, SS 500, ISO 100, EV 0, GPS (37.{7700 + index}, -122.{4100 + index}, 19) D {12.5 + index:.1f}m H {30 + index:.2f}m", ""]
    srt.write_text("\n".join(lines), encoding="utf-8")
    for name, purpose, arguments in SYNTH:
        filled = [item.replace("{s}", f"{seconds:g}").replace("{srt}", str(srt)) for item in arguments]
        record(name, "made by FFmpeg", purpose, ffmpeg([*filled, str(target / name)]))
    srt.unlink(missing_ok=True)

    (target / "samples.json").write_text(json.dumps(made, ensure_ascii=False, indent=1), encoding="utf-8")
    rows = ["# Samples of Audion Media Tools", "",
            "Short samples for live runs, made by `tests\\make_samples.py` of the program. Part of them is other people's",
            "material cut from the owner's files: **this folder is never published and goes into no archive.**", "",
            "| Sample | MB | Made from | For |", "|---|---|---|---|"]
    for entry in made:
        size = entry.get("probe", {}).get("megabytes", "-")
        rows.append(f"| {entry['sample']} | {size} | {entry['from']} | {entry['for']}{' - FAILED: ' + entry['failed'] if 'failed' in entry else ''} |")
    (target / "README.md").write_text("\n".join(rows) + "\n", encoding="utf-8")
    failed = [entry["sample"] for entry in made if "failed" in entry]
    print(f"{len(made) - len(failed)} made, {len(failed)} failed -> {target}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
