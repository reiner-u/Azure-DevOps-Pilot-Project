"""Deciding which sheets of a workbook are test sheets and which import sheets (Variants) to build from them.

Three kinds of workbook are handled:
  * an older layout with sheets literally named "EN" and "FR": one import sheet each ("EN Import", "FR Import");
  * a test sheet with an English and a French expected-result column: an EN and an FR import sheet with the same steps;
  * everything else: one import sheet per test sheet.
Sheets are recognised by their headers, never by their names (see headers.py). A sheet that marks some of its cases
automated and some not is split once more, into a Manual and an Automated sheet, after the cases have been read
(automation.py).
"""
import re
from dataclasses import dataclass, field

from .headers import FIELD_NAMES, column_has_content, find_header, fix_swapped_type_author
from .text import slug
from .variants import Variant

LANGUAGE_SHEETS = (("EN", "EN Import"), ("FR", "FR Import"))     # (source sheet name, import sheet name) of the older layout
MAX_SHEET_NAME = 31                                              # Excel's limit


class NotATestDocument(Exception):
    """The workbook has no sheet that looks like a test sheet."""


@dataclass
class Plan:
    variants: list = field(default_factory=list)
    legacy: bool = False             # the older EN / FR two-sheet layout
    bilingual: bool = False          # one sheet with English and French expected results
    diagnostics: list = field(default_factory=list)   # why each sheet was not used (for the "no test sheet" message)


def plan_variants(wb, notes):
    """Decide which worksheets are test sheets and which import sheets to build from them. Review notes go into `notes`."""
    found, diagnostics = _find_test_sheets(wb, notes)
    language_sheets = [(ws, header) for ws, header in found if ws.title in dict(LANGUAGE_SHEETS)]
    if language_sheets:
        return Plan(_plan_language_sheets(language_sheets, found, notes), legacy=True, diagnostics=diagnostics)
    if not found:
        return Plan(diagnostics=diagnostics)
    variants, bilingual = _plan_sheets(found, notes)
    return Plan(variants, bilingual=bilingual, diagnostics=diagnostics)


def _find_test_sheets(wb, notes):
    """-> ([(worksheet, Header)] for the sheets that look like test sheets, [why each other sheet was not used])."""
    found, diagnostics = [], []
    for ws in wb.worksheets:
        header = find_header(ws)
        if header.ok:
            if ws.sheet_state != "visible":
                notes.append(f"hidden sheet {ws.title!r} looks like a test sheet and was ignored")
                continue
            fix_swapped_type_author(ws, header, notes)
            for text, field_name in header.fuzzy:
                if field_name in header.cols or field_name == "exp":
                    notes.append(f"{ws.title}: header {text!r} looks misspelled; read it as "
                                 f"{FIELD_NAMES.get(field_name, field_name)} (check column_map)")
            if header.id_guess:
                notes.append(f"{ws.title}: no column is named like a test case ID; used {header.id_guess!r} as the ID column "
                             f"(check column_map)")
            found.append((ws, header))
        else:
            missing = ", ".join(FIELD_NAMES[k] for k in header.missing)
            diagnostics.append(f"{ws.title!r} (best header row matched {header.score} known column(s); missing: {missing})")
            if header.score >= 2 and ws.sheet_state == "visible":
                # looks like a test sheet with unfamiliar headers: never drop it silently
                notes.append(f"sheet {ws.title!r} was NOT imported: it has some test-case headers but is missing {missing}")
    return found, diagnostics


def _plan_language_sheets(language_sheets, found, notes):
    """The older layout: sheets named EN and FR, each with its own expected results."""
    variants = []
    for language, import_name in LANGUAGE_SHEETS:
        match = next(((ws, header) for ws, header in language_sheets if ws.title == language), None)
        if match is None:
            notes.append(f"sheet {language} not found")
            continue
        ws, header = match
        variants.append(Variant(name=import_name, tag=language, ws=ws, header=header, src_sheet=language, prefix=language))
    for ws, _header in found:
        if ws.title not in dict(LANGUAGE_SHEETS):
            notes.append(f"sheet {ws.title!r} looks like a test sheet but was not used (this workbook has EN/FR sheets)")
    return variants


class SheetNamer:
    """Gives every import sheet a valid, unique name (Excel: at most 31 characters, none of []:*?/\\, no duplicates)."""

    def __init__(self):
        self.taken = set()

    def unique(self, name):
        name = re.sub(r"[\[\]:*?/\\]", " ", name).strip()[:MAX_SHEET_NAME]
        base, counter = name, 2
        while name.lower() in self.taken:
            name = f"{base[:28]} {counter}"
            counter += 1
        self.taken.add(name.lower())
        return name


def _plan_sheets(found, notes):
    """One import sheet per test sheet, or an EN and an FR sheet for a sheet with two expected-result columns."""
    variants, bilingual, namer = [], False, SheetNamer()
    several = len(found) > 1
    for ws, header in found:
        title = ws.title.strip()
        french_col = header.cols.get("exp_fr")
        if french_col is not None and not column_has_content(ws, header, french_col):
            notes.append(f"{title}: the French expected-result column is empty, so only one import sheet was built")
            french_col = None
        if french_col is None:
            variants.append(Variant(name=namer.unique(f"{title[:24]} Import" if several else "Import"), tag=title, ws=ws,
                                    header=header, src_sheet=title, prefix=slug(title, 24)))
            continue
        bilingual = True
        en_name = namer.unique(f"{title[:20]} EN" if several else "EN Import")
        fr_name = namer.unique(f"{title[:20]} FR" if several else "FR Import")
        prefix = (slug(title, 16) + "_") if several else ""
        variants.append(Variant(
            name=en_name, tag=f"{title} (EN)", ws=ws, header=header, src_sheet=title, prefix=prefix + "EN",
            skip_cols=(french_col,),
            variant_note="Expected result language: English (the source has English and French expected results; "
                         "this is the English case)"))
        variants.append(Variant(
            name=fr_name, tag=f"{title} (FR)", ws=ws, header=header, src_sheet=title, prefix=prefix + "FR",
            exp_key="exp_fr", skip_cols=(header.cols["exp"],), first=False,
            variant_note="Expected result language: French (same steps as the English case; the source has no French steps)"))
    return variants, bilingual


def column_map(variants):
    """Which source column was used for what, one entry per source sheet (shown in the report and the window)."""
    entries, seen = [], set()
    for variant in variants:
        if variant.src_sheet in seen:
            continue
        seen.add(variant.src_sheet)
        header = variant.header
        pairs = [f"{name}={header.headers[col]!r}" for name, col in header.cols.items()
                 if col is not None and col < len(header.headers)]
        entries.append(f"{variant.src_sheet} (header row {header.row}): " + ", ".join(pairs))
    return " || ".join(entries)
