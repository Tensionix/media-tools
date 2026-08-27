@echo off
setlocal EnableDelayedExpansion
set "HERE=%~dp0"
set "BASE=%HERE%\.."
for %%A in ("%BASE%") do set "BASE=%%~fA\"
set "SRC=%BASE%Source"
set "OUT=%BASE%Transcoded"
set "LUTS=%BASE%LUTs"
set "FFBIN=%BASE%Tools\ffmpeg\bin"
set "YTDLPBIN=%BASE%Tools\yt-dlp\bin"
set "PATH=%FFBIN%;%YTDLPBIN%;%PATH%"
if not exist "%OUT%" mkdir "%OUT%" >nul 2>&1
REM SAFE GPU decode flag for CPU encoders
if "%USE_GPU%"=="1" ( set "GPU_DEC=-hwaccel cuda" ) else ( set "GPU_DEC=" )
echo --- ffmpeg / ffprobe ---
ffmpeg -hide_banner -version | findstr /R /C:"ffmpeg version" /C:"configuration"
ffprobe -hide_banner -version | findstr /R /C:"ffprobe version" /C:"configuration"
echo.
echo --- Filters check (zscale/tonemap) ---
ffmpeg -hide_banner -filters | findstr /I "zscale tonemap" || echo [!] zscale/tonemap not found.
echo.
echo SRC=%SRC%
echo OUT=%OUT%
endlocal
if not defined AUDION_NO_PAUSE pause
