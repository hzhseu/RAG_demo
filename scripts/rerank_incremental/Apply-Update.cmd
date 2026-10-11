@echo off
setlocal
if "%~1"=="" (
  powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0Apply-Update.ps1" -TargetDirectory "%~dp0."
) else (
  powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0Apply-Update.ps1" -TargetDirectory "%~1"
)
set "update_exit=%ERRORLEVEL%"
echo.
pause
exit /b %update_exit%
