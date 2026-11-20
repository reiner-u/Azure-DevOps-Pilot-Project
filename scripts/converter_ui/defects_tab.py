"""The ALM Defect Converter tab: ALM defect exports to Azure DevOps Bug work items.

A placeholder for now. The converter itself is not built yet, so the tab only says so.
"""
from tkinter import ttk

TAB_TITLE = "ALM Defect Converter"
PLACEHOLDER_TEXT = "Work in Progress"


class DefectsTab(ttk.Frame):
    def __init__(self, parent):
        super().__init__(parent)
        self.placeholder = ttk.Label(self, text=PLACEHOLDER_TEXT, font=("Segoe UI", 16))
        self.placeholder.pack(expand=True)
