@echo off
setlocal EnableExtensions
chcp 65001 >nul
call "%~dp0Common\run-profile.cmd" "%~n0" %*
exit /b %ERRORLEVEL%
