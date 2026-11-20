"""The texts the window shows about a run. Plain functions of report rows, so they need no window to be tested."""
import os


def result_details(row):
    """The Details box text for one result row."""
    notes = row.note_list()
    lines = [f"Document: {row.source}", f"Status: {row.status}"]
    if row.import_file:
        lines.append(f"Import file: {row.import_file}")
    if row.sheets_used:
        lines.append(f"Sheets read: {row.sheets_used}")
    if row.column_map:
        lines.append(f"Columns used: {row.column_map}")
    lines.append("")
    lines.append("Review notes:" if notes else "No review notes.")
    lines += [f"  - {note}" for note in notes]
    return "\n".join(lines)


def run_summary(rows, report_path, dry_run):
    """The status line after a run."""
    built = sum(r.built for r in rows)
    skipped = sum(r.skipped for r in rows)
    failed = sum(r.failed for r in rows)
    review = sum(r.needs_review for r in rows)
    start = f"Dry run: {len(rows)} checked, nothing written. " if dry_run else f"{built} built, "
    saved = f" Report saved in {os.path.basename(report_path)}." if report_path else ""
    return start + f"{skipped} skipped, {failed} failed, {review} need review." + saved
