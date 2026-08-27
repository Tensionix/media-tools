@echo off
chcp 65001 >nul
setlocal EnableExtensions EnableDelayedExpansion
title 🎚️ Audion Media - Audio Tools
for %%A in ("%~dp0..") do set "BASE=%%~fA\"
set "SCRIPTS=%BASE%Scripts"
set "FZF_EXE=%BASE%system_core\fzf.exe"
set "RUNTIME_DIR=%BASE%._runtime"
set "MENU_FILE=%RUNTIME_DIR%\launcher_resample_menu.tmp"
set "RESULT_FILE=%RUNTIME_DIR%\launcher_resample_selection.tmp"
if not exist "%SCRIPTS%" goto ERROR_SCRIPTS
if not exist "%RUNTIME_DIR%" mkdir "%RUNTIME_DIR%" >nul 2>&1
:MENU
if exist "%FZF_EXE%" goto FZF_MENU
goto FALLBACK_MENU
:FZF_MENU
set "FZF_SMOKE_ARGS="
if "%AUDION_LAUNCHER_SMOKE%"=="1" set "FZF_SMOKE_ARGS=--filter=BACK --select-1 --exit-0"
>"%MENU_FILE%" echo [01]  🎚️ 44.1 KHZ PCM 24-BIT                 ^| resample ^| audio-resample-to-44100.cmd
>>"%MENU_FILE%" echo [02]  🎚️ 44.1 KHZ PCM 24-BIT WITH SYNC       ^| resample ^| audio-resample-to-44100_sync.cmd
>>"%MENU_FILE%" echo [03]  🎚️ 48 KHZ PCM 24-BIT                   ^| resample ^| audio-resample-to-48000.cmd
>>"%MENU_FILE%" echo [04]  🎚️ 48 KHZ PCM 24-BIT WITH SYNC         ^| resample ^| audio-resample-to-48000_sync.cmd
>>"%MENU_FILE%" echo [05]  🧪 44.1 KHZ PCM 32-BIT FLOAT           ^| float    ^| audio-resample-to-44100-32f.cmd
>>"%MENU_FILE%" echo [06]  🧪 44.1 KHZ PCM 32-BIT FLOAT WITH SYNC ^| float    ^| audio-resample-to-44100-32f_sync.cmd
>>"%MENU_FILE%" echo [07]  🧪 48 KHZ PCM 32-BIT FLOAT             ^| float    ^| audio-resample-to-48000-32f.cmd
>>"%MENU_FILE%" echo [08]  🧪 48 KHZ PCM 32-BIT FLOAT WITH SYNC   ^| float    ^| audio-resample-to-48000-32f_sync.cmd
>>"%MENU_FILE%" echo [09]  🎧 EXTRACT WAV PCM 24-BIT              ^| extract  ^| audio-extract-audio-wav.cmd
>>"%MENU_FILE%" echo [10]  🎧 EXTRACT WAV PCM 32-BIT FLOAT        ^| extract  ^| audio-extract-audio-wav-32.cmd
>>"%MENU_FILE%" echo [11]  🎧 EXTRACT M4A AAC 384K                ^| extract  ^| audio-to-m4a-384.cmd
>>"%MENU_FILE%" echo [12]  🎧 EXTRACT M4A AAC 256K                ^| extract  ^| audio-to-m4a-256.cmd
>>"%MENU_FILE%" echo [13]  📏 NORMALIZE TO -23 LUFS               ^| loudness ^| audio-lufs-23.cmd
>>"%MENU_FILE%" echo [14]  📏 NORMALIZE TO -14 LUFS               ^| loudness ^| audio-lufs-14.cmd
>>"%MENU_FILE%" echo [15]  🔻 DOWNMIX 5.1 TO 2.0                  ^| downmix  ^| audio-downmix-51-to-20.cmd
>>"%MENU_FILE%" echo [16]  🔻 FLAC WITH SOURCE SAMPLE RATE        ^| lossless ^| audio-to-flac.cmd
>>"%MENU_FILE%" echo [17]  🔻 FLAC 48 KHZ                         ^| lossless ^| audio-to-flac-48k.cmd
>>"%MENU_FILE%" echo [18]  🔻 FLAC 96 KHZ                         ^| lossless ^| audio-to-flac-96k.cmd
>>"%MENU_FILE%" echo [19]  🎧 COPY AUDIO STREAM                   ^| extract  ^| audio-extract-audio-copy.cmd
>>"%MENU_FILE%" echo [00]     BACK                                ^| back     ^| return to project menu
type "%MENU_FILE%" | "%FZF_EXE%" --bind="backspace:abort" --prompt="audion@media [AUDIO] > " --pointer=">" --header="Pick audio operation:" --layout=reverse --border=rounded --info=hidden --margin=1,2 !FZF_SMOKE_ARGS! >"%RESULT_FILE%"
set "SELECTED="
if exist "%RESULT_FILE%" set /p SELECTED=<"%RESULT_FILE%"
del /q "%MENU_FILE%" "%RESULT_FILE%" >nul 2>&1
if not defined SELECTED exit /b 0
set "CH=!SELECTED:~1,2!"
if "!CH!"=="00" exit /b 0
if "!CH!"=="19" set "CH=C"
goto DISPATCH
:FALLBACK_MENU
cls
echo AUDION MEDIA - AUDIO TOOLS
echo FZF is unavailable. Numeric fallback is active.
echo  1-4  PCM 24-bit resample
echo  5-8  PCM 32-bit float resample
echo  9-12 Audio extraction
echo 13-14 Loudness normalization
echo 15-18 Downmix and FLAC
echo  C    Copy audio stream
echo  Q    Back
set "CH="
set /p CH=Select:
if /I "%CH%"=="Q" exit /b 0
:DISPATCH
set "TARGET="
if /I "%CH%"=="C" set "TARGET=audio-extract-audio-copy.cmd"
if "%CH%"=="1" set "TARGET=audio-resample-to-44100.cmd"
if "%CH%"=="2" set "TARGET=audio-resample-to-44100_sync.cmd"
if "%CH%"=="3" set "TARGET=audio-resample-to-48000.cmd"
if "%CH%"=="4" set "TARGET=audio-resample-to-48000_sync.cmd"
if "%CH%"=="5" set "TARGET=audio-resample-to-44100-32f.cmd"
if "%CH%"=="6" set "TARGET=audio-resample-to-44100-32f_sync.cmd"
if "%CH%"=="7" set "TARGET=audio-resample-to-48000-32f.cmd"
if "%CH%"=="8" set "TARGET=audio-resample-to-48000-32f_sync.cmd"
if "%CH%"=="9" set "TARGET=audio-extract-audio-wav.cmd"
if "%CH%"=="10" set "TARGET=audio-extract-audio-wav-32.cmd"
if "%CH%"=="11" set "TARGET=audio-to-m4a-384.cmd"
if "%CH%"=="12" set "TARGET=audio-to-m4a-256.cmd"
if "%CH%"=="13" set "TARGET=audio-lufs-23.cmd"
if "%CH%"=="14" set "TARGET=audio-lufs-14.cmd"
if "%CH%"=="15" set "TARGET=audio-downmix-51-to-20.cmd"
if "%CH%"=="16" set "TARGET=audio-to-flac.cmd"
if "%CH%"=="17" set "TARGET=audio-to-flac-48k.cmd"
if "%CH%"=="18" set "TARGET=audio-to-flac-96k.cmd"
if not defined TARGET goto INVALID
if not exist "%SCRIPTS%\%TARGET%" goto ERROR_TARGET
call "%SCRIPTS%\%TARGET%"
goto MENU
:INVALID
echo [WARN] Invalid choice: %CH%
if not defined AUDION_NO_PAUSE pause
goto MENU
:ERROR_SCRIPTS
echo [ERROR] Scripts folder was not found: "%SCRIPTS%"
exit /b 2
:ERROR_TARGET
echo [ERROR] Target script was not found: "%SCRIPTS%\%TARGET%"
exit /b 3
