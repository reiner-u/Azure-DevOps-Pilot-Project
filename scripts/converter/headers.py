"""Working out which column of a sheet is which.

Documents written over many years name their columns differently ("Test Scenario ID", "Test case ID ", "Execution Steps",
"Buisness Requirment"...), so columns are matched by meaning:

  1. HEADER_PATTERNS: one regular expression per field. To teach the converter a new header wording, add it to the pattern
     of the field it means (or, for a typo, rely on step 2).
  2. FUZZY_WORDS: when no pattern matches, a header very close to a known word ("Pre-conditon", "Excution") is read as that
     field, and the report notes say so.

A sheet counts as a test sheet when its header row (searched in the first 25 rows) has an ID, a description, an Execution and
an Expected Result column.
"""
import difflib
import re
from dataclasses import dataclass, field
from typing import Optional

from .text import clean

# --- 1. exact patterns ---------------------------------------------------------------------------------------------------
# (field, pattern, example headers). The headers are lower-cased and matched from their start. Order matters: the first
# pattern that matches wins, so "automation notes" must come before "automat".
HEADER_PATTERNS = (
    ("id", r"test (scenarios?|cases?) id\b|(tc|scenario|case) id\b|id$",
     "Test Scenario ID, Test Case ID, TC ID, Scenario ID, ID"),
    ("br", r"b[uis]{3,4}ness req(?!.*source)|br( id)?$|requirements? id$|req(uirement)? ?id$",
     "Business Requirement ID, Buisness Requirment, BR ID, Requirement ID"),
    ("title", r"((test )?(scenarios?|cases?) )?(description|title)\b|(test )?(scenarios?|cases?) (title|name)\b",
     "Description, Test Scenario Description, Test Case Title, Scenario Name"),
    ("type", r"((test )?(scenarios?|cases?) )?type$",
     "Type, Test Scenario Type"),
    ("author", r"author|user id$|created by",
     "Author, Created By, User ID"),
    ("subject", r"subject",
     "Subject"),
    ("pre", r"pre-? ?conditions?",
     "Pre-condition, Preconditions, Pre condition"),
    ("exe", r"execution",
     "Execution, Execution Steps"),
    ("notes", r"automation notes",
     "Automation Notes"),
    ("auto", r"automat",
     "Automated, Automatable"),
    ("exp", r"expected results?",
     "Expected Result, Expected Results (EN), Expected Result FR"),
)
_COMPILED_PATTERNS = tuple((name, re.compile(pattern)) for name, pattern, _examples in HEADER_PATTERNS)

# --- 2. typo tolerance ---------------------------------------------------------------------------------------------------
# Misspelled headers ("Pre-conditon", "Excution") are common in hand-edited documents. When no pattern matches, a header very
# close to one of these words (letters only, no spaces) is read as that field. Short words are left out on purpose: they
# are too easy to mismatch.
FUZZY_WORDS = (("precondition", "pre"), ("execution", "exe"), ("expectedresult", "exp"), ("description", "title"),
               ("subject", "subject"), ("author", "author"), ("automated", "auto"))
FUZZY_CUTOFF = 0.86      # 1.0 = identical. Lower catches more typos but starts to mistake unrelated headers.
FUZZY_MIN_LENGTH = 6     # headers with fewer letters than this are never matched fuzzily

# --- the fields ----------------------------------------------------------------------------------------------------------
REQUIRED_FIELDS = ("id", "title", "exe", "exp")           # a sheet without all of these is not a test sheet
FIELD_NAMES = dict(id="ID", br="business requirement", title="description", type="type", author="author",
                   subject="subject", pre="pre-condition", exe="execution", exp="expected result",
                   exp_fr="French expected result", auto="automated", notes="automation notes")

# Columns that are never copied into the Description (the report lists them instead).
IGNORED_COLUMN = re.compile(r"^(reviewed|review date|reviewer)")

HEADER_SEARCH_ROWS = 25


def clean_header(value):
    """Header cell text with every run of whitespace (non-breaking spaces too) turned into one space."""
    return re.sub(r"[\s\xa0]+", " ", str(value if value is not None else "")).strip()


def _expected_result_language(header):
    """'FR', 'EN' or None, from words such as 'French' or '(EN)' in an Expected Result header."""
    if re.search(r"\b(fr|fra|french|fran[cç]ais)\b", header):
        return "FR"
    if re.search(r"\b(en|eng|english)\b", header):
        return "EN"
    return None


