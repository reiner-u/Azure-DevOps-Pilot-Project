"""ALM defect exports in, Azure DevOps Bug work items out (CSV for Boards > Work Items > Import).

A sibling of the `converter` package, not part of it: that one writes the two-row Test Plans layout for test cases, this one
writes a flat CSV of work items. What they share, they import from `converter` rather than copy (settings, area, text,
images, label).

How the pieces fit together, in the order an export flows through them:

    headers     which column of the export is which (ALM wordings -> field names)
    defect      the "Defect" record and DefectReader: one export row -> one Defect
    mapping     ALM values -> ADO values (state, severity, priority, people) and the Bug CSV columns
    checks      the review notes ("severity 'Urgent' has no ADO value", "11,400 rows: 12 files")
    writer      the CSV files themselves, at most MAX_ROWS_PER_IMPORT rows each
    convert     one export file, start to finish
    batch       many files: report rows and the CSV report
    cli         the command line (scripts/build_bugs_from_defects.py just calls it)

UNFINISHED. The shape is here and it runs, but three things are guesses until the real files are to hand:
  * the ALM column wordings in headers.py (from typical ALM/HPQC exports, not from our export);
  * the Bug field names in mapping.py (they come from the process template: export one Bug from ADO to CSV and read them);
  * every value map in mapping.py is empty, so states, severities and priorities come out blank and get a review note.
Nothing here imports tkinter, so the tests run without a window.
"""
