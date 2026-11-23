"""Converting one ALM defect export into Bug CSVs, start to finish.

The steps, in order (each lives in its own module):
  1. load the workbook and find the sheet that looks like a defect export   (headers)
  2. read every defect                                                      (defect)
  3. collect review notes                                                   (checks)
  4. write the CSV files, at most 1,000 rows each                           (writer, mapping)
A dry run stops after step 3 and writes nothing.
"""
import os
from dataclasses import dataclass, field
from typing import Optional

import openpyxl

from converter import area as area_path

from .checks import review_notes
from .defect import read_defects
from .headers import FIELD_NAMES, find_header


class NotADefectExport(Exception):
    """No sheet in the workbook looks like a defect export."""


@dataclass
class DefectConversion:
    """What a conversion produced (or, for a dry run, would produce)."""
    defects: list = field(default_factory=list)
    notes: list = field(default_factory=list)
    files: list = field(default_factory=list)        # the CSV paths written, in import order
    sheet: Optional[str] = None                      # the export sheet that was read
    column_map: str = ""                             # which export column was used for what


def convert(src, out_dir, dry_run=False, area=None, stem=None):
    """Convert one export. Returns a DefectConversion. Raises NotADefectExport when no sheet can be read."""
    area = area or area_path.DEFAULT
    workbook = openpyxl.load_workbook(src, data_only=True, read_only=True)
    try:
        sheet, header = _find_export_sheet(workbook)
        notes = []
        defects = read_defects(sheet, header, notes)
        notes = [f"{sheet.title}: {note}" for note in notes]
        notes += [f"{sheet.title}: {note}" for note in review_notes(defects, header)]
        result = DefectConversion(defects=defects, notes=notes, sheet=sheet.title, column_map=_column_map(header))
        if dry_run:
            return result
        from .writer import write_csvs          # imported here so a dry run needs none of the mapping tables
        stem = stem or os.path.splitext(os.path.basename(src))[0]
        result.files = write_csvs(defects, out_dir, stem, area)
        return result
    finally:
        workbook.close()


def _find_export_sheet(workbook):
    """The sheet with the most recognised columns, as long as it has the required ones."""
    best = None
    for ws in workbook.worksheets:
        header = find_header(ws)
        if best is None or header.score > best[1].score:
            best = (ws, header)
    if best is None or not best[1].ok:
        missing = ", ".join(FIELD_NAMES[name] for name in (best[1].missing if best else ("id", "title")))
        raise NotADefectExport(f"no defect export sheet recognised (missing: {missing}). Compare the export's header row "
                               f"with DEFECT_PATTERNS in defects/headers.py")
    return best


def _column_map(header):
    """Which export column was used for what, for the report."""
    return ", ".join(f"{name}={header.headers[col]!r}" for name, col in header.cols.items()
                     if col < len(header.headers))
