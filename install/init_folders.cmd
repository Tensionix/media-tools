@echo off
setlocal EnableExtensions

set "SCRIPT_DIR=%~dp0"
if "%SCRIPT_DIR:~-1%"=="\" set "SCRIPT_DIR=%SCRIPT_DIR:~0,-1%"

for %%A in ("%SCRIPT_DIR%") do set "HERE=%%~nxA"

set "ROOT=%SCRIPT_DIR%"
if /I "%HERE%"=="install" for %%A in ("%SCRIPT_DIR%\..") do set "ROOT=%%~fA"

call :MK "%ROOT%\input"
call :MK "%ROOT%\output"
call :MK "%ROOT%\LUTs"
call :MK "%ROOT%\Scripts"
call :MK "%ROOT%\Tools"
call :MK "%ROOT%\Tools\7zip"
call :MK "%ROOT%\Tools\7zip\bin"
call :MK "%ROOT%\Tools\ffmpeg"
call :MK "%ROOT%\Tools\ffmpeg\bin"
call :MK "%ROOT%\Tools\yt-dlp"
call :MK "%ROOT%\Tools\yt-dlp\bin"
call :MK "%ROOT%\Tools\deno"
call :MK "%ROOT%\logs"
call :MK "%ROOT%\report"
call :MK "%ROOT%\workspace"
call :MK "%ROOT%\config"
call :MK "%ROOT%\runtime"
call :MK "%ROOT%\wheelhouse"
call :MK "%ROOT%\._runtime"
call :MK "%ROOT%\Docs"
call :MK "%ROOT%\system_core"
call :MK "%ROOT%\system_core\core"
call :MK "%ROOT%\system_core\services"
call :MK "%ROOT%\install"
call :MK "%ROOT%\install\download"
call :MK "%ROOT%\licenses"

exit /b 0

:MK
if not exist "%~1\" mkdir "%~1" >nul 2>nul
goto :eof
