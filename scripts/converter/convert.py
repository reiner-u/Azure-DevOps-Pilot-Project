"""Converting one source workbook into one import workbook, start to finish.

The steps, in order (each lives in its own module):
  1. load the workbook and its pictures                         (images)
  2. decide which sheets to read and which import sheets to build (planning)
  3. read every case                                             (cases)
  4. collect review notes                                        (checks)
  5. save the pictures next to the import workbook               (AttachmentStore, below)
  6. write the workbook and put the sensitivity label on it      (writer, label)
A dry run stops after step 4 and writes nothing.
"""
import os
import re
from dataclasses import dataclass, field
from typing import Optional

import openpyxl

from . import area as area_path
from . import settings
from .cases import read_cases
from .checks import read_declared_counts, review_notes
from .images import extract_images
from .label import label_bytes, save_workbook
from .planning import NotATestDocument, column_map, plan_variants
from .text import slug
from .writer import write_read_me, write_sheet


@dataclass
class ConversionInfo:
    """What a conversion produced (or, for a dry run, would produce)."""
    variants: list
    notes: list                        # review notes
    out: str                           # path of the import workbook
    legacy: bool                       # the older EN / FR two-sheet layout
    sheets: list                       # names of the source sheets that were read
    column_map: str                    # which source column was used for what
    label: Optional[bool] = None       # whether the sensitivity label was added (None for a dry run)


class AttachmentStore:
    """Saves pictures in attachments/<workbook name>/ next to the import workbook and hands back their relative paths."""

    def __init__(self, out_path):
        self.folder = os.path.join(os.path.dirname(os.path.abspath(out_path)), "attachments",
                                   os.path.splitext(os.path.basename(out_path))[0])

    def save(self, file_name, data):
        os.makedirs(self.folder, exist_ok=True)
        with open(os.path.join(self.folder, file_name), "wb") as fh:
            fh.write(data)
        return f"attachments/{os.path.basename(self.folder)}/{file_name}"

    def save_case_pictures(self, variant):
        """Save the pictures of every case of a variant and remember where (case.image_files, case.other_files)."""
        for case in variant.cases:
            base = f"{variant.prefix}_{slug(case.scenario_id, 120) if case.scenario_id else 'row' + str(case.row)}"
            many = len(case.images) > 1
            case.image_files = [self.save(f"{base}{'_' + str(n) if many else ''}.{ext}", data)
                                for n, (data, ext) in enumerate(case.images, 1)]
            many = len(case.other_images) > 1
            case.other_files = []
            for n, (column, data, ext) in enumerate(case.other_images, 1):
                column_slug = re.sub(r"[^a-z0-9]+", "_", column.lower()).strip("_")
                case.other_files.append((column, self.save(f"{base}_{column_slug}{'_' + str(n) if many else ''}.{ext}", data)))

    def save_reference_pictures(self, pictures):
        """Pictures on sheets that are not test sheets (e.g. screenshots in a notes sheet)."""
        for n, (sheet, data, ext) in enumerate(pictures, 1):
            self.save(f"reference_sheet_{slug(sheet, 30)}_{n}.{ext}", data)


def convert(src, out, feature, label_from=None, dry_run=False, area=None):
    """Convert one source workbook. Returns a ConversionInfo with what was built and the review notes.
    `area` is the full ADO Area Path to write on every case (default: the configured one)."""
    area = area or area_path.DEFAULT
    source_wb = openpyxl.load_workbook(src)
    pictures, unanchored = extract_images(src)
    notes = []
    plan = plan_variants(source_wb, notes)
    if not plan.variants:
        raise NotATestDocument(_no_test_sheet_message(plan.diagnostics))
    for variant in plan.variants:
        variant.cases = read_cases(variant, pictures.get(variant.src_sheet, []), notes)

    used_sheets = {v.src_sheet for v in plan.variants}
    reference_pictures = [(sheet, data, ext) for sheet, found in pictures.items() if sheet not in used_sheets
                          for (_, _, data, ext) in found]
    notes += review_notes(plan.variants, read_declared_counts(src), plan.legacy, sum(unanchored.values()))
    if area == area_path.PLACEHOLDER:
        notes.append("Area Path is still the placeholder 'Project\\Area\\Path': copy scripts/local_config.example.json to "
                     "local_config.json and set area_root and area_rest, then convert again")
    if reference_pictures:
        names = sorted({sheet for sheet, _, _ in reference_pictures})
        notes.append(f"{len(reference_pictures)} picture(s) on non-test sheet(s) {names} saved to attachments/ as reference "
                     f"screenshots; attach where they belong")
    info = ConversionInfo(variants=plan.variants, notes=notes, out=out, legacy=plan.legacy, sheets=sorted(used_sheets),
                          column_map=column_map(plan.variants))
    if dry_run:
        return info

    store = AttachmentStore(out)
    for variant in plan.variants:
        store.save_case_pictures(variant)
    store.save_reference_pictures(reference_pictures)

    has_pictures = (any(c.images or c.other_images for v in plan.variants for c in v.cases) or bool(reference_pictures))
    workbook = openpyxl.Workbook()
    write_read_me(workbook, feature, os.path.basename(src), plan.variants, plan.legacy, plan.bilingual, has_pictures,
                  area, settings.STATE)
    for variant in plan.variants:
        write_sheet(workbook, variant.name, variant.cases, area, settings.STATE)
    label_data = label_bytes(label_from, src)
    save_workbook(workbook, out, label_data)
    info.label = bool(label_data)
    return info


def _no_test_sheet_message(diagnostics):
    shown = diagnostics[:4] + ([f"... and {len(diagnostics) - 4} more sheet(s)"] if len(diagnostics) > 4 else [])
    return ("no test sheet recognised (if this IS a test document, send this message and the document to the person who "
            "maintains the tool). Sheets looked at: " + ("; ".join(shown) if shown else "none"))
