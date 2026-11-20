# Changelog

Newest first. The version is `TOOL_VERSION` in `scripts/converter/settings.py` and shows in the window's title bar.
Release zips are shared through a work channel, not GitHub.

## 2026.11.20
- Restructured for readability and modularity. No change to what the converter produces: all 22 older documents, the 7 current working copies and several deliberately broken files give identical import workbooks (every cell, row height, picture and sensitivity label), identical review notes and identical reports before and after.
- The single 1,000-line converter script is now a package, `scripts/converter/`, with one job per file (headers, steps, cases, planning, checks, writer, label, images, convert, batch, cli). The window is `scripts/converter_ui/`. `build_import_from_source.py` and `converter_gui.py` stay as the entry points, so the batch files and commands are unchanged.
- A test case is now a `Case` record with named fields instead of a dictionary with keys added along the way, a report line is a `ReportRow`, and a header row is a `Header`.
- Column header wordings are a table (`HEADER_PATTERNS`) with examples; review notes are a list of small checks (`CHECKS`), so adding either is a one-line change.
- The Area Path is passed to the conversion instead of being kept in a global that the window changed.
- Tests: about a hundred checks on made-up documents (`run_tests.bat`), a regression tool for comparing output on your own documents (`tests/regression_check.py`), and `build_exe.bat` runs the tests before building.
- Only wording change: the "Area Path is still the placeholder" note now names the right config keys (`area_root` and `area_rest`).

## 2026.11.19
- Folders renamed for clarity: `source` is now `To Convert` and `imports` is now `Converted to ADO` (the `reports` folder is unchanged). The window labels say the same. Settings remembered from an older version still work; a remembered folder that no longer exists falls back to the new default.
- The exe is now built straight into the project folder instead of a `share` subfolder, so the latest build is in the main directory. Release zips go in `releases/`, and the end-user guide is `ADO_Test_Converter_README.txt` next to the exe.

## 2026.11.05.1
- Step numbers glued to the text (`1.User clicks...`, `2)Select...`) are now read as numbering. Before, the number stayed in the step text, and a glued number in the middle of a cell left two steps merged into one. Only a list that runs 1, 2, 3... from the start of the cell counts, so `1.5 mm`, `1.1 Check` and version numbers are left alone.

## 2026.11.05
- The ADO Area Path is set per run. The window has an "ADO Area Path" row: a fixed, locked root followed by a box for the rest (remembered between runs; blank means the root only). `--area` does the same on the command line.
- The root and the box's default come from `scripts/local_config.json` (`area_root`, `area_rest`; an older `area_path` still works). The root is kept in that git-ignored file on purpose, not in the code.
- The report has an `area_path` column showing which path each file was built with.

## 2026.10.27.1
- Misspelled column headers are now read as what they obviously mean ("Pre-conditon", "Excution"). Before this, a document with a misspelled Execution header was skipped as "no test sheet recognised", and a misspelled Pre-condition header was copied into the Description instead of becoming steps. Each corrected header is listed in the report notes so it can be checked.

## 2026.10.27
- The ADO Area Path now comes from `scripts/local_config.json` (not committed; copy `local_config.example.json`). Without it the placeholder is used and every report says so.
- Clearer message when a document has no recognisable test sheet: it lists the sheets looked at and tells people what to send to whoever maintains the tool.
- `build_exe.bat` bundles the local config and sensitivity label only if they exist, and writes a versioned zip.

## 2026.10.26
- First shareable build: window (`converter_gui.py`) packaged as a single exe.
- Test sheets and columns are found from the header row instead of sheet names, so other OSAP modules convert too.
- Multi-sheet documents, bilingual one-row documents (EN Import and FR Import sheets), long titles shortened with the full text kept in the Description, pictures carried over as attachments.

## 2026.10.21
- First converter for the Financial Literacy documents.