def classify_exact(header):
    """Header text -> (field, language) by pattern, or (None, None). Language is only set for Expected Result columns."""
    header = clean_header(header).lower()
    if not header:
        return None, None
    for name, pattern in _COMPILED_PATTERNS:
        if pattern.match(header):
            return name, (_expected_result_language(header) if name == "exp" else None)
    return None, None


def classify_fuzzy(header):
    """Header text -> (field, language) for a near-miss spelling of a known header, else (None, None)."""
    header = clean_header(header).lower()
    letters = re.sub(r"[^a-z]", "", header)
    if len(letters) < FUZZY_MIN_LENGTH:
        return None, None
    best_ratio, best_field = 0.0, None
    for word, name in FUZZY_WORDS:
        # compare against the same number of letters as the word (plus one), so "Execution Steps" still matches "execution"
        ratio = difflib.SequenceMatcher(None, letters[:len(word) + 1], word).ratio()
        if ratio > best_ratio:
            best_ratio, best_field = ratio, name
    if best_ratio < FUZZY_CUTOFF:
        return None, None
    return best_field, (_expected_result_language(header) if best_field == "exp" else None)


def classify(header):
    """Exact patterns first, then the typo-tolerant fallback."""
    name, language = classify_exact(header)
    return (name, language) if name else classify_fuzzy(header)


@dataclass
class Header:
    """The header row found on a sheet."""
    row: int = 0                                  # 1-based row number of the header row (0 = none found)
    cols: dict = field(default_factory=dict)      # field name -> 0-based column index
    headers: list = field(default_factory=list)   # cleaned text of every cell in the header row
    score: int = 0                                # how many known columns the row has
    id_guess: Optional[str] = None                # header text used as the ID column although it is not named like one
    fuzzy: list = field(default_factory=list)     # [(header text, field)] read through typo tolerance
    missing: list = field(default_factory=lambda: list(REQUIRED_FIELDS))
    ok: bool = False                              # True when every required field was found


def find_header(ws, scan=HEADER_SEARCH_ROWS):
    """Look for the header row in the first rows of a sheet and return the best candidate as a Header."""
    best = None
    for row_number, row in enumerate(ws.iter_rows(min_row=1, max_row=scan, values_only=True), start=1):
        cols, fuzzy = {}, []
        for index, value in enumerate(row):
            name, language = classify_exact(value)
            if name is None:
                name, language = classify_fuzzy(value)
                if name is None:
                    continue
                fuzzy.append((clean_header(value), name))
            if name == "exp":
                cols.setdefault("exp_fr" if language == "FR" else "exp", index)
            else:
                cols.setdefault(name, index)
        if "exp" not in cols and "exp_fr" in cols:
            cols["exp"] = cols.pop("exp_fr")          # only a French column: treat it as the expected result
        id_guess = None
        if "id" not in cols and all(k in cols for k in ("title", "exe", "exp")):
            # the ID column has an unusual header: take the one unclaimed column whose header ends in "id"
            candidates = [i for i, v in enumerate(row)
                          if i not in cols.values() and re.search(r"id\b", clean_header(v).lower())]
            if len(candidates) == 1:
                cols["id"], id_guess = candidates[0], clean_header(row[candidates[0]])
        if best is None or len(cols) > best.score:
            best = Header(row=row_number, cols=cols, headers=[clean_header(v) for v in row], score=len(cols),
                          id_guess=id_guess, fuzzy=fuzzy)
    if best is None:
        return Header()
    best.missing = [k for k in REQUIRED_FIELDS if k not in best.cols]
    best.ok = not best.missing
    return best


def column_has_content(ws, header, col):
    """True if any row below the header has something in this column."""
    return any(clean(r[col]) for r in ws.iter_rows(min_row=header.row + 1, values_only=True) if col < len(r))


def fix_swapped_type_author(ws, header, notes):
    """Some sources put 'Author' over the Type data and 'Type' over the author names (Required Documents). Trust the data."""
    cols = header.cols
    if cols.get("type") is None or cols.get("author") is None:
        return
    looks_like_type = re.compile(r"\s*(manual|automat)", re.I)
    under_type = under_author = 0
    for row in ws.iter_rows(min_row=header.row + 1, max_row=header.row + 40, values_only=True):
        under_type += bool(row[cols["type"]] and looks_like_type.match(str(row[cols["type"]])))
        under_author += bool(row[cols["author"]] and looks_like_type.match(str(row[cols["author"]])))
    if under_author > under_type and under_author >= 3:
        cols["type"], cols["author"] = cols["author"], cols["type"]
        notes.append(f"{ws.title}: the 'Type' and 'Author' headers look swapped in the source (Manual/Automated sits under "
                     f"'Author'); used the data, not the headers")
