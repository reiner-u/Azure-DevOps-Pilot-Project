"""The main window: puts the panels together and runs conversions."""
import os
import tkinter as tk
from tkinter import messagebox, ttk

from converter import settings

from . import settings_store, summaries
from .file_list import FileList
from .folder_bar import FolderBar
from .paths import open_path
from .defects_tab import TAB_TITLE as DEFECTS_TAB_TITLE, DefectsTab
from .results import DetailsBox, ResultsTable
from .runner import ConversionRunner


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(f"Test document converter: Excel to Azure DevOps import files (v{settings.TOOL_VERSION})")
        self.geometry(self._size_that_fits(1040, 800))
        self.minsize(760, 520)
        self.runner = ConversionRunner()
        self.busy = False           # True while a conversion is running (buttons disabled, folder list frozen)
        self.rows = {}              # this run's results (ReportRows) by source file name
        self.last_report = None     # path of the report written by the last real run
        self._build()
        self.refresh()
        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self._poll_job = self.after(100, self.poll)

    # ----- layout -----
    def _size_that_fits(self, width, height):
        """The wanted size, capped to the screen. A laptop at 150% reports about 1365x853, and a window taller than
        that puts the bottom row of buttons under the taskbar where nobody finds them."""
        margin_x, margin_y = 60, 110          # window frame, title bar and the taskbar
        width = min(width, self.winfo_screenwidth() - margin_x)
        height = min(height, self.winfo_screenheight() - margin_y)
        return f"{max(width, 760)}x{max(height, 520)}"

    def _build(self):
        """Two tabs: the test case converter, and the ALM defect converter (a placeholder until it is built)."""
        self.tabs = ttk.Notebook(self)
        self.tabs.pack(fill="both", expand=True, padx=4, pady=4)
        page = ttk.Frame(self.tabs)
        self.tabs.add(page, text="Test Case Converter")
        self._build_test_case_page(page)
        self.defects = DefectsTab(self.tabs)
        self.tabs.add(self.defects, text=DEFECTS_TAB_TITLE)

    def _build_test_case_page(self, page):
        """The panels, top to bottom. Pack order is not the same as the order on screen: the footer is packed first,
        against the bottom, so that Tk hands it its space before the three stretching panes get theirs. Packed last it
        was the first thing to be squeezed off a laptop screen, and nobody knew those buttons were there."""
        self.folders = FolderBar(page, settings_store.load(), on_folder_chosen=self._on_folder_chosen)
        self.folders.pack(side="top", fill="x", padx=8, pady=(8, 2))
        self._build_footer(page)
        self.files = FileList(page, self.folders.source.get, self.folders.imports.get, self.set_status)
        self.files.pack(fill="both", expand=True, padx=8, pady=4)
        self._build_action_bar(page)
        self.results = ResultsTable(page, on_select=self.show_selected_result)
        self.results.pack(fill="both", expand=True, padx=8, pady=4)
        self.details = DetailsBox(page)
        self.details.pack(fill="both", expand=True, padx=8, pady=4)

    def _build_action_bar(self, page):
        bar = ttk.Frame(page)
        bar.pack(fill="x", padx=8, pady=2)
        self.buttons = []
        # Both buttons force a new version: a conversion always writes V2, V3... rather than skipping a converted
        # document, so the check button must judge the same files the convert button would build.
        for text, dry_run in (("Check Conversion Compatibility", True), ("Convert selected", False)):
            button = ttk.Button(bar, text=text, command=lambda d=dry_run: self.start(d))
            button.pack(side="left", padx=3)
            self.buttons.append(button)
        self.progress = ttk.Progressbar(bar, length=200)
        self.progress.pack(side="left", padx=10)
        self.status = ttk.Label(bar, text="Ready.")
        self.status.pack(side="left", padx=4)

    def _build_footer(self, page):
        footer = ttk.Frame(page)
        footer.pack(side="bottom", fill="x", padx=8, pady=(2, 8))
        for text, command in (("Open Converted to ADO folder", lambda: open_path(self.folders.imports.get())),
                              ("Open attachments folder (pictures)",
                               lambda: open_path(os.path.join(self.folders.imports.get(), "attachments"))),
                              ("Open latest report", self.open_report),
                              ("Open selected import file", self.open_selected_import)):
            ttk.Button(footer, text=text, command=command).pack(side="left", padx=3)

    # ----- small things -----
    def set_status(self, text):
        self.status.config(text=text)

    def refresh(self):
        if not self.busy:
            self.files.refresh()

    def _on_folder_chosen(self):
        self.save_settings()
        self.refresh()

    def save_settings(self):
        settings_store.save(self.folders.source.get(), self.folders.imports.get(), self.folders.reports.get(),
                            self.folders.area.get())

    def on_close(self):
        if self.busy and not messagebox.askyesno("Still working", "A conversion is running. Close anyway?"):
            return
        self.save_settings()
        self.destroy()

    def destroy(self):
        """Stop the 100 ms poll before the window goes, or Tk complains about a callback on a window that is gone."""
        if getattr(self, "_poll_job", None) is not None:
            self.after_cancel(self._poll_job)
            self._poll_job = None
        super().destroy()

    # ----- running a conversion -----
    def start(self, dry_run):
        """Run the ticked documents. Always a new version (V2, V3...); existing import workbooks are never overwritten."""
        if self.busy:
            return
        names = self.files.selected()
        if not names:
            messagebox.showinfo("Nothing selected", "Tick at least one document first.")
            return
        area_path = self.folders.full_area_path()
        self.save_settings()
        self.busy = True
        for button in self.buttons:
            button.state(["disabled"])
        self.results.clear()
        self.rows = {}
        self.details.show("")
        self.progress.configure(maximum=len(names), value=0)
        self.set_status("Working...")
        self.runner.start(self.folders.source.get(), self.folders.imports.get(), self.folders.reports.get(),
                          names, dry_run, True, area_path)

    def poll(self):
        """Handle what the background thread has reported (runs every 100 ms)."""
        for message in self.runner.pending():
            kind = message[0]
            if kind == "row":
                _, i, n, row = message
                self.rows[row.source] = row
                self.results.add(row)
                self.progress.configure(value=i)
                self.set_status(f"{i} of {n} done...")
            elif kind == "done":
                _, rows, report_path, dry_run = message
                self._finish(rows, report_path, dry_run)
            else:
                self._finish_with_error(message[1])
        self._poll_job = self.after(100, self.poll)

    def _end_run(self):
        self.busy = False
        for button in self.buttons:
            button.state(["!disabled"])
        self.refresh()

    def _finish(self, rows, report_path, dry_run):
        self.last_report = report_path
        self._end_run()
        self.set_status(summaries.run_summary(rows, report_path, dry_run))

    def _finish_with_error(self, traceback_text):
        self._end_run()
        self.set_status("Stopped by an error.")
        messagebox.showerror("Something went wrong", traceback_text[-1500:])

    # ----- details and shortcuts -----
    def selected_row(self):
        source = self.results.selected_source()
        return self.rows.get(source) if source else None

    def show_selected_result(self):
        row = self.selected_row()
        if row:
            self.details.show(summaries.result_details(row))

    def open_report(self):
        path = self.last_report
        if not path:
            try:
                reports = self.folders.reports.get()
                files = sorted(f for f in os.listdir(reports) if f.endswith(".csv"))
                path = os.path.join(reports, files[-1]) if files else None
            except OSError:
                path = None
        if path:
            open_path(path)
        else:
            messagebox.showinfo("No report yet", "A report is written after each real conversion (not after a dry run).")

    def open_selected_import(self):
        row = self.selected_row()
        if row and row.import_file and row.built:
            open_path(os.path.join(self.folders.imports.get(), row.import_file))
        else:
            messagebox.showinfo("Nothing to open", "Select a result row that was built in this session.")
