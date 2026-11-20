"""Runs a conversion on a background thread so the window stays responsive, and reports back through a queue.

Messages, in the order they arrive:
    ("row", i, n, report_row)       one file finished
    ("done", rows, report_path, dry_run)
    ("error", traceback_text)       something unexpected went wrong
"""
import queue
import threading
import traceback

from converter.batch import run_all, write_report
from converter.label import first_labelled_workbook


class ConversionRunner:
    def __init__(self):
        self.messages = queue.Queue()

    def start(self, source, imports, reports, names, dry_run, force, area):
        args = (source, imports, reports, names, dry_run, force, area)
        threading.Thread(target=self._work, args=args, daemon=True).start()

    def pending(self):
        """Yield every message that has arrived and not been handled yet."""
        try:
            while True:
                yield self.messages.get_nowait()
        except queue.Empty:
            return

    def _work(self, source, imports, reports, names, dry_run, force, area):
        try:
            label = first_labelled_workbook(imports)
            rows = run_all(source, imports, force, dry_run, label, only=set(names), area=area,
                           progress=lambda i, n, row: self.messages.put(("row", i, n, row)))
            report_path = None if dry_run or not rows else write_report(rows, reports)
            self.messages.put(("done", rows, report_path, dry_run))
        except Exception:
            self.messages.put(("error", traceback.format_exc()))
