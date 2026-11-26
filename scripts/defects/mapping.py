"""ALM values -> ADO values, and the columns of the Bug CSV.

THIS IS THE FILE TO FILL IN, and it cannot be guessed: the field names and the allowed values come from the process
template of our ADO project. To get them, create one Bug in ADO by hand, export it (Boards > Work Items > the view's
"Export to CSV"), and read the header row and the drop-down values. Then:

  * put the exact CSV column names in BUG_COLUMNS, in the order you want them in the file;
  * fill the three value maps below with every ALM value that appears in the export (the review report lists the ones
    that are still missing, so a first run tells you what to add).

An unmapped value is never invented: it comes out blank and the report says which defects were affected.

Known facts about the native CSV import, from Microsoft Learn (checked Nov 20, 2026; worth confirming against our own
project, because process templates differ):
  * "Work Item Type" and "Title" are required, and an "ID" column must NOT be filled in for new items (a filled ID means
    "update the item with this ID");
  * at most MAX_ROWS_PER_IMPORT items per import;
  * imported items arrive in the type's initial state (New for a Bug), so a closed ALM defect does not import as closed:
    STATE_FROM_ALM is what you would set afterwards (a bulk edit, or the REST API), not something the CSV will honour;
  * identity fields (Assigned To) must match an existing user exactly, as "Display Name <email>";
  * HTML fields (Repro Steps, System Info, Description) keep their markup, so line breaks have to be <p> or <br/>;
  * the imported items are not saved until "Save items" is clicked.
"""

MAX_ROWS_PER_IMPORT = 1000               # ADO's limit for one CSV import

# The CSV columns, in order. Column 1 must stay "Work Item Type" and column 2 "Title". The rest are the usual Bug fields:
# CHECK EVERY NAME against a Bug exported from our own project before a real import.
BUG_COLUMNS = ("Work Item Type", "Title", "Assigned To", "State", "Area Path", "Severity", "Priority", "Repro Steps",
               "System Info", "Tags")

WORK_ITEM_TYPE = "Bug"

# ALM status -> ADO Bug state. STILL EMPTY, and it is NOT used when a work item is created: proved by test on
# 2026-11-25 that a Bug is always created in its type's initial state, and ADO refuses to save one staged as anything
# else. So this map is for the second pass -- a bulk edit over the migrated bugs, grouped by their ALM-status tag --
# and its values have to come from our own process template. ALM's eleven statuses, and how many defects had each:
#   Closed 25,627 | Rejected 1,037 | Ready For Retest 244 | Assigned 227 | Deferred 200 | New 136 | Fixed 85
#   Need More Info 57 | Re-Opened 22 | Open 4 | In Progress 4
STATE_FROM_ALM = {}

# ALM severity -> ADO severity. Read off the real data: ALM uses exactly four values and they line up one to one.
SEVERITY_FROM_ALM = {"1-Critical": "1 - Critical", "2-High": "2 - High", "3-Medium": "3 - Medium",
                     "4-Low": "4 - Low"}

# ALM priority -> ADO priority. ALM uses three values; ADO's Priority is a number.
PRIORITY_FROM_ALM = {"1-Must Have": "1", "2-Should Have": "2", "3-Want to Have": "3"}

# ALM user name -> "Display Name <email>" of the matching ADO user. Anyone not in here is left unassigned, because an
# identity ADO does not know fails the whole import.
IDENTITIES = {}


def mapped(table, value):
    """A value from a map, or None when the map has no entry for it (blank in the CSV, named in the review notes)."""
    if value is None:
        return None
    return table.get(str(value).strip()) or table.get(str(value).strip().lower())


def tags_for(defect):
    """Tags that keep the ALM provenance on the work item, so an imported Bug can always be traced back.

    Tags are semicolon-separated in the CSV. Keeping the ALM ID and status here means no information is lost even while
    STATE_FROM_ALM is empty and every item imports as New."""
    tags = [f"ALM-{defect.defect_id}" if defect.defect_id else "ALM-no-id", "migrated-from-ALM"]
    if defect.status:
        tags.append(f"ALM-status-{defect.status}")
    return ";".join(tags)


# --- from ALM's REST fields to a Bug -------------------------------------------------------------------------------
# The names on the left are ALM's internal field names (see DEFECT_FIELDS in alm.py), not the headings in an Excel
# export. The names on the right are Azure DevOps reference names, which are what the REST API wants.
BUG_REFERENCE_NAMES = {
    "title": "System.Title",
    "area_path": "System.AreaPath",
    "repro_steps": "Microsoft.VSTS.TCM.ReproSteps",
    "system_info": "Microsoft.VSTS.TCM.SystemInfo",
    "severity": "Microsoft.VSTS.Common.Severity",
    "priority": "Microsoft.VSTS.Common.Priority",
    "found_in": "Microsoft.VSTS.Build.FoundIn",
    "integration_build": "Microsoft.VSTS.Build.IntegrationBuild",
    "tags": "System.Tags",
}

# Everything ALM had that ADO has no field of its own for goes into System Info, so nothing is lost in the move.
SYSTEM_INFO_LINES = (
    ("ALM defect ID", "id"), ("ALM status", "status"), ("ALM resolution", "user-03"),
    ("Defect type", "user-04"), ("Detected by", "detected-by"), ("Detected on date", "creation-time"),
    ("Closing date", "closing-date"), ("Modified date", "last-modified"),
    ("Detected in release", "detected-in-rel"), ("Detected in build", "detection-version"),
    ("Test phase", "user-05"), ("Test environment", "user-06"), ("Module", "user-12"),
    ("Language", "user-11"), ("Project", "user-01"), ("Fix details", "user-25"),
)

TITLE_LIMIT = 255                    # ADO's System.Title


def tags_from_alm(defect):
    """Tags that keep the ALM provenance on the Bug, and group it for the state edit that follows a migration."""
    tags = ["migrated-from-ALM"]
    if defect.get("status"):
        tags.append(f"ALM-status-{defect['status']}")
    if defect.get("user-04"):
        tags.append(f"ALM-type-{defect['user-04']}")
    return "; ".join(tags)


def bug_fields_from_alm(defect, area_path, alm_id_field="", title_limit=TITLE_LIMIT):
    """One ALM defect (as alm.fields_of returns it) -> {ADO reference name: value}, ready for a JSON Patch.

    Nothing is invented: a value with no mapping is left out, and the caller reports it. State is never set, because a
    work item cannot be created in anything but its type's initial state."""
    names = BUG_REFERENCE_NAMES
    title = (defect.get("name") or f"(no summary in ALM, defect {defect.get('id')})").strip()
    full_title = title if len(title) > title_limit else None
    if full_title:
        title = title[:title_limit - 3].rsplit(" ", 1)[0] + "..."

    lines = [f"{label}: {defect[key]}" for label, key in SYSTEM_INFO_LINES if defect.get(key)]
    if full_title:
        lines.append(f"Full ALM summary: {full_title}")

    fields = {
        names["title"]: title,
        names["area_path"]: area_path,
        names["repro_steps"]: defect.get("description") or "",
        names["system_info"]: "<br/>".join(lines),
        names["severity"]: mapped(SEVERITY_FROM_ALM, defect.get("severity")) or "",
        names["priority"]: mapped(PRIORITY_FROM_ALM, defect.get("priority")) or "",
        names["found_in"]: defect.get("detection-version") or "",
        names["integration_build"]: defect.get("closing-version") or "",
        names["tags"]: tags_from_alm(defect),
    }
    if alm_id_field and defect.get("id"):
        fields[alm_id_field] = defect["id"]
    return {name: value for name, value in fields.items() if value not in (None, "")}
