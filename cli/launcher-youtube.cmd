@echo off
setlocal EnableExtensions EnableDelayedExpansion
chcp 65001 >nul
title 🎬 YouTube Downloader (legacy)
REM Base layout
for %%A in ("%~dp0..") do set "BASE=%%~fA\"
set "SCRIPTS=%BASE%Scripts"
set "TOOLS=%BASE%Tools"
set "YTDLP=%TOOLS%\yt-dlp\bin\yt-dlp.exe"
set "FZF_EXE=%BASE%system_core\fzf.exe"
set "RUNTIME_DIR=%BASE%._runtime"
set "MENU_FILE=%RUNTIME_DIR%\launcher_youtube_menu.tmp"
set "RESULT_FILE=%RUNTIME_DIR%\launcher_youtube_selection.tmp"
REM Prefer Download\ (singular); if only Downloads\ exists, use it; else create Download\
set "DL=%BASE%Download"
if exist "%BASE%Downloads" set "DL=%BASE%Downloads"
if not exist "%DL%" mkdir "%DL%" >nul 2>&1
if not exist "%RUNTIME_DIR%" mkdir "%RUNTIME_DIR%" >nul 2>&1
REM Fixed-width description column (we measure ASCII "plain" label)
set "COLW=44"
cls
echo.
echo 🎬 YOUTUBE DOWNLOADER  (yt-dlp)
echo ------------------------------------------------------------
echo Auto-discovery: only existing yt-*.cmd scripts are listed.
echo Output folder: %DL%\
echo.
set COUNT=0
set "FZF_ACTIVE="
if exist "%FZF_EXE%" set "FZF_ACTIVE=1"
>"%MENU_FILE%" type nul
call :H "📺 Video (MP4)"
call :ADD "yt-best-mp4.cmd"            "✅ Best MP4 — default"                     "Best MP4 - default"
call :ADD "yt-1080p-avc-mp4.cmd"       "🎞️ 1080p AVC MP4"                          "1080p AVC MP4"
call :ADD "yt-best-mp4-safari.cmd"     "🧭 Best MP4 — Safari client"               "Best MP4 - Safari client"
call :ADD "yt-best-mp4-safe.cmd"       "🛡️ Best MP4 — SAFE mode (slow/retries)"    "Best MP4 - SAFE mode (slow/retries)"
call :ADD "yt-best-av1.cmd"            "🧠 Best AV1 (if available)"                "Best AV1 (if available)"
call :ADD "yt-webm-vp9.cmd"            "🌐 WebM VP9"                               "WebM VP9"
call :H "💬 Subtitles"
call :ADD "yt-embed-subs.cmd"          "📎 Embed subs into file"                   "Embed subs into file"
call :ADD "yt-subs-only.cmd"           "💬 Download subs only"                     "Download subs only"
call :H "🎧 Audio-only"
call :ADD "yt-best-m4a.cmd"            "🎧 Best M4A"                               "Best M4A"
call :ADD "yt-opus.cmd"                "🎚️ Opus"                                   "Opus"
call :ADD "yt-mp3.cmd"                 "🎵 MP3"                                    "MP3"
call :H "📚 Playlists"
call :ADD "yt-playlist-best.cmd"       "📚 Playlist — best"                        "Playlist - best"
call :ADD "yt-playlist-1080p-avc.cmd"  "🎞️ Playlist — 1080p AVC"                   "Playlist - 1080p AVC"
call :H "🧾 Batch (URLs.txt)"
call :ADD "yt-batch-best-mp4.cmd"      "🧾 Batch — best MP4"                       "Batch - best MP4"
call :ADD "yt-batch-480p-aac.cmd"      "📼 Batch — 480p + AAC"                     "Batch - 480p + AAC"
call :H "🧪 Advanced"
call :ADD "yt-clip-sections.cmd"       "✂️ Clip by sections"                       "Clip by sections"
call :ADD "yt-selftest.cmd"            "🧪 Selftest"                               "Selftest"
echo.
echo Helpers
echo   U) Update yt-dlp through portable installer
echo   T) 📝 Open URLs.txt (create if missing)
echo   O) 📂 Open output folder: %DL%\
echo   Q) Quit
echo.
if "%COUNT%"=="0" (
  echo [!] No yt-*.cmd found in "%SCRIPTS%".
  echo     Place your scripts there and re-run.
  if not defined AUDION_NO_PAUSE pause
  exit /b 1
)
if defined FZF_ACTIVE goto FZF_MENU
set /p PICK="Choose number or U/T/O/Q: "
goto HANDLE_PICK
:FZF_MENU
>>"%MENU_FILE%" echo [90]  ⬆️ UPDATE YT-DLP      ^| action ^| portable installer
>>"%MENU_FILE%" echo [91]  📝 OPEN URLS.TXT      ^| action ^| create when missing
>>"%MENU_FILE%" echo [92]  📂 OPEN OUTPUT FOLDER ^| action ^| %DL%
>>"%MENU_FILE%" echo [00]  BACK                  ^| back   ^| return to project menu
set "FZF_SMOKE_ARGS="
if "%AUDION_LAUNCHER_SMOKE%"=="1" set "FZF_SMOKE_ARGS=--filter=BACK --select-1 --exit-0"
type "%MENU_FILE%" | "%FZF_EXE%" --bind="backspace:abort" --prompt="audion@media [YOUTUBE] > " --pointer=">" --header="Pick download preset:" --layout=reverse --border=rounded --info=hidden --margin=1,2 !FZF_SMOKE_ARGS! >"%RESULT_FILE%"
set "SELECTED="
if exist "%RESULT_FILE%" set /p SELECTED=<"%RESULT_FILE%"
del /q "%MENU_FILE%" "%RESULT_FILE%" >nul 2>&1
if not defined SELECTED exit /b 0
set "PICK=!SELECTED:~1,2!"
if "!PICK!"=="00" set "PICK=Q"
if "!PICK!"=="90" set "PICK=U"
if "!PICK!"=="91" set "PICK=T"
if "!PICK!"=="92" set "PICK=O"
if not "!PICK:~0,1!"=="0" goto HANDLE_PICK
set /a PICK=1!PICK!-100
:HANDLE_PICK
if /I "%PICK%"=="Q" exit /b 0
if /I "%PICK%"=="O" ( start "" "%DL%" & exit /b 0 )
if /I "%PICK%"=="T" (
  if not exist "%DL%\urls.txt" type nul > "%DL%\urls.txt"
  start notepad "%DL%\urls.txt"
  exit /b 0
)
if /I "%PICK%"=="U" (
  if exist "%BASE%install\Install-Portable-yt-dlp.cmd" (
    call "%BASE%install\Install-Portable-yt-dlp.cmd" /NOPAUSE
  ) else (
    echo [!] Installer was not found.
  )
  if not defined AUDION_NO_PAUSE pause
  exit /b 0
)
set "TARGET="
for /f "tokens=2 delims==" %%Z in ('set ITEM[ ^| findstr /I /R "^ITEM\[%PICK%\]="') do set "TARGET=%%Z"
if not defined TARGET (
  echo [!] Invalid choice.
  if not defined AUDION_NO_PAUSE pause
  exit /b 1
)
echo.
set "URL="
set /p URL="(Optional) Paste URL and press Enter (leave blank to let the script prompt): "
echo.
echo [RUN] "%TARGET%" %URL%
if defined URL (
  call "%TARGET%" "%URL%"
) else (
  call "%TARGET%"
)
echo.
if not defined AUDION_NO_PAUSE pause
exit /b 0
:H
if defined FZF_ACTIVE exit /b 0
echo.
echo %~1
exit /b 0
:ADD
REM args: scriptName  displayText  plainText
set "FN=%~1"
set "DISP=%~2"
set "PLAIN=%~3"
if exist "%SCRIPTS%\%FN%" (
  set /a COUNT+=1
  set "ITEM[!COUNT!]=%SCRIPTS%\%FN%"
  set "NN=0!COUNT!"
  set "NN=!NN:~-2!"
  >>"%MENU_FILE%" echo [!NN!]  !DISP!            ^| preset ^| !FN!
  call :PRINT !COUNT! "%DISP%" "%PLAIN%" "%FN%"
)
exit /b 0
:PRINT
if defined FZF_ACTIVE exit /b 0
REM args: num display plain file
set "N=%~1"
set "DISP=%~2"
set "PLAIN=%~3"
set "F=%~4"
call :STRLEN L "%PLAIN%"
set /a PAD=%COLW% - L
if !PAD! LSS 2 set PAD=2
REM build padding spaces (robust, avoids substring issues)
set "P="
for /L %%i in (1,1,!PAD!) do set "P=!P! "
set "NN=%N%"
if %N% LSS 10 set "NN= %N%"
echo   !NN!^) !DISP!!P!(%F%)
exit /b 0
:STRLEN
REM args: outvar  string
set "s=%~2"
set /a len=0
:STRLEN_LOOP
if defined s (
  set "s=!s:~1!"
  set /a len+=1
  goto STRLEN_LOOP
)
set "%~1=%len%"
exit /b 0
