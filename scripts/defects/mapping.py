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

# ALM status -> ADO Bug state. EMPTY ON PURPOSE: fill from the template's allowed states.
# A typical Agile-template mapping looks like {"New": "New", "Open": "Active", "Fixed": "Resolved", "Closed": "Closed",
# "Rejected": "Closed", "Reopened": "Active"}, but ours may differ, and see the note about the initial state above.
STATE_FROM_ALM = {}

# ALM severity -> ADO severity (Agile template offers "1 - Critical", "2 - High", "3 - Medium", "4 - Low").
SEVERITY_FROM_ALM = {}

# ALM priority -> ADO priority (Agile template offers 1, 2, 3, 4 as numbers).
PRIORITY_FROM_ALM = {}

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
