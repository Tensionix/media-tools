@echo off
setlocal EnableExtensions EnableDelayedExpansion
chcp 65001 >nul
title 🎞️ FPS → 23.976 (Curated)
REM =============================================================
REM  launcher-fps.cmd (curated list)
REM
REM  Goal:
REM   - No auto-discovery.
REM   - Show a fixed, readable menu with script names in ( ... ).
REM   - Group presets by conversion mode:
REM       VARISPEED / CONFORM
REM
REM  Folder layout (package root):
REM   Scripts\ff-XXto23976-*.cmd
REM   Scripts\run-fps-convert.cmd
REM =============================================================
for %%A in ("%~dp0..") do set "BASE=%%~fA\"
set "SCRIPTS=%BASE%Scripts"
set "FZF_EXE=%BASE%system_core\fzf.exe"
set "MENU_FILE=%BASE%._runtime\launcher_fps_menu.tmp"
set "RESULT_FILE=%BASE%._runtime\launcher_fps_selection.tmp"
REM (optional) ffmpeg bin in PATH for called scripts
set "FFBIN=%BASE%Tools\ffmpeg\bin"
if exist "%FFBIN%\NUL" set "PATH=%FFBIN%;%PATH%"
REM Padding helpers for aligned "(script.cmd)" column
set "COLW=30"
set "SPACES=                                                                                                                                "
:MENU
cls
echo.
echo 🎞️ 23.976 CONVERSION MODE
echo(
echo ------------------------------------------------------------
echo.
echo 🎬 VARISPEED  (lower pitch, like film)
echo(
call :ITEM  1 "24.00  → 23.976" "ff-24to23976-varispeed.cmd"
call :ITEM  2 "25.00  → 23.976" "ff-25to23976-varispeed.cmd"
call :ITEM  3 "29.97  → 23.976" "ff-2997to23976-varispeed.cmd"
call :ITEM  4 "50.00  → 23.976" "ff-50to23976-varispeed.cmd"
call :ITEM  5 "59.94  → 23.976" "ff-5994to23976-varispeed.cmd"
call :ITEM  6 "100.00 → 23.976" "ff-100to23976-varispeed.cmd"
call :ITEM  7 "119.88 → 23.976" "ff-11988to23976-varispeed.cmd"
call :ITEM  8 "179.82 → 23.976" "ff-17982to23976-varispeed.cmd"
echo.
echo 🎼 CONFORM  (keep pitch, audio time-stretch)
echo(
call :ITEM  9  "25.00  → 23.976" "ff-25to23976-conform.cmd"
call :ITEM 10  "29.97  → 23.976" "ff-2997to23976-conform.cmd"
call :ITEM 11  "59.94  → 23.976" "ff-5994to23976-conform.cmd"
echo.
echo 🧩 Master
echo(
call :ITEM   M "Interactive menu" "launcher-select-fps-speed.cmd"
echo.
echo   Q) ❌ Quit
echo.
set "CH="
if exist "%FZF_EXE%" (
  >"%MENU_FILE%" echo [01]  🎬 24.00 TO 23.976      ^| varispeed ^| ff-24to23976-varispeed.cmd
  >>"%MENU_FILE%" echo [02]  🎬 25.00 TO 23.976      ^| varispeed ^| ff-25to23976-varispeed.cmd
  >>"%MENU_FILE%" echo [03]  🎬 29.97 TO 23.976      ^| varispeed ^| ff-2997to23976-varispeed.cmd
  >>"%MENU_FILE%" echo [04]  🎬 50.00 TO 23.976      ^| varispeed ^| ff-50to23976-varispeed.cmd
  >>"%MENU_FILE%" echo [05]  🎬 59.94 TO 23.976      ^| varispeed ^| ff-5994to23976-varispeed.cmd
  >>"%MENU_FILE%" echo [06]  🎬 100.00 TO 23.976     ^| varispeed ^| ff-100to23976-varispeed.cmd
  >>"%MENU_FILE%" echo [07]  🎬 119.88 TO 23.976     ^| varispeed ^| ff-11988to23976-varispeed.cmd
  >>"%MENU_FILE%" echo [08]  🎬 179.82 TO 23.976     ^| varispeed ^| ff-17982to23976-varispeed.cmd
  >>"%MENU_FILE%" echo [09]  🎞️ 25.00 TO 23.976      ^| conform   ^| ff-25to23976-conform.cmd
  >>"%MENU_FILE%" echo [10]  🎞️ 29.97 TO 23.976      ^| conform   ^| ff-2997to23976-conform.cmd
  >>"%MENU_FILE%" echo [11]  🎞️ 59.94 TO 23.976      ^| conform   ^| ff-5994to23976-conform.cmd
  >>"%MENU_FILE%" echo [12]  🧩 INTERACTIVE FPS MENU ^| wizard    ^| launcher-select-fps-speed.cmd
  >>"%MENU_FILE%" echo [00]     BACK                 ^| back      ^| return to project menu
  set "FZF_SMOKE_ARGS="
  if "!AUDION_LAUNCHER_SMOKE!"=="1" set "FZF_SMOKE_ARGS=--filter=BACK --select-1 --exit-0"
  type "%MENU_FILE%" | "%FZF_EXE%" --bind="backspace:abort" --prompt="audion@media [FPS] > " --pointer=">" --layout=reverse --border=rounded --info=hidden --margin=1,2 !FZF_SMOKE_ARGS! >"%RESULT_FILE%"
  set "SELECTED="
  if exist "%RESULT_FILE%" set /p SELECTED=<"%RESULT_FILE%"
  del /q "%MENU_FILE%" "%RESULT_FILE%" >nul 2>&1
  if not defined SELECTED exit /b 0
  set "CH=!SELECTED:~1,2!"
  if "!CH!"=="00" exit /b 0
  if "!CH!"=="12" set "CH=M"
  if not "!CH:~0,1!"=="0" goto FPS_PICK_READY
  set /a CH=1!CH!-100
) else set /p CH=Select:
:FPS_PICK_READY
if /I "%CH%"=="Q" exit /b 0
if /I "%CH%"=="M" call "%BASE%cli\launcher-select-fps-speed.cmd" & goto MENU
REM map selection -> file
set "FN="
if "%CH%"=="1"  set "FN=ff-24to23976-varispeed.cmd"
if "%CH%"=="2"  set "FN=ff-25to23976-varispeed.cmd"
if "%CH%"=="3"  set "FN=ff-2997to23976-varispeed.cmd"
if "%CH%"=="4"  set "FN=ff-50to23976-varispeed.cmd"
if "%CH%"=="5"  set "FN=ff-5994to23976-varispeed.cmd"
if "%CH%"=="6"  set "FN=ff-100to23976-varispeed.cmd"
if "%CH%"=="7"  set "FN=ff-11988to23976-varispeed.cmd"
if "%CH%"=="8"  set "FN=ff-17982to23976-varispeed.cmd"
if "%CH%"=="9"  set "FN=ff-25to23976-conform.cmd"
if "%CH%"=="10" set "FN=ff-2997to23976-conform.cmd"
if "%CH%"=="11" set "FN=ff-5994to23976-conform.cmd"
if not defined FN (
  echo.
  echo [!] Invalid choice.
  timeout /t 1 >nul
  goto MENU
)
if not exist "%SCRIPTS%\%FN%" (
  echo.
  echo [X] Not found:
  echo     "%SCRIPTS%\%FN%"
  echo.
  if not defined AUDION_NO_PAUSE pause
  goto MENU
)
echo.
echo ▶️ RUN: %FN%
echo.
call "%SCRIPTS%\%FN%"
echo.
if not defined AUDION_NO_PAUSE pause
goto MENU
:ITEM
REM args: key  label  filename
set "K=%~1"
set "LABEL=%~2"
set "FILE=%~3"
REM hide missing scripts (but keep curated layout readable)
if not exist "%SCRIPTS%\%FILE%" exit /b 0
REM compute padding for "(file)"
call :STRLEN LEN "%LABEL%"
set /a PAD=%COLW% - LEN
if !PAD! LSS 2 set PAD=2
set "P="
for /L %%i in (1,1,!PAD!) do set "P=!P! "
REM align 1..9 keys
set "KK=%K%"
for /f "delims=0123456789" %%Z in ("%K%") do set "ISNUM=%%Z"
if "%K%"=="1" set "KK= 1"
if "%K%"=="2" set "KK= 2"
if "%K%"=="3" set "KK= 3"
if "%K%"=="4" set "KK= 4"
if "%K%"=="5" set "KK= 5"
if "%K%"=="6" set "KK= 6"
if "%K%"=="7" set "KK= 7"
if "%K%"=="8" set "KK= 8"
if "%K%"=="9" set "KK= 9"
echo   %KK%^) %LABEL%!P!(%FILE%)
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
