@echo off
setlocal
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0install.ps1" %*
set "_INSTALL_EXIT=%errorlevel%"
if not "%_INSTALL_EXIT%"=="0" (
    echo.
    echo Installation failed. Review the error above.
    pause
)
exit /b %_INSTALL_EXIT%
