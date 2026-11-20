"""Telling automated test cases apart from manual ones, and splitting a sheet's cases into two import sheets.

Some documents have an optional "Automated (Yes or No)" column. When a sheet has one and its cases are a mix, that sheet
gives two import sheets instead of one, a Manual one and an Automated one, the same way a sheet with English and French
expected results gives an EN and an FR sheet (planning.py). A suite in ADO is then filled from one sheet only.

Why the values are not simply read as yes/no: the column is filled in by hand, and the real documents hold blanks,
"Yes, partially", "N/A" and strays such as "duplicate" or "45/53". So only a value whose first word means yes counts as
automated, only a value whose first word means no counts as manual, and anything else is unmarked. Unmarked cases go on
the Manual sheet (a test case in ADO is manual unless it is linked to automation) and every one of them is named in a
review note, so nobody has to take a blank cell on trust.

This runs after the cases have been read, because the split depends on the value in each row, while planning.py works out
the sheets before any row is read. Splitting also comes after the review notes, so the notes still describe the source
sheet as a whole rather than each half of it.
"""
import re
from dataclasses import replace

from .planning import SheetNamer
from .text import list_for_note

AUTOMATED, MANUAL, UNMARKED = "automated", "manual", "unmarked"     # the group a single case belongs to

MANUAL_SHEET, AUTOMATED_SHEET = "Manual", "Automated"               # what the two import sheets are called

# The first word of the cell decides. "Yes, partially" is automated (the exact source wording stays in the Description).
YES_WORDS = frozenset(("y", "yes", "yeah", "yep", "true", "auto", "automated", "automatic", "automate", "automatable"))
NO_WORDS = frozenset(("n", "no", "nope", "not", "false", "manual", "manually", "none"))
# Values that say "nobody filled this in" rather than yes or no. Matched whole, so "Not yet" is still a "no".
NO_ANSWER = re.compile(r"n\s*[/\\]\s*a|n\.\s*a\.?|na|not\s*applicable|tbd|tba|unknown|pending|\?+|-+|x", re.I)


def group_of(value):
    """Which group a source value belongs to: AUTOMATED, MANUAL or UNMARKED (blank, unclear or not a yes/no)."""
    text = (value or "").strip()
    if not text or NO_ANSWER.fullmatch(text):
        return UNMARKED
    first = next((word for word in re.split(r"[^A-Za-z]+", text) if word), "").lower()
    if first in YES_WORDS:
        return AUTOMATED
    if first in NO_WORDS:
        return MANUAL
    return UNMARKED


def grouped(cases):
    """{AUTOMATED: [case], MANUAL: [case], UNMARKED: [case]} for one sheet's cases."""
    groups = {AUTOMATED: [], MANUAL: [], UNMARKED: []}
    for case in cases:
        groups[group_of(case.automated)].append(case)
    return groups


def split_by_automation(variants, notes):
    """-> the import sheets to build, splitting the ones whose source sheet marks some cases automated and some not.

    A variant is passed through unchanged when its sheet has no Automated column, or when every case falls on the same
    side of it (one sheet is clearer than an empty second one). Review notes go into `notes`."""
    namer, result = SheetNamer(), []
    for variant in variants:
        groups = grouped(variant.cases)
        automated, manual = groups[AUTOMATED], groups[MANUAL] + groups[UNMARKED]
        if variant.header.cols.get("auto") is None or not automated or not manual:
            note = _single_sheet_note(variant, groups) if variant.cases else None
            if note:
                notes.append(note)
            result.append(replace(variant, name=namer.unique(variant.name)))
            continue
        manual.sort(key=lambda case: case.row)
        manual_name, automated_name = _split_names(variant.name, namer)
        notes.append(f"{variant.tag}: split by the {_column_name(variant)!r} column into {manual_name!r} "
                     f"({len(manual)} case(s), the ones not marked automated) and {automated_name!r} "
                     f"({len(automated)} case(s))"
                     + _unmarked_note(groups, f"the {manual_name!r} sheet"))
        result.append(replace(variant, name=manual_name, tag=f"{variant.tag} ({MANUAL_SHEET})", cases=manual))
        result.append(replace(variant, name=automated_name, tag=f"{variant.tag} ({AUTOMATED_SHEET})", cases=automated))
    return result


def column_header(variants):
    """The source column the split was made on, for the Read Me sheet, or None when nothing was split."""
    for variant in variants:
        if variant.tag.endswith(f"({MANUAL_SHEET})"):
            return _column_name(variant)
    return None


def _column_name(variant):
    header = variant.header
    column = header.cols.get("auto")
    return header.headers[column] if column is not None and column < len(header.headers) else "Automated"


def _split_names(name, namer):
    """The two sheet names for a sheet that is split: 'Import' -> 'Manual Import', 'EN Import' -> 'EN Manual'."""
    suffix = " Import"
    base = name[:-len(suffix)] if name.endswith(suffix) and len(name) > len(suffix) else None
    if base:
        return namer.unique(f"{base} {MANUAL_SHEET}"), namer.unique(f"{base} {AUTOMATED_SHEET}")
    if name == "Import":
        return namer.unique(f"{MANUAL_SHEET} {suffix.strip()}"), namer.unique(f"{AUTOMATED_SHEET} {suffix.strip()}")
    return namer.unique(f"{name} {MANUAL_SHEET}"), namer.unique(f"{name} {AUTOMATED_SHEET}")


def _unmarked_note(groups, where):
    """The part of a note that names the cases whose value was blank or unclear, and says where they ended up."""
    unmarked = groups[UNMARKED]
    if not unmarked:
        return ""
    one = len(unmarked) == 1
    return (f". {len(unmarked)} of them {'has' if one else 'have'} a blank or unclear value and {'is' if one else 'are'} "
            f"on {where}: {list_for_note(case.label for case in unmarked)} (check {'this' if one else 'these'})")


def _single_sheet_note(variant, groups):
    """The note for a sheet that has an Automated column but was not split, or None when nothing had to be decided.

    A sheet whose cases all say no needs no note: one import sheet of manual cases is what the source says."""
    column = _column_name(variant)
    if not groups[AUTOMATED] and not groups[MANUAL]:
        return (f"{variant.tag}: the {column!r} column is blank or unclear for all {len(groups[UNMARKED])} case(s), so "
                f"they are all on the one import sheet (nothing was split)")
    if groups[UNMARKED]:
        return (f"{variant.tag}: no case is marked automated in the {column!r} column, so there is one import sheet"
                + _unmarked_note(groups, "it"))
    if not groups[MANUAL]:
        return (f"{variant.tag}: every case is marked automated in the {column!r} column, so there is one import sheet "
                f"and no {MANUAL_SHEET!r} sheet")
    return None
