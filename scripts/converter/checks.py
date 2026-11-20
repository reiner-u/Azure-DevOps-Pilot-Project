"""Review notes: the things a person should look at before importing.

The converter never silently guesses. Whatever it could not decide for you becomes a note in the report (and in the window's
Details box). Every check below looks at the cases of one Variant and returns one note, or None when everything is fine.

To add a check: write a function `_something(variant, context)` that returns a note string or None, and add it to CHECKS in
the position where its note should appear. Set `first_sheet_only=True` unless the problem would show up the same way in the
FR sheet of a bilingual document (those notes would only be repeated).
"""
import re
from collections import namedtuple

import openpyxl

from .steps import NOT_NUMBERED, RENUMBERED
from .text import MAX_TITLE_LENGTH, list_for_note, short_id

# Phrases that mean a step relies on another case ("refer to the pre-conditions in 001"): an ADO case has to stand alone.
CROSS_REFERENCE = re.compile(r"\brefer(?:s|red)? to\b|\bsame as\b|\blisted in\b|\bsee (?:case|test|scenario|pre)", re.I)

Context = namedtuple("Context", "declared legacy")      # declared: case counts from the source's Total Testcases sheet


def _labels(cases, condition):
    """The review-note names of the cases for which `condition(case)` is true."""
    return [case.label for case in cases if condition(case)]


# ----- checks, one per kind of problem -----------------------------------------------------------------------------------
def _no_cases(v, ctx):
    if not v.cases:
        return f"{v.tag}: no test cases found"


def _count_differs_from_declared(v, ctx):
    key = v.tag if ctx.legacy else re.sub(r"[^a-z0-9]", "", v.src_sheet.lower())
    if key in ctx.declared and ctx.declared[key] != len(v.cases):
        return f"{v.tag}: the source's Total Testcases sheet says {ctx.declared[key]}, found {len(v.cases)}"


def _duplicate_ids(v, ctx):
    ids = [c.scenario_id for c in v.cases if c.scenario_id]
    duplicates = sorted({short_id(i) for i in ids if ids.count(i) > 1})
    if duplicates:
        return f"{v.tag}: duplicate scenario IDs {duplicates}"


def _blank_ids(v, ctx):
    rows = [f"row {c.row}" for c in v.cases if not c.scenario_id]
    if rows:
        return f"{v.tag}: blank test case ID {list_for_note(rows)} (imported with no ID line; check the source)"


def _expected_result_pictures(v, ctx):
    names = _labels(v.cases, lambda c: c.images)
    if names:
        return f"{v.tag}: expected result has a picture for {list_for_note(names)}; pictures saved to attachments/, attach by hand"


def _pictures_in_other_cells(v, ctx):
    named = [f"{c.label} ({'/'.join(sorted({column for column, _, _ in c.other_images}))})" for c in v.cases if c.other_images]
    if named:
        return (f"{v.tag}: picture(s) in another cell of the case's row {list_for_note(named)}; "
                f"saved to attachments/, attach by hand")


def _blank_expected_results(v, ctx):
    names = _labels(v.cases, lambda c: not c.expected and not c.images)
    if names:
        return f"{v.tag}: blank expected result {list_for_note(names)}"


def _angle_brackets(v, ctx):
    names = _labels(v.cases, lambda c: c.expected and re.search(r"[<>]", c.expected))
    if names:
        return f"{v.tag}: angle brackets in expected result {list_for_note(names)} (check they display in ADO)"


def _missing_requirement_ids(v, ctx):
    if v.cases and "br" in v.cases[0].fields_present:
        names = _labels(v.cases, lambda c: not c.requirement_id)
        if names:
            return f"{v.tag}: no business requirement ID {list_for_note(names)}"


def _long_titles(v, ctx):
    names = _labels(v.cases, lambda c: c.title_full)
    if names:
        return (f"{v.tag}: description over {MAX_TITLE_LENGTH} characters {list_for_note(names)}; the title was shortened to "
                f"fit ADO's limit and the full text is in the Description")


def _missing_titles(v, ctx):
    names = _labels(v.cases, lambda c: not c.title)
    if names:
        return f"{v.tag}: missing title {list_for_note(names)} (ADO will reject)"


def _joined_titles(v, ctx):
    names = _labels(v.cases, lambda c: c.title_was_joined)
    if names:
        return f"{v.tag}: title had line breaks, joined with spaces {list_for_note(names)}"


def _no_steps(v, ctx):
    names = _labels(v.cases, lambda c: not c.steps)
    if names:
        return f"{v.tag}: no steps (empty pre-condition and execution) {list_for_note(names)}"


