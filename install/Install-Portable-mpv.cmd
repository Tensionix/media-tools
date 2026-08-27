@echo off
setlocal EnableExtensions EnableDelayedExpansion

title Audion Media Tools - Install Portable mpv

set "SCRIPT_DIR=%~dp0"
if "%SCRIPT_DIR:~-1%"=="\" set "SCRIPT_DIR=%SCRIPT_DIR:~0,-1%"
for %%A in ("%SCRIPT_DIR%\..") do set "ROOT=%%~fA"

set "INSTALLER=%SCRIPT_DIR%\Install-Portable-mpv.ps1"
set "PS_EXE="
set "NO_PAUSE=0"
if /I "%AUDION_NO_PAUSE%"=="1" set "NO_PAUSE=1"

:PARSE_ARGS
if "%~1"=="" goto DONE_ARGS
if /I "%~1"=="/NOPAUSE" set "NO_PAUSE=1"
if /I "%~1"=="--no-pause" set "NO_PAUSE=1"
shift
goto PARSE_ARGS
:DONE_ARGS

if exist "%ROOT%\system_core\powershell\pwsh.exe" set "PS_EXE=%ROOT%\system_core\powershell\pwsh.exe"
if not defined PS_EXE where pwsh.exe >nul 2>nul && set "PS_EXE=pwsh.exe"
if not defined PS_EXE where powershell.exe >nul 2>nul && set "PS_EXE=powershell.exe"
if not defined PS_EXE goto ERR_POWERSHELL
if not exist "%INSTALLER%" goto ERR_INSTALLER

"%PS_EXE%" -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%INSTALLER%" -ProjectRoot "%ROOT%"
if errorlevel 1 goto ERR_INSTALL

call :PAUSE_IF_NEEDED
exit /b 0

:ERR_POWERSHELL
echo [ERROR] PowerShell was not found.
call :PAUSE_IF_NEEDED
exit /b 1

:ERR_INSTALLER
echo [ERROR] Installer script was not found: %INSTALLER%
call :PAUSE_IF_NEEDED
exit /b 1

:ERR_INSTALL
echo [ERROR] mpv install failed.
call :PAUSE_IF_NEEDED
exit /b 1

:PAUSE_IF_NEEDED
if not "%NO_PAUSE%"=="1" pause
goto :eof
