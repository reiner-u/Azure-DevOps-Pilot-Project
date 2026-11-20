@echo off
rem Builds the converter: ADO_Test_Converter.exe in this folder (one file, no Python needed to run it).
rem Needs Python 3 and internet access once (pip installs PyInstaller and openpyxl into a temporary _build folder, which is deleted at the end).
rem Run this again after ANY change under scripts\ (converter\, converter_ui\, converter_gui.py), and bump TOOL_VERSION in scripts\converter\settings.py first.
rem The zip (exe plus ADO_Test_Converter_README.txt if present) goes in releases\ and is named from TOOL_VERSION. Hand the zip out through a work channel, never GitHub.
rem The tests (tests\) run first; a failing test stops the build.
rem scripts\local_config.json (Area Path) and scripts\LabelInfo.xml (sensitivity label) are bundled into the exe when they exist; they are not kept in the code repository.
cd /d "%~dp0"
set ADD=
if exist "%~dp0scripts\LabelInfo.xml" set ADD=%ADD% --add-data "%~dp0scripts\LabelInfo.xml;."
if exist "%~dp0scripts\local_config.json" set ADD=%ADD% --add-data "%~dp0scripts\local_config.json;."
if exist _build rd /s /q _build
python -m venv _build\venv || goto :fail
_build\venv\Scripts\python -m pip install --quiet --disable-pip-version-check pyinstaller openpyxl || goto :fail
set PYTHONDONTWRITEBYTECODE=1
_build\venv\Scripts\python -m unittest discover -s tests || goto :fail
_build\venv\Scripts\python -m PyInstaller --noconfirm --clean --onefile --windowed --name ADO_Test_Converter --distpath "%~dp0." --workpath _build\work --specpath _build --paths "%~dp0scripts" %ADD% --exclude-module numpy --exclude-module pandas --exclude-module matplotlib --exclude-module PIL "%~dp0scripts\converter_gui.py" || goto :fail
rd /s /q _build
set V=
for /f "tokens=2 delims==" %%a in ('findstr /b /c:"TOOL_VERSION" "%~dp0scripts\converter\settings.py"') do set V=%%a
set V=%V: =%
set V=%V:"=%
if not exist releases md releases
set ZIPFILES=ADO_Test_Converter.exe
if exist "%~dp0ADO_Test_Converter_README.txt" set ZIPFILES=ADO_Test_Converter.exe,ADO_Test_Converter_README.txt
powershell -NoProfile -Command "Compress-Archive -Force -Path %ZIPFILES% -DestinationPath releases\ADO_Test_Converter_v%V%.zip" || goto :fail
echo.
echo Built ADO_Test_Converter.exe (version %V%) and releases\ADO_Test_Converter_v%V%.zip
if not "%1"=="nopause" pause
goto :eof
:fail
echo BUILD FAILED
if not "%1"=="nopause" pause
