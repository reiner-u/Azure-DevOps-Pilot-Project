# Changelog

Newest first. The version is `TOOL_VERSION` in `scripts/build_import_from_source.py` and shows in the window's title bar.
Release zips are shared through a work channel, not GitHub.

## Unreleased
- The ADO Area Path can be set per run: new "ADO Area Path" box in the window (remembered between runs) and `--area` on the command line. It overrides `local_config.json` and is tidied (forward slashes, doubled or edge backslashes). The report has a new `area_path` column showing what each file was built with.

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
