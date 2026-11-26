"""A record of which ALM defects have already been migrated, so a run can be stopped and restarted.

A full migration is roughly 180,000 calls over several hours. Something will fail partway: a session expiring, a
network blip, one bad file. Without a ledger the only options after a failure are to start again (creating thousands
of duplicate bugs) or to work out by hand where it stopped.

The file is JSON Lines, one record per migrated defect, appended as it goes, so a crash cannot lose what came before
it and the file can be read while a run is still going. Azure DevOps itself is the authority -- the ALM ID field on
each Bug -- and this is the fast local copy of that answer; check_against() compares the two.
"""
import json
import os
import time


class Ledger:
    """Which ALM defect IDs are already in Azure DevOps, and as which work item."""

    def __init__(self, path):
        self.path = path
        self.entries = {}
        self._load()

    def _load(self):
        if not os.path.exists(self.path):
            return
        with open(self.path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                except ValueError:
                    continue                      # a half-written last line after a crash: ignore it
                if record.get("alm_id"):
                    self.entries[str(record["alm_id"])] = record

    def __contains__(self, alm_id):
        return str(alm_id) in self.entries

    def __len__(self):
        return len(self.entries)

    def record(self, alm_id, work_item_id, files=0, byte_count=0, note=""):
        """Write one defect down. Appends and flushes, so the line is on disk before the next defect starts."""
        entry = {"alm_id": str(alm_id), "work_item_id": work_item_id, "files": files, "bytes": byte_count,
                 "at": time.strftime("%Y-%m-%d %H:%M:%S"), "note": note}
        self.entries[str(alm_id)] = entry
        os.makedirs(os.path.dirname(os.path.abspath(self.path)), exist_ok=True)
        with open(self.path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry) + "\n")
            fh.flush()
        return entry

    def todo(self, alm_ids):
        """The ones not done yet, in the order given."""
        return [i for i in alm_ids if str(i) not in self.entries]

    def totals(self):
        return {"defects": len(self.entries),
                "files": sum(e.get("files", 0) for e in self.entries.values()),
                "bytes": sum(e.get("bytes", 0) for e in self.entries.values())}

    def check_against(self, in_ado):
        """Compare the ledger with what Azure DevOps actually has: `in_ado` is {alm id: work item id}.

        -> (missing from ADO, missing from the ledger). Both should be empty after a clean run; anything in the first
        list is a defect this ledger claims to have migrated but ADO cannot find."""
        mine, theirs = set(self.entries), set(str(k) for k in in_ado)
        return sorted(mine - theirs), sorted(theirs - mine)
