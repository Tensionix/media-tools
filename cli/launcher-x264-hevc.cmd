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
set "MENU_FILE=%BASE%._runtime\launcher_x264_menu.tmp"
set "RESULT_FILE=%BASE%._runtime\launcher_x264_selection.tmp"
if exist "%FFBIN%" set "PATH=%FFBIN%;%PATH%"
if not exist "%OUT%" mkdir "%OUT%" >nul 2>&1
if not exist "%SCRIPTS%" (
echo [!] Not found: "%SCRIPTS%"
exit /b 1
)
title launcher: x264 / HEVC
echo 🎞️ x264 / HEVC (CPU)
echo(
echo ------------------------------------------------------------
echo Presets (fixed list). NVENC scripts are excluded.
echo.
echo 📉 4K → 1080p (x264)
echo(
call :PRINT 1 "CRF 14" "ff-x264-4k-to-1080-crf14.cmd"
call :PRINT 2 "CRF 17" "ff-x264-4k-to-1080-crf17.cmd"
call :PRINT 3 "CRF 21" "ff-x264-4k-to-1080-crf21.cmd"
echo.
echo 🎞️ x264 (web)
echo(
call :PRINT 4 "CRF 14" "ff-x264-crf14.cmd"
call :PRINT 5 "CRF 17" "ff-x264-crf17.cmd"
call :PRINT 6 "CRF 21" "ff-x264-crf21.cmd"
echo.
echo 🌗 HDR → SDR (Hable)
echo(
call :PRINT 7 "HEVC Main10" "ff-hdr2sdr-hable-hevc10.cmd"
call :PRINT 8 "x264"        "ff-hdr2sdr-hable-x264.cmd"
echo.
echo  Q) ❌ Quit
echo.
set "PICK="
if exist "%FZF_EXE%" (
  >"%MENU_FILE%" echo [01]  📉 4K TO 1080P CRF 14     ^| x264    ^| ff-x264-4k-to-1080-crf14.cmd
  >>"%MENU_FILE%" echo [02]  📉 4K TO 1080P CRF 17     ^| x264    ^| ff-x264-4k-to-1080-crf17.cmd
  >>"%MENU_FILE%" echo [03]  📉 4K TO 1080P CRF 21     ^| x264    ^| ff-x264-4k-to-1080-crf21.cmd
  >>"%MENU_FILE%" echo [04]  🎞️ X264 CRF 14            ^| x264    ^| ff-x264-crf14.cmd
  >>"%MENU_FILE%" echo [05]  🎞️ X264 CRF 17            ^| x264    ^| ff-x264-crf17.cmd
  >>"%MENU_FILE%" echo [06]  🎞️ X264 CRF 21            ^| x264    ^| ff-x264-crf21.cmd
  >>"%MENU_FILE%" echo [07]  🌈 HDR TO SDR HEVC MAIN10 ^| hdr_sdr ^| ff-hdr2sdr-hable-hevc10.cmd
  >>"%MENU_FILE%" echo [08]  🌈 HDR TO SDR X264        ^| hdr_sdr ^| ff-hdr2sdr-hable-x264.cmd
  >>"%MENU_FILE%" echo [00]     BACK                   ^| back    ^| return to project menu
  set "FZF_SMOKE_ARGS="
  if "!AUDION_LAUNCHER_SMOKE!"=="1" set "FZF_SMOKE_ARGS=--filter=BACK --select-1 --exit-0"
  type "%MENU_FILE%" | "%FZF_EXE%" --bind="backspace:abort" --prompt="audion@media [X264/HEVC] > " --pointer=">" --layout=reverse --border=rounded --info=hidden --margin=1,2 !FZF_SMOKE_ARGS! >"%RESULT_FILE%"
  set "SELECTED="
  if exist "%RESULT_FILE%" set /p SELECTED=<"%RESULT_FILE%"
  del /q "%MENU_FILE%" "%RESULT_FILE%" >nul 2>&1
  if not defined SELECTED exit /b 0
  set "PICK=!SELECTED:~1,2!"
  if "!PICK!"=="00" exit /b 0
  set /a PICK=1!PICK!-100
) else set /p PICK="Select: "
if /I "%PICK%"=="Q" exit /b 0
set "FN="
if "%PICK%"=="1" set "FN=ff-x264-4k-to-1080-crf14.cmd"
if "%PICK%"=="2" set "FN=ff-x264-4k-to-1080-crf17.cmd"
if "%PICK%"=="3" set "FN=ff-x264-4k-to-1080-crf21.cmd"
if "%PICK%"=="4" set "FN=ff-x264-crf14.cmd"
if "%PICK%"=="5" set "FN=ff-x264-crf17.cmd"
if "%PICK%"=="6" set "FN=ff-x264-crf21.cmd"
if "%PICK%"=="7" set "FN=ff-hdr2sdr-hable-hevc10.cmd"
if "%PICK%"=="8" set "FN=ff-hdr2sdr-hable-x264.cmd"
if not defined FN (
  echo.
  echo [!] Invalid choice.
  timeout /t 1 >nul
  goto :eof
)
if not exist "%SCRIPTS%\%FN%" (
  echo.
  echo [X] Not found:
  echo     "%SCRIPTS%\%FN%"
  if not defined AUDION_NO_PAUSE pause
  exit /b 1
)
echo.
echo ▶️ RUN: %FN%
echo.
call "%SCRIPTS%\%FN%"
endlocal
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
