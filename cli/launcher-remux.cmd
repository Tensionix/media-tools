@echo off
setlocal EnableExtensions EnableDelayedExpansion
chcp 65001 >nul
REM Auto-discovery launchers (v1.1.2), NVENC entries excluded.
for %%A in ("%~dp0..") do set "BASE=%%~fA\"
set "SCRIPTS=%BASE%Scripts"
set "SRC=%BASE%Source"
set "OUT=%BASE%Transcoded"
set "TOOLS=%BASE%Tools"
set "FFBIN=%TOOLS%\ffmpeg\bin"
set "YTDLP=%TOOLS%\yt-dlp\bin\yt-dlp.exe"
set "FZF_EXE=%BASE%system_core\fzf.exe"
set "MENU_FILE=%BASE%._runtime\launcher_remux_menu.tmp"
set "RESULT_FILE=%BASE%._runtime\launcher_remux_selection.tmp"
if exist "%FFBIN%" set "PATH=%FFBIN%;%PATH%"
if not exist "%OUT%" mkdir "%OUT%" >nul 2>&1
if not exist "%SCRIPTS%" (
echo [!] Not found: "%SCRIPTS%"
exit /b 1
)
title launcher: Remuxers
echo 📦 Remuxers (container swap, no re-encode)
echo ------------------------------------------------------------
echo Presets (fixed list).
echo.
echo 🧩 Scripted remux
echo(
call :PRINT 1 "MKV → MP4 (script)" "ff-remux-mkv-to-mp4.cmd"
call :PRINT 2 "MP4 → MKV (script)" "ff-remux-mp4-to-mkv.cmd"
echo.
echo ⚡ Batch presets (folder-based)
echo(
call :PRINT 3 "MP4 → MKV (copy)" "ff-remux-mp4-to-mkv-copy.cmd"
call :PRINT 4 "MKV → MP4 (+faststart)" "ff-remux-mkv-to-mp4-faststart.cmd"
call :PRINT 5 "MOV → MXF (copy)" "ff-remux-mov-to-mxf-copy.cmd"
call :PRINT 6 "MXF → MOV (copy)" "ff-remux-mxf-to-mov-copy.cmd"
echo.
echo  Q) ❌ Quit
echo.
set "PICK="
if exist "%FZF_EXE%" (
  >"%MENU_FILE%" echo [01]  🧩 MKV TO MP4 SCRIPTED  ^| scripted ^| ff-remux-mkv-to-mp4.cmd
  >>"%MENU_FILE%" echo [02]  🧩 MP4 TO MKV SCRIPTED  ^| scripted ^| ff-remux-mp4-to-mkv.cmd
  >>"%MENU_FILE%" echo [03]  ⚡ MP4 TO MKV COPY      ^| batch    ^| ff-remux-mp4-to-mkv-copy.cmd
  >>"%MENU_FILE%" echo [04]  ⚡ MKV TO MP4 FASTSTART ^| batch    ^| ff-remux-mkv-to-mp4-faststart.cmd
  >>"%MENU_FILE%" echo [05]  ⚡ MOV TO MXF COPY      ^| batch    ^| ff-remux-mov-to-mxf-copy.cmd
  >>"%MENU_FILE%" echo [06]  ⚡ MXF TO MOV COPY      ^| batch    ^| ff-remux-mxf-to-mov-copy.cmd
  >>"%MENU_FILE%" echo [00]     BACK                 ^| back     ^| return to project menu
  set "FZF_SMOKE_ARGS="
  if "!AUDION_LAUNCHER_SMOKE!"=="1" set "FZF_SMOKE_ARGS=--filter=BACK --select-1 --exit-0"
  type "%MENU_FILE%" | "%FZF_EXE%" --bind="backspace:abort" --prompt="audion@media [REMUX] > " --pointer=">" --layout=reverse --border=rounded --info=hidden --margin=1,2 !FZF_SMOKE_ARGS! >"%RESULT_FILE%"
  set "SELECTED="
  if exist "%RESULT_FILE%" set /p SELECTED=<"%RESULT_FILE%"
  del /q "%MENU_FILE%" "%RESULT_FILE%" >nul 2>&1
  if not defined SELECTED exit /b 0
  set "PICK=!SELECTED:~1,2!"
  if "!PICK!"=="00" exit /b 0
  set /a PICK=1!PICK!-100
) else set /p PICK="Select: "
if /I "%PICK%"=="Q" exit /b 0
set "TARGET="
if "%PICK%"=="1" set "TARGET=%SCRIPTS%\ff-remux-mkv-to-mp4.cmd"
if "%PICK%"=="2" set "TARGET=%SCRIPTS%\ff-remux-mp4-to-mkv.cmd"
if "%PICK%"=="3" set "TARGET=%SCRIPTS%\ff-remux-mp4-to-mkv-copy.cmd"
if "%PICK%"=="4" set "TARGET=%SCRIPTS%\ff-remux-mkv-to-mp4-faststart.cmd"
if "%PICK%"=="5" set "TARGET=%SCRIPTS%\ff-remux-mov-to-mxf-copy.cmd"
if "%PICK%"=="6" set "TARGET=%SCRIPTS%\ff-remux-mxf-to-mov-copy.cmd"
if not defined TARGET (
  echo.
  echo [!] Invalid choice.
  timeout /t 1 >nul
  exit /b 1
)
if not exist "%TARGET%" (
  echo.
  echo [X] Not found:
  echo     "%TARGET%"
  if not defined AUDION_NO_PAUSE pause
  exit /b 1
)
echo.
echo ▶️ RUN: "%TARGET%"
echo.
call "%TARGET%"
exit /b 0
REM Padding column (align "(script.cmd)")
set "COLW=42"
:PRINT
REM args: key label file
set "K=%~1"
set "LABEL=%~2"
set "FILE=%~3"
call :STRLEN L "%LABEL%"
set /a PAD=%COLW% - L
if !PAD! LSS 2 set PAD=2
set "P="
for /L %%i in (1,1,!PAD!) do set "P=!P! "
REM align 1..9 keys with leading space
set "KK=%K%"
if "%K%"=="1" set "KK= 1"
if "%K%"=="2" set "KK= 2"
if "%K%"=="3" set "KK= 3"
if "%K%"=="4" set "KK= 4"
if "%K%"=="5" set "KK= 5"
if "%K%"=="6" set "KK= 6"
if "%K%"=="7" set "KK= 7"
if "%K%"=="8" set "KK= 8"
if "%K%"=="9" set "KK= 9"
echo   !KK!^) !LABEL!!P!^(%FILE%^)
exit /b 0
:STRLEN
REM args: outvar string
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
