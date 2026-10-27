@echo off
cd /d "%~dp0"
python scripts\build_import_from_source.py --all
echo.
pause
