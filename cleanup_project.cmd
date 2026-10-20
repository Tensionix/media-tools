@echo off
setlocal EnableExtensions EnableDelayedExpansion
chcp 65001 >nul

title Audion Media Tools - Cleanup

set "BASE_DIR=%~dp0"
if "%BASE_DIR:~-1%"=="\" set "BASE_DIR=%BASE_DIR:~0,-1%"
cd /d "%BASE_DIR%" || exit /b 1

set "BASE_PREFIX=%BASE_DIR%\"
set "BASE_PREFIX_WORK=%BASE_PREFIX%"
set /a BASE_PREFIX_LEN=0
:base_prefix_len_loop
if defined BASE_PREFIX_WORK (
  set "BASE_PREFIX_WORK=!BASE_PREFIX_WORK:~1!"
  set /a BASE_PREFIX_LEN+=1
  goto base_prefix_len_loop
)
set "BASE_PREFIX_WORK="

set "ERROR_COUNT=0"
set "AUTO_YES=0"
set "DRY_RUN=0"

for %%A in (%*) do (
  if /I "%%~A"=="/Y" set "AUTO_YES=1"
  if /I "%%~A"=="/YES" set "AUTO_YES=1"
  if /I "%%~A"=="-Y" set "AUTO_YES=1"
  if /I "%%~A"=="-YES" set "AUTO_YES=1"
  if /I "%%~A"=="--yes" set "AUTO_YES=1"
  if /I "%%~A"=="/DRYRUN" set "DRY_RUN=1"
  if /I "%%~A"=="/DRY-RUN" set "DRY_RUN=1"
  if /I "%%~A"=="--dry-run" set "DRY_RUN=1"
  if /I "%%~A"=="/?" goto usage
  if /I "%%~A"=="-h" goto usage
  if /I "%%~A"=="--help" goto usage
)

if not exist "%BASE_DIR%\system_core\cli.py" (
  echo [ERROR] Project marker not found:
  echo %BASE_DIR%\system_core\cli.py
  echo.
  echo Cleanup aborted.
  call :WAIT_KEY
  exit /b 1
)

if not exist "%BASE_DIR%\config\tool_manifest.yaml" (
  echo [ERROR] Project marker not found:
  echo %BASE_DIR%\config\tool_manifest.yaml
  echo.
  echo Cleanup aborted.
  call :WAIT_KEY
  exit /b 1
)

echo ======================================================================
echo   AUDION MEDIA TOOLS - LEAN REBUILD CLEANUP
echo ======================================================================
echo Root:
echo   %BASE_DIR%
echo.
echo This script returns the project to a small source-only / LEAN state.
echo It keeps downloaded content (output\Download), LUTs, scripts, documentation, permanent configs and licenses.
echo It removes generated workspace content, build/runtime payloads, downloaded tool payloads and caches:
echo   - input, output (but output\Download), logs, report, workspace contents
echo   - runtime, wheelhouse, install\download contents, including cached 7-Zip distributives
echo   - Tools\ffmpeg, Tools\mpv, Tools\yt-dlp, Tools\deno, Tools\7zip, Tools\cineraw contents
echo   - the state of the window and the machine: window settings and forms, path history, the sealed and the open
echo     cookies, the download archive, the terminal history, the caches of components, LUTs and hardware
echo   - root/runtime/system_core cache folders: .runtime, _runtime, ._runtime, __pycache__
echo   - root pytest/mypy/ruff caches, root build/dist folders
echo   - system_core\fzf.exe: step 03 of the builder brings it back
echo   - Source\bin, Source\obj, Source\Ps\bin, Source\Ps\obj: what a build of the window leaves; App\ stays
echo   - system_core\7zip bootstrap extractor contents
echo   - transient installer temp folders in system_core
echo   - generated files inside managed cleanup folders
echo.
echo Protected user data: output\Download, LUTs.
echo Protected source: Scripts, system_core source, config, Docs, launchers, install scripts, licenses.
echo.
if "%DRY_RUN%"=="1" echo Dry-run: ON. Nothing will be deleted.
echo.

if "%AUTO_YES%"=="1" goto clean

:ask
choice /C YNQ /N /M "Proceed with project cleanup? [Y/N/Q]: "
if errorlevel 3 goto quit
if errorlevel 2 goto cancelled
if errorlevel 1 goto clean
goto ask

