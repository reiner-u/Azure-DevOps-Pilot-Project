"""Whole-document tests: build an import workbook from a made-up source and look at what comes out."""
import os
import tempfile
import unittest
import zipfile

import openpyxl

import _paths  # noqa: F401
import fixtures
from converter import settings
from converter.convert import convert
from converter.automation import AUTOMATED, MANUAL, UNMARKED, group_of
from converter.planning import NotATestDocument

AREA = "Demo Project\\Demo Area"


class ConvertCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = self._tmp.name
        self.addCleanup(self._tmp.cleanup)

    def path(self, name):
        return os.path.join(self.dir, name)

    def build(self, source, name="out.xlsx", **options):
        """Convert `source`; returns (ConversionInfo, the finished workbook)."""
        out = self.path(name)
        info = convert(source, out, "Demo feature", area=AREA, **options)
        return info, openpyxl.load_workbook(out)

    @staticmethod
    def title_rows(ws):
        return [row for row in ws.iter_rows(min_row=2, values_only=True) if row[1] == "Test Case"]

    @staticmethod
    def step_rows(ws):
        return [row for row in ws.iter_rows(min_row=2, values_only=True) if row[3] is not None]


class Layout(ConvertCase):
    def setUp(self):
        super().setUp()
        self.source = fixtures.simple_document(self.path("src.xlsx"), fixtures.case(1), fixtures.case(2, exp="Second result"))
        self.info, self.wb = self.build(self.source)
        self.ws = self.wb["Import"]

    def test_sheets(self):
        self.assertEqual(self.wb.sheetnames, ["Read Me", "Import"])

    def test_header_row(self):
        headers = [c.value for c in self.ws[1]]
        self.assertEqual(headers, ["ID", "Work Item Type", "Title", "Test Step", "Step Action", "Step Expected", "Area Path",
                                   "Assigned To", "State", "Description"])

    def test_title_row_carries_area_path_and_state(self):
        first = self.title_rows(self.ws)[0]
        self.assertEqual(first[2], "Sign in, variant 1")
        self.assertEqual(first[6], AREA)
        self.assertEqual(first[8], settings.STATE)
        self.assertIsNone(first[0])                     # ID stays blank so ADO creates new test cases

    def test_precondition_steps_come_before_execution_steps_and_are_numbered(self):
        rows = self.step_rows(self.ws)[:5]
        self.assertEqual([r[3] for r in rows], [1, 2, 3, 4, 5])
        self.assertEqual([r[4] for r in rows], ["Open the sign-in page", "Have an active account", "Enter the user name",
                                                "Enter the password", "Click Sign in"])

    def test_expected_result_sits_on_the_last_step_only(self):
        rows = self.step_rows(self.ws)[:5]
        self.assertEqual([r[5] for r in rows], [None, None, None, None, "The home page is shown"])

    def test_second_case_follows_the_first(self):
        self.assertEqual(len(self.title_rows(self.ws)), 2)
        self.assertEqual(self.title_rows(self.ws)[1][2], "Sign in, variant 2")
        self.assertEqual(self.step_rows(self.ws)[-1][5], "Second result")

    def test_description_lists_where_the_case_came_from(self):
        description = self.title_rows(self.ws)[0][9]
        self.assertEqual(description.splitlines(), [
            "Source scenario ID: DEMO_Login_001", "Business requirement ID: BR_001", "Test scenario type: Manual",
            "Original author: A. Tester", "Automated: No"])

    def test_read_me_names_the_area_path_and_counts(self):
        text = "\n".join(str(c) for row in self.wb["Read Me"].iter_rows(values_only=True) for c in row if c)
        self.assertIn(AREA, text)
        self.assertIn("2 test cases (Import)", text)

    def test_info(self):
        self.assertEqual(self.info.sheets, ["Test Cases"])
        self.assertFalse(self.info.legacy)
        self.assertIn("Test Cases (header row 1)", self.info.column_map)


