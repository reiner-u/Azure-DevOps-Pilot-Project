"""Reading test cases from a source sheet.

CaseReader turns each row of a sheet into a Case. Everything that is later written to the import workbook or mentioned in a
review note is a field of Case, so this file is the place to look when asking "where does this value come from?".
"""
from dataclasses import dataclass, field
from typing import Optional

from openpyxl.utils import get_column_letter

from .headers import IGNORED_COLUMN
from .steps import NOT_NUMBERED, split_execution, split_precondition
from .text import (MAX_TITLE_LENGTH, clean, list_for_note, norm, short_id, shorten_title, tidy_lines)


@dataclass
class Case:
    """One test case: one row of a source sheet."""
    row: int                                          # row number in the source sheet
    scenario_id: Optional[str] = None
    title: Optional[str] = None                       # the description, shortened to ADO's 128-character limit
    title_full: Optional[str] = None                  # the original description when it had to be shortened
    title_was_joined: bool = False                    # the description had line breaks that were joined with spaces
    requirement_id: Optional[str] = None              # business requirement ID
    scenario_type: Optional[str] = None
    author: Optional[str] = None
    subject: Optional[str] = None
    automated: Optional[str] = None
    automated_label: str = "Automated"                # "Automatable" when the source column is called that
    automation_notes: Optional[str] = None
    section: Optional[str] = None                     # the heading row above this case, if any
    expected: Optional[str] = None                    # expected result text
    fields_present: set = field(default_factory=set)  # which optional columns the source sheet has ("br", "type", ...)
    extras: list = field(default_factory=list)        # [(header, text)] of columns the converter does not know
    steps: list = field(default_factory=list)         # step actions: pre-condition steps, then execution steps
    n_execution_steps: int = 0
    precondition_fell_back: bool = False              # pre-condition was not a clean numbered list
    execution_numbering: str = NOT_NUMBERED           # NUMBERED, RENUMBERED or NOT_NUMBERED (see steps.py)
    execution_multiline: bool = False
    variant_note: Optional[str] = None                # extra Description line, e.g. the expected result language
    # pictures found in the source row: [(bytes, ext)] in the expected-result cell, [(column name, bytes, ext)] elsewhere
    images: list = field(default_factory=list)
    other_images: list = field(default_factory=list)
    # where the pictures were saved (relative paths), filled in when the workbook is built
    image_files: list = field(default_factory=list)
    other_files: list = field(default_factory=list)       # [(column name, path)]

    @property
    def label(self):
        """How review notes name this case: the end of its scenario ID, or its row number when it has none."""
        return short_id(self.scenario_id) if self.scenario_id else f"row {self.row}"


def pictures_by_cell(images):
    """{(row, col): [(bytes, ext)]} with 1-based rows. Identical pictures stacked in one cell count once."""
    by_cell = {}
    for row0, col0, data, ext in images:
        in_cell = by_cell.setdefault((row0 + 1, col0), [])
        if not any(data == picture[0] for picture in in_cell):
            in_cell.append((data, ext))
    return by_cell


