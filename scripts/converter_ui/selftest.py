"""A check that runs the real window hidden: build it, dry-run every document, print the result, quit. Writes no workbooks.

Used after building the exe. A windowed exe has no console, so --selftest-out <file> writes the output to a file instead:
    ADO_Test_Converter.exe --selftest-out result.txt [--force] <To Convert folder> <Converted to ADO folder>
"""
import contextlib
import io
import sys
import time
import traceback
from tkinter import messagebox

from .app import App


def selftest(argv):
    """Build the window hidden, dry-run every document, print the result and quit. `argv` = [source folder, imports folder]."""
    messagebox.showerror = lambda *a, **k: print("ERROR DIALOG:", *a)       # never open a dialog nobody can see
    messagebox.showinfo = lambda *a, **k: print("INFO DIALOG:", *a)
    app = App()
    app.withdraw()
    if len(argv) >= 2:
        app.folders.source.set(argv[0])
        app.folders.imports.set(argv[1])
        app.refresh()
    app.files.tick("all")
    app.start(True, "--force" in sys.argv)
    started = time.time()
    while app.busy and time.time() - started < 600:
        app.update()
        time.sleep(0.05)
    rows = list(app.rows.values())
    print(f"selftest: {len(app.files.names())} listed, {len(rows)} results, {sum(r.failed for r in rows)} failed, "
          f"status line: {app.status.cget('text')}")
    if rows:
        app.results.select(rows[0].source)
        app.show_selected_result()
        print("detail text starts:", app.details.text.get("1.0", "1.4"), "...")
    app.destroy()


def selftest_to_file(argv):
    """--selftest-out <file> ...: write the self-test output to a file (a windowed exe has no console)."""
    out_path = argv[argv.index("--selftest-out") + 1]
    folders = [a for a in argv if not a.startswith("--") and a != out_path]
    buffer = io.StringIO()
    try:
        with contextlib.redirect_stdout(buffer):
            selftest(folders)
    except Exception:
        buffer.write(traceback.format_exc())
    with open(out_path, "w", encoding="utf-8") as fh:
        fh.write(buffer.getvalue())
