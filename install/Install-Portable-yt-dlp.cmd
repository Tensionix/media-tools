@echo off
setlocal EnableExtensions EnableDelayedExpansion

title Audion Media Tools - Install Portable yt-dlp

set "SCRIPT_DIR=%~dp0"
if "%SCRIPT_DIR:~-1%"=="\" set "SCRIPT_DIR=%SCRIPT_DIR:~0,-1%"
for %%A in ("%SCRIPT_DIR%\..") do set "ROOT=%%~fA"

set "DL=%ROOT%\install\download"
set "YTDLP_DIR=%ROOT%\Tools\yt-dlp"
set "YTDLP_BIN=%ROOT%\Tools\yt-dlp\bin"
set "EXE=%DL%\yt-dlp.exe"
set "URL=https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp.exe"
set "DENO_INSTALLER=%ROOT%\install\Install-Portable-Deno.cmd"
set "PS_EXE="
set "NO_PAUSE=0"
set "SKIP_DENO=0"

:PARSE_ARGS
if "%~1"=="" goto DONE_ARGS
if /I "%~1"=="/NOPAUSE" set "NO_PAUSE=1"
if /I "%~1"=="--no-pause" set "NO_PAUSE=1"
if /I "%~1"=="/SKIP_DENO" set "SKIP_DENO=1"
if /I "%~1"=="--skip-deno" set "SKIP_DENO=1"
shift
goto PARSE_ARGS
:DONE_ARGS
if /I "%AUDION_NO_PAUSE%"=="1" set "NO_PAUSE=1"

if exist "%ROOT%\system_core\powershell\pwsh.exe" set "PS_EXE=%ROOT%\system_core\powershell\pwsh.exe"
if not defined PS_EXE where pwsh.exe >nul 2>nul && set "PS_EXE=pwsh.exe"
if not defined PS_EXE where powershell.exe >nul 2>nul && set "PS_EXE=powershell.exe"

if not exist "%DL%\" mkdir "%DL%" >nul 2>nul
if not exist "%YTDLP_BIN%\" mkdir "%YTDLP_BIN%" >nul 2>nul

echo ======================================================================
echo   AUDION MEDIA TOOLS - INSTALL PORTABLE YT-DLP
echo ======================================================================
echo Root:    %ROOT%
echo Target:  %YTDLP_BIN%
echo DL:      %DL%
echo PS:      %PS_EXE%
echo.

if not defined PS_EXE goto ERR_POWERSHELL

echo [1/4] Downloading yt-dlp latest Windows executable...
"%PS_EXE%" -NoLogo -NoProfile -ExecutionPolicy Bypass -Command ^
  "$ErrorActionPreference='Stop';" ^
  "$ProgressPreference='SilentlyContinue';" ^
  "$headers=@{'User-Agent'='Audion-Media-Tools'};" ^
  "Write-Host ('[URL] ' + '%URL%');" ^
  "Invoke-WebRequest -Headers $headers -Uri '%URL%' -OutFile '%EXE%'"
if errorlevel 1 goto ERR_DOWNLOAD

if not exist "%EXE%" goto ERR_DOWNLOAD
for %%F in ("%EXE%") do echo [OK] Downloaded: %%~zF bytes
echo.

echo [2/4] Copying yt-dlp.exe...
call :RESET_DIR "%YTDLP_DIR%"
if errorlevel 1 goto ERR_COPY
mkdir "%YTDLP_BIN%" >nul 2>nul
if not exist "%YTDLP_BIN%\" goto ERR_COPY
copy /y "%EXE%" "%YTDLP_BIN%\yt-dlp.exe" >nul
if errorlevel 1 goto ERR_COPY

echo [3/4] Verifying...
"%YTDLP_BIN%\yt-dlp.exe" --version
if errorlevel 1 goto ERR_VERIFY

if "%SKIP_DENO%"=="1" goto DONE_DENO
echo.
echo [4/4] Installing Deno JS runtime for yt-dlp external JavaScript support...
if not exist "%DENO_INSTALLER%" goto ERR_DENO_INSTALLER
call "%DENO_INSTALLER%" /NOPAUSE
if errorlevel 1 goto ERR_DENO
:DONE_DENO

echo.
echo [SUCCESS] yt-dlp installed: %YTDLP_BIN%\yt-dlp.exe
if not "%SKIP_DENO%"=="1" echo [SUCCESS] Deno component installed for yt-dlp.
call :PAUSE_IF_NEEDED
exit /b 0

:ERR_POWERSHELL
echo [ERROR] PowerShell was not found.
call :PAUSE_IF_NEEDED
exit /b 1

:ERR_DOWNLOAD
echo [ERROR] yt-dlp download failed.
call :PAUSE_IF_NEEDED
exit /b 1

:ERR_COPY
echo [ERROR] Copy to Tools\yt-dlp\bin failed.
call :PAUSE_IF_NEEDED
exit /b 1

:ERR_VERIFY
echo [ERROR] yt-dlp verification failed.
call :PAUSE_IF_NEEDED
exit /b 1

:ERR_DENO_INSTALLER
echo [ERROR] Deno installer was not found: %DENO_INSTALLER%
call :PAUSE_IF_NEEDED
exit /b 1

:ERR_DENO
echo [ERROR] Deno component install failed.
call :PAUSE_IF_NEEDED
exit /b 1

:RESET_DIR
set "TARGET_DIR=%~1"
if not defined TARGET_DIR exit /b 1
if /I not "%TARGET_DIR%"=="%YTDLP_DIR%" exit /b 1
if exist "%TARGET_DIR%\" rd /s /q "%TARGET_DIR%" >nul 2>nul
mkdir "%TARGET_DIR%" >nul 2>nul
if not exist "%TARGET_DIR%\" exit /b 1
exit /b 0

:PAUSE_IF_NEEDED
if not "%NO_PAUSE%"=="1" pause
goto :eof
