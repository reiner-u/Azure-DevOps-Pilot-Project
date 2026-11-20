"""The window's texts (no window needed) and, where tkinter and a screen exist, a hidden-window run of the real thing."""
import os
import tempfile
import time
import unittest

import _paths  # noqa: F401
import fixtures
from converter.batch import ReportRow
from converter_ui import summaries

try:
    import tkinter
    tkinter.Tk().destroy()
    HAVE_TK = True
except Exception:                       # no tkinter installed, or no display to open a window on
    HAVE_TK = False


class Texts(unittest.TestCase):
    def test_details_for_a_row_with_notes(self):
        row = ReportRow("Doc.xlsx", import_file="Doc_V1.xlsx", status="built", sheets_used="Cases", column_map="Cases: id='ID'",
                        notes="first note | second note", review="yes")
        self.assertEqual(summaries.result_details(row).splitlines(), [
            "Document: Doc.xlsx", "Status: built", "Import file: Doc_V1.xlsx", "Sheets read: Cases",
            "Columns used: Cases: id='ID'", "", "Review notes:", "  - first note", "  - second note"])

    def test_details_for_a_row_without_notes_or_output(self):
        row = ReportRow("Doc.xlsx", status="skipped: not an .xlsx file")
        self.assertEqual(summaries.result_details(row).splitlines(),
                         ["Document: Doc.xlsx", "Status: skipped: not an .xlsx file", "", "No review notes."])

    def test_run_summary(self):
        rows = [ReportRow("a", status="built", review="no"), ReportRow("b", status="built", review="yes"),
                ReportRow("c", status="skipped: x", review="yes"), ReportRow("d", status="FAILED: y", review="yes")]
        self.assertEqual(summaries.run_summary(rows, os.path.join("x", "conversion_report_1.csv"), False),
                         "2 built, 1 skipped, 1 failed, 3 need review. Report saved in conversion_report_1.csv.")
        self.assertEqual(summaries.run_summary(rows, None, True),
                         "Dry run: 4 checked, nothing written. 1 skipped, 1 failed, 3 need review.")


@unittest.skipUnless(HAVE_TK, "needs tkinter and a screen")
class HiddenWindow(unittest.TestCase):
    def test_dry_run_through_the_real_window(self):
        from converter_ui import settings_store
        from converter_ui.app import App
        with tempfile.TemporaryDirectory() as tmp:
            source, imports, reports = (os.path.join(tmp, n) for n in ("To Convert", "Converted to ADO", "reports"))
            for folder in (source, imports, reports):
                os.makedirs(folder)
            fixtures.simple_document(os.path.join(source, "Login tests.xlsx"), fixtures.case(1, exp=None))
            settings_store.SETTINGS_FILE = os.path.join(tmp, "gui_settings.json")      # do not touch the real settings
            app = App()
            self.addCleanup(app.destroy)
            app.withdraw()
            app.folders.source.set(source)
            app.folders.imports.set(imports)
            app.folders.reports.set(reports)
            app.refresh()
            self.assertEqual(app.files.names(), ["Login tests.xlsx"])
            self.assertEqual(app.files.selected(), ["Login tests.xlsx"])         # not converted yet, so ticked
            app.start(True, False)
            started = time.time()
            while app.busy and time.time() - started < 60:
                app.update()
                time.sleep(0.02)
            self.assertFalse(app.busy)
            self.assertEqual(list(app.rows), ["Login tests.xlsx"])
            self.assertIn("Dry run: 1 checked", app.status.cget("text"))
            app.results.select("Login tests.xlsx")
            app.show_selected_result()
            self.assertIn("blank expected result", app.details.text.get("1.0", "end"))
            self.assertEqual(os.listdir(imports), [])


if __name__ == "__main__":
    unittest.main()
