"""Review notes for a defect export: what someone has to look at before importing Bugs into ADO.

Same convention as converter/checks.py: each check takes the list of Defects plus the Header and returns one note or None,
and CHECKS is the order the notes appear in. Add a check by writing a function and putting it in the table.

The first three checks are the ones that matter most while mapping.py is still empty: they list exactly which ALM values
have no ADO value yet.
"""
from collections import Counter

from converter.text import list_for_note

from . import mapping
from .mapping import IDENTITIES, PRIORITY_FROM_ALM, SEVERITY_FROM_ALM, STATE_FROM_ALM, mapped


def _unmapped_values(defects, attribute, table):
    """{ALM value: how many defects have it} for the values that are not in `table`."""
    counts = Counter()
    for defect in defects:
        value = getattr(defect, attribute)
        if value and mapped(table, value) is None:
            counts[value] += 1
    return counts


def _unmapped_states(defects, header):
    counts = _unmapped_values(defects, "status", STATE_FROM_ALM)
    if counts:
        return (f"ALM status(es) with no ADO state: {dict(counts)}; State is blank for those Bugs. Fill STATE_FROM_ALM in "
                f"defects/mapping.py (and remember an imported item starts in the type's initial state anyway)")


def _unmapped_severities(defects, header):
    counts = _unmapped_values(defects, "severity", SEVERITY_FROM_ALM)
    if counts:
        return f"ALM severity(ies) with no ADO value: {dict(counts)}; fill SEVERITY_FROM_ALM in defects/mapping.py"


def _unmapped_priorities(defects, header):
    counts = _unmapped_values(defects, "priority", PRIORITY_FROM_ALM)
    if counts:
        return f"ALM priority(ies) with no ADO value: {dict(counts)}; fill PRIORITY_FROM_ALM in defects/mapping.py"


def _unknown_people(defects, header):
    names = sorted({d.assigned_to for d in defects if d.assigned_to and mapped(IDENTITIES, d.assigned_to) is None})
    if names:
        return (f"{len(names)} ALM user name(s) with no ADO identity: {list_for_note(names)}; those Bugs are imported "
                f"unassigned. An identity ADO does not know fails the import, so add them to IDENTITIES as "
                f"'Display Name <email>'")


def _missing_titles(defects, header):
    names = [d.label for d in defects if not d.title]
    if names:
        return f"defect(s) with no summary: {list_for_note(names)}; ADO needs a Title, so a placeholder was written"


def _shortened_titles(defects, header):
    names = [d.label for d in defects if d.title_full]
    if names:
        return f"summary too long for a Title and shortened for: {list_for_note(names)} (the full text is in System Info)"


def _duplicate_ids(defects, header):
    counts = Counter(d.defect_id for d in defects if d.defect_id)
    repeated = sorted(value for value, count in counts.items() if count > 1)
    if repeated:
        return f"ALM defect ID(s) appearing more than once: {list_for_note(repeated)}"


def _import_rounds(defects, header):
    limit = mapping.MAX_ROWS_PER_IMPORT
    if len(defects) > limit:
        files = -(-len(defects) // limit)
        return (f"{len(defects)} defects is over ADO's {limit}-per-import limit, so they are split into {files} files "
                f"that have to be imported and saved one at a time")


# in the order the notes should appear
CHECKS = (_unmapped_states, _unmapped_severities, _unmapped_priorities, _unknown_people, _missing_titles,
          _shortened_titles, _duplicate_ids, _import_rounds)


def review_notes(defects, header):
    """Every note for one export sheet, in CHECKS order."""
    return [note for note in (check(defects, header) for check in CHECKS) if note]
