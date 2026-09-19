@echo off
setlocal
cd /d "%~dp0"

where pythonw >nul 2>nul
if errorlevel 1 (
  echo Python not found. Run install.bat first.
  pause
  exit /b 1
)

start "" pythonw "%~dp0blythe_a4_maker.pyw"

