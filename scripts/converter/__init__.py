"""The converter engine: Excel test documents (ALM / HPQC style) in, Azure DevOps Test Plans import workbooks out.

How the pieces fit together, in the order a document flows through them:

    settings    version, default folder names, local_config.json (Area Path root, State)
    area        the ADO Area Path written on every test case
    text        small text helpers (whitespace, titles, file-name slugs)
    steps       splitting a Pre-condition / Execution cell into numbered steps
    headers     which column of a sheet is which (header patterns, typo tolerance)
    images      pictures embedded in a document (read straight from the xlsx zip)
    variants    the "Variant" record: one import sheet to build (EN Import, FR Import, ...)
    cases       the "Case" record and CaseReader: one source row -> one Case
    planning    which sheets are test sheets and which variants to build from them
    checks      the review notes ("blank expected result", "duplicate IDs", ...)
    writer      building the import workbook (Read Me sheet, one sheet per variant)
    label       the Microsoft sensitivity label and saving the finished workbook
    convert     one document, start to finish (calls everything above)
    batch       many documents: skip/version logic, report rows, the CSV report
    cli         the command line (scripts/build_import_from_source.py just calls it)

The window (scripts/converter_ui/) and the tests (tests/) use these modules directly. Nothing in this package imports tkinter.
"""
