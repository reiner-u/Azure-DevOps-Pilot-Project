"""One defect at a time, from ALM to an Azure DevOps Bug: the middle of the pipeline.

    ALM REST  ->  this  ->  ADO REST
    (session)     map       (PAT)
                  ledger

Nothing is staged on disk. Each attachment is pulled from ALM into memory and pushed straight to ADO, so a run of
26,570 defects never needs the ~15 GB anywhere: the biggest thing in memory at once is one attachment.

Every run is a dry run unless told otherwise, and every migrated defect is written to the ledger as it finishes, so a
run can be stopped and restarted without creating a single duplicate.
"""
import time
from dataclasses import dataclass, field
from typing import Optional

from . import mapping
from .alm import AlmError
from .ado import AdoError


@dataclass
class Migrated:
    """What happened to one defect."""
    alm_id: str
    work_item_id: Optional[int] = None
    files: int = 0
    bytes: int = 0
    skipped: str = ""                       # why it was not migrated, when it was not
    failed: str = ""
    seconds: float = 0.0
    unmapped: list = field(default_factory=list)    # values ALM had that we have no ADO value for
    fields: dict = field(default_factory=dict)      # what would be written to the Bug, so a dry run can show it
    attachment_names: list = field(default_factory=list)

    @property
    def done(self):
        return bool(self.work_item_id) or (not self.skipped and not self.failed)


def unmapped_values(defect):
    """ALM values this defect carries that no map covers, so the caller can report them rather than lose them."""
    missing = []
    for label, value, table in (("severity", defect.get("severity"), mapping.SEVERITY_FROM_ALM),
                                ("priority", defect.get("priority"), mapping.PRIORITY_FROM_ALM)):
        if value and mapping.mapped(table, value) is None:
            missing.append(f"{label}={value!r}")
    return missing


def migrate_defect(defect, alm_session, ado_session, area_path, ledger=None, with_attachments=True, already=None):
    """Create one Bug from one ALM defect, attachments and all. Never raises: returns a Migrated either way.

    `already` is {alm id: work item id} that Azure DevOps itself reports, or None when it could not be asked.
    When it could be asked it is the authority, in both directions: a defect it has is skipped, and a defect it does
    NOT have is migrated even if the ledger claims otherwise -- which is what happens after someone deletes the work
    items and runs again."""
    alm_id = str(defect.get("id"))
    started = time.perf_counter()
    result = Migrated(alm_id=alm_id, unmapped=unmapped_values(defect))
    if already is not None:
        if alm_id in already:
            result.skipped = f"already in Azure DevOps as work item {already[alm_id]}"
            if ledger is not None and alm_id not in ledger:     # heal a ledger that lost the line
                ledger.record(alm_id, already[alm_id], note="found in Azure DevOps, not in the ledger")
            return result
    elif ledger is not None and alm_id in ledger:               # no way to ask ADO, so the ledger is all we have
        result.skipped = f"already migrated as work item {ledger.entries[alm_id].get('work_item_id')}"
        return result
    try:
        urls, by_name = [], {}
        if with_attachments and str(defect.get("attachment", "")).upper() == "Y":
            for item in alm_session.attachments(alm_id):
                name = item.get("name")
                data = alm_session.fetch_attachment(alm_id, name)
                result.files += 1
                result.bytes += len(data)
                result.attachment_names.append(name)
                url = ado_session.upload_attachment(name, data)
                if url:
                    urls.append(url)
                    by_name[name] = url          # so a picture embedded in the text can point at it
        fields = mapping.bug_fields_from_alm(defect, area_path, ado_session.config.alm_id_field,
                                             image_urls=by_name)
        result.fields = fields
        result.work_item_id = ado_session.create_bug(fields, urls, comment=f"Attached to ALM defect {alm_id}")
        if ledger is not None and not ado_session.dry_run:
            ledger.record(alm_id, result.work_item_id, result.files, result.bytes)
    except (AlmError, AdoError) as e:
        result.failed = str(e)
    except Exception as e:                   # one bad defect must never stop a run of thousands
        result.failed = f"{type(e).__name__}: {e}"
    result.seconds = time.perf_counter() - started
    return result


def already_in_ado(ado_session, defects):
    """Ask Azure DevOps which of these defects it already has, by their ALM ID.

    -> {alm id: work item id}, or None when it cannot be asked at all. The difference matters: an empty answer means
    Azure DevOps has none of them, which is a fact worth acting on, while None means we are flying on the ledger."""
    if not getattr(ado_session.config, "alm_id_field", "") or not ado_session.token:
        return None
    return ado_session.existing_alm_ids([str(d.get("id")) for d in defects if d.get("id")])


def migrate(defects, alm_session, ado_session, area_path, ledger=None, progress=None, with_attachments=True,
            already=None):
    """Migrate each defect in turn. `progress(index, total, result)` is called after each one."""
    defects = list(defects)
    if already is None:
        already = already_in_ado(ado_session, defects)
    results = []
    for index, defect in enumerate(defects, 1):
        result = migrate_defect(defect, alm_session, ado_session, area_path, ledger, with_attachments, already)
        results.append(result)
        if progress:
            progress(index, len(defects), result)
    return results


def summarise(results):
    """The line to print at the end of a run."""
    created = [r for r in results if r.work_item_id]
    failed = [r for r in results if r.failed]
    skipped = [r for r in results if r.skipped]
    return {
        "defects": len(results),
        "created": len(created),
        "failed": len(failed),
        "skipped": len(skipped),
        "files": sum(r.files for r in results),
        "bytes": sum(r.bytes for r in results),
        "seconds": sum(r.seconds for r in results),
        "unmapped": sorted({u for r in results for u in r.unmapped}),
    }
