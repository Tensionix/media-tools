# FFmpeg Gyan FULL Build Notice

Audion Media Tools installers use Gyan FULL Windows FFmpeg builds for `Tools\ffmpeg\bin`.

Before publishing a release archive that bundles FFmpeg binaries:

- record the output of `Tools\ffmpeg\bin\ffmpeg.exe -hide_banner -version`;
- record the output of `Tools\ffmpeg\bin\ffmpeg.exe -hide_banner -buildconf`;
- identify the exact Gyan package used and its source commit URL;
- publish or link the matching FFmpeg source/build information next to the release archive;
- do not use FFmpeg builds that require `--enable-nonfree` or otherwise become non-redistributable.

Reference pages:

- FFmpeg legal information: https://www.ffmpeg.org/legal.html
- Gyan FFmpeg builds: https://www.gyan.dev/ffmpeg/builds/