class StepSplittingInADocument(ConvertCase):
    def steps_of(self, **changes):
        source = fixtures.simple_document(self.path("src.xlsx"), fixtures.case(1, **changes))
        _info, wb = self.build(source)
        return [r[4] for r in self.step_rows(wb["Import"])]

    def test_glued_numbers(self):
        self.assertEqual(self.steps_of(pre="1.Open the page 2.Log in", exe="1.Click Save"),
                         ["Open the page", "Log in", "Click Save"])

    def test_unnumbered_execution_is_split_by_sentence(self):
        self.assertEqual(self.steps_of(pre=None, exe="Click Save. Check the message."), ["Click Save.", "Check the message."])

    def test_no_precondition(self):
        self.assertEqual(self.steps_of(pre=None, exe="1. Click"), ["Click"])


class ReviewNotes(ConvertCase):
    def notes_for(self, *cases, **options):
        info, _wb = self.build(fixtures.simple_document(self.path("src.xlsx"), *cases), **options)
        return info.notes

    def assertNote(self, notes, fragment):
        self.assertTrue(any(fragment in n for n in notes), f"no note containing {fragment!r} in {notes}")

    def test_a_clean_document_has_no_notes(self):
        self.assertEqual(self.notes_for(fixtures.case(1), fixtures.case(2)), [])

    def test_blank_expected_result(self):
        self.assertNote(self.notes_for(fixtures.case(1, exp=None)), "blank expected result ['001']")

    def test_duplicate_ids(self):
        notes = self.notes_for(fixtures.case(1), fixtures.case(2, id="DEMO_Login_001"))
        self.assertNote(notes, "duplicate scenario IDs ['001']")

    def test_blank_id_is_named_by_row(self):
        self.assertNote(self.notes_for(fixtures.case(1, id=None)), "blank test case ID ['row 2']")

    def test_angle_brackets(self):
        self.assertNote(self.notes_for(fixtures.case(1, exp="Shows <name>")), "angle brackets in expected result ['001']")

    def test_missing_requirement_id(self):
        self.assertNote(self.notes_for(fixtures.case(1, br=None)), "no business requirement ID ['001']")

    def test_long_title_is_shortened_and_the_full_text_kept(self):
        long_title = "Sign in with a very long description " * 6
        source = fixtures.simple_document(self.path("src.xlsx"), fixtures.case(1, title=long_title))
        info, wb = self.build(source)
        row = self.title_rows(wb["Import"])[0]
        self.assertLessEqual(len(row[2]), 128)
        self.assertTrue(row[2].endswith("..."))
        self.assertIn("Full source description: " + long_title.strip(), row[9])
        self.assertTrue(any("description over 128 characters ['001']" in n for n in info.notes))

    def test_unnumbered_precondition_is_flagged(self):
        self.assertNote(self.notes_for(fixtures.case(1, pre="Have an account\nBe signed out")),
                        "pre-condition is not a clean 1..n numbered list")

    def test_cross_reference_between_cases(self):
        self.assertNote(self.notes_for(fixtures.case(2, pre="1. Refer to the pre-conditions in 001")),
                        "refers to another case ['002']")

    def test_many_sentences_in_execution(self):
        self.assertNote(self.notes_for(fixtures.case(1, exe="One. Two. Three. Four.")),
                        "Execution split into more than 3 steps by sentence ['001']")

    def test_case_with_no_steps(self):
        self.assertNote(self.notes_for(fixtures.case(1, pre=None, exe=None)), "no steps")


