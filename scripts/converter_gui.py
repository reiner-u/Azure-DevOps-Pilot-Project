#!/usr/bin/env python3
"""Window for the test-document converter (same engine as convert_all.bat, see build_import_from_source.py).

Start it with convert_gui.bat. It needs only Python 3 with tkinter (included with the standard Windows installer) and openpyxl.
  * pick the source and imports folders (remembered between runs)
  * tick the documents to convert, then Dry run / Convert selected / New version of selected
  * the results table shows case counts and a review flag; click a row to read its notes and which columns were used
Nothing is changed in source/. Existing import versions are never overwritten.
"""
import json, os, queue, subprocess, sys, threading, traceback
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

FROZEN = getattr(sys, "frozen", False)              # True when running as the packaged .exe
HERE = os.path.dirname(sys.executable) if FROZEN else os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import build_import_from_source as core          # the converter

ROOT = HERE if FROZEN else os.path.dirname(HERE)  # exe: source/imports/reports sit next to the exe
SETTINGS = os.path.join(HERE, "gui_settings.json")
CHECK, UNCHECK = "[x]", "[ ]"


def open_path(path):
    """Open a file or folder with whatever the operating system uses."""
    if not os.path.exists(path):
        messagebox.showinfo("Not found", f"Nothing to open yet:\n{path}")
        return
    if hasattr(os, "startfile"):
        os.startfile(path)                                    # Windows
    else:
        subprocess.Popen(["open" if sys.platform == "darwin" else "xdg-open", path])


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(f"Test document converter: Excel to Azure DevOps import files (v{core.TOOL_VERSION})")
        self.geometry("1040x800")
        self.minsize(820, 640)
        cfg = self.load_settings()
        def pick(key):      # a remembered folder, unless it no longer exists (e.g. the tool was copied to another computer)
            saved = cfg.get(key)
            return saved if saved and os.path.isdir(saved) else os.path.join(ROOT, key)
        self.source, self.imports, self.reports = (tk.StringVar(value=pick(k)) for k in ("source", "imports", "reports"))
        for v in (self.source, self.imports, self.reports):     # first run next to a fresh exe: make the default folders
            if v.get().startswith(ROOT):
                os.makedirs(v.get(), exist_ok=True)
        self.q = queue.Queue()
        self.busy = False
        self.rows = {}              # results by source file name
        self.last_report = None
        self.build()
        self.refresh()
        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self.after(100, self.poll)

    # ----- settings -----
    def load_settings(self):
        try:
            with open(SETTINGS, encoding="utf-8") as fh:
                return json.load(fh)
        except (OSError, ValueError):
            return {}

    def save_settings(self):
        try:
            with open(SETTINGS, "w", encoding="utf-8") as fh:
                json.dump(dict(source=self.source.get(), imports=self.imports.get(), reports=self.reports.get()), fh, indent=1)
        except OSError:
            pass

    def on_close(self):
        if self.busy and not messagebox.askyesno("Still working", "A conversion is running. Close anyway?"):
            return
        self.save_settings()
        self.destroy()

    # ----- layout -----
    def build(self):
        pad = dict(padx=8, pady=3)
        top = ttk.Frame(self)
        top.pack(fill="x", padx=8, pady=(8, 2))
        top.columnconfigure(1, weight=1)
        for r, (label, var) in enumerate((("Source folder", self.source), ("Imports folder", self.imports), ("Reports folder", self.reports))):
            ttk.Label(top, text=label).grid(row=r, column=0, sticky="w", **pad)
            ttk.Entry(top, textvariable=var).grid(row=r, column=1, sticky="ew", **pad)
            ttk.Button(top, text="Browse...", command=lambda v=var: self.browse(v)).grid(row=r, column=2, **pad)

        files = ttk.LabelFrame(self, text="1. Documents in the source folder (click [ ] to tick or untick)")
        files.pack(fill="both", expand=True, padx=8, pady=4)
        bar = ttk.Frame(files)
        bar.pack(fill="x", padx=4, pady=2)
        for text, cmd in (("Select all", lambda: self.tick("all")), ("Select none", lambda: self.tick("none")),
                          ("Select not converted yet", lambda: self.tick("new")), ("Refresh list", self.refresh)):
            ttk.Button(bar, text=text, command=cmd).pack(side="left", padx=2)
        self.file_tree = self.make_tree(files, ("sel", "file", "status"), ("", "Document", "Status"), (40, 560, 260), height=8)
        self.file_tree.column("sel", anchor="center", stretch=False)
        self.file_tree.bind("<Button-1>", self.on_file_click)

        act = ttk.Frame(self)
        act.pack(fill="x", padx=8, pady=2)
        self.buttons = []
        for text, dry, force in (("Dry run (check only, writes nothing)", True, False), ("Convert selected", False, False),
                                 ("Convert as a NEW version (V2, V3...)", False, True)):
            b = ttk.Button(act, text=text, command=lambda d=dry, f=force: self.start(d, f))
            b.pack(side="left", padx=3)
            self.buttons.append(b)
        self.progress = ttk.Progressbar(act, length=200)
        self.progress.pack(side="left", padx=10)
        self.status = ttk.Label(act, text="Ready.")
        self.status.pack(side="left", padx=4)

        res = ttk.LabelFrame(self, text="2. Results (red = failed or skipped, yellow = has review notes; click a row for details)")
        res.pack(fill="both", expand=True, padx=8, pady=4)
        self.res_tree = self.make_tree(res, ("file", "out", "status", "cases", "steps", "review"),
                                       ("Document", "Import file built", "Status", "Cases", "Steps/case", "Review"),
                                       (250, 280, 160, 150, 70, 60), height=8)
        self.res_tree.tag_configure("review", background="#fff3c4")
        self.res_tree.tag_configure("bad", background="#f8cfcf")
        self.res_tree.bind("<<TreeviewSelect>>", self.on_result_select)

        det = ttk.LabelFrame(self, text="3. Details for the selected result")
        det.pack(fill="both", expand=True, padx=8, pady=4)
        self.detail = tk.Text(det, height=9, wrap="word", state="disabled", font=("Segoe UI", 9))
        sb = ttk.Scrollbar(det, command=self.detail.yview)
        self.detail.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.detail.pack(fill="both", expand=True, padx=4, pady=4)

        foot = ttk.Frame(self)
        foot.pack(fill="x", padx=8, pady=(2, 8))
        for text, cmd in (("Open imports folder", lambda: open_path(self.imports.get())),
                          ("Open attachments folder (pictures)", lambda: open_path(os.path.join(self.imports.get(), "attachments"))),
                          ("Open latest report", self.open_report),
                          ("Open selected import file", self.open_selected_import)):
            ttk.Button(foot, text=text, command=cmd).pack(side="left", padx=3)

    def make_tree(self, parent, cols, heads, widths, height):
        frame = ttk.Frame(parent)
        frame.pack(fill="both", expand=True, padx=4, pady=2)
        tree = ttk.Treeview(frame, columns=cols, show="headings", height=height, selectmode="browse")
        for c, h, w in zip(cols, heads, widths):
            tree.heading(c, text=h)
            tree.column(c, width=w, anchor="w")
        sb = ttk.Scrollbar(frame, command=tree.yview)
        tree.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        tree.pack(fill="both", expand=True)
        return tree

    # ----- the file list -----
    def browse(self, var):
        d = filedialog.askdirectory(initialdir=var.get() or ROOT)
        if d:
            var.set(os.path.normpath(d))
            self.save_settings()
            self.refresh()

    def file_status(self, fn):
        if not fn.lower().endswith(".xlsx"):
            return "Not an .xlsx file"
        v = core.existing_versions(self.imports.get(), fn)
        return f"Converted (V{max(v)})" if v else "Not converted yet"

    def refresh(self):
        if self.busy:
            return
        old = {i: self.file_tree.set(i, "sel") for i in self.file_tree.get_children()}
        self.file_tree.delete(*self.file_tree.get_children())
        src = self.source.get()
        if not os.path.isdir(src):
            self.status.config(text="The source folder does not exist.")
            return
        for fn in core.source_files(src):
            st = self.file_status(fn)
            sel = old.get(fn, CHECK if st == "Not converted yet" else UNCHECK)
            self.file_tree.insert("", "end", iid=fn, values=(sel, fn, st))
        self.status.config(text=f"{len(self.file_tree.get_children())} file(s) in the source folder.")

    def on_file_click(self, event):
        if self.file_tree.identify_region(event.x, event.y) == "cell" and self.file_tree.identify_column(event.x) == "#1":
            iid = self.file_tree.identify_row(event.y)
            if iid:
                self.file_tree.set(iid, "sel", UNCHECK if self.file_tree.set(iid, "sel") == CHECK else CHECK)
            return "break"

    def tick(self, mode):
        for i in self.file_tree.get_children():
            if mode == "all":
                on = True
            elif mode == "none":
                on = False
            else:
                on = self.file_tree.set(i, "status") == "Not converted yet"
            self.file_tree.set(i, "sel", CHECK if on else UNCHECK)

    def selected_files(self):
        return [i for i in self.file_tree.get_children() if self.file_tree.set(i, "sel") == CHECK]

    # ----- running -----
    def start(self, dry, force):
        if self.busy:
            return
        names = self.selected_files()
        if not names:
            messagebox.showinfo("Nothing selected", "Tick at least one document first.")
            return
        if force and not dry and not messagebox.askyesno(
                "New version", f"Build a new version (V2, V3...) for the {len(names)} ticked document(s)?\nExisting versions are kept."):
            return
        self.save_settings()
        self.busy = True
        for b in self.buttons:
            b.state(["disabled"])
        self.res_tree.delete(*self.res_tree.get_children())
        self.rows = {}
        self.set_detail("")
        self.progress.configure(maximum=len(names), value=0)
        self.status.config(text="Working...")
        args = (self.source.get(), self.imports.get(), self.reports.get(), names, dry, force)
        threading.Thread(target=self.worker, args=args, daemon=True).start()

    def worker(self, source, imports, reports, names, dry, force):
        try:
            label = core.default_label(imports)
            rows = core.run_all(source, imports, force, dry, label, only=set(names),
                                progress=lambda i, n, row: self.q.put(("row", i, n, row)))
            path = None if dry or not rows else core.write_report(rows, reports)
            self.q.put(("done", rows, path, dry))
        except Exception:
            self.q.put(("error", traceback.format_exc()))

    def poll(self):
        try:
            while True:
                msg = self.q.get_nowait()
                if msg[0] == "row":
                    _, i, n, row = msg
                    self.add_result(row)
                    self.progress.configure(value=i)
                    self.status.config(text=f"{i} of {n} done...")
                elif msg[0] == "done":
                    _, rows, path, dry = msg
                    self.finish(rows, path, dry)
                else:
                    self.finish_error(msg[1])
        except queue.Empty:
            pass
        self.after(100, self.poll)

    def add_result(self, row):
        self.rows[row["source"]] = row
        bad = row["status"].startswith(("FAILED", "skipped"))
        tag = ("bad",) if bad else (("review",) if row["review"] == "yes" else ())
        self.res_tree.insert("", "end", iid=row["source"], tags=tag,
                             values=(row["source"], row["import_file"], row["status"][:60], row["cases"], row["steps_per_case"],
                                     "yes" if row["review"] == "yes" else ("no" if row["review"] else "")))

    def end_run(self):
        self.busy = False
        for b in self.buttons:
            b.state(["!disabled"])
        self.refresh()

    def finish(self, rows, path, dry):
        built = sum(1 for r in rows if r["status"] == "built")
        failed = sum(1 for r in rows if r["status"].startswith("FAILED"))
        skipped = sum(1 for r in rows if r["status"].startswith("skipped"))
        review = sum(1 for r in rows if r["review"] == "yes")
        self.last_report = path
        text = (f"Dry run: {len(rows)} checked, nothing written. " if dry else f"{built} built, ") + \
               f"{skipped} skipped, {failed} failed, {review} need review." + (f" Report saved in {os.path.basename(path)}." if path else "")
        self.end_run()
        self.status.config(text=text)

    def finish_error(self, tb):
        self.end_run()
        self.status.config(text="Stopped by an error.")
        messagebox.showerror("Something went wrong", tb[-1500:])

    # ----- details and shortcuts -----
    def set_detail(self, text):
        self.detail.config(state="normal")
        self.detail.delete("1.0", "end")
        self.detail.insert("1.0", text)
        self.detail.config(state="disabled")

    def on_result_select(self, _event=None):
        sel = self.res_tree.selection()
        row = self.rows.get(sel[0]) if sel else None
        if not row:
            return
        notes = row["notes"].split(" | ") if row["notes"] else []
        parts = [f"Document: {row['source']}", f"Status: {row['status']}"]
        if row["import_file"]:
            parts.append(f"Import file: {row['import_file']}")
        if row["sheets_used"]:
            parts.append(f"Sheets read: {row['sheets_used']}")
        if row["column_map"]:
            parts.append(f"Columns used: {row['column_map']}")
        parts.append("")
        parts.append("Review notes:" if notes else "No review notes.")
        parts += [f"  - {n}" for n in notes]
        self.set_detail("\n".join(parts))

    def open_report(self):
        path = self.last_report
        if not path:
            try:
                files = sorted(f for f in os.listdir(self.reports.get()) if f.endswith(".csv"))
                path = os.path.join(self.reports.get(), files[-1]) if files else None
            except OSError:
                path = None
        if path:
            open_path(path)
        else:
            messagebox.showinfo("No report yet", "A report is written after each real conversion (not after a dry run).")

    def open_selected_import(self):
        sel = self.res_tree.selection()
        row = self.rows.get(sel[0]) if sel else None
        if row and row["import_file"] and row["status"] == "built":
            open_path(os.path.join(self.imports.get(), row["import_file"]))
        else:
            messagebox.showinfo("Nothing to open", "Select a result row that was built in this session.")