def _precondition_split_by_line(v, ctx):
    names = _labels(v.cases, lambda c: c.precondition_fell_back)
    if names:
        return (f"{v.tag}: pre-condition is not a clean 1..n numbered list; split by line instead "
                f"{list_for_note(names)} (check the steps)")


def _execution_renumbered(v, ctx):
    names = _labels(v.cases, lambda c: c.execution_numbering == RENUMBERED)
    if names:
        return (f"{v.tag}: Execution numbering is not a clean 1..n run (repeated or skipped number); split by line instead "
                f"{list_for_note(names)} (check the steps)")


def _execution_lines_without_numbers(v, ctx):
    names = _labels(v.cases, lambda c: c.execution_multiline)
    if names:
        return (f"{v.tag}: Execution has several lines but no numbering, split by sentence {list_for_note(names)} "
                f"(check the steps)")


def _execution_split_into_many_sentences(v, ctx):
    names = _labels(v.cases, lambda c: c.n_execution_steps > 3 and c.execution_numbering == NOT_NUMBERED)
    if names:
        return (f"{v.tag}: Execution split into more than 3 steps by sentence {list_for_note(names)} "
                f"(check the sentence splitting)")


def _refers_to_another_case(v, ctx):
    names = _labels(v.cases, lambda c: CROSS_REFERENCE.search(" ".join(c.steps)))
    if names:
        return (f"{v.tag}: pre-condition/execution refers to another case {list_for_note(names)}; each ADO case stands alone, "
                f"so copy the detail in or link the cases")


# (check, first_sheet_only). The order here is the order of the notes in the report.
CHECKS = (
    (_no_cases, False),
    (_count_differs_from_declared, True),
    (_duplicate_ids, True),
    (_blank_ids, True),
    (_expected_result_pictures, False),
    (_pictures_in_other_cells, True),
    (_blank_expected_results, False),
    (_angle_brackets, False),
    (_missing_requirement_ids, True),
    (_long_titles, True),
    (_missing_titles, True),
    (_joined_titles, True),
    (_no_steps, True),
    (_precondition_split_by_line, True),
    (_execution_renumbered, True),
    (_execution_lines_without_numbers, True),
    (_execution_split_into_many_sentences, True),
    (_refers_to_another_case, True),
)


def review_notes(variants, declared, legacy, unanchored_total):
    """All review notes for a converted workbook, in report order."""
    context = Context(declared, legacy)
    notes = []
    for variant in variants:
        for check, first_sheet_only in CHECKS:
            if first_sheet_only and not variant.first:
                continue
            note = check(variant, context)
            if note:
                notes.append(note)
    notes += _english_french_comparison(variants, legacy)
    if unanchored_total:
        notes.append(f"{unanchored_total} picture(s) not anchored to any cell were NOT carried over")
    return notes


def _english_french_comparison(variants, legacy):
    """For the older EN / FR two-sheet layout: do both sheets describe the same cases?"""
    if not legacy:
        return []
    if len(variants) == 1:
        return ["only one of the EN / FR sheets was found"]
    if len(variants) != 2:
        return []
    english, french = variants[0].cases, variants[1].cases
    if len(english) != len(french):
        return [f"EN has {len(english)} cases but FR has {len(french)}"]
    differing = [en.label for en, fr in zip(english, french) if en.title != fr.title or len(en.steps) != len(fr.steps)]
    if differing:
        return [f"EN and FR differ in title or step count for {list_for_note(differing)}"]
    return []


def read_declared_counts(path):
    """Case counts claimed on the source's 'Total Testcases' sheet, e.g. {'EN': 21, 'FR': 21, 'schoolsearch': 22}.
    Reads the values Excel last calculated, so formulas such as =COUNTA(...) work when the file was saved by Excel."""
    counts = {}
    try:
        workbook = openpyxl.load_workbook(path, data_only=True)
    except Exception:
        return counts
    if "Total Testcases" not in workbook.sheetnames:
        return counts
    count_col = module_col = None
    for row in workbook["Total Testcases"].iter_rows(values_only=True):
        cells = [str(v).strip().lower() if v is not None else "" for v in row]
        if any(c.startswith("no. of test") for c in cells):
            count_col = next(i for i, c in enumerate(cells) if c.startswith("no. of test"))
            module_col = next((i for i, c in enumerate(cells) if c.startswith("module")), None)
            continue
        if count_col is not None and module_col is not None and row[module_col] \
                and str(row[module_col]).strip().lower() != "total":
            try:
                count = int(float(str(row[count_col])))
            except ValueError:
                continue
            language = re.search(r"(EN|FR)\s*$", str(row[module_col]).strip().upper())
            if language:
                counts[language.group(1)] = count
            counts[re.sub(r"[^a-z0-9]", "", str(row[module_col]).lower())] = count
    return counts
