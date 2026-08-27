@echo off
setlocal EnableExtensions EnableDelayedExpansion
REM =============================================================
REM  Interactive front-end for the shared FPS profiles.
REM  The actual FFmpeg command is built only by Scripts\Common\script_runner.py.
REM  Modes: CONFORM (keep pitch via atempo) / VARISPEED (lower pitch)
REM  Outputs mirror the GUI FPS profiles, including MOV/MXF audio contracts.
REM =============================================================
chcp 65001 >nul
REM ---- Resolve base paths ----
for %%A in ("%~dp0..") do set "BASE=%%~fA\"
set "SCRIPTS=%BASE%Scripts"
set "FZF_EXE=%BASE%system_core\fzf.exe"
set "RUNTIME_DIR=%BASE%._runtime"
set "MENU_FILE=%RUNTIME_DIR%\fps_speed_menu.tmp"
set "RESULT_FILE=%RUNTIME_DIR%\fps_speed_selection.tmp"
if not exist "%RUNTIME_DIR%" mkdir "%RUNTIME_DIR%" >nul 2>&1
REM ---- Menu: Mode ----
:mode_menu
if exist "%FZF_EXE%" goto fzf_mode_menu
echo.
echo 🎞️ 23.976 CONVERSION MODE
echo [1] CONFORM (keep pitch, audio time-stretch)
echo [2] VARISPEED (lower pitch, like film)
echo [Q] Quit
choice /C 12Q /N /M "Select mode: "
set "MODE_CH=%ERRORLEVEL%"
if "%MODE_CH%"=="3" goto :eof
if "%MODE_CH%"=="1" (set "MODE=CONFORM") else (set "MODE=VARISPEED")
goto fps_menu
:fzf_mode_menu
>"%MENU_FILE%" echo [01]  CONFORM        ^| mode       ^| keep pitch with audio time-stretch
>>"%MENU_FILE%" echo [02]  VARISPEED      ^| mode       ^| lower pitch like film playback
>>"%MENU_FILE%" echo [00]  BACK           ^| back       ^| return to project menu
call :FZF_SELECT "audion@media [FPS MODE]"
if not defined SELECTED goto :eof
set "MODE_CH=!SELECTED:~1,2!"
if "!MODE_CH!"=="00" goto :eof
if "!MODE_CH!"=="01" set "MODE=CONFORM"
if "!MODE_CH!"=="02" set "MODE=VARISPEED"
REM ---- Menu: Source FPS ----
:fps_menu
if exist "%FZF_EXE%" goto fzf_fps_menu
echo.
echo 🎚️ Source FPS → 23.976
echo [1] 25.00
echo [2] 29.97
echo [3] 50.00
echo [4] 59.94
echo [5] 100.00
echo [6] 119.88
echo [7] 179.82
echo [B] Back
choice /C 1234567B /N /M "Select source FPS: "
set "FPS_CH=%ERRORLEVEL%"
if "%FPS_CH%"=="8" goto :mode_menu
goto apply_fps
:fzf_fps_menu
>"%MENU_FILE%" echo [01]  25.00 FPS      ^| source_fps ^| convert to 23.976
>>"%MENU_FILE%" echo [02]  29.97 FPS      ^| source_fps ^| convert to 23.976
>>"%MENU_FILE%" echo [03]  50.00 FPS      ^| source_fps ^| convert to 23.976
>>"%MENU_FILE%" echo [04]  59.94 FPS      ^| source_fps ^| convert to 23.976
>>"%MENU_FILE%" echo [05]  100.00 FPS     ^| source_fps ^| convert to 23.976
>>"%MENU_FILE%" echo [06]  119.88 FPS     ^| source_fps ^| convert to 23.976
>>"%MENU_FILE%" echo [07]  179.82 FPS     ^| source_fps ^| convert to 23.976
>>"%MENU_FILE%" echo [00]  BACK           ^| back       ^| return to mode selection
call :FZF_SELECT "audion@media [SOURCE FPS]"
if not defined SELECTED goto mode_menu
set "FPS_CH=!SELECTED:~1,2!"
if "!FPS_CH!"=="00" goto mode_menu
set /a FPS_CH=1!FPS_CH!-100
:apply_fps
if "%FPS_CH%"=="1" (set "SRC_TAG=25"     & set "FPS_ID=25") else ^
if "%FPS_CH%"=="2" (set "SRC_TAG=29.97"  & set "FPS_ID=2997") else ^
if "%FPS_CH%"=="3" (set "SRC_TAG=50"     & set "FPS_ID=50") else ^
if "%FPS_CH%"=="4" (set "SRC_TAG=59.94"  & set "FPS_ID=5994") else ^
if "%FPS_CH%"=="5" (set "SRC_TAG=100"    & set "FPS_ID=100") else ^
if "%FPS_CH%"=="6" (set "SRC_TAG=119.88" & set "FPS_ID=11988") else ^
if "%FPS_CH%"=="7" (set "SRC_TAG=179.82" & set "FPS_ID=17982")
REM ---- Menu: Output mode ----
:out_menu
set "AUDION_FPS_AUDIO_PCM_DEPTH="
set "AUDION_FPS_AUDIO_OVERSAMPLE="
set "IS_PCM="
set "IS_MXF="
if exist "%FZF_EXE%" goto fzf_out_menu
echo.
echo 📦 Output format
echo [1] H.264 MP4 (CRF14, AAC 384k)
echo [2] H.265 MP4 (CRF16, AAC 384k)
echo [3] ProRes 422 MOV (PCM 16/24/32f, up to 192 kHz)
echo [4] ProRes 422 MXF (PCM 16/24, final 48 kHz)
echo [5] DNxHR HQX MOV (PCM 16/24/32f, up to 192 kHz)
echo [6] DNxHR HQX MXF (PCM 16/24, final 48 kHz)
echo [B] Back
choice /C 123456B /N /M "Select output: "
set "OUT_CH=%ERRORLEVEL%"
if "%OUT_CH%"=="7" goto :fps_menu
goto apply_output
:fzf_out_menu
>"%MENU_FILE%" echo [01]  H.264 MP4      ^| output     ^| CRF 14 and AAC 384K
>>"%MENU_FILE%" echo [02]  H.265 MP4      ^| output     ^| CRF 16 and AAC 384K
>>"%MENU_FILE%" echo [03]  PRORES 422 MOV ^| output     ^| PCM 16/24/32F and up to 192 KHZ
>>"%MENU_FILE%" echo [04]  PRORES 422 MXF ^| output     ^| PCM 16/24 and final 48 KHZ
>>"%MENU_FILE%" echo [05]  DNXHR HQX MOV  ^| output     ^| PCM 16/24/32F and up to 192 KHZ
>>"%MENU_FILE%" echo [06]  DNXHR HQX MXF  ^| output     ^| PCM 16/24 and final 48 KHZ
>>"%MENU_FILE%" echo [00]  BACK           ^| back       ^| return to FPS selection
call :FZF_SELECT "audion@media [OUTPUT]"
if not defined SELECTED goto fps_menu
set "OUT_CH=!SELECTED:~1,2!"
if "!OUT_CH!"=="00" goto fps_menu
set /a OUT_CH=1!OUT_CH!-100
:apply_output
if "%OUT_CH%"=="1" (set "OUT_MODE=H264"   & set "AUDION_FPS_OUTPUT_PROFILE=h264") else ^
if "%OUT_CH%"=="2" (set "OUT_MODE=HEVC"   & set "AUDION_FPS_OUTPUT_PROFILE=hevc") else ^
if "%OUT_CH%"=="3" (set "OUT_MODE=PRORES MOV" & set "AUDION_FPS_OUTPUT_PROFILE=prores" & set "IS_PCM=1") else ^
if "%OUT_CH%"=="4" (set "OUT_MODE=PRORES MXF" & set "AUDION_FPS_OUTPUT_PROFILE=prores_mxf" & set "IS_PCM=1" & set "IS_MXF=1") else ^
if "%OUT_CH%"=="5" (set "OUT_MODE=DNXHR MOV" & set "AUDION_FPS_OUTPUT_PROFILE=dnxhr" & set "IS_PCM=1") else ^
if "%OUT_CH%"=="6" (set "OUT_MODE=DNXHR MXF" & set "AUDION_FPS_OUTPUT_PROFILE=dnxhr_mxf" & set "IS_PCM=1" & set "IS_MXF=1")
if defined IS_PCM goto pcm_menu
goto run_profile
:pcm_menu
if exist "%FZF_EXE%" goto fzf_pcm_menu
echo.
echo 🎧 PCM bit depth
echo [1] PCM 16-bit
echo [2] PCM 24-bit
if not defined IS_MXF echo [3] PCM 32-bit float (MOV only)
echo [B] Back
if defined IS_MXF (choice /C 12B /N /M "Select PCM depth: ") else (choice /C 123B /N /M "Select PCM depth: ")
set "PCM_CH=%ERRORLEVEL%"
if defined IS_MXF (if "%PCM_CH%"=="3" goto out_menu) else (if "%PCM_CH%"=="4" goto out_menu)
goto apply_pcm
:fzf_pcm_menu
>"%MENU_FILE%" echo [01]  PCM 16-BIT     ^| audio      ^| signed integer PCM
>>"%MENU_FILE%" echo [02]  PCM 24-BIT     ^| audio      ^| signed integer PCM
if not defined IS_MXF >>"%MENU_FILE%" echo [03]  PCM 32-FLOAT   ^| audio      ^| Apple MOV only
>>"%MENU_FILE%" echo [00]  BACK           ^| back       ^| return to output selection
call :FZF_SELECT "audion@media [PCM DEPTH]"
if not defined SELECTED goto out_menu
set "PCM_CH=!SELECTED:~1,2!"
if "!PCM_CH!"=="00" goto out_menu
set /a PCM_CH=1!PCM_CH!-100
:apply_pcm
if "%PCM_CH%"=="1" set "AUDION_FPS_AUDIO_PCM_DEPTH=s16"
if "%PCM_CH%"=="2" set "AUDION_FPS_AUDIO_PCM_DEPTH=s24"
if "%PCM_CH%"=="3" set "AUDION_FPS_AUDIO_PCM_DEPTH=f32"
goto rate_menu
:rate_menu
if exist "%FZF_EXE%" goto fzf_rate_menu
echo.
echo 🎚️ Audio work rate
echo [1] SOURCE / x1
echo [2] 2x (88.2/96 kHz family)
echo [3] 4x (176.4/192 kHz family)
if defined IS_MXF echo     MXF is processed at this rate and finalized at 48 kHz.
echo [B] Back
choice /C 123B /N /M "Select work rate: "
set "RATE_CH=%ERRORLEVEL%"
if "%RATE_CH%"=="4" goto pcm_menu
goto apply_rate
:fzf_rate_menu
>"%MENU_FILE%" echo [01]  SOURCE / X1    ^| work rate  ^| keep the source sample-rate family
>>"%MENU_FILE%" echo [02]  X2             ^| work rate  ^| 88.2 or 96 KHZ
>>"%MENU_FILE%" echo [03]  X4             ^| work rate  ^| 176.4 or 192 KHZ
>>"%MENU_FILE%" echo [00]  BACK           ^| back       ^| return to PCM depth
call :FZF_SELECT "audion@media [AUDIO WORK RATE]"
if not defined SELECTED goto pcm_menu
set "RATE_CH=!SELECTED:~1,2!"
if "!RATE_CH!"=="00" goto pcm_menu
set /a RATE_CH=1!RATE_CH!-100
:apply_rate
if "%RATE_CH%"=="1" set "AUDION_FPS_AUDIO_OVERSAMPLE=x1"
if "%RATE_CH%"=="2" set "AUDION_FPS_AUDIO_OVERSAMPLE=x2"
if "%RATE_CH%"=="3" set "AUDION_FPS_AUDIO_OVERSAMPLE=x4"
:run_profile
if /I "%MODE%"=="CONFORM" (set "MODE_ID=conform") else (set "MODE_ID=varispeed")
set "PROFILE=ff-%FPS_ID%to23976-%MODE_ID%"
set "TARGET=%SCRIPTS%\%PROFILE%.cmd"
if not exist "%TARGET%" goto ERROR_PROFILE
echo.
echo 🚀 RUN
echo Mode: %MODE%   Src FPS: %SRC_TAG%   Out: %OUT_MODE%
if defined IS_PCM echo PCM: %AUDION_FPS_AUDIO_PCM_DEPTH%   Work rate: %AUDION_FPS_AUDIO_OVERSAMPLE%
if defined IS_MXF echo MXF audio output: 48000 Hz
echo Shared profile: %PROFILE%
echo.
call "%TARGET%"
exit /b %ERRORLEVEL%
:FZF_SELECT
set "SELECTED="
set "FZF_SMOKE_ARGS="
if "%AUDION_LAUNCHER_SMOKE%"=="1" set "FZF_SMOKE_ARGS=--filter=BACK --select-1 --exit-0"
type "%MENU_FILE%" | "%FZF_EXE%" --bind="backspace:abort" --prompt="%~1 > " --pointer=">" --layout=reverse --border=rounded --info=hidden --margin=1,2 !FZF_SMOKE_ARGS! >"%RESULT_FILE%"
if exist "%RESULT_FILE%" set /p SELECTED=<"%RESULT_FILE%"
del /q "%MENU_FILE%" "%RESULT_FILE%" >nul 2>&1
exit /b 0
:ERROR_PROFILE
echo [ERROR] Shared FPS profile was not found: "%TARGET%"
exit /b 2