:clean
echo.
echo [CLEAN] Starting project cleanup...
echo.

call :RemoveDir "%BASE_DIR%\.runtime"
call :RemoveDir "%BASE_DIR%\_runtime"
call :RemoveDir "%BASE_DIR%\._runtime"
call :RemoveDir "%BASE_DIR%\__pycache__"
call :RemoveDir "%BASE_DIR%\.pytest_cache"
call :RemoveDir "%BASE_DIR%\.mypy_cache"
call :RemoveDir "%BASE_DIR%\.ruff_cache"
call :RemoveDir "%BASE_DIR%\system_core\__pycache__"
call :RemoveDir "%BASE_DIR%\system_core\core\__pycache__"
call :RemoveDir "%BASE_DIR%\system_core\services\__pycache__"
call :RemoveDir "%BASE_DIR%\system_core\tests\__pycache__"
call :RemoveDir "%BASE_DIR%\tests\__pycache__"

call :ClearDir "%BASE_DIR%\input"
call :ClearDir "%BASE_DIR%\output" "Download"
call :ClearDir "%BASE_DIR%\logs"
call :ClearDir "%BASE_DIR%\report"
call :ClearDir "%BASE_DIR%\workspace"
call :ClearDir "%BASE_DIR%\runtime"
call :ClearDir "%BASE_DIR%\wheelhouse"
call :RemoveFile "%BASE_DIR%\install\download\7zr.exe"
call :RemoveFilesInDirByPattern "%BASE_DIR%\install\download" "7z*.7z"
call :RemoveFilesInDirByPattern "%BASE_DIR%\install\download" "7zip*.7z"
call :ClearDir "%BASE_DIR%\install\download"
call :RemoveDir "%BASE_DIR%\system_core\7zip"
call :ClearDir "%BASE_DIR%\Tools\ffmpeg"
call :RemoveFilesInDirByPattern "%BASE_DIR%\Tools" "ffmpeg-*-source.tar.gz"
call :ClearDir "%BASE_DIR%\Tools\mpv"
call :RemoveFilesInDirByPattern "%BASE_DIR%\Tools" "mpv-*-source.tar.gz"
call :ClearDir "%BASE_DIR%\Tools\cineraw"
call :ClearDir "%BASE_DIR%\Tools\yt-dlp"
call :ClearDir "%BASE_DIR%\Tools\deno"
call :ClearDir "%BASE_DIR%\Tools\7zip"

call :RemoveFile "%BASE_DIR%\output\.gitkeep"

call :RemoveDir "%BASE_DIR%\build"
call :RemoveDir "%BASE_DIR%\dist"
call :RemoveDir "%BASE_DIR%\system_core\_ffmpeg_tmp"
call :RemoveDir "%BASE_DIR%\system_core\_ffmpeg_btbn_tmp"
call :RemoveDir "%BASE_DIR%\system_core\_deno_tmp"
call :RemoveDir "%BASE_DIR%\system_core\_7zip_tmp"
call :RemoveDir "%BASE_DIR%\system_core\_fzf_tmp"
call :RemoveFile "%BASE_DIR%\system_core\fzf.exe"
call :RemoveFile "%BASE_DIR%\config\hardware_capabilities_cache.json"
call :RemoveFile "%BASE_DIR%\config\window_settings.json"
call :RemoveFile "%BASE_DIR%\config\path_history.json"
call :RemoveFile "%BASE_DIR%\config\terminal_commands.json"
call :RemoveFile "%BASE_DIR%\config\components_cache.json"
call :RemoveFile "%BASE_DIR%\config\gui_lut_cache.json"
call :RemoveFile "%BASE_DIR%\config\cookies.dpapi"
call :RemoveFile "%BASE_DIR%\config\cookies.txt"
call :RemoveFile "%BASE_DIR%\config\download-archive.txt"
call :RemoveDir "%BASE_DIR%\Source\bin"
call :RemoveDir "%BASE_DIR%\Source\obj"
call :RemoveDir "%BASE_DIR%\Source\Ps\bin"
call :RemoveDir "%BASE_DIR%\Source\Ps\obj"

if exist "%BASE_DIR%\install\init_folders.cmd" (
  if "%DRY_RUN%"=="1" (
    echo [DRY] call install\init_folders.cmd
  ) else (
    call "%BASE_DIR%\install\init_folders.cmd" >nul 2>nul
  )
)