def selftest(argv):
    """Build the window hidden, run a dry run over every document, print the result and quit. Writes nothing."""
    messagebox.showerror = lambda *a, **k: print("ERROR DIALOG:", *a)   # never open a dialog nobody can see
    messagebox.showinfo = lambda *a, **k: print("INFO DIALOG:", *a)
    app = App()
    app.withdraw()
    if len(argv) >= 2:
        app.source.set(argv[0])
        app.imports.set(argv[1])
        app.refresh()
    app.tick("all")
    app.start(True, "--force" in sys.argv)
    import time
    t0 = time.time()
    while app.busy and time.time() - t0 < 600:
        app.update()
        time.sleep(0.05)
    rows = list(app.rows.values())
    print(f"selftest: {len(app.file_tree.get_children())} listed, {len(rows)} results, "
          f"{sum(1 for r in rows if r['status'].startswith('FAILED'))} failed, status line: {app.status.cget('text')}")
    if rows:
        app.res_tree.selection_set(rows[0]["source"])
        app.on_result_select()
        print("detail text starts:", app.detail.get("1.0", "1.4"), "...")
    app.destroy()


def selftest_to_file(argv):
    """A windowed exe has no console, so --selftest-out <file> writes the self-test output to a file."""
    import contextlib, io
    out = argv[argv.index("--selftest-out") + 1]
    rest = [a for a in argv if not a.startswith("--") and a != out]
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            selftest(rest)
    except Exception:
        buf.write(traceback.format_exc())
    with open(out, "w", encoding="utf-8") as fh:
        fh.write(buf.getvalue())


if __name__ == "__main__":
    if "--selftest-out" in sys.argv:
        selftest_to_file(sys.argv[1:])
    elif "--selftest" in sys.argv:
        selftest([a for a in sys.argv[1:] if not a.startswith("--")])
    else:
        try:
            App().mainloop()
        except Exception:
            messagebox.showerror("Could not start", traceback.format_exc()[-1500:])
