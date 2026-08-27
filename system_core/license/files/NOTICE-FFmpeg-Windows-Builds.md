# FFmpeg Windows Build Notice

Audion Media Tools installers can install either BtbN win64 GPL builds or Gyan FULL Windows FFmpeg builds into `Tools\ffmpeg\bin`.

Before publishing a release archive that bundles FFmpeg binaries:

- record the output of `Tools\ffmpeg\bin\ffmpeg.exe -hide_banner -version`;
- record the output of `Tools\ffmpeg\bin\ffmpeg.exe -hide_banner -buildconf`;
- identify the exact FFmpeg package used and its source/build information;
- publish or link the matching FFmpeg source/build information next to the release archive;
- do not use FFmpeg builds that require `--enable-nonfree` or otherwise become non-redistributable.

Reference pages:

- FFmpeg legal information: https://www.ffmpeg.org/legal.html
- BtbN FFmpeg builds: https://github.com/BtbN/FFmpeg-Builds
- Gyan FFmpeg builds: https://www.gyan.dev/ffmpeg/builds/
