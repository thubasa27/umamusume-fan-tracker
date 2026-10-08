@echo off
rem Builds the portable zip (dist\FanTracker-portable-v<version>.zip).
chcp 65001 >nul
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0build_portable.ps1" %*
set EXITCODE=%ERRORLEVEL%
pause
exit /b %EXITCODE%
