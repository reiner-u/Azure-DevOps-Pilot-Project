@echo off
rem Runs the tests (made-up documents only; takes a few seconds). Add -v for one line per test. "nopause" skips the pause.
cd /d "%~dp0"
set PYTHONDONTWRITEBYTECODE=1
if "%1"=="nopause" goto :nopause
python -m unittest discover -s tests %*
pause
goto :eof
:nopause
python -m unittest discover -s tests
