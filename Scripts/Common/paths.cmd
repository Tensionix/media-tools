@echo off

if not defined ROOT for %%A in ("%~dp0..\..") do set "ROOT=%%~fA"

set "SRC=%ROOT%\Source"
set "OUT=%ROOT%\Transcoded"
set "DL=%ROOT%\Download"
set "LOG=%ROOT%\Logs"
set "TOOLS=%ROOT%\Tools"

if defined AUDION_SOURCE for %%A in ("%AUDION_SOURCE%") do set "SRC=%%~fA"
if defined AUDION_SRC for %%A in ("%AUDION_SRC%") do set "SRC=%%~fA"
if defined SOURCE for %%A in ("%SOURCE%") do set "SRC=%%~fA"

if defined AUDION_OUTPUT for %%A in ("%AUDION_OUTPUT%") do set "OUT=%%~fA"
if defined AUDION_OUT for %%A in ("%AUDION_OUT%") do set "OUT=%%~fA"
if defined AUDION_DESTINATION for %%A in ("%AUDION_DESTINATION%") do set "OUT=%%~fA"

if defined AUDION_DOWNLOAD for %%A in ("%AUDION_DOWNLOAD%") do set "DL=%%~fA"
if defined AUDION_DOWNLOAD_DIR for %%A in ("%AUDION_DOWNLOAD_DIR%") do set "DL=%%~fA"
