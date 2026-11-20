#!/usr/bin/env python3
"""Window for the test-document converter (same engine as convert_all.bat, see converter/).

Start it with convert_gui.bat. It needs only Python 3 with tkinter (included with the standard Windows installer) and openpyxl.
  * pick the To Convert and Converted to ADO folders (remembered between runs)
  * tick the documents to convert, then Dry run / Convert selected / New version of selected
  * the results table shows case counts and a review flag; click a row to read its notes and which columns were used
Nothing is changed in the To Convert folder. Existing import versions are never overwritten.

The window's code is in converter_ui/ (see its __init__.py for a map). This file only starts it, and handles the hidden
--selftest options used after building the exe.
"""
import os
import sys
import traceback

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from tkinter import messagebox

from converter_ui.app import App
from converter_ui.selftest import selftest, selftest_to_file


def main(argv):
    if "--selftest-out" in argv:
        selftest_to_file(argv)
    elif "--selftest" in argv:
        selftest([a for a in argv if not a.startswith("--")])
    else:
        try:
            App().mainloop()
        except Exception:
            messagebox.showerror("Could not start", traceback.format_exc()[-1500:])


if __name__ == "__main__":
    main(sys.argv[1:])