echo.
if not "%ERROR_COUNT%"=="0" goto cleanup_failed
if "%DRY_RUN%"=="1" goto dry_run_done
echo [OK] Cleanup finished.
echo [OK] Project is back to source-only LEAN shape.
echo [OK] runtime, wheelhouse, Tools, install\download and generated work folders were recreated empty.
goto cleanup_done

:dry_run_done
echo [OK] Dry run finished. Nothing was deleted.

:cleanup_done
if not "%AUTO_YES%"=="1" call :WAIT_KEY
exit /b 0

:cleanup_failed
echo [ERROR] Cleanup finished with %ERROR_COUNT% error(s).
echo Close GUI, terminals, Python processes, FFmpeg/yt-dlp/Deno/7-Zip processes, and try again.
if not "%AUTO_YES%"=="1" call :WAIT_KEY
exit /b 1

:cancelled
echo.
echo [CANCELLED] Nothing was deleted.
if not "%AUTO_YES%"=="1" call :WAIT_KEY
exit /b 0

:quit
echo.
echo [QUIT] Nothing was deleted.
if not "%AUTO_YES%"=="1" call :WAIT_KEY
exit /b 0


:usage
echo Usage:
echo   cleanup_project.cmd [/Y] [/DRYRUN]
echo.
echo Options:
echo   /Y, /YES, --yes       Run without confirmation.
echo   /DRYRUN, --dry-run    Print actions without deleting anything.
exit /b 0
:ClearDir
set "TARGET_DIR=%~1"
rem A second argument names a folder inside that stays: downloads in output\Download.
set "KEEP_NAME=%~2"
call :AssertInside "%TARGET_DIR%" || (
  set /a ERROR_COUNT+=1
  exit /b 1
)
if not exist "%TARGET_DIR%\" (
  if "%DRY_RUN%"=="1" (
    echo [DRY] mkdir "%TARGET_DIR%"
  ) else (
    echo [CREATE] %TARGET_DIR%
    md "%TARGET_DIR%" >nul 2>nul
    if not exist "%TARGET_DIR%\" call :MarkError "Could not create directory: %TARGET_DIR%"
  )
  exit /b 0
)
call :IsLink "%TARGET_DIR%"
if "!IS_LINK!"=="1" (
  call :MarkError "Not cleared: %TARGET_DIR% is a link to another place, and what lies there is not the project's"
  exit /b 1
)
echo [CLEAR] %TARGET_DIR%
for /f "delims=" %%I in ('dir /a /b "%TARGET_DIR%" 2^>nul') do (
  call :IsLink "%TARGET_DIR%\%%I"
  if /I "%%I"=="%KEEP_NAME%" (
    echo   [KEEP] %TARGET_DIR%\%%I
  ) else if "!IS_LINK!"=="1" (
    call :RemoveLink "%TARGET_DIR%\%%I"
  ) else (
    if exist "%TARGET_DIR%\%%I\" (
      if "%DRY_RUN%"=="1" (
        echo   [DRY] rmdir /s /q "%TARGET_DIR%\%%I"
      ) else (
        echo   rmdir "%TARGET_DIR%\%%I"
        attrib -r -s -h "%TARGET_DIR%\%%I\*" /s /d >nul 2>nul
        rd /s /q "%TARGET_DIR%\%%I" >nul 2>nul
        if exist "%TARGET_DIR%\%%I\" call :MarkError "Could not remove directory: %TARGET_DIR%\%%I"
      )
    ) else (
      if "%DRY_RUN%"=="1" (
        echo   [DRY] del "%TARGET_DIR%\%%I"
      ) else (
        echo   del "%TARGET_DIR%\%%I"
        attrib -r -s -h "%TARGET_DIR%\%%I" >nul 2>nul
        del /f /q "%TARGET_DIR%\%%I" >nul 2>nul
        if exist "%TARGET_DIR%\%%I" call :MarkError "Could not remove file: %TARGET_DIR%\%%I"
      )
    )
  )
)
exit /b 0

