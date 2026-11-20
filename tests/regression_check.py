"""Check that a code change did not change what the converter produces for YOUR documents.

The repository contains no real test documents, so this tool lets you compare on your own, outside the repository:

    python tests/regression_check.py snapshot "To Convert" snapshots/before     (before you change anything)
    python tests/regression_check.py compare  "To Convert" snapshots/before     (after the change)

`snapshot` converts every document in the folder into the snapshot folder (nothing else is touched). `compare` converts them
again into a temporary folder and lists every difference: sheets, cell values, row heights, pictures, review notes, case counts.
No output after "differences: 0" means nothing changed. Differences are not always wrong (a deliberate fix changes output),
but each one should be something you meant. Keep the snapshots folder out of git (it holds your documents' content).
"""
import json
import os
import sys
import tempfile

import openpyxl

import _paths  # noqa: F401
from converter import area
from converter.batch import run_all


def build(source_dir, out_dir):
    """Convert everything in source_dir into out_dir; returns the report rows as plain dicts."""
    from dataclasses import asdict
    rows = run_all(source_dir, out_dir, force=False, dry_run=False, label_from=None, area=area.DEFAULT)
    return [asdict(row) for row in rows]


def cell_signature(cell):
    return (cell.value, cell.number_format, cell.font.b, cell.fill.fill_type, cell.alignment.wrap_text)


def compare_workbooks(label, path_a, path_b, problems):
    wa, wb = openpyxl.load_workbook(path_a), openpyxl.load_workbook(path_b)
    if wa.sheetnames != wb.sheetnames:
        problems.append(f"{label}: sheets {wa.sheetnames} -> {wb.sheetnames}")
        return
    for name in wa.sheetnames:
        a, b = wa[name], wb[name]
        if (a.max_row, a.max_column) != (b.max_row, b.max_column):
            problems.append(f"{label}/{name}: size {a.max_row}x{a.max_column} -> {b.max_row}x{b.max_column}")
            continue
        for r in range(1, a.max_row + 1):
            if a.row_dimensions[r].height != b.row_dimensions[r].height:
                problems.append(f"{label}/{name}: row {r} height")
            for c in range(1, a.max_column + 1):
                if cell_signature(a.cell(r, c)) != cell_signature(b.cell(r, c)):
                    problems.append(f"{label}/{name} row {r} column {c}: {str(a.cell(r, c).value)[:60]!r} -> "
                                    f"{str(b.cell(r, c).value)[:60]!r}")


def list_files(folder):
    return sorted(os.path.relpath(os.path.join(root, f), folder) for root, _dirs, files in os.walk(folder) for f in files)


def snapshot(source_dir, snapshot_dir):
    os.makedirs(snapshot_dir, exist_ok=True)
    rows = build(source_dir, os.path.join(snapshot_dir, "imports"))
    with open(os.path.join(snapshot_dir, "rows.json"), "w", encoding="utf-8") as fh:
        json.dump(rows, fh, indent=1)
    print(f"snapshot saved: {len(rows)} document(s) in {snapshot_dir}")


def compare(source_dir, snapshot_dir):
    with tempfile.TemporaryDirectory() as tmp:
        rows = build(source_dir, os.path.join(tmp, "imports"))
        problems = []
        with open(os.path.join(snapshot_dir, "rows.json"), encoding="utf-8") as fh:
            before = json.load(fh)
        keep = ("source", "import_file", "status", "cases", "steps_per_case", "review", "notes", "column_map")
        if [{k: r[k] for k in keep} for r in rows] != [{k: r[k] for k in keep} for r in before]:
            for new, old in zip(rows, before):
                for key in keep:
                    if new[key] != old[key]:
                        problems.append(f"{new['source']}: {key} changed: {str(old[key])[:80]!r} -> {str(new[key])[:80]!r}")
            if len(rows) != len(before):
                problems.append(f"document count {len(before)} -> {len(rows)}")
        old_dir, new_dir = os.path.join(snapshot_dir, "imports"), os.path.join(tmp, "imports")
        old_files, new_files = list_files(old_dir), list_files(new_dir)
        if old_files != new_files:
            problems.append(f"files differ: removed {sorted(set(old_files) - set(new_files))}, "
                            f"added {sorted(set(new_files) - set(old_files))}")
        for rel in sorted(set(old_files) & set(new_files)):
            a, b = os.path.join(old_dir, rel), os.path.join(new_dir, rel)
            if rel.endswith(".xlsx"):
                compare_workbooks(rel, a, b, problems)
            elif open(a, "rb").read() != open(b, "rb").read():
                problems.append(f"{rel}: picture changed")
    for problem in problems:
        print("DIFF", problem)
    print(f"differences: {len(problems)}")
    return 1 if problems else 0


if __name__ == "__main__":
    if len(sys.argv) != 4 or sys.argv[1] not in ("snapshot", "compare"):
        sys.exit(__doc__)
    action, source, snap = sys.argv[1:]
    sys.exit(snapshot(source, snap) if action == "snapshot" else compare(source, snap))
