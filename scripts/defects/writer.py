"""Writing the Bug CSV files that ADO's work item import takes.

One CSV per import run, at most MAX_ROWS_PER_IMPORT rows each, because ADO refuses a bigger file: an export of 11,400
defects becomes 12 files, imported one after another. No ID column is written, so every row is a new work item.

Text fields are HTML in ADO, so line breaks become paragraphs; anything else would arrive as one run-on block.
"""
import csv
import html
import os

from . import mapping
from .mapping import (BUG_COLUMNS, IDENTITIES, PRIORITY_FROM_ALM, SEVERITY_FROM_ALM, STATE_FROM_ALM, WORK_ITEM_TYPE,
                      mapped, tags_for)


def html_paragraphs(text):
    """Plain text -> the HTML an ADO rich-text field expects: one <p> per line, special characters escaped."""
    if not text:
        return ""
    lines = [html.escape(line.strip()) for line in str(text).splitlines() if line.strip()]
    return "".join(f"<p>{line}</p>" for line in lines)


def repro_steps(defect):
    """The Repro Steps field: the ALM reproduction steps, with the description above them when both are filled in."""
    parts = [part for part in (defect.description, defect.steps) if part]
    return html_paragraphs("\n".join(parts))


def system_info(defect):
    """The System Info field: everything ALM had that has no ADO field of its own, so nothing is lost in the move."""
    lines = []
    for label, value in (("ALM defect ID", defect.defect_id), ("ALM status", defect.status),
                         ("Detected by", defect.detected_by), ("Detection date", defect.detected_date),
                         ("Closing date", defect.closing_date), ("Version", defect.version),
                         ("Environment", defect.environment), ("Subject", defect.subject),
                         ("Comments", defect.comments)):
        if value:
            lines.append(f"{label}: {value}")
    if defect.title_full:
        lines.append(f"Full ALM summary: {defect.title_full}")
    lines += [f"{header}: {text}" for header, text in defect.extras]
    return html_paragraphs("\n".join(lines))


def row_for(defect, area_path):
    """One CSV row for one defect, as a dict keyed by BUG_COLUMNS."""
    return {
        "Work Item Type": WORK_ITEM_TYPE,
        "Title": defect.title or f"(no summary in ALM, defect {defect.label})",
        "Assigned To": mapped(IDENTITIES, defect.assigned_to) or "",
        "State": mapped(STATE_FROM_ALM, defect.status) or "",
        "Area Path": area_path,
        "Severity": mapped(SEVERITY_FROM_ALM, defect.severity) or "",
        "Priority": mapped(PRIORITY_FROM_ALM, defect.priority) or "",
        "Repro Steps": repro_steps(defect),
        "System Info": system_info(defect),
        "Tags": tags_for(defect),
    }


def write_csvs(defects, out_dir, stem, area_path, chunk=None):
    """Write the CSVs for one export. Returns the paths written, in import order.
    `chunk` defaults to mapping.MAX_ROWS_PER_IMPORT, read at call time so the limit has one home."""
    chunk = chunk or mapping.MAX_ROWS_PER_IMPORT
    os.makedirs(out_dir, exist_ok=True)
    batches = [defects[start:start + chunk] for start in range(0, len(defects), chunk)] or [[]]
    paths = []
    for number, batch in enumerate(batches, 1):
        suffix = f"_part{number:02d}of{len(batches):02d}" if len(batches) > 1 else ""
        path = os.path.join(out_dir, f"{stem}_ADO_Bugs{suffix}.csv")
        with open(path, "w", newline="", encoding="utf-8-sig") as fh:
            writer = csv.DictWriter(fh, fieldnames=list(BUG_COLUMNS), extrasaction="ignore")
            writer.writeheader()
            for defect in batch:
                writer.writerow(row_for(defect, area_path))
        paths.append(path)
    return paths
