@echo off
setlocal EnableExtensions
chcp 65001 >nul

set "REPO_ZIP=https://github.com/apinanautan/blythe-a4-maker/archive/refs/heads/main.zip"
set "APPDIR=%USERPROFILE%\Desktop\Blythe"
set "TMPZIP=%TEMP%\blythe-a4-maker.zip"
set "TMPDIR=%TEMP%\blythe-a4-maker-install"

echo ========================================
echo   Blythe A4 Maker - Easy Installer
echo ========================================
echo.

where python >nul 2>nul
if errorlevel 1 (
  echo Installing Python...
  where winget >nul 2>nul
  if errorlevel 1 (
    echo Python is required. Install Python 3 from python.org and run this file again.
    pause
    exit /b 1
  )
  winget install -e --id Python.Python.3.13 --accept-source-agreements --accept-package-agreements
  if errorlevel 1 (
    echo Python installation failed.
    pause
    exit /b 1
  )
  set "PATH=%LOCALAPPDATA%\Programs\Python\Python313;%LOCALAPPDATA%\Programs\Python\Python313\Scripts;%PATH%"
)

if exist "%TMPDIR%" rmdir /s /q "%TMPDIR%"
if exist "%TMPZIP%" del /q "%TMPZIP%"

echo Downloading latest version...
curl.exe -L --fail "%REPO_ZIP%" -o "%TMPZIP%"
if errorlevel 1 (
  echo Download failed. Check your internet connection.
  pause
  exit /b 1
)

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "Expand-Archive -LiteralPath '%TMPZIP%' -DestinationPath '%TMPDIR%' -Force"
if errorlevel 1 (
  echo Cannot extract downloaded file.
  pause
  exit /b 1
)

if not exist "%APPDIR%" mkdir "%APPDIR%"
robocopy "%TMPDIR%\blythe-a4-maker-main" "%APPDIR%" /E /R:1 /W:1 /NFL /NDL /NJH /NJS /NP >nul
if errorlevel 8 (
  echo Copy failed.
  pause
  exit /b 1
)

echo Installing Python package...
python -m pip install -r "%APPDIR%\requirements.txt" --disable-pip-version-check
if errorlevel 1 (
  echo Pillow installation failed.
  pause
  exit /b 1
)

echo.
echo Installed: %APPDIR%
echo Opening Blythe A4 Maker...
start "" "%APPDIR%\run.bat"

endlocal

