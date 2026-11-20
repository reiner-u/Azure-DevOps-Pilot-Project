"""Converting many documents: which files to pick up, version numbers, one report row per file, and the CSV report.

convert_file never raises: whatever happens to a file, it returns a ReportRow saying what happened, so one bad document cannot
stop a batch. The window and the command line both use run_all().
"""
import csv
import datetime
import glob
import os
import re
from dataclasses import asdict, dataclass, fields

from . import area as area_path
from . import settings
from .convert import convert
from .label import first_labelled_workbook
from .planning import NotATestDocument
from .text import slug


@dataclass
class ReportRow:
    """One line of the report (and one row of the window's results table). The fields are the CSV columns, in this order."""
    source: str                    # source file name
    import_file: str = ""          # the import workbook built from it
    area_path: str = ""            # the Area Path it was built with
    status: str = ""               # "built", "analysed only (dry run)", "skipped: ...", "FAILED: ..."
    cases: str = ""                # e.g. "EN Import: 21; FR Import: 21"
    steps_per_case: str = ""       # the different step counts found, e.g. "6/8"
    review: str = ""               # "yes" when there are review notes, "no" when there are none, "" when nothing was built
    sheets_used: str = ""
    column_map: str = ""
    notes: str = ""                # review notes joined with " | "

    @property
    def built(self):
        return self.status == "built"

    @property
    def failed(self):
        return self.status.startswith("FAILED")

    @property
    def skipped(self):
        return self.status.startswith("skipped")

    @property
    def needs_review(self):
        return self.review == "yes"

    def note_list(self):
        return self.notes.split(" | ") if self.notes else []


REPORT_COLUMNS = [f.name for f in fields(ReportRow)]


def source_files(source_dir):
    """Everything in the To Convert folder except Excel lock files (~$...) and hidden files."""
    return [name for name in sorted(os.listdir(source_dir))
            if os.path.isfile(os.path.join(source_dir, name)) and not name.startswith(("~$", "."))]


def import_stem(source_name):
    """The part of an import workbook's name that comes from the source file name."""
    return slug(os.path.splitext(source_name)[0])


def existing_versions(imports_dir, source_name):
    """Version numbers of the import workbooks already built from this source file."""
    pattern = os.path.join(imports_dir, f"{import_stem(source_name)}_AzureDevOps_Import_V*.xlsx")
    return sorted(int(re.search(r"_V(\d+)\.xlsx$", path).group(1)) for path in glob.glob(pattern))


def feature_title(source_name):
    """The title shown on the import workbook's Read Me sheet: the file name without extension, underscores as spaces."""
    return re.sub(r"\s+", " ", os.path.splitext(source_name)[0].replace("_", " ")).strip()


def convert_file(name, source_dir, imports_dir, force=False, dry_run=False, label_from=None, area=None):
    """Convert one file from the To Convert folder. Never raises: always returns a ReportRow."""
    area = area or area_path.DEFAULT
    row = ReportRow(source=name, area_path=area)
    if not name.lower().endswith(".xlsx"):
        row.status = "skipped: not an .xlsx file (save older .xls / .xlsm files as .xlsx first)"
        return row
    versions = existing_versions(imports_dir, name)
    if versions and not force:
        row.status = f"skipped: already converted (V{max(versions)}); use --force for a new version"
        return row
    out_name = f"{import_stem(name)}_AzureDevOps_Import_V{max(versions, default=0) + 1}.xlsx"
    try:
        info = convert(os.path.join(source_dir, name), os.path.join(imports_dir, out_name), feature_title(name),
                       label_from, dry_run, area)
    except NotATestDocument as e:
        row.status = (f"skipped: {e}. This is not a test document, or its headers are not recognised "
                      f"(move it out of the {settings.SOURCE_DIRNAME} folder if it never will be)")
        row.review = "yes"
        return row
    except PermissionError:
        row.status = "FAILED: cannot open the file (is it open in Excel? close it and run again)"
        row.review = "yes"
        return row
    except Exception as e:     # keep going: one bad file must not stop the batch
        row.status = f"FAILED: {type(e).__name__}: {e}"
        row.review = "yes"
        return row
    variants = info.variants
    row.import_file = out_name
    row.status = "analysed only (dry run)" if dry_run else "built"
    row.cases = "; ".join(f"{v.name}: {len(v.cases)}" for v in variants)
    row.steps_per_case = "/".join(str(n) for n in sorted({len(c.steps) for v in variants for c in v.cases}))
    row.sheets_used = ", ".join(info.sheets)
    row.column_map = info.column_map
    row.review = "yes" if info.notes else "no"
    row.notes = " | ".join(info.notes)
    return row


def run_all(source_dir, imports_dir, force, dry_run, label_from, only=None, progress=None, area=None):
    """Convert every file in the To Convert folder (or just the names in `only`).
    progress(i, n, row) is called after each file. Returns the list of ReportRows."""
    label_from = label_from or first_labelled_workbook(imports_dir)
    names = [name for name in source_files(source_dir) if only is None or name in only]
    rows = []
    for i, name in enumerate(names, 1):
        row = convert_file(name, source_dir, imports_dir, force, dry_run, label_from, area)
        rows.append(row)
        if progress:
            progress(i, len(names), row)
    return rows


def write_report(rows, folder):
    """Write the rows to reports/conversion_report_<timestamp>.csv and return its path."""
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, "conversion_report_" + datetime.datetime.now().strftime("%Y%m%d_%H%M%S") + ".csv")
    with open(path, "w", newline="", encoding="utf-8-sig") as fh:
        writer = csv.DictWriter(fh, fieldnames=REPORT_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(asdict(row) for row in rows)
    return path