:RemoveDir
set "TARGET=%~1"
if not exist "%TARGET%\" exit /b 0
call :AssertInside "%TARGET%" || (
  set /a ERROR_COUNT+=1
  exit /b 1
)
call :IsLink "%TARGET%"
if "!IS_LINK!"=="1" (
  call :RemoveLink "%TARGET%"
  exit /b 0
)
if "%DRY_RUN%"=="1" (
  echo   [DRY] rmdir /s /q "%TARGET%"
  exit /b 0
)
echo   rmdir "%TARGET%"
attrib -r -s -h "%TARGET%\*" /s /d >nul 2>nul
rd /s /q "%TARGET%" >nul 2>nul
if exist "%TARGET%\" call :MarkError "Could not remove directory: %TARGET%"
exit /b 0

:RemoveFile
set "TARGET=%~1"
if not exist "%TARGET%" exit /b 0
call :AssertInside "%TARGET%" || (
  set /a ERROR_COUNT+=1
  exit /b 1
)
if "%DRY_RUN%"=="1" (
  echo   [DRY] del "%TARGET%"
  exit /b 0
)
echo   del "%TARGET%"
attrib -r -s -h "%TARGET%" >nul 2>nul
del /f /q "%TARGET%" >nul 2>nul
if exist "%TARGET%" call :MarkError "Could not remove file: %TARGET%"
exit /b 0
:RemoveFilesInDirByPattern
set "TARGET_DIR=%~1"
set "PATTERN=%~2"
if not exist "%TARGET_DIR%\" exit /b 0
call :AssertInside "%TARGET_DIR%" || (
  set /a ERROR_COUNT+=1
  exit /b 1
)
call :IsLink "%TARGET_DIR%"
if "!IS_LINK!"=="1" (
  call :MarkError "Not cleared: %TARGET_DIR% is a link to another place"
  exit /b 1
)
echo [FILES] Removing %PATTERN% in %TARGET_DIR%
for /f "delims=" %%F in ('dir /a-d /b "%TARGET_DIR%\%PATTERN%" 2^>nul') do (
  if "%DRY_RUN%"=="1" (
    echo   [DRY] del "%TARGET_DIR%\%%F"
  ) else (
    echo   del "%TARGET_DIR%\%%F"
    attrib -r -s -h "%TARGET_DIR%\%%F" >nul 2>nul
    del /f /q "%TARGET_DIR%\%%F" >nul 2>nul
    if exist "%TARGET_DIR%\%%F" call :MarkError "Could not remove file: %TARGET_DIR%\%%F"
  )
)
exit /b 0

:IsLink
rem IS_LINK=1 when the path is a link - a junction or a symbolic link, of a folder or a file: the parent lists it among
rem its reparse points. A path inside a project may lead out of it through such a link; its contents are never walked.
set "IS_LINK=0"
set "LINK_PATH=%~f1"
for %%P in ("!LINK_PATH!\..") do set "LINK_PARENT=%%~fP"
for %%N in ("!LINK_PATH!") do set "LINK_NAME=%%~nxN"
for /f "delims=" %%L in ('dir /al /b "!LINK_PARENT!" 2^>nul') do if /I "%%L"=="!LINK_NAME!" set "IS_LINK=1"
exit /b 0

:RemoveLink
rem The link itself goes; what it leads to stays where it is.
if "%DRY_RUN%"=="1" (
  echo   [DRY] unlink "%~1"
  exit /b 0
)
echo   unlink "%~1"
if exist "%~1\" (rd "%~1" >nul 2>nul) else (del /f /q /a:l "%~1" >nul 2>nul)
call :IsLink "%~1"
if "!IS_LINK!"=="1" call :MarkError "Could not remove link: %~1"
exit /b 0

:AssertInside
set "TARGET_ABS=%~f1"
if /I "%TARGET_ABS%"=="%BASE_DIR%" (
  echo [SKIP] Refusing to clean project root directly.
  exit /b 1
)
set "TARGET_HEAD=!TARGET_ABS:~0,%BASE_PREFIX_LEN%!"
if /I "!TARGET_HEAD!"=="!BASE_PREFIX!" exit /b 0
echo [SKIP] Outside project root: %TARGET_ABS%
exit /b 1

:MarkError
echo   [ERROR] %~1
set /a ERROR_COUNT+=1
exit /b 0

:WAIT_KEY
echo Press any key to continue . . .
if not defined AUDION_NO_PAUSE pause >nul
goto :eof
