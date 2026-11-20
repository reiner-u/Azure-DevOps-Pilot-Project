"""The results table and the Details box."""
import tkinter as tk
from tkinter import ttk

from .widgets import make_tree


class ResultsTable(ttk.LabelFrame):
    """One row per document after a run. Red = failed or skipped, yellow = has review notes."""

    def __init__(self, parent, on_select):
        super().__init__(parent, text="2. Results (red = failed or skipped, yellow = has review notes; click a row for details)")
        self.tree = make_tree(self, ("file", "out", "status", "cases", "steps", "review"),
                              ("Document", "Import file built", "Status", "Cases", "Steps/case", "Review"),
                              (250, 280, 160, 150, 70, 60), height=8)
        self.tree.tag_configure("review", background="#fff3c4")
        self.tree.tag_configure("bad", background="#f8cfcf")
        self.tree.bind("<<TreeviewSelect>>", lambda _event: on_select())

    def clear(self):
        self.tree.delete(*self.tree.get_children())

    def add(self, row):
        tag = ("bad",) if row.failed or row.skipped else (("review",) if row.needs_review else ())
        review = "yes" if row.needs_review else ("no" if row.review else "")
        self.tree.insert("", "end", iid=row.source, tags=tag,
                         values=(row.source, row.import_file, row.status[:60], row.cases, row.steps_per_case, review))

    def selected_source(self):
        """File name of the selected row, or None."""
        selection = self.tree.selection()
        return selection[0] if selection else None

    def select(self, source):
        self.tree.selection_set(source)


class DetailsBox(ttk.LabelFrame):
    """Read-only text about the selected result: status, sheets and columns used, review notes."""

    def __init__(self, parent):
        super().__init__(parent, text="3. Details for the selected result")
        self.text = tk.Text(self, height=9, wrap="word", state="disabled", font=("Segoe UI", 9))
        scrollbar = ttk.Scrollbar(self, command=self.text.yview)
        self.text.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        self.text.pack(fill="both", expand=True, padx=4, pady=4)

    def show(self, content):
        self.text.config(state="normal")
        self.text.delete("1.0", "end")
        self.text.insert("1.0", content)
        self.text.config(state="disabled")
