"""The rows at the top of the window: the three folders and the ADO Area Path."""
import os
import tkinter as tk
from tkinter import filedialog, ttk

from converter import area

from . import settings_store
from .paths import ROOT


class FolderBar(ttk.Frame):
    """Folder pickers (To Convert, Converted to ADO, Reports) and the Area Path row.
    The values are the StringVars `source`, `imports`, `reports` and `area` (the editable part after the fixed root)."""

    def __init__(self, parent, saved, on_folder_chosen):
        super().__init__(parent)
        self.on_folder_chosen = on_folder_chosen
        self.source, self.imports, self.reports = (tk.StringVar(value=settings_store.remembered_folder(saved, key))
                                                   for key in ("source", "imports", "reports"))
        for var in (self.source, self.imports, self.reports):     # first run next to a fresh exe: make the default folders
            if var.get().startswith(ROOT):
                os.makedirs(var.get(), exist_ok=True)
        self.area = tk.StringVar(value=settings_store.remembered_area_rest(saved))
        self._build()

    def _build(self):
        pad = dict(padx=8, pady=3)
        self.columnconfigure(1, weight=1)
        folders = (("To Convert folder", self.source), ("Converted to ADO folder", self.imports),
                   ("Reports folder", self.reports))
        for row, (label, var) in enumerate(folders):
            ttk.Label(self, text=label).grid(row=row, column=0, sticky="w", **pad)
            ttk.Entry(self, textvariable=var).grid(row=row, column=1, sticky="ew", **pad)
            ttk.Button(self, text="Browse...", command=lambda v=var: self._browse(v)).grid(row=row, column=2, **pad)
        ttk.Label(self, text="ADO Area Path").grid(row=3, column=0, sticky="w", **pad)
        area_box = ttk.Frame(self)
        area_box.grid(row=3, column=1, sticky="ew", **pad)
        area_box.columnconfigure(1, weight=1)
        ttk.Label(area_box, text=area.ROOT + " \\", relief="sunken", padding=(6, 2)).grid(row=0, column=0, sticky="ns")
        ttk.Entry(area_box, textvariable=self.area).grid(row=0, column=1, sticky="ew")
        ttk.Label(self, text="the part after the fixed root; blank = the root only.\nMust already exist in ADO.").grid(
            row=3, column=2, sticky="w", **pad)

    def _browse(self, var):
        folder = filedialog.askdirectory(initialdir=var.get() or ROOT)
        if folder:
            var.set(os.path.normpath(folder))
            self.on_folder_chosen()

    def full_area_path(self):
        """Tidy what was typed in the box (shown back to the person) and return the full Area Path for this run.
        A blank box means the root only, not the configured default."""
        self.area.set(area.tidy(self.area.get()))
        return area.compose(self.area.get())
