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
set "MENU_FILE=%BASE%._runtime\launcher_prores_menu.tmp"
set "RESULT_FILE=%BASE%._runtime\launcher_prores_selection.tmp"
if exist "%FFBIN%" set "PATH=%FFBIN%;%PATH%"
if not exist "%OUT%" mkdir "%OUT%" >nul 2>&1
if not exist "%SCRIPTS%" (
echo [!] Not found: "%SCRIPTS%"
exit /b 1
)
title launcher: ProRes / DNxHR
echo 🎬 ProRes / DNxHR (CPU)
echo(
echo ------------------------------------------------------------
echo Presets (fixed list).
echo.
echo 🍏 ProRes 422
echo(
call :PRINT 1 "MOV container" "ff-prores-422-mov.cmd"
call :PRINT 2 "MXF container" "ff-prores-422-mxf.cmd"
echo.
echo 🍏 ProRes LT
echo(
call :PRINT 3 "MOV container" "ff-prores-lt-mov.cmd"
call :PRINT 4 "MXF container" "ff-prores-lt-mxf.cmd"
echo.
echo 🍏 ProRes Proxy
echo(
call :PRINT 5 "MOV container" "ff-prores-proxy-mov.cmd"
call :PRINT 6 "MXF container" "ff-prores-proxy-mxf.cmd"
echo.
echo 🎞️ DNxHR HQ / HQX
echo(
call :PRINT 7  "HQ  MOV container" "ff-dnxhr-hq-mov.cmd"
call :PRINT 8  "HQ  MXF container" "ff-dnxhr-hq-mxf.cmd"
call :PRINT 9  "HQX MOV container" "ff-dnxhr-hqx-mov.cmd"
call :PRINT 10 "HQX MXF container" "ff-dnxhr-hqx-mxf.cmd"
echo.
echo  Q) ❌ Quit
echo.
set "PICK="
if exist "%FZF_EXE%" (
  >"%MENU_FILE%" echo [01]  🍏 PRORES 422 MOV   ^| prores422 ^| ff-prores-422-mov.cmd
  >>"%MENU_FILE%" echo [02]  🍏 PRORES 422 MXF   ^| prores422 ^| ff-prores-422-mxf.cmd
  >>"%MENU_FILE%" echo [03]  🍏 PRORES LT MOV    ^| prores_lt ^| ff-prores-lt-mov.cmd
  >>"%MENU_FILE%" echo [04]  🍏 PRORES LT MXF    ^| prores_lt ^| ff-prores-lt-mxf.cmd
  >>"%MENU_FILE%" echo [05]  🍏 PRORES PROXY MOV ^| proxy     ^| ff-prores-proxy-mov.cmd
  >>"%MENU_FILE%" echo [06]  🍏 PRORES PROXY MXF ^| proxy     ^| ff-prores-proxy-mxf.cmd
  >>"%MENU_FILE%" echo [07]  🎬 DNXHR HQ MOV     ^| dnxhr_hq  ^| ff-dnxhr-hq-mov.cmd
  >>"%MENU_FILE%" echo [08]  🎬 DNXHR HQ MXF     ^| dnxhr_hq  ^| ff-dnxhr-hq-mxf.cmd
  >>"%MENU_FILE%" echo [09]  🎬 DNXHR HQX MOV    ^| dnxhr_hqx ^| ff-dnxhr-hqx-mov.cmd
  >>"%MENU_FILE%" echo [10]  🎬 DNXHR HQX MXF    ^| dnxhr_hqx ^| ff-dnxhr-hqx-mxf.cmd
  >>"%MENU_FILE%" echo [00]     BACK             ^| back      ^| return to project menu
  set "FZF_SMOKE_ARGS="
  if "!AUDION_LAUNCHER_SMOKE!"=="1" set "FZF_SMOKE_ARGS=--filter=BACK --select-1 --exit-0"
  type "%MENU_FILE%" | "%FZF_EXE%" --bind="backspace:abort" --prompt="audion@media [PRORES/DNXHR] > " --pointer=">" --layout=reverse --border=rounded --info=hidden --margin=1,2 !FZF_SMOKE_ARGS! >"%RESULT_FILE%"
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
if "%PICK%"=="1"  set "FN=ff-prores-422-mov.cmd"
if "%PICK%"=="2"  set "FN=ff-prores-422-mxf.cmd"
if "%PICK%"=="3"  set "FN=ff-prores-lt-mov.cmd"
if "%PICK%"=="4"  set "FN=ff-prores-lt-mxf.cmd"
if "%PICK%"=="5"  set "FN=ff-prores-proxy-mov.cmd"
if "%PICK%"=="6"  set "FN=ff-prores-proxy-mxf.cmd"
if "%PICK%"=="7"  set "FN=ff-dnxhr-hq-mov.cmd"
if "%PICK%"=="8"  set "FN=ff-dnxhr-hq-mxf.cmd"
if "%PICK%"=="9"  set "FN=ff-dnxhr-hqx-mov.cmd"
if "%PICK%"=="10" set "FN=ff-dnxhr-hqx-mxf.cmd"
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
