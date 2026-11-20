"""Convert ALM/HPQC-style Excel test documents into Azure DevOps test-case import workbooks.

BATCH (normal use):   python scripts\\build_import_from_source.py --all
    Converts every .xlsx in the "To Convert" folder that has no import workbook yet, writes
    "Converted to ADO"/<name>_AzureDevOps_Import_V1.xlsx, and writes a review report to reports/conversion_report_<timestamp>.csv.
    Files already converted are skipped (add --force to build the next version, V2, V3...; existing versions are never
    overwritten). Add --dry-run to analyse everything and write nothing.
SINGLE FILE:          python scripts\\build_import_from_source.py <source.xlsx> <output.xlsx> "<Feature title>"
OPTIONS:              --label-from <xlsx>   copy the Microsoft sensitivity label from this workbook
                      (default: the first workbook in "Converted to ADO" that has one, else the source's own label)
                      --area <path>         the ADO Area Path to write on every test case (a path that does not start with the
                      root gets the root put in front; default: scripts/local_config.json)
                      --source-dir / --imports-dir / --reports-dir   override the default folders

HOW A WORKBOOK IS READ (adapts to the file; nothing is hardcoded to one document):
  * Test sheets are found by their headers, not their names: any visible sheet with a header row (searched in the first 25 rows)
    that has a test-case ID, a description, an Execution and an Expected Result column. Version History / Total Testcases / hidden
    sheets are never imported. A workbook with sheets named EN and FR (a two-language layout) gives "EN Import" and "FR Import".
  * Column names are matched by meaning, so "Test Scenario ID", "Test Case ID" and "Test case ID " are all the ID column; "Execution"
    and "Execution Steps", "Pre-condition" and "Preconditions", "Buisness Requirment" and "Business Requirement ID" are accepted, etc.
    The report's column_map shows exactly which source column was used for what.
  * If a sheet has the Expected Result in both English and French columns, it gives an "EN Import" and an "FR Import" sheet with the same
    steps (the source has no French steps) and the matching expected result.
  * Section heading rows (a single cell in column A) are not test cases; the heading is added to the Description of the cases under it.
  * Columns the converter does not know (Notes, Comments, Source, Testing Guidelines...) are copied into the Description under their
    own header, so nothing in the source is dropped. Reviewed By / Reviewed Date are left out and listed in the report.

Rules (reverse-engineered from one hand-converted example; see README.md):
  * Two-row layout per test case: a title row, then one row per step.
  * Title row: Work Item Type=Test Case, Title=the description, Area Path, State=Design, Description.
  * Description = scenario ID, business requirement ID, type, author, automated flag (+ automation notes and any extra columns).
  * Steps: Pre-condition items become steps 1..n (numbering "1." or "1)" stripped, whitespace collapsed; items glued onto one line are
    split on the numbers); Execution follows: a numbered list becomes one step per number, otherwise one step per sentence.
    Expected Result goes on the LAST step only (trailing whitespace trimmed).
  * Pictures embedded in a case's row cannot be imported: they are saved to attachments/<workbook name>/ next to the output, the
    Description names each file, and you attach it in ADO (Expected Result pictures to the last step). Pictures on other sheets are
    saved there too. Step Expected stays as the source text.
  * Nothing in the source text is reworded (typos are kept).
  * Anything unusual is listed in the report's notes column instead of being silently guessed at.
Needs only Python 3 and openpyxl (no Pillow).
"""
import argparse
import os
import sys

from . import area as area_path
from . import settings
from .batch import run_all, write_report
from .convert import convert


def build_parser():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("source", nargs="?")
    parser.add_argument("output", nargs="?")
    parser.add_argument("feature", nargs="?")
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--label-from")
    parser.add_argument("--area", help="ADO Area Path to write on every test case (default: scripts/local_config.json)")
    parser.add_argument("--source-dir")
    parser.add_argument("--imports-dir")
    parser.add_argument("--reports-dir")
    return parser


def run_batch(args, area):
    """--all: convert everything in the To Convert folder and print a summary."""
    root = settings.PROJECT_DIR
    source_dir = args.source_dir or os.path.join(root, settings.SOURCE_DIRNAME)
    imports_dir = args.imports_dir or os.path.join(root, settings.IMPORTS_DIRNAME)
    rows = run_all(source_dir, imports_dir, args.force, args.dry_run, args.label_from, area=area)
    for row in rows:
        print(f"{row.source}\n    -> {row.status}" + (f" | {row.cases}; steps per case {row.steps_per_case}" if row.cases else ""))
        for note in row.note_list():
            print("       note:", note)
    print(f"\n{len(rows)} file(s) found: {sum(r.built for r in rows)} built, {sum(r.skipped for r in rows)} skipped, "
          f"{sum(r.failed for r in rows)} failed, {sum(r.needs_review for r in rows)} need review.")
    if rows and not args.dry_run:
        print("Review report:", write_report(rows, args.reports_dir or os.path.join(root, settings.REPORTS_DIRNAME)))


def run_single(args, area):
    """<source> <output> <feature>: convert one document and print what was built."""
    info = convert(args.source, args.output, args.feature, args.label_from, args.dry_run, area)
    for variant in info.variants:
        cases = variant.cases
        print(f"{variant.name}: {len(cases)} cases, {sum(len(c.steps) for c in cases)} step rows, "
              f"steps per case {sorted({len(c.steps) for c in cases})}")
    for note in info.notes:
        print("  note:", note)
    print("label carried over:", info.label)


def main(argv=None):
    try:
        sys.stdout.reconfigure(errors="replace")      # a console that cannot show some character must not stop the run
    except Exception:
        pass
    parser = build_parser()
    args = parser.parse_args(argv)
    area = area_path.resolve(args.area) if args.area else area_path.DEFAULT
    if args.all:
        run_batch(args, area)
    elif args.source and args.output and args.feature:
        run_single(args, area)
    else:
        parser.error("give <source.xlsx> <output.xlsx> \"<Feature title>\", or use --all")
