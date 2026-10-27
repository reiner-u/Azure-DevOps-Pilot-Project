# Test document converter

Converts Excel test-case documents (ALM / HPQC style exports) into Azure DevOps Test Plans import workbooks.
One source row becomes one test case; pre-conditions and execution steps become separate steps; the expected result goes on the last step.
Source files are never modified.

## Use

Needs Python 3 and `openpyxl` (`pip install openpyxl`). The window also needs `tkinter` (included with the standard Windows installer).

| What | How |
|---|---|
| Window | `convert_gui.bat` (or `python scripts/converter_gui.py`) |
| Command line, everything in `source/` | `convert_all.bat` (or `python scripts/build_import_from_source.py --all`) |
| One file | `python scripts/build_import_from_source.py <source.xlsx> <output.xlsx> "<feature title>"` |
| Standalone exe | `build_exe.bat` (needs internet once; builds `share/ADO_Test_Converter.exe`) |

Folders next to the scripts: `source/` (your documents), `imports/` (results), `reports/` (one CSV per run). All three are git-ignored.

## Configuration

Copy `scripts/local_config.example.json` to `scripts/local_config.json` and set `area_path` (the ADO Area Path written on every test case).
`local_config.json` is git-ignored. Optionally put a Microsoft sensitivity label file at `scripts/LabelInfo.xml` (also git-ignored)
to stamp it on the generated workbooks; otherwise the label is copied from the first labelled workbook in `imports/` or from the source.

## How documents are read

Test sheets are found by their header row (first 25 rows), not their names; columns are matched by meaning (ID, description,
pre-condition, execution, expected result, plus optional type, author, requirement, automated, notes). See the docstring at the top of
`scripts/build_import_from_source.py` for the full rules, and the notes column of each report for anything unusual in a document.

## Do not commit

Source documents, generated import workbooks, reports, attachments, the briefing, `local_config.json`, `LabelInfo.xml`, `gui_settings.json`, `_build/`, `share/`.
The `.gitignore` is a whitelist (`*` ignores everything; only the files listed in it are tracked).
