"""Where things are, whether the window runs from the scripts or from the packaged exe, and opening files and folders."""
import os
import subprocess
import sys
from tkinter import messagebox

from converter import settings

FROZEN = getattr(sys, "frozen", False)                     # True when running as the packaged .exe
HERE = os.path.dirname(sys.executable) if FROZEN else settings.SCRIPTS_DIR
ROOT = HERE if FROZEN else settings.PROJECT_DIR            # the To Convert, Converted to ADO and reports folders sit here
DEFAULT_FOLDERS = dict(source=settings.SOURCE_DIRNAME, imports=settings.IMPORTS_DIRNAME, reports=settings.REPORTS_DIRNAME)
SETTINGS_FILE = os.path.join(HERE, "gui_settings.json")    # next to the exe, or in scripts/ when run from the scripts


def open_path(path):
    """Open a file or folder with whatever the operating system uses."""
    if not os.path.exists(path):
        messagebox.showinfo("Not found", f"Nothing to open yet:\n{path}")
        return
    if hasattr(os, "startfile"):
        os.startfile(path)                                 # Windows
    else:
        subprocess.Popen(["open" if sys.platform == "darwin" else "xdg-open", path])
