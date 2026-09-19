@echo off
cd /d "%~dp0"
where pythonw >nul 2>nul
if errorlevel 1 (
  call "%~dp0app\install.bat"
  exit /b %errorlevel%
)
python -c "import PIL" >nul 2>nul
if errorlevel 1 python -m pip install -r "%~dp0app\requirements.txt" --disable-pip-version-check
start "" pythonw "%~dp0app\blythe_a4_maker.pyw"
