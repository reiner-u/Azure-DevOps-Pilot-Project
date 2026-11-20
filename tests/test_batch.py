"""Batch mode: picking up files, version numbers, skipping, failing safely, and the CSV report."""
import csv
import os
import tempfile
import unittest

import _paths  # noqa: F401
import fixtures
from converter import batch, settings
from converter.label import first_labelled_workbook

AREA = "Demo Project\\Demo Area"


class BatchCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.source, self.imports, self.reports = (os.path.join(tmp.name, n) for n in ("src", "imports", "reports"))
        for folder in (self.source, self.imports):
            os.makedirs(folder)

    def add_document(self, name="Login tests.xlsx", *cases):
        return fixtures.simple_document(os.path.join(self.source, name), *(cases or (fixtures.case(1),)))

    def run_all(self, **options):
        defaults = dict(force=False, dry_run=False, label_from=None, area=AREA)
        defaults.update(options)
        return batch.run_all(self.source, self.imports, **defaults)

    def imports_listing(self):
        return sorted(f for f in os.listdir(self.imports) if f.endswith(".xlsx"))


class PickingUpFiles(BatchCase):
    def test_lock_files_and_hidden_files_are_ignored(self):
        self.add_document("Real.xlsx")
        for junk in ("~$Real.xlsx", ".hidden.xlsx"):
            open(os.path.join(self.source, junk), "w").close()
        self.assertEqual(batch.source_files(self.source), ["Real.xlsx"])

    def test_names_are_made_safe_for_the_import_file(self):
        self.assertEqual(batch.import_stem("Login tests (v2).xlsx"), "Login_tests_v2")
        self.assertEqual(batch.feature_title("Login_tests  final.xlsx"), "Login tests final")


class Versions(BatchCase):
    def test_first_run_builds_v1(self):
        self.add_document()
        rows = self.run_all()
        self.assertEqual([r.status for r in rows], ["built"])
        self.assertEqual(rows[0].import_file, "Login_tests_AzureDevOps_Import_V1.xlsx")
        self.assertEqual(self.imports_listing(), ["Login_tests_AzureDevOps_Import_V1.xlsx"])

    def test_a_second_run_skips_files_already_converted(self):
        self.add_document()
        self.run_all()
        rows = self.run_all()
        self.assertEqual(rows[0].status, "skipped: already converted (V1); use --force for a new version")
        self.assertEqual(len(self.imports_listing()), 1)

    def test_force_builds_the_next_version_and_keeps_the_old_one(self):
        self.add_document()
        self.run_all()
        rows = self.run_all(force=True)
        self.assertEqual(rows[0].import_file, "Login_tests_AzureDevOps_Import_V2.xlsx")
        self.assertEqual(len(self.imports_listing()), 2)
        self.assertEqual(batch.existing_versions(self.imports, "Login tests.xlsx"), [1, 2])

    def test_only_the_named_files_are_converted(self):
        self.add_document("One.xlsx")
        self.add_document("Two.xlsx")
        rows = self.run_all(only={"Two.xlsx"})
        self.assertEqual([r.source for r in rows], ["Two.xlsx"])


class OneBadFileDoesNotStopTheBatch(BatchCase):
    def test_a_corrupt_file_fails_and_the_rest_continue(self):
        self.add_document("Good.xlsx")
        with open(os.path.join(self.source, "Broken.xlsx"), "w") as fh:
            fh.write("this is not a zip")
        rows = {r.source: r for r in self.run_all()}
        self.assertTrue(rows["Broken.xlsx"].failed)
        self.assertEqual(rows["Broken.xlsx"].review, "yes")
        self.assertTrue(rows["Good.xlsx"].built)

    def test_a_non_xlsx_file_is_skipped_with_advice(self):
        with open(os.path.join(self.source, "old.xls"), "w") as fh:
            fh.write("x")
        row = self.run_all()[0]
        self.assertTrue(row.skipped)
        self.assertIn("save older .xls / .xlsm files as .xlsx first", row.status)

    def test_a_document_that_is_not_a_test_document_is_skipped_and_flagged(self):
        fixtures.write_workbook(os.path.join(self.source, "Notes.xlsx"), {"Sheet1": [["Name", "Comment"], ["a", "b"]]})
        row = self.run_all()[0]
        self.assertTrue(row.skipped)
        self.assertEqual(row.review, "yes")
        self.assertIn(f"move it out of the {settings.SOURCE_DIRNAME} folder", row.status)
        self.assertEqual(self.imports_listing(), [])


