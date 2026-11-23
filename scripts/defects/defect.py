"""Reading defects from an ALM export sheet.

DefectReader turns each row of the export into a Defect. Everything that later reaches the CSV or a review note is a field
of Defect, so this file answers "where does this value come from?".
"""
from dataclasses import dataclass, field
from typing import Optional

from converter.text import clean, norm, short_id, shorten_title, tidy_lines

from .headers import FIELD_NAMES

# ADO's System.Title holds 255 characters. The test-case converter uses 128 because the Test Plans grid is narrower;
# confirm this one against a Bug in our project, then keep the full text in the Description as that converter does.
MAX_TITLE_LENGTH = 255


@dataclass
class Defect:
    """One defect: one row of the export."""
    row: int                                          # row number in the export sheet
    defect_id: Optional[str] = None
    title: Optional[str] = None                       # the summary, shortened to ADO's limit
    title_full: Optional[str] = None                  # the original summary when it had to be shortened
    description: Optional[str] = None
    steps: Optional[str] = None                       # reproduction steps, as written
    status: Optional[str] = None                      # the ALM status, before mapping
    severity: Optional[str] = None
    priority: Optional[str] = None
    assigned_to: Optional[str] = None                 # the ALM user name, before mapping
    detected_by: Optional[str] = None
    detected_date: Optional[str] = None
    closing_date: Optional[str] = None
    version: Optional[str] = None
    environment: Optional[str] = None
    subject: Optional[str] = None
    comments: Optional[str] = None
    extras: list = field(default_factory=list)        # [(header, text)] of columns no pattern matched
    fields_present: set = field(default_factory=set)  # which known columns the export has

    @property
    def label(self):
        """How review notes name this defect: its ALM ID, or its row number when it has none."""
        return short_id(self.defect_id) if self.defect_id else f"row {self.row}"


TEXT_FIELDS = ("id", "title", "description", "steps", "status", "severity", "priority", "assigned_to", "detected_by",
               "detected_date", "closing_date", "version", "environment", "subject", "comments")
MULTILINE_FIELDS = ("description", "steps", "comments")      # keep line breaks, drop blank lines


class DefectReader:
    """Reads the defects of one sheet. Call read(); notes about the sheet's columns are added to `notes`."""

    def __init__(self, ws, header, notes):
        self.ws, self.header, self.notes = ws, header, notes
        self.cols, self.headers = header.cols, header.headers
        self.extra_cols = [index for index, text in enumerate(self.headers)
                           if text and index not in set(self.cols.values())]
        self.skipped_rows = []

    def read(self):
        self._note_missing_columns()
        defects = []
        for row_number, row in enumerate(self.ws.iter_rows(min_row=self.header.row + 1, values_only=True),
                                         start=self.header.row + 1):
            if not clean(self._cell(row, "id")) and not clean(self._cell(row, "title")):
                if any(clean(value) for value in row):
                    self.skipped_rows.append(row_number)
                continue
            defects.append(self._read_defect(row_number, row))
        self._note_summary()
        return defects

    def _cell(self, row, name):
        col = self.cols.get(name)
        return row[col] if col is not None and col < len(row) else None

    def _read_defect(self, row_number, row):
        text = {name: clean(self._cell(row, name)) for name in TEXT_FIELDS}
        for name in MULTILINE_FIELDS:
            if text[name]:
                text[name] = tidy_lines(text[name])
        defect = Defect(row=row_number)
        defect.defect_id = norm(text["id"]) if text["id"] else None
        title = norm(text["title"]) if text["title"] else None
        if title and len(title) > MAX_TITLE_LENGTH:
            defect.title_full, title = title, shorten_title(title, MAX_TITLE_LENGTH)
        defect.title = title
        for name in TEXT_FIELDS:
            if name not in ("id", "title"):
                setattr(defect, name, text[name])
        defect.fields_present = set(self.cols)
        self._read_extra_columns(defect, row)
        return defect

    def _read_extra_columns(self, defect, row):
        """Columns no pattern matched are kept so nothing from ALM is silently dropped (they go into System Info)."""
        for col in self.extra_cols:
            value = clean(row[col]) if col < len(row) else None
            if value:
                defect.extras.append((self.headers[col], tidy_lines(value)))

    def _note_missing_columns(self):
        for name in ("steps", "status", "severity", "priority", "assigned_to"):
            if self.cols.get(name) is None:
                self.notes.append(f"no {FIELD_NAMES[name]} column in the export, so that field is blank on every Bug "
                                  f"(check the header wordings in defects/headers.py)")
        unknown = self.header.unknown_columns()
        if unknown:
            self.notes.append(f"column(s) no pattern matched: {unknown} (they go into System Info; add a pattern in "
                              f"defects/headers.py for any that deserve a field of their own)")

    def _note_summary(self):
        if self.skipped_rows:
            first = self.skipped_rows[:12]
            more = f", ... +{len(self.skipped_rows) - 12} more" if len(self.skipped_rows) > 12 else ""
            self.notes.append(f"row(s) {first}{more} have text but no defect ID or summary; skipped")


def read_defects(ws, header, notes):
    return DefectReader(ws, header, notes).read()
