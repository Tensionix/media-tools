@echo off
setlocal EnableExtensions EnableDelayedExpansion
chcp 65001 >nul
title 🧭 Audion Media - Main Menu
set "BASE=%~dp0"
for %%A in ("%BASE%") do set "BASE=%%~fA\"
set "FZF_EXE=%BASE%system_core\fzf.exe"
set "RUNTIME_DIR=%BASE%._runtime"
set "MENU_FILE=%RUNTIME_DIR%\launcher_project_menu.tmp"
set "RESULT_FILE=%RUNTIME_DIR%\launcher_project_selection.tmp"
if not exist "%RUNTIME_DIR%" mkdir "%RUNTIME_DIR%" >nul 2>&1
:MENU
if exist "%FZF_EXE%" goto FZF_MENU
goto FALLBACK_MENU
:FZF_MENU
set "SELECTED="
set "FZF_SMOKE_ARGS="
if "%AUDION_LAUNCHER_SMOKE%"=="1" set "FZF_SMOKE_ARGS=--filter=BACK --select-1 --exit-0"
>"%MENU_FILE%" echo [01]  ▶️ YOUTUBE DOWNLOAD PRESETS    ^| youtube     ^| yt-dlp presets and downloads
>>"%MENU_FILE%" echo [02]  🎞️ FPS CONVERT TO 23.976       ^| fps_convert ^| conform and varispeed
>>"%MENU_FILE%" echo [03]  ⚡ FPS SPEED SELECTOR          ^| fps_speed   ^| interpret and speed presets
>>"%MENU_FILE%" echo [04]  🎚️ AUDIO RESAMPLE AND LOUDNESS ^| audio       ^| resample, extract and normalize
>>"%MENU_FILE%" echo [05]  🎨 LUT GRADING                 ^| lut         ^| pregamma and LUT processing
>>"%MENU_FILE%" echo [06]  🎬 PRORES AND DNXHR            ^| mezzanine   ^| intermediate production codecs
>>"%MENU_FILE%" echo [07]  📦 REMUX                       ^| remux       ^| container swap without re-encode
>>"%MENU_FILE%" echo [08]  🎞️ X264 AND HEVC               ^| delivery    ^| CPU delivery presets
>>"%MENU_FILE%" echo [09]  🧰 BUILDER AND INSTALLERS      ^| builder     ^| project setup and dependencies
>>"%MENU_FILE%" echo [00]     BACK                        ^| back        ^| close project menu
type "%MENU_FILE%" | "%FZF_EXE%" --bind="backspace:abort" --prompt="audion@media [PROJECT] > " --pointer=">" --header="Pick tool:" --layout=reverse --border=rounded --info=hidden --margin=1,2 !FZF_SMOKE_ARGS! >"%RESULT_FILE%"
if exist "%RESULT_FILE%" set /p SELECTED=<"%RESULT_FILE%"
del /q "%MENU_FILE%" >nul 2>&1
del /q "%RESULT_FILE%" >nul 2>&1
if "%AUDION_LAUNCHER_DEBUG%"=="1" echo SELECTED=[!SELECTED!]
if not defined SELECTED exit /b 0
set "MENU_CODE=!SELECTED:~1,2!"
set "CH=!MENU_CODE!"
if "!MENU_CODE!"=="01" set "CH=1"
if "!MENU_CODE!"=="02" set "CH=2"
if "!MENU_CODE!"=="03" set "CH=S"
if "!MENU_CODE!"=="04" set "CH=3"
if "!MENU_CODE!"=="05" set "CH=4"
if "!MENU_CODE!"=="06" set "CH=5"
if "!MENU_CODE!"=="07" set "CH=6"
if "!MENU_CODE!"=="08" set "CH=7"
if "!MENU_CODE!"=="09" set "CH=8"
if "!MENU_CODE!"=="00" set "CH=Q"
goto DISPATCH
:FALLBACK_MENU
cls
echo.
echo AUDION MEDIA TOOLS - PROJECT MENU
echo --------------------------------------------
echo FZF is unavailable. Numeric fallback is active.
echo.
echo  1^) YouTube download presets ^(yt-dlp^)
echo  2^) FPS convert to 23.976 ^(conform / varispeed^)
echo  S^) FPS Speed selector ^(interpret / speed presets^)
echo  3^) Audio resample / extract / loudness
echo  4^) LUT grading ^(pregamma / LUT only^)
echo  5^) ProRes / DNxHR encodes
echo  6^) Remux ^(container swap, no re-encode^)
echo  7^) x264 / HEVC CPU presets
echo  8^) Builder / installers
echo  Q^) Quit
echo.
set "CH="
set /p CH=Choose:
for /f "tokens=* delims= " %%A in ("!CH!") do set "CH=%%A"
:DISPATCH
if /I "%CH%"=="Q" exit /b 0
if "%CH%"=="1" call "%BASE%cli\launcher-youtube.cmd" & goto MENU
if "%CH%"=="2" call "%BASE%cli\launcher-fps.cmd" & goto MENU
if /I "%CH%"=="S" call "%BASE%cli\launcher-select-fps-speed.cmd" & goto MENU
if "%CH%"=="3" call "%BASE%cli\launcher-resample.cmd" & goto MENU
if "%CH%"=="4" call "%BASE%cli\launcher-lut-grading.cmd" & goto MENU
if "%CH%"=="5" call "%BASE%cli\launcher-prores-dnxhr.cmd" & goto MENU
if "%CH%"=="6" call "%BASE%cli\launcher-remux.cmd" & goto MENU
if "%CH%"=="7" call "%BASE%cli\launcher-x264-hevc.cmd" & goto MENU
if "%CH%"=="8" call "%BASE%builder_main.cmd" & goto MENU
echo [WARN] Invalid choice: %CH%
timeout /t 1 >nul
goto MENU
