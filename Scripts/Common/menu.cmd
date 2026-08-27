@echo off
set "READ_KEY_CMD=choice /c 1234567890q /n"

rem usage: call :ask_yes_no "Question?" && (do yes) || (do no)
goto :eof

:ask_yes_no
setlocal
set "_q=%~1"
<nul set /p =%_q% [Y/N] :
choice /c YN /n >nul
if errorlevel 2 (endlocal & exit /b 1)
endlocal & exit /b 0
