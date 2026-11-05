# Changelog

Newest first. The version is `TOOL_VERSION` in `scripts/build_import_from_source.py` and shows in the window's title bar.
Release zips are shared through a work channel, not GitHub.

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
