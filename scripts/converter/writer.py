"""Building the import workbook: a Read Me sheet plus one sheet per Variant, in the layout ADO Test Plans import expects.

Layout of an import sheet: two kinds of rows per test case.
  * a title row: Work Item Type = Test Case, Title, Area Path, State, Description
  * one row per step beneath it: Test Step (number), Step Action, Step Expected
The expected result sits on the last step only. ID and Assigned To stay blank (ADO creates new test cases).
"""
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

HEADERS = ["ID", "Work Item Type", "Title", "Test Step", "Step Action", "Step Expected", "Area Path", "Assigned To", "State",
           "Description"]
WIDTHS = [12, 18, 42, 12, 85, 75, 48, 28, 14, 55]
# Column widths (Title, Description, Step Action, Step Expected) used to guess how tall a row has to be
TITLE_WIDTH, DESCRIPTION_WIDTH, ACTION_WIDTH, EXPECTED_WIDTH = 42, 55, 85, 75


def description(case):
    """The Description of a test case: where it came from, plus anything in the source row that has no column of its own."""
    present = case.fields_present
    lines = [f"Source scenario ID: {case.scenario_id or '(blank in source)'}"]
    if case.title_full:
        lines.append(f"Full source description: {case.title_full}")
    if "br" in present:
        lines.append(f"Business requirement ID: {case.requirement_id or '(blank in source)'}")
    if "type" in present:
        lines.append(f"Test scenario type: {case.scenario_type or '(blank in source)'}")
    if case.subject:
        lines.append(f"Subject: {case.subject}")
    if "author" in present:
        lines.append(f"Original author: {case.author or '(blank in source)'}")
    if "auto" in present:
        lines.append(f"{case.automated_label}: {case.automated or '(blank in source)'}")
    if case.automation_notes:
        lines.append(f"Automation notes: {case.automation_notes}")
    if case.section:
        lines.append(f"Section: {case.section}")
    for label, text in case.extras:
        lines.append(f"{label}: {text}")
    if case.variant_note:
        lines.append(case.variant_note)
    if case.image_files:
        many = len(case.image_files) > 1
        what = "a picture here as well as text" if case.expected else "a picture here instead of text"
        lines.append(f"Expected result image{'s' if many else ''}: {', '.join(case.image_files)} (the source has {what}; "
                     f"images cannot be imported, so attach {'them' if many else 'it'} to the last step in ADO)")
    for column, path in case.other_files:
        lines.append(f"Picture in the {column} cell: {path} (images cannot be imported; attach it to the step it belongs to in ADO)")
    return "\n".join(lines)


