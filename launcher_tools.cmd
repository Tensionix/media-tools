@echo off
setlocal EnableExtensions EnableDelayedExpansion

title Audion Media Tools - Tools Launcher

set "BASE_DIR=%~dp0"
if "%BASE_DIR:~-1%"=="\" set "BASE_DIR=%BASE_DIR:~0,-1%"
cd /d "%BASE_DIR%"

set "CORE_DIR=%BASE_DIR%\system_core"
set "INSTALL_DIR=%BASE_DIR%\install"
set "FZF_EXE=%CORE_DIR%\fzf.exe"
set "RUNTIME_DIR=%BASE_DIR%\._runtime"
set "MENU_FILE=%RUNTIME_DIR%\tools_menu.txt"
set "RES_FILE=%RUNTIME_DIR%\tools_menu_res.txt"
set "PYTHON_AVAILABLE="
set "TOOLS_PROMPT=audion@media [TOOLS] > "

if not exist "%RUNTIME_DIR%" mkdir "%RUNTIME_DIR%" >nul 2>nul
call :RESOLVE_PYTHON

:MAIN
cls
echo ======================================================================
echo   AUDION MEDIA TOOLS - TOOLS / SERVICE
echo ======================================================================
if defined PYTHON_AVAILABLE (
  echo Python: %PYTHON_CMD% %PYTHON_ARGS%
) else (
  echo Python: not resolved
)
echo.

if exist "%FZF_EXE%" goto FZF_MENU
goto FALLBACK_MENU

:FZF_MENU
> "%MENU_FILE%" echo [01] ENV DOCTOR                           ^| doctor              ^| verify runtime and imports
>>"%MENU_FILE%" echo.
>>"%MENU_FILE%" echo [02] OPEN licenses                        ^| open_licenses       ^| explorer
>>"%MENU_FILE%" echo [03] OPEN system_core                     ^| open_core           ^| explorer
>>"%MENU_FILE%" echo [04] OPEN install                         ^| open_install        ^| explorer
>>"%MENU_FILE%" echo [05] OPEN wheelhouse                      ^| open_wheels         ^| explorer
>>"%MENU_FILE%" echo [00] BACK                                 ^| back                ^| return

type "%MENU_FILE%" | "%FZF_EXE%" --prompt="%TOOLS_PROMPT%" --pointer=">" --header="Pick tool:" --layout=reverse --border="rounded" --info=hidden --margin=1,2 > "%RES_FILE%"

set "CHOICE="
set /p CHOICE=<"%RES_FILE%"
del /q "%MENU_FILE%" "%RES_FILE%" >nul 2>&1
if not defined CHOICE goto MAIN

for /f "tokens=2 delims=|" %%a in ("%CHOICE%") do set "RAW=%%a"
call :TRIM RAW

if /I "%RAW%"=="doctor" goto DOCTOR
if /I "%RAW%"=="open_core" goto OPEN_CORE
if /I "%RAW%"=="open_install" goto OPEN_INSTALL
if /I "%RAW%"=="open_wheels" goto OPEN_WHEELS
if /I "%RAW%"=="open_licenses" goto OPEN_LICENSES
if /I "%RAW%"=="back" exit /b 0
goto MAIN

:FALLBACK_MENU
echo [1] Env doctor
echo [2] Open licenses
echo [3] Open system_core
echo [4] Open install
echo [5] Open wheelhouse
echo [0] Back
echo.
choice /C 123450 /N /M "Select: "
if errorlevel 6 exit /b 0
if errorlevel 5 goto OPEN_WHEELS
if errorlevel 4 goto OPEN_INSTALL
if errorlevel 3 goto OPEN_CORE
if errorlevel 2 goto OPEN_LICENSES
if errorlevel 1 goto DOCTOR
goto MAIN

:DOCTOR
call :REQUIRE_PYTHON || goto MAIN
"%PYTHON_CMD%" %PYTHON_ARGS% "%CORE_DIR%\doctor.py"
if not defined AUDION_NO_PAUSE pause
goto MAIN

:OPEN_CORE
start "" explorer "%CORE_DIR%"
goto MAIN

:OPEN_INSTALL
start "" explorer "%INSTALL_DIR%"
goto MAIN

:OPEN_WHEELS
start "" explorer "%BASE_DIR%\wheelhouse"
goto MAIN

:OPEN_LICENSES
if not exist "%BASE_DIR%\licenses" mkdir "%BASE_DIR%\licenses" >nul 2>nul
start "" explorer "%BASE_DIR%\licenses"
goto MAIN

:REQUIRE_PYTHON
if defined PYTHON_AVAILABLE exit /b 0
echo [ERROR] Python runtime was not resolved.
if not defined AUDION_NO_PAUSE pause
exit /b 1

:RESOLVE_PYTHON
set "PYTHON_CMD="
set "PYTHON_ARGS="
set "PYTHON_AVAILABLE="
if exist "%BASE_DIR%\runtime\python.exe" (
  set "PYTHON_CMD=%BASE_DIR%\runtime\python.exe"
  set "PYTHON_AVAILABLE=1"
  goto :eof
)
if exist "%BASE_DIR%\runtime\python\python.exe" (
  set "PYTHON_CMD=%BASE_DIR%\runtime\python\python.exe"
  set "PYTHON_AVAILABLE=1"
  goto :eof
)
py -3.12 -V >nul 2>nul
if not errorlevel 1 (
  set "PYTHON_CMD=py"
  set "PYTHON_ARGS=-3.12"
  set "PYTHON_AVAILABLE=1"
  goto :eof
)
py -3 -V >nul 2>nul
if not errorlevel 1 (
  set "PYTHON_CMD=py"
  set "PYTHON_ARGS=-3"
  set "PYTHON_AVAILABLE=1"
  goto :eof
)
where python.exe >nul 2>nul
if not errorlevel 1 (
  set "PYTHON_CMD=python"
  set "PYTHON_AVAILABLE=1"
  goto :eof
)
where python3.exe >nul 2>nul
if not errorlevel 1 (
  set "PYTHON_CMD=python3"
  set "PYTHON_AVAILABLE=1"
  goto :eof
)
goto :eof

:TRIM
set "_TMP=!%~1!"
for /f "tokens=* delims= " %%z in ("!_TMP!") do set "_TMP=%%z"
:TRIM_R
if not defined _TMP goto TRIM_DONE
if not "!_TMP:~-1!"==" " goto TRIM_DONE
set "_TMP=!_TMP:~0,-1!"
goto TRIM_R
:TRIM_DONE
set "%~1=!_TMP!"
goto :eof
