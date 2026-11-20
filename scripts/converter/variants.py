"""One sheet of the import workbook that will be built from a source sheet."""
from dataclasses import dataclass, field
from typing import Optional

from .headers import Header


@dataclass
class Variant:
    """A source sheet can give one import sheet ("Import") or several: an EN and an FR sheet when the source has English and
    French expected results, or one per language sheet in an older two-sheet layout. Each of those is a Variant."""
    name: str                          # name of the import sheet, e.g. "EN Import"
    tag: str                           # how review notes refer to it, e.g. "EN" or "Sheet1 (FR)"
    ws: object                         # the openpyxl worksheet it is read from
    header: Header                     # the header row found on that sheet
    src_sheet: str                     # name of the source sheet
    prefix: str                        # start of the file names of the pictures saved for this variant
    exp_key: str = "exp"               # which column holds the expected result: "exp" or "exp_fr"
    skip_cols: tuple = ()              # the other language's expected-result column (not an "extra" column, not a picture)
    first: bool = True                 # False for the second variant read from the same sheet (its notes would repeat)
    variant_note: Optional[str] = None  # a line added to each Description, e.g. the expected result language
    cases: list = field(default_factory=list)      # the Case records, filled in by read_cases
