@echo off
setlocal EnableExtensions
chcp 65001 >nul

set "COMMON_DIR=%~dp0"
for %%A in ("%COMMON_DIR%..\..") do set "ROOT=%%~fA"

set "PYTHON_EXE=%ROOT%\runtime\python.exe"
if not exist "%PYTHON_EXE%" set "PYTHON_EXE=%ROOT%\.runtime\python.exe"
if not exist "%PYTHON_EXE%" set "PYTHON_EXE=python"

set "RUNNER=%COMMON_DIR%script_runner.py"
if not exist "%RUNNER%" (
  echo [ERROR] Script runner was not found: "%RUNNER%"
  exit /b 1
)

"%PYTHON_EXE%" "%RUNNER%" %*
exit /b %ERRORLEVEL%