class CaseReader:
    """Reads the cases of one Variant. Call read(); review notes about the sheet's columns are added to `notes`."""

    def __init__(self, variant, images, notes):
        header = variant.header
        self.variant, self.notes, self.tag = variant, notes, variant.tag
        self.cols, self.headers = header.cols, header.headers
        self.expected_col = self.cols[variant.exp_key]
        self.skip_cols = variant.skip_cols
        used = {i for i in self.cols.values() if i is not None}
        unused = [i for i in range(len(self.headers)) if i not in used]
        self.extra_cols = [i for i in unused if not IGNORED_COLUMN.match(self.headers[i].lower())]
        self.ignored_cols = [i for i in unused if IGNORED_COLUMN.match(self.headers[i].lower())]
        self.pictures = pictures_by_cell(images)
        self.column_names = {self.cols.get("pre"): "Pre-condition", self.cols.get("exe"): "Execution",
                             self.expected_col: "Expected Result"}
        self.automated_label = "Automated"
        if "auto" in self.cols:
            self.automated_label = ("Automatable" if self.headers[self.cols["auto"]].lower().startswith("automatable")
                                    else "Automated")
        # collected while reading, summarised in review notes at the end
        self.skipped_rows, self.extra_headers, self.blank_extra_headers, self.ignored_headers = [], set(), set(), set()
        self.pictures_placed = 0

    # ----- reading -----
    def read(self):
        if self.variant.first:
            self._note_missing_columns()
        cases, section = [], None
        first_data_row = self.variant.header.row + 1
        for row_number, row in enumerate(self.variant.ws.iter_rows(min_row=first_data_row, values_only=True),
                                         start=first_data_row):
            if not clean(self._cell(row, "title")) and not clean(self._cell(row, "id")):
                section = self._handle_row_without_case(row_number, row, section)
                continue
            cases.append(self._read_case(row_number, row, section))
        if self.variant.first:
            self._note_summary()
        return cases

    def _cell(self, row, field_name):
        """The value of a field in a row (None when the sheet has no such column or the row is short)."""
        col = self.cols.get(field_name)
        return row[col] if col is not None and col < len(row) else None

    def _handle_row_without_case(self, row_number, row, section):
        """A row with neither an ID nor a description: a section heading (one cell in column A), a stray row, or empty."""
        filled = [i for i, value in enumerate(row) if clean(value)]
        if len(filled) == 1 and filled[0] == 0:
            return norm(row[0])                      # a heading row such as "Page fields"
        if filled:
            self.skipped_rows.append(row_number)
        return section

    def _read_case(self, row_number, row, section):
        case = Case(row=row_number, section=section, automated_label=self.automated_label)
        self._read_text_fields(case, row)
        self._read_expected_result(case, row)
        self._read_pictures(case, row_number)
        self._read_extra_columns(case, row)
        pre = split_precondition(self._cell(row, "pre"))
        execution = split_execution(self._cell(row, "exe"))
        case.precondition_fell_back = pre.fell_back
        case.execution_numbering, case.execution_multiline = execution.numbering, execution.multiline
        case.steps = pre.steps + execution.steps
        case.n_execution_steps = len(execution.steps)
        case.variant_note = self.variant.variant_note
        return case

    def _read_text_fields(self, case, row):
        text = {name: clean(self._cell(row, name))
                for name in ("type", "subject", "author", "id", "br", "title", "auto", "notes")}
        for name in ("type", "author", "br", "auto"):     # these may be multi-line: keep line breaks, drop blank lines
            if text[name]:
                text[name] = tidy_lines(text[name])
        case.scenario_type, case.subject, case.author = text["type"], text["subject"], text["author"]
        case.requirement_id, case.automated, case.automation_notes = text["br"], text["auto"], text["notes"]
        case.scenario_id = norm(text["id"]) if text["id"] else text["id"]
        title = text["title"]
        case.title_was_joined = bool(title and "\n" in title)
        if case.title_was_joined:
            title = norm(title)
        if title and len(title) > MAX_TITLE_LENGTH:
            case.title_full, title = title, shorten_title(title)
        case.title = title
        case.fields_present = {name for name, col in self.cols.items()
                               if col is not None and name not in ("exp", "exp_fr")}

    def _read_expected_result(self, case, row):
        col = self.expected_col
        case.expected = clean(row[col]) if col < len(row) else None

    def _read_pictures(self, case, row_number):
        case.images = self.pictures.get((row_number, self.expected_col), [])
        case.other_images = [(self._column_name(col), data, ext)
                             for (row, col), in_cell in sorted(self.pictures.items())
                             if row == row_number and col != self.expected_col and col not in self.skip_cols
                             for data, ext in in_cell]
        self.pictures_placed += len(case.images) + len(case.other_images)

    def _column_name(self, col):
        if self.column_names.get(col):
            return self.column_names[col]
        return self.headers[col] if col < len(self.headers) and self.headers[col] else f"column {col + 1}"

    def _read_extra_columns(self, case, row):
        """Columns the converter does not know are copied into the Description under their own header."""
        for col in self.extra_cols:
            value = clean(row[col]) if col < len(row) else None
            if value:
                label = self.headers[col] or f"column {get_column_letter(col + 1)}"
                (self.extra_headers if self.headers[col] else self.blank_extra_headers).add(label)
                case.extras.append((label, "\n".join(norm(line) for line in value.splitlines() if line.strip())))
        for col in self.ignored_cols:
            if col < len(row) and clean(row[col]):
                self.ignored_headers.add(self.headers[col])

    # ----- review notes about the sheet as a whole -----
    def _note_missing_columns(self):
        for name, label in (("auto", "Automated"), ("br", "business requirement ID"), ("author", "author"), ("type", "type")):
            if self.cols.get(name) is None:
                self.notes.append(f"{self.tag}: no {label} column in the source, so the Description has no such line")
        if self.cols.get("pre") is None:
            self.notes.append(f"{self.tag}: no Pre-condition column in the source; the steps come from Execution only")

    def _note_summary(self):
        tag = self.tag
        if self.skipped_rows:
            self.notes.append(f"{tag}: row(s) {list_for_note(self.skipped_rows)} have text but no case ID or description and "
                              f"are not a section heading; skipped (a case continued on a second row?)")
        total_pictures = sum(len(in_cell) for (_row, col), in_cell in self.pictures.items() if col not in self.skip_cols)
        if total_pictures > self.pictures_placed:
            self.notes.append(f"{tag}: {total_pictures - self.pictures_placed} picture(s) sit on rows with no test case and "
                              f"were NOT carried over (check the source by hand)")
        if self.extra_headers or self.blank_extra_headers:
            self.notes.append(f"{tag}: extra column(s) copied into the Description: "
                              f"{sorted(self.extra_headers | self.blank_extra_headers)}")
        if self.ignored_headers:
            self.notes.append(f"{tag}: column(s) not carried over: {sorted(self.ignored_headers)}")


def read_cases(variant, images, notes):
    """The Cases of one Variant, read from its sheet. `images` are that sheet's pictures from extract_images."""
    return CaseReader(variant, images, notes).read()