class UnusualDocuments(ConvertCase):
    def test_misspelled_headers_are_read_and_reported(self):
        headers = list(fixtures.HEADERS)
        headers[3], headers[4] = "Pre-conditon", "Excution"
        source = fixtures.write_workbook(self.path("src.xlsx"), {"Cases": [headers, fixtures.case(1)]})
        info, wb = self.build(source)
        self.assertEqual(len(self.step_rows(wb["Import"])), 5)
        self.assertTrue(any("'Pre-conditon' looks misspelled" in n for n in info.notes))
        self.assertTrue(any("'Excution' looks misspelled" in n for n in info.notes))

    def test_section_heading_rows_go_into_the_description(self):
        # a heading is a row with only column A filled; column A must not be the ID column, so add a Subject column first
        rows = [["Subject"] + fixtures.HEADERS, ["Page fields"], ["Login"] + fixtures.case(1), ["Buttons"],
                ["Login"] + fixtures.case(2)]
        info, wb = self.build(fixtures.write_workbook(self.path("src.xlsx"), {"Cases": rows}))
        titles = self.title_rows(wb["Import"])
        self.assertIn("Section: Page fields", titles[0][9])
        self.assertIn("Section: Buttons", titles[1][9])
        self.assertEqual(len(titles), 2)

    def test_unknown_columns_are_copied_into_the_description(self):
        rows = [fixtures.HEADERS + ["Comments", "Reviewed By"], fixtures.case(1) + ["Check on mobile too", "R. Viewer"]]
        info, wb = self.build(fixtures.write_workbook(self.path("src.xlsx"), {"Cases": rows}))
        description = self.title_rows(wb["Import"])[0][9]
        self.assertIn("Comments: Check on mobile too", description)
        self.assertNotIn("R. Viewer", description)
        self.assertTrue(any("column(s) not carried over: ['Reviewed By']" in n for n in info.notes))

    def test_a_case_without_a_requirement_column_has_no_such_line(self):
        headers = [h for h in fixtures.HEADERS if h != "Business Requirement ID"]
        row = [v for h, v in zip(fixtures.HEADERS, fixtures.case(1)) if h != "Business Requirement ID"]
        info, wb = self.build(fixtures.write_workbook(self.path("src.xlsx"), {"Cases": [headers, row]}))
        self.assertNotIn("Business requirement ID", self.title_rows(wb["Import"])[0][9])
        self.assertTrue(any("no business requirement ID column" in n for n in info.notes))

    def test_version_history_and_hidden_sheets_are_not_imported(self):
        sheets = {"Version History": [["Version", "Date"], ["1", "2026"]], "Cases": [fixtures.HEADERS, fixtures.case(1)],
                  "Old": [fixtures.HEADERS, fixtures.case(9)]}
        source = fixtures.write_workbook(self.path("src.xlsx"), sheets, hidden=("Old",))
        info, wb = self.build(source)
        self.assertEqual(wb.sheetnames, ["Read Me", "Import"])
        self.assertTrue(any("hidden sheet 'Old'" in n for n in info.notes))

    def test_two_test_sheets_give_two_import_sheets(self):
        sheets = {"Login": [fixtures.HEADERS, fixtures.case(1)], "Logout": [fixtures.HEADERS, fixtures.case(2)]}
        _info, wb = self.build(fixtures.write_workbook(self.path("src.xlsx"), sheets))
        self.assertEqual(wb.sheetnames, ["Read Me", "Login Import", "Logout Import"])

    def test_a_document_with_no_test_sheet_is_refused_with_a_helpful_message(self):
        source = fixtures.write_workbook(self.path("src.xlsx"), {"Notes": [["Name", "Comment"], ["a", "b"]]})
        with self.assertRaises(NotATestDocument) as caught:
            self.build(source)
        self.assertIn("no test sheet recognised", str(caught.exception))
        self.assertIn("'Notes'", str(caught.exception))


class Languages(ConvertCase):
    def test_en_and_fr_sheets(self):
        sheets = {"EN": [fixtures.HEADERS, fixtures.case(1)], "FR": [fixtures.HEADERS, fixtures.case(1, exp="La page")]}
        info, wb = self.build(fixtures.write_workbook(self.path("src.xlsx"), sheets))
        self.assertEqual(wb.sheetnames, ["Read Me", "EN Import", "FR Import"])
        self.assertTrue(info.legacy)
        self.assertEqual(self.step_rows(wb["FR Import"])[-1][5], "La page")

    def test_one_sheet_with_english_and_french_expected_results(self):
        headers = list(fixtures.HEADERS)
        headers[5] = "Expected Result (EN)"
        headers.append("Expected Result (FR)")
        rows = [headers, fixtures.case(1) + ["La page d'accueil"]]
        info, wb = self.build(fixtures.write_workbook(self.path("src.xlsx"), {"Cases": rows}))
        self.assertEqual(wb.sheetnames, ["Read Me", "EN Import", "FR Import"])
        self.assertEqual(self.step_rows(wb["EN Import"])[-1][5], "The home page is shown")
        self.assertEqual(self.step_rows(wb["FR Import"])[-1][5], "La page d'accueil")
        self.assertIn("Expected result language: French", self.title_rows(wb["FR Import"])[0][9])
        self.assertEqual(len([r for r in self.step_rows(wb["EN Import"])]), len(self.step_rows(wb["FR Import"])))

    def test_an_empty_french_column_gives_only_one_sheet(self):
        headers = list(fixtures.HEADERS) + ["Expected Result (FR)"]
        headers[5] = "Expected Result (EN)"
        rows = [headers, fixtures.case(1) + [None]]
        info, wb = self.build(fixtures.write_workbook(self.path("src.xlsx"), {"Cases": rows}))
        self.assertEqual(wb.sheetnames, ["Read Me", "Import"])
        self.assertTrue(any("French expected-result column is empty" in n for n in info.notes))