def estimate_row_height(texts_and_widths):
    """Excel does not auto-fit rows when a file is written, so guess the height from the longest wrapped text."""
    lines = 1
    for text, width in texts_and_widths:
        if not text:
            continue
        wrapped = sum(max(1, -(-len(part) // max(1, int(width * 1.05)))) for part in str(text).split("\n"))
        lines = max(lines, wrapped)
    return min(409, 15 * lines + 4)


def write_sheet(workbook, name, cases, area_path, state):
    """Add one import sheet with all the cases (title row, then step rows)."""
    ws = workbook.create_sheet(name)
    ws.append(HEADERS)
    for index, width in enumerate(WIDTHS, 1):
        ws.column_dimensions[get_column_letter(index)].width = width
    for cell in ws[1]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="1F3864")
        cell.alignment = Alignment(vertical="center", wrap_text=True)
    for case in cases:
        text = description(case)
        ws.append([None, "Test Case", case.title, None, None, None, area_path, None, state, text])
        ws.row_dimensions[ws.max_row].height = estimate_row_height([(case.title, TITLE_WIDTH), (text, DESCRIPTION_WIDTH)])
        last_step = len(case.steps)
        for number, action in enumerate(case.steps, 1):
            expected = case.expected if number == last_step else None
            ws.append([None, None, None, number, action, expected, None, None, None, None])
            ws.row_dimensions[ws.max_row].height = estimate_row_height([(action, ACTION_WIDTH), (expected, EXPECTED_WIDTH)])
    wrap_top = Alignment(wrap_text=True, vertical="top")
    for row in ws.iter_rows(min_row=2):
        for cell in row:
            cell.alignment = wrap_top
    ws.freeze_panes = "A2"


def write_read_me(workbook, feature, source_name, variants, legacy, bilingual, has_images, area_path, state,
                  automation_column=None):
    """The first sheet: what this workbook is and how to import it.
    `automation_column` is the source column the manual/automated split was made on, or None when nothing was split."""
    ws = workbook.active
    ws.title = "Read Me"
    summary = "Each sheet contains " + " / ".join(f"{len(v.cases)} test cases ({v.name})" for v in variants) + "."
    names = [v.name for v in variants]
    sheet_names = " and ".join([", ".join(names[:-1]), names[-1]] if len(names) > 1 else names)
    if legacy:
        purpose = f"Prepared from the EN and FR worksheets in {source_name}."
        import_text = f"Import {sheet_names} separately in Azure DevOps. " + summary
        important = ("Import only the language sheet you want in the selected suite. Importing both creates EN and FR test "
                     "cases. Delete earlier imports of the same file first to avoid duplicates.")
    else:
        sheets = sorted({v.src_sheet for v in variants})
        purpose = f"Prepared from the worksheet(s) {', '.join(repr(s) for s in sheets)} in {source_name}."
        import_text = "Import each sheet separately in Azure DevOps (one sheet per target suite). " + summary
        important = ("Import only the sheet you want in the selected suite. Delete earlier imports of the same file first to "
                     "avoid duplicates.")
    rows = [
        (f"Azure DevOps Test Case Import Workbook: {feature}", None),
        ("Purpose", purpose),
        ("Import sheets", import_text),
        ("Required headers", "ID, Work Item Type, Title, Test Step, Step Action, Step Expected, Area Path, Assigned To, State "
                             "(Description is an extra column; untick it in the mapping screen if ADO rejects it)."),
        ("New test cases", "ID is blank so ADO creates new test cases. Do not enter existing IDs unless you intend to update "
                           "those cases."),
        ("Assigned To", "Blank. Enter a valid ADO identity if your organization requires an assignee."),
        ("Layout", "Two kinds of rows per test case. Title row: Work Item Type, Title, Area Path, State, Description. Step rows "
                   "beneath it: Test Step, Step Action, Step Expected only. Test Step, Step Action and Step Expected must be "
                   "on the same row."),
        ("Test steps", "Source pre-condition items are steps 1..n (one per step). The source Execution text follows: one step "
                       "per number when it is a numbered list, otherwise one step per sentence. The Expected Result sits on "
                       "the last step only. Source wording is unchanged."),
        ("Area Path", area_path),
        ("State", state),
        ("Important", important),
        ("Source mapping", "Title = the source description; Description = scenario ID, business requirement ID, scenario type, "
                           "author, automated flag and automation notes where the source has them, plus the section heading "
                           "and any other source columns (notes, comments...); Step Expected = source Expected Result."),
    ]
    if bilingual:
        rows.append(("English / French", "The source has one set of steps with the expected result in English and in French. The "
                                         "EN sheet(s) carry the English expected result and the FR sheet(s) the French one. The "
                                         "steps are the same in both because the source has no French steps."))
    if automation_column:
        rows.append(("Manual / automated", f"The source marks each case automated or not in its '{automation_column}' column, so "
                                           f"the cases are split into a Manual and an Automated sheet. Cases left blank or "
                                           f"unclear in that column are on the Manual sheet and are listed in the conversion "
                                           f"report. Import the sheet that belongs in the suite you are filling."))
    if has_images:
        rows.append(("Images", "Some source cells contain pictures, not text. Those cases are named in the Description and the "
                               "picture files are saved under attachments/ next to this workbook. Attach them in ADO after "
                               "importing (Expected Result pictures to the last step)."))
    for row in rows:
        ws.append(list(row))
    ws["A1"].font = Font(bold=True, size=14)
    for row_number in range(2, ws.max_row + 1):
        ws.cell(row_number, 1).font = Font(bold=True)
        ws.cell(row_number, 2).alignment = Alignment(wrap_text=True, vertical="top")
        ws.cell(row_number, 1).alignment = Alignment(vertical="top")
    ws.column_dimensions["A"].width = 22
    ws.column_dimensions["B"].width = 120
