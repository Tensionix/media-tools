@echo off
setlocal EnableExtensions
chcp 65001 >nul

rem The door of every wrapper of Scripts\: Scripts\<name>.cmd calls it with its own name, and it hands the
rem name and the arguments to the console command - media_cli.cmd wrapper <name> [arguments]. What a
rem wrapper runs is written in config\wrappers.yaml; the work is the engine's, the same a button of the
rem window does. The environment the wrappers have always read (AUDION_SOURCE, AUDION_OUTPUT,
rem AUDION_DRY_RUN, AUDION_CRF and the rest) is read by the console command.

for %%A in ("%~dp0..\..") do set "ROOT=%%~fA"
rem Not a block in brackets: a path with a bracket in it - "Program Files (x86)" - would close it.
if not exist "%ROOT%\media_cli.cmd" goto NO_CLI
call "%ROOT%\media_cli.cmd" wrapper %*
exit /b %ERRORLEVEL%

:NO_CLI
echo [ERROR] The console command was not found: "%ROOT%\media_cli.cmd"
exit /b 2
