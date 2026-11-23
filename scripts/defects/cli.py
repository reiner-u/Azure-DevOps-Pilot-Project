"""Convert ALM defect exports into Azure DevOps Bug import CSVs.

BATCH (normal use):   python scripts\\build_bugs_from_defects.py --all
    Converts every .xlsx in the "ALM Defects" folder, writes "Bug CSVs for ADO"/<name>_ADO_Bugs[_partNNofNN].csv
    and a review report to reports/defect_report_<timestamp>.csv.
SINGLE FILE:          python scripts\\build_bugs_from_defects.py <export.xlsx> <output folder>
OPTIONS:              --dry-run             read and check everything, write nothing
                      --area <path>         the ADO Area Path for every Bug (default: scripts/local_config.json)
                      --defects-dir / --bugs-dir / --reports-dir    override the default folders

UNFINISHED, so always start with --dry-run: the value maps in defects/mapping.py are empty, which means State, Severity,
Priority and Assigned To come out blank and the report tells you which ALM values are still unmapped. The column wordings
in defects/headers.py are guesses from typical ALM exports and need checking against the real one.

Before importing anything into ADO: the CSV import takes at most 1,000 rows per file, every item arrives in the Bug's
initial state (so a closed ALM defect does not import as closed), and identity fields must match an existing ADO user.
Thousands of Bugs are hard to undo, so agree the plan with whoever owns Boards first.
"""
import argparse
import os
import sys

from converter import area as area_path
from converter import settings

from .batch import BUGS_DIRNAME, DEFECTS_DIRNAME, REPORTS_DIRNAME, convert_file, run_all, write_report


def build_parser():
    parser = argparse.ArgumentParser(prog="build_bugs_from_defects", add_help=True,
                                     description="ALM defect exports to Azure DevOps Bug import CSVs")
    parser.add_argument("source", nargs="?", help="one export file (.xlsx)")
    parser.add_argument("out", nargs="?", help="folder for the CSVs")
    parser.add_argument("--all", action="store_true", help=f"convert every export in the {DEFECTS_DIRNAME} folder")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--area")
    parser.add_argument("--defects-dir")
    parser.add_argument("--bugs-dir")
    parser.add_argument("--reports-dir")
    return parser


def _print_row(row):
    print(f"{row.source}\n    -> {row.status} | {row.defects} defect(s) | {row.import_rounds} import round(s)"
          f"{' | ' + row.csv_files if row.csv_files else ''}")
    for note in row.note_list():
        print(f"       note: {note}")


def main(argv=None):
    args = build_parser().parse_args(argv)
    area = area_path.resolve(args.area) if args.area else area_path.DEFAULT
    project = settings.PROJECT_DIR
    defects_dir = args.defects_dir or os.path.join(project, DEFECTS_DIRNAME)
    bugs_dir = args.bugs_dir or os.path.join(project, BUGS_DIRNAME)
    reports_dir = args.reports_dir or os.path.join(project, REPORTS_DIRNAME)

    if args.all or not args.source:
        if not os.path.isdir(defects_dir):
            print(f"no {DEFECTS_DIRNAME} folder yet: create it and put the ALM exports in it")
            return 1
        rows = run_all(defects_dir, bugs_dir, args.dry_run, area=area)
        if not rows:
            print(f"no files in {defects_dir}")
            return 0
        for row in rows:
            _print_row(row)
        built = sum(r.built for r in rows)
        print(f"\n{len(rows)} file(s): {built} built, {sum(r.failed for r in rows)} failed, "
              f"{sum(r.needs_review for r in rows)} need review.")
        print("Review report:", write_report(rows, reports_dir))
        return 0

    row = convert_file(os.path.basename(args.source), os.path.dirname(os.path.abspath(args.source)),
                       args.out or bugs_dir, args.dry_run, area)
    _print_row(row)
    return 1 if row.failed else 0


if __name__ == "__main__":
    sys.exit(main())
