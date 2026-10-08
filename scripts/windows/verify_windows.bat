@echo off
rem Windows verification launcher. Starts the app minimized after the checks pass.
rem Pass-through options: -SkipTests -E2E -NoStart
chcp 65001 >nul
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0verify_windows.ps1" -Minimized %*
set EXITCODE=%ERRORLEVEL%
rem Keep the window open when something failed, or when the app is not started (-NoStart).
if not "%EXITCODE%"=="0" pause
echo %* | find /i "-NoStart" >nul && pause
exit /b %EXITCODE%
