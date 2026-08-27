@echo off
for /f "tokens=1,2 delims==" %%a in ('"prompt $H & for %%b in (1) do rem"') do set "BS=%%a"

set "C_OK=[OK]"
set "C_ERR=[!]"
set "C_DO=[>>]"
