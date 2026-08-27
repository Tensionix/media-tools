@echo off
setlocal EnableExtensions EnableDelayedExpansion

title Audion Media Tools - Install Portable Deno

set "SCRIPT_DIR=%~dp0"
if "%SCRIPT_DIR:~-1%"=="\" set "SCRIPT_DIR=%SCRIPT_DIR:~0,-1%"
for %%A in ("%SCRIPT_DIR%\..") do set "ROOT=%%~fA"

set "DL=%ROOT%\install\download"
set "DENO_DIR=%ROOT%\Tools\deno"
set "TMP=%ROOT%\system_core\_deno_tmp"
set "ZIP=%DL%\deno-x86_64-pc-windows-msvc.zip"
set "URL=https://github.com/denoland/deno/releases/latest/download/deno-x86_64-pc-windows-msvc.zip"
set "PS_EXE="
set "NO_PAUSE=0"

if /I "%~1"=="/NOPAUSE" set "NO_PAUSE=1"
if /I "%~1"=="--no-pause" set "NO_PAUSE=1"

if exist "%ROOT%\system_core\powershell\pwsh.exe" set "PS_EXE=%ROOT%\system_core\powershell\pwsh.exe"
if not defined PS_EXE where pwsh.exe >nul 2>nul && set "PS_EXE=pwsh.exe"
if not defined PS_EXE where powershell.exe >nul 2>nul && set "PS_EXE=powershell.exe"

if not exist "%DL%\" mkdir "%DL%" >nul 2>nul
if not exist "%DENO_DIR%\" mkdir "%DENO_DIR%" >nul 2>nul

echo ======================================================================
echo   AUDION MEDIA TOOLS - INSTALL PORTABLE DENO
echo ======================================================================
echo Root:    %ROOT%
echo Target:  %DENO_DIR%
echo DL:      %DL%
echo PS:      %PS_EXE%
echo.

if not defined PS_EXE goto ERR_POWERSHELL

echo [1/4] Downloading latest Deno Windows executable...
if exist "%ZIP%" del /f /q "%ZIP%" >nul 2>nul
"%PS_EXE%" -NoLogo -NoProfile -ExecutionPolicy Bypass -Command ^
  "$ErrorActionPreference='Stop';" ^
  "$ProgressPreference='SilentlyContinue';" ^
  "$headers=@{'User-Agent'='Audion-Media-Tools'};" ^
  "Write-Host ('[URL] ' + '%URL%');" ^
  "Invoke-WebRequest -Headers $headers -Uri '%URL%' -OutFile '%ZIP%'"
if errorlevel 1 goto ERR_DOWNLOAD

if not exist "%ZIP%" goto ERR_DOWNLOAD
for %%F in ("%ZIP%") do echo [OK] Downloaded: %%~zF bytes
echo.

echo [2/4] Extracting Deno...
if exist "%TMP%" rd /s /q "%TMP%" >nul 2>nul
mkdir "%TMP%" >nul 2>nul
"%PS_EXE%" -NoLogo -NoProfile -ExecutionPolicy Bypass -Command ^
  "$ErrorActionPreference='Stop';" ^
  "Expand-Archive -Path '%ZIP%' -DestinationPath '%TMP%' -Force"
if errorlevel 1 goto ERR_EXTRACT

if not exist "%TMP%\deno.exe" goto ERR_NOEXE

echo [3/4] Copying deno.exe...
call :RESET_DIR "%DENO_DIR%"
if errorlevel 1 goto ERR_COPY
copy /y "%TMP%\deno.exe" "%DENO_DIR%\deno.exe" >nul
if errorlevel 1 goto ERR_COPY

echo [4/4] Verifying...
"%DENO_DIR%\deno.exe" --version
if errorlevel 1 goto ERR_VERIFY

rd /s /q "%TMP%" >nul 2>nul

echo.
echo [SUCCESS] Deno installed: %DENO_DIR%\deno.exe
call :PAUSE_IF_NEEDED
exit /b 0

:ERR_POWERSHELL
echo [ERROR] PowerShell was not found.
call :PAUSE_IF_NEEDED
exit /b 1

:ERR_DOWNLOAD
echo [ERROR] Deno download failed.
call :PAUSE_IF_NEEDED
exit /b 1

:ERR_EXTRACT
echo [ERROR] Deno extract failed.
call :PAUSE_IF_NEEDED
exit /b 1

:ERR_NOEXE
echo [ERROR] deno.exe was not found after extraction.
call :PAUSE_IF_NEEDED
exit /b 1

:ERR_COPY
echo [ERROR] Copy to Tools\deno failed.
call :PAUSE_IF_NEEDED
exit /b 1

:ERR_VERIFY
echo [ERROR] Deno verification failed.
call :PAUSE_IF_NEEDED
exit /b 1

:RESET_DIR
set "TARGET_DIR=%~1"
if not defined TARGET_DIR exit /b 1
if /I not "%TARGET_DIR%"=="%DENO_DIR%" exit /b 1
if exist "%TARGET_DIR%\" rd /s /q "%TARGET_DIR%" >nul 2>nul
mkdir "%TARGET_DIR%" >nul 2>nul
if not exist "%TARGET_DIR%\" exit /b 1
exit /b 0

:PAUSE_IF_NEEDED
if not "%NO_PAUSE%"=="1" pause
goto :eof