class DryRun(BatchCase):
    def test_nothing_is_written(self):
        self.add_document()
        rows = self.run_all(dry_run=True)
        self.assertEqual(rows[0].status, "analysed only (dry run)")
        self.assertEqual(rows[0].cases, "Import: 1")
        self.assertEqual(os.listdir(self.imports), [])


class ReportRows(BatchCase):
    def test_a_built_row_summarises_the_conversion(self):
        self.add_document("Login tests.xlsx", fixtures.case(1), fixtures.case(2, pre=None, exe="1. Click"))
        row = self.run_all()[0]
        self.assertEqual((row.cases, row.steps_per_case), ("Import: 2", "1/5"))
        self.assertEqual(row.area_path, AREA)
        self.assertEqual(row.review, "no")
        self.assertEqual(row.note_list(), [])
        self.assertIn("Test Cases (header row 1)", row.column_map)

    def test_progress_is_reported_after_each_file(self):
        self.add_document("One.xlsx")
        self.add_document("Two.xlsx")
        seen = []
        self.run_all(progress=lambda i, n, row: seen.append((i, n, row.source)))
        self.assertEqual(seen, [(1, 2, "One.xlsx"), (2, 2, "Two.xlsx")])

    def test_the_csv_report_has_one_line_per_file_and_the_documented_columns(self):
        self.add_document("One.xlsx")
        self.add_document("Two.xlsx", fixtures.case(1, exp=None))
        rows = self.run_all()
        path = batch.write_report(rows, self.reports)
        with open(path, encoding="utf-8-sig", newline="") as fh:
            lines = list(csv.DictReader(fh))
        self.assertEqual(list(lines[0]), batch.REPORT_COLUMNS)
        self.assertEqual(batch.REPORT_COLUMNS[:4], ["source", "import_file", "area_path", "status"])
        self.assertEqual([line["source"] for line in lines], ["One.xlsx", "Two.xlsx"])
        self.assertEqual([line["review"] for line in lines], ["no", "yes"])
        self.assertIn("blank expected result", lines[1]["notes"])

    def test_status_helpers(self):
        self.assertTrue(batch.ReportRow("a", status="built").built)
        self.assertTrue(batch.ReportRow("a", status="FAILED: boom").failed)
        self.assertTrue(batch.ReportRow("a", status="skipped: why").skipped)
        self.assertTrue(batch.ReportRow("a", review="yes").needs_review)
        self.assertFalse(batch.ReportRow("a", status="analysed only (dry run)").built)


class Label(BatchCase):
    def test_new_workbooks_copy_the_label_of_the_first_labelled_workbook_in_the_imports_folder(self):
        labelled = self.add_document("Has label.xlsx")
        fixtures.add_label(labelled)
        os.replace(labelled, os.path.join(self.imports, "Earlier_AzureDevOps_Import_V1.xlsx"))
        self.assertEqual(first_labelled_workbook(self.imports), os.path.join(self.imports, "Earlier_AzureDevOps_Import_V1.xlsx"))
        self.add_document("New.xlsx")
        self.run_all()
        import zipfile
        with zipfile.ZipFile(os.path.join(self.imports, "New_AzureDevOps_Import_V1.xlsx")) as z:
            self.assertEqual(z.read("docMetadata/LabelInfo.xml"), fixtures.LABEL_XML)

    def test_no_labelled_workbook_in_an_empty_or_missing_folder(self):
        self.assertIsNone(first_labelled_workbook(self.imports))
        self.assertIsNone(first_labelled_workbook(os.path.join(self.imports, "nope")))


if __name__ == "__main__":
    unittest.main()
