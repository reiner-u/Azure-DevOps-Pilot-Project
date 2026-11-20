import unittest

import openpyxl

import _paths  # noqa: F401
from converter import area, headers


class ExactHeaders(unittest.TestCase):
    def assertField(self, header, field, language=None):
        self.assertEqual(headers.classify_exact(header), (field, language), header)

    def test_the_id_column_in_its_many_spellings(self):
        for header in ("Test Scenario ID", "Test Case ID", "test case id ", "TC ID", "Scenario ID", "ID"):
            self.assertField(header, "id")

    def test_business_requirement_with_typos_that_patterns_cover(self):
        for header in ("Business Requirement ID", "Buisness Requirment", "BR ID", "Requirement ID"):
            self.assertField(header, "br")

    def test_description_and_title(self):
        for header in ("Description", "Test Scenario Description", "Test Case Title", "Scenario Name"):
            self.assertField(header, "title")

    def test_steps_and_expected_result(self):
        self.assertField("Pre-condition", "pre")
        self.assertField("Preconditions", "pre")
        self.assertField("Execution Steps", "exe")
        self.assertField("Expected Result", "exp")

    def test_expected_result_language(self):
        self.assertField("Expected Result (EN)", "exp", "EN")
        self.assertField("Expected Result French", "exp", "FR")

    def test_automation_notes_are_not_the_automated_flag(self):
        self.assertField("Automation Notes", "notes")
        self.assertField("Automated", "auto")

    def test_unknown_and_empty_headers(self):
        self.assertEqual(headers.classify_exact("Comments"), (None, None))
        self.assertEqual(headers.classify_exact(None), (None, None))
        self.assertEqual(headers.classify_exact("  "), (None, None))

    def test_every_pattern_has_a_distinct_field_and_example(self):
        names = [name for name, _pattern, _examples in headers.HEADER_PATTERNS]
        self.assertEqual(len(names), len(set(names)))
        self.assertTrue(all(examples for _n, _p, examples in headers.HEADER_PATTERNS))


class MisspelledHeaders(unittest.TestCase):
    def test_close_misspellings_are_read(self):
        self.assertEqual(headers.classify("Pre-conditon")[0], "pre")
        self.assertEqual(headers.classify("Excution")[0], "exe")
        self.assertEqual(headers.classify("Expcted Result")[0], "exp")

    def test_unrelated_words_are_not_guessed(self):
        for header in ("Comments", "Reviewer", "Priority", "Status"):
            self.assertEqual(headers.classify(header), (None, None), header)

    def test_short_headers_are_never_fuzzy_matched(self):
        self.assertEqual(headers.classify_fuzzy("Pre"), (None, None))


def sheet_with(rows):
    ws = openpyxl.Workbook().active
    for row in rows:
        ws.append(row)
    return ws


class FindingTheHeaderRow(unittest.TestCase):
    STANDARD = ["Test Scenario ID", "Description", "Pre-condition", "Execution", "Expected Result"]

    def test_header_row_below_a_title_block(self):
        header = headers.find_header(sheet_with([["Document title"], [], self.STANDARD, ["x"] * 5]))
        self.assertTrue(header.ok)
        self.assertEqual(header.row, 3)
        self.assertEqual(header.cols["id"], 0)

    def test_a_sheet_without_the_required_columns_is_not_ok(self):
        header = headers.find_header(sheet_with([["Name", "Comment"], ["a", "b"]]))
        self.assertFalse(header.ok)
        self.assertEqual(set(header.missing), set(headers.REQUIRED_FIELDS))

    def test_an_empty_sheet(self):
        header = headers.find_header(sheet_with([]))
        self.assertFalse(header.ok)

    def test_unusual_id_header_is_guessed_when_it_is_the_only_candidate(self):
        header = headers.find_header(sheet_with([["Scenario code id", "Description", "Execution", "Expected Result"]]))
        self.assertTrue(header.ok)
        self.assertEqual(header.id_guess, "Scenario code id")

    def test_swapped_type_and_author_columns_are_repaired_from_the_data(self):
        ws = sheet_with([["ID", "Description", "Execution", "Expected Result", "Type", "Author"]]
                        + [[f"T{i}", "d", "e", "x", "A. Tester", "Manual"] for i in range(5)])
        header = headers.find_header(ws)
        notes = []
        headers.fix_swapped_type_author(ws, header, notes)
        self.assertEqual((header.cols["type"], header.cols["author"]), (5, 4))
        self.assertEqual(len(notes), 1)


class AreaPaths(unittest.TestCase):
    def test_tidy(self):
        self.assertEqual(area.tidy(" a//b\\\\c/ "), "a\\b\\c")
        self.assertEqual(area.tidy(None), "")

    def test_blank_rest_means_the_root_only(self):
        self.assertEqual(area.compose(""), area.ROOT)

    def test_rest_goes_after_the_root(self):
        self.assertEqual(area.compose("Team\\Sub"), area.ROOT + "\\Team\\Sub")

    def test_a_repeated_root_is_not_doubled(self):
        self.assertEqual(area.compose(area.ROOT), area.ROOT)
        self.assertEqual(area.compose(area.ROOT + "\\Team"), area.ROOT + "\\Team")
        self.assertEqual(area.compose(area.ROOT.upper() + "\\Team"), area.ROOT + "\\Team")

    def test_resolve_blank_is_the_default(self):
        self.assertEqual(area.resolve(""), area.DEFAULT)
        self.assertEqual(area.resolve("Other"), area.ROOT + "\\Other")

    def test_rest_of_is_the_inverse_of_compose(self):
        self.assertEqual(area.rest_of(area.compose("Team\\Sub")), "Team\\Sub")
        self.assertEqual(area.rest_of(area.ROOT), "")


if __name__ == "__main__":
    unittest.main()
