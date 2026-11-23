"""Tests for the defects package: ALM defect exports in, Bug import CSVs out.

The exports here are made up. Nothing in this file is real OSAP or ALM content.
"""
import csv
import os
import tempfile
import unittest

import _paths  # noqa: F401
import fixtures
from defects import checks, headers, mapping
from defects.convert import NotADefectExport, convert
from defects.writer import html_paragraphs, write_csvs

AREA = "Demo Project\\Demo Area"


class Headers(unittest.TestCase):
    def test_the_usual_alm_wordings_are_recognised(self):
        for header, expected in (("Defect ID", "id"), ("Summary", "title"), ("Reproduction Steps", "steps"),
                                 ("Status", "status"), ("Severity", "severity"), ("Priority", "priority"),
                                 ("Assigned To", "assigned_to"), ("Detected By", "detected_by"),
                                 ("Detection Date", "detected_date"), ("Closing Date", "closing_date"),
                                 ("Subject", "subject"), ("R&D Comments", "comments")):
            self.assertEqual(headers.classify(header), expected, header)

    def test_an_unknown_header_is_not_guessed(self):
        self.assertIsNone(headers.classify("Planned Closing Version"))
        self.assertIsNone(headers.classify(None))

    def test_every_pattern_has_a_distinct_field_and_example(self):
        names = [name for name, _pattern, _examples in headers.DEFECT_PATTERNS]
        self.assertEqual(len(names), len(set(names)))
        self.assertTrue(all(examples for _n, _p, examples in headers.DEFECT_PATTERNS))
        self.assertTrue(all(name in headers.FIELD_NAMES for name in names))


class ConvertCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = self._tmp.name
        self.addCleanup(self._tmp.cleanup)

    def path(self, name):
        return os.path.join(self.dir, name)

    def build(self, *defects, **options):
        """Convert a made-up export; returns (DefectConversion, the rows of the first CSV)."""
        source = fixtures.defect_export(self.path("export.xlsx"), *defects, **options.pop("export", {}))
        result = convert(source, self.path("out"), area=AREA, **options)
        rows = []
        if result.files:
            with open(result.files[0], newline="", encoding="utf-8-sig") as fh:
                rows = list(csv.DictReader(fh))
        return result, rows


class ReadingAnExport(ConvertCase):
    def test_one_row_becomes_one_bug(self):
        result, rows = self.build(fixtures.defect(1), fixtures.defect(2))
        self.assertEqual(len(result.defects), 2)
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["Work Item Type"], "Bug")
        self.assertEqual(rows[0]["Title"], "Sign-in page shows the wrong message, variant 1")
        self.assertEqual(rows[0]["Area Path"], AREA)
        self.assertNotIn("ID", rows[0])                      # a filled ID would update an item instead of creating one

    def test_the_header_row_is_found_under_a_title_block(self):
        result, rows = self.build(fixtures.defect(1), export=dict(title_block=True))
        self.assertEqual(len(rows), 1)
        self.assertEqual(result.sheet, "Defects")

    def test_a_sheet_without_an_id_and_summary_is_refused(self):
        source = fixtures.write_workbook(self.path("export.xlsx"), {"Notes": [["Comments"], ["nothing here"]]})
        with self.assertRaises(NotADefectExport):
            convert(source, self.path("out"), area=AREA)

    def test_the_alm_values_are_kept_where_ado_has_no_field(self):
        _result, rows = self.build(fixtures.defect(1))
        info = rows[0]["System Info"]
        self.assertIn("ALM defect ID: DEF-0001", info)
        self.assertIn("ALM status: Open", info)
        self.assertIn("Detected by: tester2", info)
        self.assertIn("Seen on the test environment only.", info)

    def test_the_alm_id_and_status_become_tags(self):
        _result, rows = self.build(fixtures.defect(1))
        self.assertEqual(rows[0]["Tags"], "ALM-DEF-0001;migrated-from-ALM;ALM-status-Open")

    def test_unknown_columns_are_carried_into_system_info_and_reported(self):
        extra_headers = fixtures.ALM_DEFECT_HEADERS + ["Planned Closing Version"]
        row = fixtures.defect(1) + ["26.11"]
        result, rows = self.build(row, export=dict(headers=extra_headers))
        self.assertIn("Planned Closing Version: 26.11", rows[0]["System Info"])
        self.assertTrue(any("no pattern matched" in n for n in result.notes), result.notes)

    def test_steps_and_description_become_html_paragraphs(self):
        _result, rows = self.build(fixtures.defect(1))
        self.assertIn("<p>1. Open the sign-in page</p>", rows[0]["Repro Steps"])
        self.assertNotIn("\n", rows[0]["Repro Steps"])

    def test_html_special_characters_are_escaped(self):
        self.assertEqual(html_paragraphs("a < b & c"), "<p>a &lt; b &amp; c</p>")
        self.assertEqual(html_paragraphs(None), "")

    def test_a_long_summary_is_shortened_and_the_full_text_kept(self):
        long_title = "Sign-in " + "very " * 60 + "long"
        _result, rows = self.build(fixtures.defect(1, title=long_title))
        self.assertLessEqual(len(rows[0]["Title"]), 255)
        self.assertTrue(rows[0]["Title"].endswith("..."))
        self.assertIn("Full ALM summary:", rows[0]["System Info"])

    def test_a_dry_run_writes_nothing(self):
        result, _rows = self.build(fixtures.defect(1), dry_run=True)
        self.assertEqual(result.files, [])
        self.assertFalse(os.path.exists(self.path("out")))
        self.assertEqual(len(result.defects), 1)


