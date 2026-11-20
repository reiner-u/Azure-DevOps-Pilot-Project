# Test document converter

Converts Excel test-case documents (ALM / HPQC style exports) into Azure DevOps Test Plans import workbooks.
One source row becomes one test case; pre-conditions and execution steps become separate steps; the expected result goes on the last step.
Source files are never modified.

## Use

Needs Python 3 and `openpyxl` (`pip install openpyxl`). The window also needs `tkinter` (included with the standard Windows installer).

| What | How |
|---|---|
| Window | `convert_gui.bat` (or `python scripts/converter_gui.py`) |
| Command line, everything in `To Convert/` | `convert_all.bat` (or `python scripts/build_import_from_source.py --all`) |
| One file | `python scripts/build_import_from_source.py <source.xlsx> <output.xlsx> "<feature title>"` |
| Tests | `run_tests.bat` |
| Standalone exe | `build_exe.bat` (needs internet once; builds `ADO_Test_Converter.exe` in the project folder and a zip in `releases/`) |

Folders next to the scripts (and next to the exe): `To Convert/` (your documents), `Converted to ADO/` (results), `reports/` (one CSV per run). All three are git-ignored.

## Configuration

Copy `scripts/local_config.example.json` to `scripts/local_config.json` and set `area_root` (the fixed first part of the ADO Area Path, shown as a locked label in the window) and `area_rest` (the default for the editable box after it). The Area Path written on every test case is `area_root\\<box>`; it can also be set per run with `--area`. A box left blank means the root only.
`local_config.json` is git-ignored. Optionally put a Microsoft sensitivity label file at `scripts/LabelInfo.xml` (also git-ignored)
to stamp it on the generated workbooks; otherwise the label is copied from the first labelled workbook in `Converted to ADO/` or from the source.

## How documents are read

Test sheets are found by their header row (first 25 rows), not their names; columns are matched by meaning (ID, description,
pre-condition, execution, expected result, plus optional type, author, requirement, automated, notes). The full rules are in the
docstring at the top of `scripts/converter/cli.py` (also what `--help` prints), and the notes column of each report lists anything
unusual in a document. The tool never guesses silently: whatever it could not decide becomes a review note.

## Where things are

The code is split into small modules. `scripts/build_import_from_source.py` and `scripts/converter_gui.py` only start things.

| Folder | What is in it |
|---|---|
| `scripts/converter/` | The engine, one job per file: `headers` (which column is which), `steps` (splitting a cell into steps), `cases` (one row -> one `Case`), `planning` (which sheets, which import sheets), `checks` (review notes), `writer` (the import workbook), `label`, `images`, `convert` (one document), `batch` (many documents and the report), `cli`. `converter/__init__.py` has the map in order of flow. Nothing in it uses tkinter. |
| `scripts/converter_ui/` | The window: folder bar, file list, results table, details box, the runner thread, a hidden self-test. |
| `tests/` | The tests and `regression_check.py`. Only made-up documents; no real content. |

## Changing the converter

| I want to... | Change this |
|---|---|
| Accept a new wording of a column header | `HEADER_PATTERNS` in `scripts/converter/headers.py` (one line per field, with examples). Typos are already tolerated (`FUZZY_WORDS`, `FUZZY_CUTOFF`). |
| Add a review note ("check X before importing") | Write a small function in `scripts/converter/checks.py` and add it to `CHECKS` where its note should appear. |
| Change how cells become steps | `scripts/converter/steps.py`. |
| Change the columns or look of the import sheet, or the Read Me text | `scripts/converter/writer.py`. |
| Change the default folder names or the version | `scripts/converter/settings.py` (bump `TOOL_VERSION` for every release and add a line to `CHANGELOG.md`). |
| Change the Area Path or State | `scripts/local_config.json` (not in the repository). |

After any change: run `run_tests.bat`, then run the regression check below on your own documents.

## Tests

`run_tests.bat` (or `python -m unittest discover -s tests`) runs about a hundred checks in a few seconds: text and step splitting, header
matching, whole documents converted from made-up workbooks (including pictures, EN/FR layouts and the sensitivity label),
batch versions and the report, and the window's texts. If tkinter and a screen are available it also runs the real window hidden.
`build_exe.bat` runs them first and stops if one fails.

The tests cannot know your real documents. To check that a change did not alter what the converter produces for them:

    python tests/regression_check.py snapshot "To Convert" snapshots/before     (before changing anything)
    python tests/regression_check.py compare  "To Convert" snapshots/before     (after the change)

It lists every difference (cell, row height, picture, review note, case count); "differences: 0" means nothing changed. A deliberate
fix will show differences, but each one should be something you meant. Keep `snapshots/` out of git (the whitelist already does).

## Do not commit

Source documents, generated import workbooks, reports, attachments, the briefing, `local_config.json`, `LabelInfo.xml`, `gui_settings.json`, `snapshots/`, `_build/`, `releases/`, the exe, `_archive/`.
The `.gitignore` is a whitelist (`*` ignores everything; only the files listed in it are tracked).
