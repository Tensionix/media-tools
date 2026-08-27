@echo off
setlocal EnableExtensions
title Audion Media Tools - Init Folders
for %%I in ("%~dp0..") do set "ROOT=%%~fI"
if "%ROOT:~-1%"=="\" set "ROOT=%ROOT:~0,-1%"
echo ======================================================================
echo   AUDION MEDIA TOOLS - INIT FOLDERS
echo ======================================================================
echo Root: %ROOT%
echo.
if not exist "%ROOT%\install\init_folders.cmd" (
  echo [ERROR] install\init_folders.cmd was not found.
  if not defined AUDION_NO_PAUSE pause
  exit /b 1
)
call "%ROOT%\install\init_folders.cmd"
if errorlevel 1 (
  echo.
  echo [ERROR] Folder initialization failed.
  if not defined AUDION_NO_PAUSE pause
  exit /b 1
)
echo.
echo [OK] Folder structure is ready.
echo.
echo Media tools are installed by builder_main.cmd:
echo   Tools\ffmpeg\bin\
echo   Tools\yt-dlp\bin\
echo   Tools\7zip\bin\
echo.
echo Internal builder tools use:
echo   system_core\fzf.exe
echo   system_core\powershell\
echo.
if not defined AUDION_NO_PAUSE pause
exit /b 0
