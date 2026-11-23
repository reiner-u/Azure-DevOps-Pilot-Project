"""Working out which column of an ALM defect export is which.

Same idea as converter/headers.py: a table of patterns, first match wins, matched from the start of the lower-cased header.
Deliberately a separate table, because ALM defect columns and ALM test-case columns have almost nothing in common.

!! THE PATTERNS ARE GUESSES !! They come from how ALM/HPQC exports are usually headed, not from our own export. Open the
real export, compare its header row with DEFECT_PATTERNS, and fix the wordings before trusting any output. The review
report lists every column that was not recognised, which is the quickest way to see what is missing.
"""
import re
from dataclasses import dataclass, field
from typing import Optional

from converter.headers import clean_header

# (field, pattern, example headers). Order matters: "detected by" must come before "detect" patterns for dates, and
# "closing date" before "date".
DEFECT_PATTERNS = (
    ("id", r"defect id|bug id|defect no|issue id|^id$",
     "Defect ID, Bug ID, ID"),
    ("title", r"summary|^title|headline",
     "Summary, Defect Summary, Title"),
    ("steps", r"(steps to )?reproduc|repro steps|how to repeat",
     "Reproduction Steps, Steps to Reproduce"),
    ("description", r"description|details$",
     "Description"),
    ("status", r"status|^state",
     "Status, Defect Status, State"),
    ("severity", r"severity",
     "Severity"),
    ("priority", r"priority",
     "Priority"),
    ("assigned_to", r"assigned[- ]?to|responsible|owner",
     "Assigned To, Responsible"),
    ("detected_by", r"detected[- ]?by|reported[- ]?by|created[- ]?by|submitter",
     "Detected By, Reported By"),
    ("detected_date", r"detect(ed|ion)[- ]?(on[- ]?)?date|creation (time|date)|date (detected|reported)",
     "Detection Date, Detected on Date, Creation Time"),
    ("closing_date", r"clos(ing|ed)[- ]?(on[- ]?)?date",
     "Closing Date, Closed on Date"),
    ("version", r"detected in (version|release)|version|release",
     "Detected in Version, Version"),
    ("environment", r"environment|detected in env|test ?env",
     "Environment"),
    ("subject", r"subject|module|component|functional area",
     "Subject, Module, Component"),
    ("comments", r"(r&d |dev(eloper)? )?comments?|notes$",
     "Comments, R&D Comments"),
)
_COMPILED = tuple((name, re.compile(pattern)) for name, pattern, _examples in DEFECT_PATTERNS)

REQUIRED_FIELDS = ("id", "title")        # ADO needs a Title; the ALM ID is how a row is traced back to ALM
FIELD_NAMES = dict(id="defect ID", title="summary", steps="reproduction steps", description="description",
                   status="status", severity="severity", priority="priority", assigned_to="assigned to",
                   detected_by="detected by", detected_date="detection date", closing_date="closing date",
                   version="version", environment="environment", subject="subject", comments="comments")

HEADER_SEARCH_ROWS = 25                  # an export may have a title block above the header row


def classify(header):
    """Header text -> a field name, or None. No typo tolerance yet: add it here if the export turns out to need it."""
    text = clean_header(header).lower()
    if not text:
        return None
    for name, pattern in _COMPILED:
        if pattern.match(text):
            return name
    return None


@dataclass
class Header:
    """The header row found on a sheet of the export."""
    row: int = 0                                  # 1-based row number (0 = none found)
    cols: dict = field(default_factory=dict)      # field name -> 0-based column index
    headers: list = field(default_factory=list)   # cleaned text of every cell in the header row
    score: int = 0                                # how many known columns the row has
    missing: list = field(default_factory=lambda: list(REQUIRED_FIELDS))
    ok: bool = False

    def unknown_columns(self):
        """Headers with text that no pattern matched: the list to work through when fixing DEFECT_PATTERNS."""
        used = {index for index in self.cols.values()}
        return [text for index, text in enumerate(self.headers) if text and index not in used]


def find_header(ws, scan=HEADER_SEARCH_ROWS):
    """The best header-row candidate in the first rows of a sheet, as a Header."""
    best = None
    for row_number, row in enumerate(ws.iter_rows(min_row=1, max_row=scan, values_only=True), start=1):
        cols = {}
        for index, value in enumerate(row):
            name = classify(value)
            if name is not None:
                cols.setdefault(name, index)
        if best is None or len(cols) > best.score:
            best = Header(row=row_number, cols=cols, headers=[clean_header(v) for v in row], score=len(cols))
    if best is None:
        return Header()
    best.missing = [name for name in REQUIRED_FIELDS if name not in best.cols]
    best.ok = not best.missing
    return best