class Pictures(ConvertCase):
    def test_a_picture_in_the_expected_result_cell_is_saved_and_named(self):
        source = fixtures.simple_document(self.path("src.xlsx"), fixtures.case(1, exp=None), fixtures.case(2))
        fixtures.add_picture(source, row0=1, col0=5)          # case 1's Expected Result cell
        info, wb = self.build(source)
        description = self.title_rows(wb["Import"])[0][9]
        self.assertIn("Expected result image: attachments/out/Test_Cases_DEMO_Login_001.png", description)
        self.assertIn("a picture here instead of text", description)
        with open(self.path("attachments/out/Test_Cases_DEMO_Login_001.png"), "rb") as fh:
            self.assertEqual(fh.read(), fixtures.TINY_PNG)
        self.assertTrue(any("expected result has a picture for ['001']" in n for n in info.notes))
        self.assertFalse(any("blank expected result" in n for n in info.notes))

    def test_a_picture_in_another_cell_is_named_after_that_column(self):
        source = fixtures.simple_document(self.path("src.xlsx"), fixtures.case(1))
        fixtures.add_picture(source, row0=1, col0=4)          # the Execution cell
        info, wb = self.build(source)
        self.assertIn("Picture in the Execution cell: attachments/out/Test_Cases_DEMO_Login_001_execution.png",
                      self.title_rows(wb["Import"])[0][9])

    def test_a_picture_on_a_row_without_a_case_is_reported(self):
        source = fixtures.simple_document(self.path("src.xlsx"), fixtures.case(1))
        fixtures.add_picture(source, row0=20, col0=5)
        info, _wb = self.build(source)
        self.assertTrue(any("picture(s) sit on rows with no test case and were NOT carried over" in n for n in info.notes))


class SensitivityLabel(ConvertCase):
    def test_the_label_of_the_source_is_copied(self):
        source = fixtures.simple_document(self.path("src.xlsx"), fixtures.case(1))
        fixtures.add_label(source)
        info, _wb = self.build(source)
        self.assertTrue(info.label)
        with zipfile.ZipFile(self.path("out.xlsx")) as z:
            self.assertEqual(z.read("docMetadata/LabelInfo.xml"), fixtures.LABEL_XML)
            self.assertIn(b"LabelInfo.xml", z.read("[Content_Types].xml"))
            self.assertIn(b"LabelInfo.xml", z.read("_rels/.rels"))

    def test_a_workbook_that_opens_in_openpyxl_after_labelling(self):
        source = fixtures.simple_document(self.path("src.xlsx"), fixtures.case(1))
        fixtures.add_label(source)
        self.build(source)
        self.assertEqual(openpyxl.load_workbook(self.path("out.xlsx")).sheetnames, ["Read Me", "Import"])


