@echo off
cd /d "%~dp0"
if exist "dist\Umeko\Umeko.exe" (
    start "" "dist\Umeko\Umeko.exe"
    exit /b
)
if exist ".venv\Scripts\pythonw.exe" (
    start "" ".venv\Scripts\pythonw.exe" "main.py"
    exit /b
)
echo Please run setup.ps1 first. See README.md.
pause
