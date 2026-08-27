@echo off
setlocal EnableExtensions
chcp 65001 >nul

rem Common portable environment for scripts living in Scripts\.
rem Override contract shared with the GUI:
rem   AUDION_SOURCE / AUDION_OUTPUT / AUDION_DOWNLOAD
rem   AUDION_CRF / AUDION_CQ / AUDION_AUDIO_BITRATE
rem   AUDION_ENCODE_BACKEND / AUDION_DECODE_BACKEND
rem   AUDION_DRY_RUN / AUDION_OVERWRITE / AUDION_LIMIT_FIRST_FILE
rem   AUDION_YTDLP_JS_RUNTIMES / AUDION_YTDLP_COOKIES_BROWSER
rem   AUDION_YTDLP_COOKIES / AUDION_YTDLP_SPONSORBLOCK

set "COMMON_DIR=%~dp0"
for %%A in ("%COMMON_DIR%..\..") do set "ROOT=%%~fA"
if defined AUDION_ROOT for %%A in ("%AUDION_ROOT%") do set "ROOT=%%~fA"

call "%COMMON_DIR%paths.cmd" || exit /b 1
call "%COMMON_DIR%colors.cmd" || exit /b 1
call "%COMMON_DIR%ff.cmd" || exit /b 1
call "%COMMON_DIR%io.cmd" || exit /b 1
call "%COMMON_DIR%audio.cmd" || exit /b 1
call "%COMMON_DIR%menu.cmd" || exit /b 1

set "STATS=-stats"
set "STATS_PERIOD="
set "AUDION_AUDIO_BITRATE_DEFAULT=384k"
set "AUDION_CRF_DEFAULT=14"
set "AUDION_CQ_DEFAULT=14"

endlocal & (
  set "COMMON_DIR=%COMMON_DIR%"
  set "ROOT=%ROOT%"
  set "SRC=%SRC%"
  set "OUT=%OUT%"
  set "DL=%DL%"
  set "LOG=%LOG%"
  set "TOOLS=%TOOLS%"
  set "FFMPEG=%FFMPEG%"
  set "FFPROBE=%FFPROBE%"
  set "YTDLP=%YTDLP%"
  set "DENO=%DENO%"
  set "SEVENZIP=%SEVENZIP%"
  set "AUDIO_PCM24=%AUDIO_PCM24%"
  set "AUDIO_PCM32F=%AUDIO_PCM32F%"
  set "STATS=%STATS%"
  set "STATS_PERIOD=%STATS_PERIOD%"
  set "AUDION_AUDIO_BITRATE_DEFAULT=%AUDION_AUDIO_BITRATE_DEFAULT%"
  set "AUDION_CRF_DEFAULT=%AUDION_CRF_DEFAULT%"
  set "AUDION_CQ_DEFAULT=%AUDION_CQ_DEFAULT%"
)
