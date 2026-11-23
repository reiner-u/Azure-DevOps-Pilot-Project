"""Converting many export files: one report row per file, and the CSV report.

convert_file never raises: whatever happens to a file, it returns a ReportRow saying what happened, so one bad export
cannot stop a batch. Mirrors converter/batch.py, and reuses its source_files().
"""
import csv
import datetime
import os
from dataclasses import asdict, dataclass, fields

from converter import area as area_path
from converter.batch import source_files

from .convert import NotADefectExport, convert

DEFECTS_DIRNAME = "ALM Defects"              # where the exports are put (originals are never changed)
BUGS_DIRNAME = "Bug CSVs for ADO"            # where the CSVs are written
REPORTS_DIRNAME = "reports"


@dataclass
class ReportRow:
    """One line of the report. The fields are the CSV columns, in this order."""
    source: str
    csv_files: str = ""                      # the files written, separated by "; "
    area_path: str = ""
    status: str = ""                         # "built", "analysed only (dry run)", "skipped: ...", "FAILED: ..."
    defects: int = 0
    import_rounds: int = 0                   # how many times someone has to import and save in ADO
    review: str = ""
    sheet_used: str = ""
    column_map: str = ""
    notes: str = ""                          # review notes joined with " | "

    @property
    def built(self):
        return self.status == "built"

    @property
    def failed(self):
        return self.status.startswith("FAILED")

    @property
    def needs_review(self):
        return self.review == "yes"

    def note_list(self):
        return self.notes.split(" | ") if self.notes else []


REPORT_COLUMNS = [f.name for f in fields(ReportRow)]


def convert_file(name, defects_dir, bugs_dir, dry_run=False, area=None):
    """Convert one export file. Never raises."""
    area = area or area_path.DEFAULT
    row = ReportRow(source=name, area_path=area)
    if not name.lower().endswith((".xlsx", ".xlsm")):
        row.status = "skipped: not an .xlsx file (save an older .xls export as .xlsx first)"
        return row
    try:
        result = convert(os.path.join(defects_dir, name), bugs_dir, dry_run=dry_run, area=area)
    except NotADefectExport as e:
        row.status, row.review = f"skipped: {e}", "yes"
        return row
    except PermissionError:
        row.status = "skipped: the file is open in Excel (close it and run again)"
        return row
    except Exception as e:                   # one broken export must not stop the batch
        row.status, row.review = f"FAILED: {type(e).__name__}: {e}", "yes"
        return row
    row.status = "analysed only (dry run)" if dry_run else "built"
    row.defects = len(result.defects)
    row.import_rounds = len(result.files)
    row.csv_files = "; ".join(os.path.basename(path) for path in result.files)
    row.sheet_used, row.column_map = result.sheet or "", result.column_map
    row.notes = " | ".join(result.notes)
    row.review = "yes" if result.notes else "no"
    return row


def run_all(defects_dir, bugs_dir, dry_run=False, only=None, progress=None, area=None):
    """Convert every file in the ALM Defects folder (or just the names in `only`). Returns the ReportRows."""
    names = [name for name in source_files(defects_dir) if only is None or name in only]
    rows = []
    for index, name in enumerate(names, 1):
        row = convert_file(name, defects_dir, bugs_dir, dry_run, area)
        rows.append(row)
        if progress:
            progress(index, len(names), row)
    return rows


def write_report(rows, folder):
    """Write the rows to reports/defect_report_<timestamp>.csv and return its path."""
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, "defect_report_" + datetime.datetime.now().strftime("%Y%m%d_%H%M%S") + ".csv")
    with open(path, "w", newline="", encoding="utf-8-sig") as fh:
        writer = csv.DictWriter(fh, fieldnames=REPORT_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(asdict(row) for row in rows)
    return path
