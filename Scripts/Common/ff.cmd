@echo off

set "FFMPEG="
set "FFPROBE="
set "YTDLP="
set "DENO="
set "SEVENZIP="

if exist "%TOOLS%\ffmpeg\bin\ffmpeg.exe" set "FFMPEG=%TOOLS%\ffmpeg\bin\ffmpeg.exe"
if exist "%TOOLS%\ffmpeg\bin\ffprobe.exe" set "FFPROBE=%TOOLS%\ffmpeg\bin\ffprobe.exe"
if exist "%TOOLS%\yt-dlp\bin\yt-dlp.exe" set "YTDLP=%TOOLS%\yt-dlp\bin\yt-dlp.exe"
if exist "%TOOLS%\deno\deno.exe" set "DENO=%TOOLS%\deno\deno.exe"
if not defined DENO if exist "%TOOLS%\deno\bin\deno.exe" set "DENO=%TOOLS%\deno\bin\deno.exe"
if exist "%TOOLS%\7zip\bin\7z.exe" set "SEVENZIP=%TOOLS%\7zip\bin\7z.exe"

if not defined FFMPEG if exist "%ROOT%\ffmpeg.exe" set "FFMPEG=%ROOT%\ffmpeg.exe"
if not defined FFPROBE if exist "%ROOT%\ffprobe.exe" set "FFPROBE=%ROOT%\ffprobe.exe"

if not defined FFMPEG (
  echo [ERROR] ffmpeg.exe was not found in "%TOOLS%\ffmpeg\bin".
  exit /b 1
)

if not defined FFPROBE (
  echo [ERROR] ffprobe.exe was not found in "%TOOLS%\ffmpeg\bin".
  exit /b 1
)

set "PATH=%TOOLS%\ffmpeg\bin;%TOOLS%\yt-dlp\bin;%TOOLS%\deno;%TOOLS%\deno\bin;%TOOLS%\7zip\bin;%PATH%"
