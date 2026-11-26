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


def migrate_defect(defect, alm_session, ado_session, area_path, ledger=None, with_attachments=True):
    """Create one Bug from one ALM defect, attachments and all. Never raises: returns a Migrated either way."""
    alm_id = str(defect.get("id"))
    started = time.perf_counter()
    result = Migrated(alm_id=alm_id, unmapped=unmapped_values(defect))
    if ledger is not None and alm_id in ledger:
        result.skipped = f"already migrated as work item {ledger.entries[alm_id].get('work_item_id')}"
        return result
    try:
        urls = []
        if with_attachments and str(defect.get("attachment", "")).upper() == "Y":
            for item in alm_session.attachments(alm_id):
                name = item.get("name")
                data = alm_session.fetch_attachment(alm_id, name)
                result.files += 1
                result.bytes += len(data)
                url = ado_session.upload_attachment(name, data)
                if url:
                    urls.append(url)
        fields = mapping.bug_fields_from_alm(defect, area_path, ado_session.config.alm_id_field)
        result.work_item_id = ado_session.create_bug(fields, urls, comment=f"Attached to ALM defect {alm_id}")
        if ledger is not None and not ado_session.dry_run:
            ledger.record(alm_id, result.work_item_id, result.files, result.bytes)
    except (AlmError, AdoError) as e:
        result.failed = str(e)
    except Exception as e:                   # one bad defect must never stop a run of thousands
        result.failed = f"{type(e).__name__}: {e}"
    result.seconds = time.perf_counter() - started
    return result


def migrate(defects, alm_session, ado_session, area_path, ledger=None, progress=None, with_attachments=True):
    """Migrate each defect in turn. `progress(index, total, result)` is called after each one."""
    defects = list(defects)
    results = []
    for index, defect in enumerate(defects, 1):
        result = migrate_defect(defect, alm_session, ado_session, area_path, ledger, with_attachments)
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