class UnmappedValues(ConvertCase):
    """While the maps in mapping.py are empty, every ALM value is unmapped: the notes have to say exactly which."""

    def test_the_fields_are_blank_rather_than_guessed(self):
        _result, rows = self.build(fixtures.defect(1))
        for column in ("State", "Severity", "Priority", "Assigned To"):
            self.assertEqual(rows[0][column], "", column)

    def test_every_unmapped_value_is_named_in_the_notes(self):
        result, _rows = self.build(fixtures.defect(1), fixtures.defect(2, status="Closed"))
        notes = " ".join(result.notes)
        self.assertIn("'Open': 1", notes)
        self.assertIn("'Closed': 1", notes)
        self.assertIn("ALM severity(ies) with no ADO value", notes)
        self.assertIn("ALM user name(s) with no ADO identity", notes)

    def test_a_mapped_value_is_written_and_not_reported(self):
        self.addCleanup(mapping.STATE_FROM_ALM.clear)
        mapping.STATE_FROM_ALM["Open"] = "Active"
        result, rows = self.build(fixtures.defect(1))
        self.assertEqual(rows[0]["State"], "Active")
        self.assertFalse([n for n in result.notes if "no ADO state" in n], result.notes)

    def test_a_defect_without_a_summary_gets_a_placeholder_and_a_note(self):
        result, rows = self.build(fixtures.defect(1, title=None))
        self.assertIn("no summary in ALM", rows[0]["Title"])
        self.assertTrue(any("no summary" in n for n in result.notes), result.notes)


class ImportLimit(ConvertCase):
    """ADO takes at most 1,000 work items per CSV import, so a big export becomes several files."""

    def test_the_rows_are_split_into_files_of_the_chunk_size(self):
        source = fixtures.defect_export(self.path("export.xlsx"), *[fixtures.defect(n) for n in range(1, 8)])
        result = convert(source, self.path("out"), area=AREA, dry_run=True)
        paths = write_csvs(result.defects, self.path("out"), "export", AREA, chunk=3)
        self.assertEqual([os.path.basename(p) for p in paths],
                         ["export_ADO_Bugs_part01of03.csv", "export_ADO_Bugs_part02of03.csv",
                          "export_ADO_Bugs_part03of03.csv"])
        with open(paths[2], newline="", encoding="utf-8-sig") as fh:
            self.assertEqual(len(list(csv.DictReader(fh))), 1)

    def test_one_file_when_the_export_fits(self):
        _result, rows = self.build(fixtures.defect(1), fixtures.defect(2))
        self.assertEqual(len(rows), 2)

    def test_going_over_the_limit_is_a_review_note(self):
        self.addCleanup(setattr, mapping, "MAX_ROWS_PER_IMPORT", mapping.MAX_ROWS_PER_IMPORT)
        mapping.MAX_ROWS_PER_IMPORT = 2         # one home for the limit, so patching it here is enough
        source = fixtures.defect_export(self.path("export.xlsx"), *[fixtures.defect(n) for n in range(1, 4)])
        result = convert(source, self.path("out"), area=AREA, dry_run=True)
        self.assertTrue(any("over ADO's 2-per-import limit" in n for n in result.notes), result.notes)
        self.assertIn("2 files", " ".join(result.notes))


class Batch(ConvertCase):
    def test_a_batch_writes_a_report_row_per_file(self):
        from defects.batch import run_all, write_report
        exports, out = self.path("ALM Defects"), self.path("Bug CSVs")
        os.makedirs(exports)
        fixtures.defect_export(os.path.join(exports, "defects_a.xlsx"), fixtures.defect(1))
        fixtures.write_workbook(os.path.join(exports, "not an export.xlsx"), {"Sheet1": [["Comments"], ["x"]]})
        rows = run_all(exports, out, area=AREA)
        self.assertEqual([r.source for r in rows], ["defects_a.xlsx", "not an export.xlsx"])
        self.assertTrue(rows[0].built)
        self.assertEqual(rows[0].defects, 1)
        self.assertEqual(rows[0].import_rounds, 1)
        self.assertTrue(rows[1].status.startswith("skipped"))
        report = write_report(rows, self.path("reports"))
        self.assertTrue(os.path.exists(report))


if __name__ == "__main__":
    unittest.main()
