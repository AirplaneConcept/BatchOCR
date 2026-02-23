@echo off
setlocal
cd /d "%~dp0"

REM Prefer PowerShell 7 (pwsh) if available; fall back to Windows PowerShell.
where pwsh >nul 2>&1
if %errorlevel%==0 (
  pwsh -NoProfile -ExecutionPolicy Bypass -File "%~dp0BatchOCR.ps1"
) else (
  powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0BatchOCR.ps1"
)

endlocal
