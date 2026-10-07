@echo off
rem Windows verification launcher. Pass-through options: -SkipTests -E2E -NoStart
chcp 65001 >nul
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0verify_windows.ps1" %*
set EXITCODE=%ERRORLEVEL%
if "%~1"=="" pause
exit /b %EXITCODE%
