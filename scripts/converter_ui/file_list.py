"""The tick list of documents in the To Convert folder."""
import os
from tkinter import ttk

from converter.batch import existing_versions, source_files

from .widgets import make_tree

CHECK, UNCHECK = "[x]", "[ ]"
NOT_CONVERTED = "Not converted yet"


class FileList(ttk.LabelFrame):
    """Shows each document with a tick box and whether it has been converted. Click the [ ] to tick or untick."""

    def __init__(self, parent, get_source_dir, get_imports_dir, set_status):
        super().__init__(parent, text="1. Documents in the To Convert folder (click [ ] to tick or untick)")
        self.get_source_dir, self.get_imports_dir, self.set_status = get_source_dir, get_imports_dir, set_status
        bar = ttk.Frame(self)
        bar.pack(fill="x", padx=4, pady=2)
        for text, command in (("Select all", lambda: self.tick("all")), ("Select none", lambda: self.tick("none")),
                              ("Select not converted yet", lambda: self.tick("new")), ("Refresh list", self.refresh)):
            ttk.Button(bar, text=text, command=command).pack(side="left", padx=2)
        self.tree = make_tree(self, ("sel", "file", "status"), ("", "Document", "Status"), (40, 560, 260), height=6)
        self.tree.column("sel", anchor="center", stretch=False)
        self.tree.bind("<Button-1>", self._on_click)

    def _status_of(self, name):
        if not name.lower().endswith(".xlsx"):
            return "Not an .xlsx file"
        versions = existing_versions(self.get_imports_dir(), name)
        return f"Converted (V{max(versions)})" if versions else NOT_CONVERTED

    def refresh(self):
        """Re-read the folder, keeping the ticks the person already set."""
        previous = {item: self.tree.set(item, "sel") for item in self.tree.get_children()}
        self.tree.delete(*self.tree.get_children())
        folder = self.get_source_dir()
        if not os.path.isdir(folder):
            self.set_status("The To Convert folder does not exist.")
            return
        for name in source_files(folder):
            status = self._status_of(name)
            tick = previous.get(name, CHECK if status == NOT_CONVERTED else UNCHECK)
            self.tree.insert("", "end", iid=name, values=(tick, name, status))
        self.set_status(f"{len(self.tree.get_children())} file(s) in the To Convert folder.")

    def _on_click(self, event):
        if self.tree.identify_region(event.x, event.y) == "cell" and self.tree.identify_column(event.x) == "#1":
            item = self.tree.identify_row(event.y)
            if item:
                self.tree.set(item, "sel", UNCHECK if self.tree.set(item, "sel") == CHECK else CHECK)
            return "break"

    def tick(self, mode):
        """mode: 'all', 'none' or 'new' (only the documents not converted yet)."""
        for item in self.tree.get_children():
            on = mode == "all" or (mode == "new" and self.tree.set(item, "status") == NOT_CONVERTED)
            self.tree.set(item, "sel", CHECK if on else UNCHECK)

    def names(self):
        return list(self.tree.get_children())

    def selected(self):
        return [item for item in self.tree.get_children() if self.tree.set(item, "sel") == CHECK]