class ManualAndAutomated(ConvertCase):
    """The optional "Automated (Yes or No)" column splits a sheet into a Manual and an Automated import sheet."""

    def test_which_values_count_as_automated(self):
        for value in ("Yes", "yes", " YES ", "Y", "yes, partially", "Yes partially", "automated", "true"):
            self.assertEqual(group_of(value), AUTOMATED, value)
        for value in ("No", "no", "N", "manual", "Not yet", "false"):
            self.assertEqual(group_of(value), MANUAL, value)
        for value in (None, "", "   ", "N/A", "n/a", "TBD", "?", "-", "duplicate", "45/53", "Not applicable"):
            self.assertEqual(group_of(value), UNMARKED, repr(value))

    def test_a_mixed_sheet_gives_a_manual_and_an_automated_sheet(self):
        source = fixtures.simple_document(self.path("src.xlsx"), fixtures.case(1, auto="No"),
                                          fixtures.case(2, auto="Yes"), fixtures.case(3, auto="Yes"))
        info, wb = self.build(source)
        self.assertEqual(wb.sheetnames, ["Read Me", "Manual Import", "Automated Import"])
        self.assertEqual(len(self.title_rows(wb["Manual Import"])), 1)
        self.assertEqual(len(self.title_rows(wb["Automated Import"])), 2)
        self.assertIn("Automated: No", self.title_rows(wb["Manual Import"])[0][9])
        self.assertIn("Automated: Yes", self.title_rows(wb["Automated Import"])[0][9])
        self.assertTrue(any("split by the 'Automated' column" in n for n in info.notes), info.notes)

    def test_cases_keep_their_source_order_within_each_sheet(self):
        cases = [fixtures.case(n, auto="Yes" if n % 2 else "No") for n in range(1, 7)]
        _info, wb = self.build(fixtures.simple_document(self.path("src.xlsx"), *cases))
        self.assertEqual([row[2] for row in self.title_rows(wb["Manual Import"])],
                         ["Sign in, variant 2", "Sign in, variant 4", "Sign in, variant 6"])
        self.assertEqual([row[2] for row in self.title_rows(wb["Automated Import"])],
                         ["Sign in, variant 1", "Sign in, variant 3", "Sign in, variant 5"])

    def test_a_partially_automated_case_counts_as_automated(self):
        source = fixtures.simple_document(self.path("src.xlsx"), fixtures.case(1, auto="No"),
                                          fixtures.case(2, auto="Yes, partially"))
        _info, wb = self.build(source)
        self.assertEqual([row[2] for row in self.title_rows(wb["Automated Import"])], ["Sign in, variant 2"])
        self.assertIn("Automated: Yes, partially", self.title_rows(wb["Automated Import"])[0][9])

    def test_a_blank_or_unclear_value_goes_to_the_manual_sheet_and_is_named(self):
        source = fixtures.simple_document(self.path("src.xlsx"), fixtures.case(1, auto="Yes"),
                                          fixtures.case(2, auto=None), fixtures.case(3, auto="duplicate"))
        info, wb = self.build(source)
        self.assertEqual(len(self.title_rows(wb["Manual Import"])), 2)
        note = next(n for n in info.notes if "split by" in n)
        self.assertIn("blank or unclear value", note)
        self.assertIn("['002', '003']", note)

    def test_an_all_manual_document_is_not_split_and_gets_no_note(self):
        source = fixtures.simple_document(self.path("src.xlsx"), fixtures.case(1), fixtures.case(2))
        info, wb = self.build(source)
        self.assertEqual(wb.sheetnames, ["Read Me", "Import"])
        self.assertEqual(info.notes, [])

    def test_an_all_automated_document_is_not_split_but_says_so(self):
        source = fixtures.simple_document(self.path("src.xlsx"), fixtures.case(1, auto="Yes"))
        info, wb = self.build(source)
        self.assertEqual(wb.sheetnames, ["Read Me", "Import"])
        self.assertTrue(any("every case is marked automated" in n for n in info.notes), info.notes)

    def test_an_all_blank_column_is_not_split_but_says_so(self):
        source = fixtures.simple_document(self.path("src.xlsx"), fixtures.case(1, auto=None), fixtures.case(2, auto=None))
        info, wb = self.build(source)
        self.assertEqual(wb.sheetnames, ["Read Me", "Import"])
        self.assertTrue(any("blank or unclear for all 2 case(s)" in n for n in info.notes), info.notes)

    def test_a_document_without_the_column_is_untouched(self):
        headers = fixtures.HEADERS[:-1]
        rows = [headers, fixtures.case(1)[:-1], fixtures.case(2)[:-1]]
        info, wb = self.build(fixtures.write_workbook(self.path("src.xlsx"), {"Test Cases": rows}))
        self.assertEqual(wb.sheetnames, ["Read Me", "Import"])
        self.assertFalse([n for n in info.notes if "automated" in n and "no Automated column" not in n], info.notes)

    def test_en_and_fr_sheets_are_each_split(self):
        sheets = {"EN": [fixtures.HEADERS, fixtures.case(1, auto="No"), fixtures.case(2, auto="Yes")],
                  "FR": [fixtures.HEADERS, fixtures.case(1, auto="No", exp="La page"),
                         fixtures.case(2, auto="Yes", exp="La page")]}
        _info, wb = self.build(fixtures.write_workbook(self.path("src.xlsx"), sheets))
        self.assertEqual(wb.sheetnames, ["Read Me", "EN Manual", "EN Automated", "FR Manual", "FR Automated"])
        self.assertEqual(len(self.title_rows(wb["FR Automated"])), 1)

    def test_a_bilingual_sheet_is_split_in_both_languages(self):
        headers = list(fixtures.HEADERS)
        headers[5] = "Expected Result (EN)"
        headers.append("Expected Result (FR)")
        rows = [headers, fixtures.case(1, auto="No") + ["La page"], fixtures.case(2, auto="Yes") + ["La page"]]
        _info, wb = self.build(fixtures.write_workbook(self.path("src.xlsx"), {"Cases": rows}))
        self.assertEqual(wb.sheetnames, ["Read Me", "EN Manual", "EN Automated", "FR Manual", "FR Automated"])
        self.assertEqual(self.step_rows(wb["FR Automated"])[-1][5], "La page")

    def test_two_test_sheets_are_named_after_their_sheet(self):
        sheets = {"Page fields": [fixtures.HEADERS, fixtures.case(1, auto="No"), fixtures.case(2, auto="Yes")],
                  "Navigation": [fixtures.HEADERS, fixtures.case(3, auto="No"), fixtures.case(4, auto="Yes")]}
        _info, wb = self.build(fixtures.write_workbook(self.path("src.xlsx"), sheets))
        self.assertEqual(wb.sheetnames, ["Read Me", "Page fields Manual", "Page fields Automated",
                                         "Navigation Manual", "Navigation Automated"])

    def test_the_read_me_explains_the_split_and_names_the_column(self):
        headers = list(fixtures.HEADERS)
        headers[-1] = "Automatable (Yes or No)"
        rows = [headers, fixtures.case(1, auto="No"), fixtures.case(2, auto="Yes")]
        _info, wb = self.build(fixtures.write_workbook(self.path("src.xlsx"), {"Test Cases": rows}))
        read_me = {row[0]: row[1] for row in wb["Read Me"].iter_rows(values_only=True)}
        self.assertIn("Automatable (Yes or No)", read_me["Manual / automated"])
        self.assertIn("1 test cases (Manual Import) / 1 test cases (Automated Import)", read_me["Import sheets"])

    def test_a_picture_on_an_automated_case_still_lands_in_attachments(self):
        source = fixtures.simple_document(self.path("src.xlsx"), fixtures.case(1, auto="No"),
                                          fixtures.case(2, auto="Yes", exp=None))
        fixtures.add_picture(source, 2, 5)
        _info, wb = self.build(source)
        description = self.title_rows(wb["Automated Import"])[0][9]
        self.assertIn("attachments/out/Test_Cases_DEMO_Login_002.png", description)
        self.assertTrue(os.path.exists(self.path("attachments/out/Test_Cases_DEMO_Login_002.png")))


class DryRun(ConvertCase):
    def test_a_dry_run_analyses_but_writes_nothing(self):
        source = fixtures.simple_document(self.path("src.xlsx"), fixtures.case(1, exp=None))
        info = convert(source, self.path("out.xlsx"), "Demo feature", dry_run=True, area=AREA)
        self.assertFalse(os.path.exists(self.path("out.xlsx")))
        self.assertTrue(any("blank expected result" in n for n in info.notes))
        self.assertIsNone(info.label)


if __name__ == "__main__":
    unittest.main()
