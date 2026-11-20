"""Small tkinter helpers shared by the window's panels."""
from tkinter import ttk


def make_tree(parent, columns, headings, widths, height):
    """A table (ttk.Treeview) with a scrollbar, packed into `parent`."""
    frame = ttk.Frame(parent)
    frame.pack(fill="both", expand=True, padx=4, pady=2)
    tree = ttk.Treeview(frame, columns=columns, show="headings", height=height, selectmode="browse")
    for column, heading, width in zip(columns, headings, widths):
        tree.heading(column, text=heading)
        tree.column(column, width=width, anchor="w")
    scrollbar = ttk.Scrollbar(frame, command=tree.yview)
    tree.configure(yscrollcommand=scrollbar.set)
    scrollbar.pack(side="right", fill="y")
    tree.pack(fill="both", expand=True)
    return tree
