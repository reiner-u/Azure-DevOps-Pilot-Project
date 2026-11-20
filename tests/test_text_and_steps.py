import unittest

import _paths  # noqa: F401  (makes the converter importable)
from converter import steps, text


class TextHelpers(unittest.TestCase):
    def test_norm_collapses_all_whitespace(self):
        self.assertEqual(text.norm("  a \n b\t\tc "), "a b c")

    def test_clean_gives_none_for_empty_cells(self):
        self.assertIsNone(text.clean(None))
        self.assertIsNone(text.clean("  \n "))
        self.assertEqual(text.clean(" x "), "x")
        self.assertEqual(text.clean(12), "12")

    def test_tidy_lines_keeps_line_breaks_but_drops_blank_lines(self):
        self.assertEqual(text.tidy_lines(" a \n\n  b  "), "a\nb")

    def test_slug(self):
        self.assertEqual(text.slug("Hello, World! (v2)"), "Hello_World_v2")
        self.assertEqual(text.slug("abcdefghij", 4), "abcd")

    def test_short_id_is_the_last_part(self):
        self.assertEqual(text.short_id("Module_Screen_007"), "007")
        self.assertEqual(text.short_id("007"), "007")

    def test_list_for_note_cuts_long_lists(self):
        self.assertEqual(text.list_for_note(["a", "b"]), "['a', 'b']")
        shown = text.list_for_note([str(i) for i in range(15)])
        self.assertTrue(shown.endswith("... +3 more]"))

    def test_shorten_title_leaves_short_titles_alone(self):
        self.assertEqual(text.shorten_title("short"), "short")

    def test_shorten_title_cuts_at_a_word_and_stays_within_the_limit(self):
        long_title = "word " * 40
        shortened = text.shorten_title(long_title)
        self.assertLessEqual(len(shortened), text.MAX_TITLE_LENGTH)
        self.assertTrue(shortened.endswith("..."))
        self.assertFalse(shortened[:-3].endswith(" "))

    def test_shorten_title_with_no_spaces_still_fits(self):
        shortened = text.shorten_title("x" * 300)
        self.assertEqual(len(shortened), text.MAX_TITLE_LENGTH)


class NumberedLists(unittest.TestCase):
    def test_clean_list_with_dots_or_brackets(self):
        self.assertEqual(steps.split_numbered("1. Open 2. Click 3. Save"), ["Open", "Click", "Save"])
        self.assertEqual(steps.split_numbered("1) Open 2) Click"), ["Open", "Click"])

    def test_numbers_glued_to_the_text_count(self):
        self.assertEqual(steps.split_numbered("1.Open the page 2.Click Save"), ["Open the page", "Click Save"])
        self.assertEqual(steps.split_numbered('1."Quoted" 2.(Bracketed)'), ['"Quoted"', "(Bracketed)"])

    def test_one_item_per_line(self):
        self.assertEqual(steps.split_numbered("1. Open\n2. Click\n3. Save"), ["Open", "Click", "Save"])

    def test_decimals_and_version_numbers_are_not_steps(self):
        self.assertIsNone(steps.split_numbered("Wait 1.5 seconds then click"))
        self.assertIsNone(steps.split_numbered("1.1 Check the version"))

    def test_list_must_start_at_one_and_run_without_gaps(self):
        self.assertIsNone(steps.split_numbered("2. Open 3. Click"))
        self.assertIsNone(steps.split_numbered("1. Open 3. Click"))
        self.assertIsNone(steps.split_numbered("1. Open 1. Click"))

    def test_text_before_the_first_number_means_not_a_list(self):
        self.assertIsNone(steps.split_numbered("Do this: 1. Open 2. Click"))

    def test_lines_that_all_start_with_numbers_but_not_cleanly(self):
        self.assertEqual(steps.split_numbered_lines("1. Open\n1. Click\n4. Save"), ["Open", "Click", "Save"])
        self.assertIsNone(steps.split_numbered_lines("1. Open\nthen click"))
        self.assertIsNone(steps.split_numbered_lines("1. Only one line"))


class Preconditions(unittest.TestCase):
    def test_empty(self):
        self.assertEqual(steps.split_precondition(None), ([], False))
        self.assertEqual(steps.split_precondition("  "), ([], False))

    def test_numbered(self):
        self.assertEqual(steps.split_precondition("1. A 2. B"), (["A", "B"], False))

    def test_unnumbered_lines_fall_back_to_one_step_per_line(self):
        result = steps.split_precondition("First thing\nSecond thing")
        self.assertEqual(result.steps, ["First thing", "Second thing"])
        self.assertTrue(result.fell_back)

    def test_a_single_unnumbered_line_is_one_step_without_a_flag(self):
        self.assertEqual(steps.split_precondition("Just one line"), (["Just one line"], False))

    def test_bullets_stay_inside_their_step(self):
        result = steps.split_precondition("1. Open the form\n- field one\n- field two\n2. Save")
        self.assertEqual(result.steps, ["Open the form - field one - field two", "Save"])


class Execution(unittest.TestCase):
    def test_numbered(self):
        result = steps.split_execution("1. Click 2. Type")
        self.assertEqual((result.steps, result.numbering), (["Click", "Type"], steps.NUMBERED))

    def test_renumbered(self):
        result = steps.split_execution("1. Click\n1. Type")
        self.assertEqual((result.steps, result.numbering), (["Click", "Type"], steps.RENUMBERED))

    def test_sentences(self):
        result = steps.split_execution("Click the button. Type a name! Done?")
        self.assertEqual(result.steps, ["Click the button.", "Type a name!", "Done?"])
        self.assertEqual(result.numbering, steps.NOT_NUMBERED)
        self.assertFalse(result.multiline)

    def test_several_unnumbered_lines_are_flagged(self):
        result = steps.split_execution("Click the button.\nType a name.")
        self.assertTrue(result.multiline)

    def test_empty(self):
        result = steps.split_execution("")
        self.assertEqual((result.steps, result.numbering, result.multiline), ([], steps.NOT_NUMBERED, False))


if __name__ == "__main__":
    unittest.main()
