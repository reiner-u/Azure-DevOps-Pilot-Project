#!/usr/bin/env python3
"""Convert ALM/HPQC-style Excel test documents into Azure DevOps test-case import workbooks.

BATCH (normal use):   python scripts\\build_import_from_source.py --all
    Converts every .xlsx in source/ that has no import workbook yet, writes imports/<name>_AzureDevOps_Import_V1.xlsx,
    and writes a review report to reports/conversion_report_<timestamp>.csv. Files already converted are skipped
    (add --force to build the next version, V2, V3...; existing versions are never overwritten).
    Add --dry-run to analyse everything and write nothing.
SINGLE FILE:          python scripts\\build_import_from_source.py <source.xlsx> <output.xlsx> "<Feature title>"
OPTIONS:              --label-from <xlsx>   copy the Microsoft sensitivity label from this workbook
                      (default: the first workbook in imports/ that has one, else the source's own label)
                      --source-dir / --imports-dir / --reports-dir   override the default folders

HOW A WORKBOOK IS READ (adapts to the file; nothing is hardcoded to one document):
  * Test sheets are found by their headers, not their names: any visible sheet with a header row (searched in the first 25 rows)
    that has a test-case ID, a description, an Execution and an Expected Result column. Version History / Total Testcases / hidden
    sheets are never imported. A workbook with sheets named EN and FR (a two-language layout) gives "EN Import" and "FR Import".
  * Column names are matched by meaning, so "Test Scenario ID", "Test Case ID" and "Test case ID " are all the ID column; "Execution"
    and "Execution Steps", "Pre-condition" and "Preconditions", "Buisness Requirment" and "Business Requirement ID" are accepted, etc.
    The report's column_map shows exactly which source column was used for what.
  * If a sheet has the Expected Result in both English and French columns, it gives an "EN Import" and an "FR Import" sheet with the same
    steps (the source has no French steps) and the matching expected result.
  * Section heading rows (a single cell in column A) are not test cases; the heading is added to the Description of the cases under it.
  * Columns the converter does not know (Notes, Comments, Source, Testing Guidelines...) are copied into the Description under their
    own header, so nothing in the source is dropped. Reviewed By / Reviewed Date are left out and listed in the report.

Rules (reverse-engineered from one hand-converted example; see README.md):
  * Two-row layout per test case: a title row, then one row per step.
  * Title row: Work Item Type=Test Case, Title=the description, Area Path, State=Design, Description.
  * Description = scenario ID, business requirement ID, type, author, automated flag (+ automation notes and any extra columns).
  * Steps: Pre-condition items become steps 1..n (numbering "1." or "1)" stripped, whitespace collapsed; items glued onto one line are
    split on the numbers); Execution follows: a numbered list becomes one step per number, otherwise one step per sentence.
    Expected Result goes on the LAST step only (trailing whitespace trimmed).
  * Pictures embedded in a case's row cannot be imported: they are saved to attachments/<workbook name>/ next to the output, the
    Description names each file, and you attach it in ADO (Expected Result pictures to the last step). Pictures on other sheets are
    saved there too. Step Expected stays as the source text.
  * Nothing in the source text is reworded (typos are kept).
  * Anything unusual is listed in the report's notes column instead of being silently guessed at.
Needs only Python 3 and openpyxl (no Pillow).
"""
import argparse, csv, datetime, difflib, glob, json, os, posixpath, re, sys, tempfile, zipfile
import xml.etree.ElementTree as ET
import openpyxl
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

def load_local_config():
    """Settings that belong to one organisation and are not kept in the code repository: scripts/local_config.json
    (copy local_config.example.json and fill it in). Inside the packaged exe the file is bundled next to the code."""
    for base in (getattr(sys, "_MEIPASS", None), os.path.dirname(os.path.abspath(__file__))):
        path = os.path.join(base, "local_config.json") if base else None
        if path and os.path.isfile(path):
            try:
                with open(path, encoding="utf-8") as fh:
                    return json.load(fh)
            except (OSError, ValueError):
                return {}
    return {}


_CFG = load_local_config()
AREA_PLACEHOLDER = "Project\\Area\\Path"
AREA = _CFG.get("area_path") or AREA_PLACEHOLDER          # ADO Area Path written on every test case
DEFAULT_AREA = AREA
STATE = _CFG.get("state") or "Design"


def set_area(path):
    """Use this ADO Area Path for everything converted from now on (blank = the configured default).
    Area Paths use backslashes; forward slashes and doubled or edge backslashes are tidied."""
    global AREA
    path = re.sub(r"\\+", r"\\", (path or "").strip().replace("/", "\\")).strip("\\")
    AREA = path or DEFAULT_AREA
    return AREA
HEADERS = ["ID", "Work Item Type", "Title", "Test Step", "Step Action", "Step Expected", "Area Path", "Assigned To", "State",
           "Description"]
WIDTHS = [12, 18, 42, 12, 85, 75, 48, 28, 14, 55]
LANGS = [("EN", "EN Import"), ("FR", "FR Import")]
LABEL = "docMetadata/LabelInfo.xml"
TOOL_VERSION = "2026.10.27.1"

M = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
R = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
XDR = "{http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing}"
A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"

IGNORED_COLS = re.compile(r"^(reviewed|review date|reviewer)")      # columns that are never copied into the Description
CROSSREF = re.compile(r"\brefer(?:s|red)? to\b|\bsame as\b|\blisted in\b|\bsee (?:case|test|scenario|pre)", re.I)


# ---------- text helpers ----------
def norm(s):
    return re.sub(r"\s+", " ", str(s)).strip()


def clean(v):
    if v is None:
        return None
    s = str(v).strip()
    return s or None


def short(sid):
    return str(sid).rsplit("_", 1)[-1]


def lab(d):
    """How a case is named in the review notes."""
    return short(d["id"]) if d["id"] else f"row {d['row']}"


def lst(items, n=12):
    items = list(items)
    s = repr(items[:n])
    return s if len(items) <= n else s[:-1] + f", ... +{len(items) - n} more]"


def slug(s, n=60):
    return re.sub(r"[^A-Za-z0-9]+", "_", str(s)).strip("_")[:n]


def tidy(v):
    """Keep a multi-line value's line breaks, but drop blank lines and trailing/leading spaces on each line."""
    return "\n".join(l.strip() for l in str(v).splitlines() if l.strip())


def shorten_title(t, limit=128):
    """ADO rejects titles over 128 characters: cut at a word boundary and add '...' (the full text goes in the Description)."""
    if len(t) <= limit:
        return t
    cut = t[:limit - 3]
    sp = cut.rfind(" ")
    if sp > limit * 0.6:
        cut = cut[:sp]
    return cut.rstrip(" ,;:-") + "..."


NUM = re.compile(r"(?:^|\s)(\d+)[.)]\s+")
LEAD_NUM = re.compile(r"^\s*\d+[.)]\s*")


def split_numbered_lines(text):
    """Several lines that each start with a number but are not a clean 1..n run (a repeated or skipped number): one step per line, number stripped."""
    lines = [l for l in str(text).splitlines() if l.strip()]
    if len(lines) >= 2 and all(LEAD_NUM.match(l) for l in lines):
        return [norm(LEAD_NUM.sub("", l)) for l in lines]
    return None


def split_numbered(text):
    """The items of a clean '1. ... 2. ...' or '1) ... 2) ...' list (1..n in order), else None."""
    parts = NUM.split(str(text).strip())
    if len(parts) >= 3 and parts[0] == "":
        nums, items = parts[1::2], parts[2::2]
        if nums == [str(i) for i in range(1, len(nums) + 1)]:
            return [norm(i) for i in items]
    return None


def split_precondition(text):
    """-> (steps, fell_back). Numbered items become steps; otherwise one step per line (fell_back=True if that gave several)."""
    if not text or not str(text).strip():
        return [], False
    items = split_numbered(text)
    if items is not None:
        return items, False
    items = split_numbered_lines(text)
    if items is not None:
        return items, True
    lines = [norm(l) for l in str(text).splitlines() if l.strip()]
    return lines, len(lines) > 1


def split_execution(text):
    """-> (steps, numbered, multiline_unnumbered). A numbered list gives one step per number, else one step per sentence."""
    if not text or not str(text).strip():
        return [], False, False
    items = split_numbered(text)
    if items is not None:
        return items, True, False
    items = split_numbered_lines(text)
    if items is not None:
        return items, "renumbered", False
    t = str(text).strip()
    parts = [norm(x) for x in re.split(r"(?<=[.!?])\s+", t) if x.strip()]
    return parts, False, len([l for l in t.splitlines() if l.strip()]) > 1


# ---------- pictures ----------
def extract_images(path):
    """Read pictures straight from the xlsx zip (no Pillow needed).
    Returns ({sheet name: [(row0, col0, bytes, ext)]}, {sheet name: pictures with no cell anchor})."""
    out, unanchored = {}, {}
    with zipfile.ZipFile(path) as z:
        names = set(z.namelist())

        def rels(part):
            d, f = part.rsplit("/", 1)
            rp = f"{d}/_rels/{f}.rels"
            if rp not in names:
                return {}
            res = {}
            for r in ET.fromstring(z.read(rp)):
                if r.get("TargetMode") == "External":
                    continue
                t = r.get("Target")
                full = t.lstrip("/") if t.startswith("/") else posixpath.normpath(posixpath.join(d, t))
                res[r.get("Id")] = (r.get("Type"), full)
            return res

        if "xl/workbook.xml" not in names:
            return out, unanchored
        wbrels = rels("xl/workbook.xml")
        for sh in ET.fromstring(z.read("xl/workbook.xml")).find(M + "sheets"):
            name, rid = sh.get("name"), sh.get(R + "id")
            if rid not in wbrels:
                continue
            for typ, target in rels(wbrels[rid][1]).values():
                if not typ.endswith("/drawing") or target not in names:
                    continue
                drels = rels(target)
                for anchor in ET.fromstring(z.read(target)):
                    frm = anchor.find(XDR + "from")
                    for blip in anchor.iter(A + "blip"):
                        emb = blip.get(R + "embed")
                        if emb not in drels or drels[emb][1] not in names:
                            continue
                        media = drels[emb][1]
                        if frm is None:
                            unanchored[name] = unanchored.get(name, 0) + 1
                            continue
                        out.setdefault(name, []).append((int(frm.find(XDR + "row").text), int(frm.find(XDR + "col").text),
                                                         z.read(media), media.rsplit(".", 1)[-1].lower()))
    return out, unanchored



# ---------- finding the test sheets and their columns ----------
def cleanhdr(v):
    return re.sub(r"[\s\xa0]+", " ", str(v if v is not None else "")).strip()


def classify_exact(h):
    """Header text -> (field, language) by pattern. Matches by meaning so wording variants of a header map to the same field."""
    h = cleanhdr(h).lower()
    if not h:
        return None, None
    if re.match(r"test (scenarios?|cases?) id\b|(tc|scenario|case) id\b|id$", h):
        return "id", None
    if re.match(r"b[uis]{3,4}ness req(?!.*source)|br( id)?$|requirements? id$|req(uirement)? ?id$", h):
        return "br", None
    if re.match(r"((test )?(scenarios?|cases?) )?(description|title)\b|(test )?(scenarios?|cases?) (title|name)\b", h):
        return "title", None
    if re.match(r"((test )?(scenarios?|cases?) )?type$", h):
        return "type", None
    if re.match(r"author|user id$|created by", h):
        return "author", None
    if re.match(r"subject", h):
        return "subject", None
    if re.match(r"pre-? ?conditions?", h):
        return "pre", None
    if re.match(r"execution", h):
        return "exe", None
    if re.match(r"automation notes", h):
        return "notes", None
    if re.match(r"automat", h):
        return "auto", None
    if re.match(r"expected results?", h):
        lang = "FR" if re.search(r"\b(fr|fra|french|fran[cç]ais)\b", h) else ("EN" if re.search(r"\b(en|eng|english)\b", h) else None)
        return "exp", lang
    return None, None


# Misspelled headers ("Pre-conditon", "Excution") are common in hand-edited documents. When no pattern matches, a header that is
# very close to one of these words is read as that field. Short words are left out on purpose (too easy to mismatch).
FUZZY_WORDS = (("precondition", "pre"), ("execution", "exe"), ("expectedresult", "exp"), ("description", "title"),
               ("subject", "subject"), ("author", "author"), ("automated", "auto"))
FUZZY_CUTOFF = 0.86


def classify_fuzzy(h):
    """Header text -> (field, language) for a near-miss spelling of a known header, else (None, None)."""
    h = cleanhdr(h).lower()
    squashed = re.sub(r"[^a-z]", "", h)
    if len(squashed) < 6:
        return None, None
    best = (0.0, None)
    for word, field in FUZZY_WORDS:
        ratio = difflib.SequenceMatcher(None, squashed[:len(word) + 1], word).ratio()
        if ratio > best[0]:
            best = (ratio, field)
    if best[0] < FUZZY_CUTOFF:
        return None, None
    if best[1] == "exp":
        return "exp", ("FR" if re.search(r"\b(fr|fra|french|fran[cç]ais)\b", h) else ("EN" if re.search(r"\b(en|eng|english)\b", h) else None))
    return best[1], None


def classify(h):
    """Exact patterns first, then the typo-tolerant fallback."""
    return classify_exact(h) if classify_exact(h)[0] else classify_fuzzy(h)


NEEDED = ("id", "title", "exe", "exp")
FIELD_NAMES = dict(id="ID", br="business requirement", title="description", type="type", author="author", subject="subject",
                   pre="pre-condition", exe="execution", exp="expected result", exp_fr="French expected result",
                   auto="automated", notes="automation notes")


def find_header(ws, scan=25):
    """Look for the header row in the first rows of a sheet. Returns dict(row, cols, headers, score, ok, missing)."""
    best = None
    for rnum, row in enumerate(ws.iter_rows(min_row=1, max_row=scan, values_only=True), start=1):
        cols = {}
        fuzzy = []
        for i, v in enumerate(row):
            f, lang = classify(v)
            if f is None:
                continue
            if not classify_exact(v)[0]:
                fuzzy.append((cleanhdr(v), f))
            if f == "exp":
                cols.setdefault("exp_fr" if lang == "FR" else "exp", i)
            else:
                cols.setdefault(f, i)
        if "exp" not in cols and "exp_fr" in cols:
            cols["exp"] = cols.pop("exp_fr")
        guess = None
        if "id" not in cols and all(k in cols for k in ("title", "exe", "exp")):
            # the ID column has an unusual header: take the one unclaimed column whose header ends in "id"
            cands = [i for i, v in enumerate(row) if i not in cols.values() and re.search(r"id\b", cleanhdr(v).lower())]
            if len(cands) == 1:
                cols["id"], guess = cands[0], cleanhdr(row[cands[0]])
        if best is None or len(cols) > best["score"]:
            best = dict(row=rnum, cols=cols, headers=[cleanhdr(v) for v in row], score=len(cols), id_guess=guess, fuzzy=fuzzy)
    if best is None:
        return dict(row=0, cols={}, headers=[], score=0, ok=False, missing=list(NEEDED))
    best["missing"] = [k for k in NEEDED if k not in best["cols"]]
    best["ok"] = not best["missing"]
    return best


def fix_swapped_type_author(ws, hdr, notes):
    """Some sources put 'Author' over the Type data and 'Type' over the author names (Required Documents). Trust the data."""
    c = hdr["cols"]
    if c.get("type") is None or c.get("author") is None:
        return
    is_type = re.compile(r"\s*(manual|automat)", re.I)
    a = b = 0
    for r in ws.iter_rows(min_row=hdr["row"] + 1, max_row=hdr["row"] + 40, values_only=True):
        a += bool(r[c["type"]] and is_type.match(str(r[c["type"]])))
        b += bool(r[c["author"]] and is_type.match(str(r[c["author"]])))
    if b > a and b >= 3:
        c["type"], c["author"] = c["author"], c["type"]
        notes.append(f"{ws.title}: the 'Type' and 'Author' headers look swapped in the source (Manual/Automated sits under 'Author'); used the data, not the headers")


def has_content(ws, hdr, col):
    return any(clean(r[col]) for r in ws.iter_rows(min_row=hdr["row"] + 1, values_only=True) if col < len(r))


# ---------- reading the source ----------
def read_cases(ws, hdr, tag, images, notes, exp_key="exp", skip_cols=(), first=True):
    c, headers, hrow = hdr["cols"], hdr["headers"], hdr["row"]
    ecol = c[exp_key]
    get = lambda r, k: (r[c[k]] if c.get(k) is not None and c[k] < len(r) else None)
    used = {i for i in c.values() if i is not None}
    extra_cols = [i for i in range(len(headers)) if i not in used and not IGNORED_COLS.match(headers[i].lower())]
    ignored_cols = [i for i in range(len(headers)) if i not in used and IGNORED_COLS.match(headers[i].lower())]
    imgmap = {}
    for row0, col0, data, ext in images:
        lst_ = imgmap.setdefault((row0 + 1, col0), [])
        if not any(data == x[0] for x in lst_):  # identical pictures stacked in one cell count once
            lst_.append((data, ext))
    names = {c.get("pre"): "Pre-condition", c.get("exe"): "Execution", ecol: "Expected Result"}

    def colname(col):
        if names.get(col):
            return names[col]
        return headers[col] if col < len(headers) and headers[col] else f"column {col + 1}"

    total_pics = sum(len(v) for k, v in imgmap.items() if k[1] not in skip_cols)
    placed = 0
    if first:
        for k, label in (("auto", "Automated"), ("br", "business requirement ID"), ("author", "author"), ("type", "type")):
            if c.get(k) is None:
                notes.append(f"{tag}: no {label} column in the source, so the Description has no such line")
        if c.get("pre") is None:
            notes.append(f"{tag}: no Pre-condition column in the source; the steps come from Execution only")
    cases, section = [], None
    skipped, extras_seen, ignored_seen, blank_hdr_seen = [], set(), set(), set()
    for rownum, r in enumerate(ws.iter_rows(min_row=hrow + 1, values_only=True), start=hrow + 1):
        if not clean(get(r, "title")) and not clean(get(r, "id")):
            filled = [i for i, v in enumerate(r) if clean(v)]
            if len(filled) == 1 and filled[0] == 0:
                section = norm(r[0])              # a heading row such as "Page fields"
            elif filled:
                skipped.append(rownum)
            continue
        d = {k: clean(get(r, k)) for k in ("type", "subject", "author", "id", "br", "title", "auto", "notes")}
        for k in ("type", "author", "br", "auto"):
            if d[k]:
                d[k] = tidy(d[k])
        if d["id"]:
            d["id"] = norm(d["id"])
        d["title_joined"] = bool(d["title"] and "\n" in d["title"])
        if d["title_joined"]:
            d["title"] = norm(d["title"])
        d["title_full"] = None
        if d["title"] and len(d["title"]) > 128:
            d["title_full"], d["title"] = d["title"], shorten_title(d["title"])
        d["row"], d["section"] = rownum, section
        d["exp"] = clean(r[ecol]) if ecol < len(r) else None
        d["cols"] = {k for k, v in c.items() if v is not None and k not in ("exp", "exp_fr")}
        d["images"] = imgmap.get((rownum, ecol), [])
        d["other_images"] = [(colname(col), data, ext)
                             for (row, col), lst_ in sorted(imgmap.items()) if row == rownum and col != ecol and col not in skip_cols
                             for data, ext in lst_]
        placed += len(d["images"]) + len(d["other_images"])
        d["extras"] = []
        for i in extra_cols:
            v = clean(r[i]) if i < len(r) else None
            if v:
                label = headers[i] or f"column {get_column_letter(i + 1)}"
                (extras_seen if headers[i] else blank_hdr_seen).add(label)
                d["extras"].append((label, "\n".join(norm(l) for l in v.splitlines() if l.strip())))
        for i in ignored_cols:
            if i < len(r) and clean(r[i]):
                ignored_seen.add(headers[i])
        pre, d["pre_fallback"] = split_precondition(get(r, "pre"))
        exe, d["exec_numbered"], d["exec_multiline"] = split_execution(get(r, "exe"))
        d["actions"] = pre + exe
        d["n_exec"] = len(exe)
        cases.append(d)
    if first:
        if skipped:
            notes.append(f"{tag}: row(s) {lst(skipped)} have text but no case ID or description and are not a section heading; skipped (a case continued on a second row?)")
        if total_pics > placed:
            notes.append(f"{tag}: {total_pics - placed} picture(s) sit on rows with no test case and were NOT carried over (check the source by hand)")
        if extras_seen or blank_hdr_seen:
            notes.append(f"{tag}: extra column(s) copied into the Description: {sorted(extras_seen | blank_hdr_seen)}")
        if ignored_seen:
            notes.append(f"{tag}: column(s) not carried over: {sorted(ignored_seen)}")
    return cases


def declared_counts(path):
    """Case counts claimed on the source's 'Total Testcases' sheet, e.g. {'EN': 21, 'FR': 21, 'schoolsearch': 22}.
    Reads the values Excel last calculated, so formulas such as =COUNTA(...) work when the file was saved by Excel."""
    out = {}
    try:
        wb = openpyxl.load_workbook(path, data_only=True)
    except Exception:
        return out
    if "Total Testcases" not in wb.sheetnames:
        return out
    col_n = col_m = None
    for row in wb["Total Testcases"].iter_rows(values_only=True):
        cells = [str(v).strip().lower() if v is not None else "" for v in row]
        if any(c.startswith("no. of test") for c in cells):
            col_n = next(i for i, c in enumerate(cells) if c.startswith("no. of test"))
            col_m = next((i for i, c in enumerate(cells) if c.startswith("module")), None)
            continue
        if col_n is not None and col_m is not None and row[col_m] and str(row[col_m]).strip().lower() != "total":
            try:
                n = int(float(str(row[col_n])))
            except ValueError:
                continue
            m = re.search(r"(EN|FR)\s*$", str(row[col_m]).strip().upper())
            if m:
                out[m.group(1)] = n
            out[re.sub(r"[^a-z0-9]", "", str(row[col_m]).lower())] = n
    return out


def analyse(variants, declared, legacy, unanchored_total):
    notes = []
    for v in variants:
        tag, cases, first = v["tag"], v["cases"], v["first"]
        if not cases:
            notes.append(f"{tag}: no test cases found")
        key = tag if legacy else re.sub(r"[^a-z0-9]", "", v["src_sheet"].lower())
        if first and key in declared and declared[key] != len(cases):
            notes.append(f"{tag}: the source's Total Testcases sheet says {declared[key]}, found {len(cases)}")
        if first:
            ids = [d["id"] for d in cases if d["id"]]
            dup = sorted({short(i) for i in ids if ids.count(i) > 1})
            if dup:
                notes.append(f"{tag}: duplicate scenario IDs {dup}")
            noid = [f"row {d['row']}" for d in cases if not d["id"]]
            if noid:
                notes.append(f"{tag}: blank test case ID {lst(noid)} (imported with no ID line; check the source)")
        pics = [lab(d) for d in cases if d["images"]]
        if pics:
            notes.append(f"{tag}: expected result has a picture for {lst(pics)}; pictures saved to attachments/, attach by hand")
        if first:
            other = [f"{lab(d)} ({'/'.join(sorted({c for c, _, _ in d['other_images']}))})" for d in cases if d["other_images"]]
            if other:
                notes.append(f"{tag}: picture(s) in another cell of the case's row {lst(other)}; saved to attachments/, attach by hand")
        blank = [lab(d) for d in cases if not d["exp"] and not d["images"]]
        if blank:
            notes.append(f"{tag}: blank expected result {lst(blank)}")
        ph = [lab(d) for d in cases if d["exp"] and re.search(r"[<>]", d["exp"])]
        if ph:
            notes.append(f"{tag}: angle brackets in expected result {lst(ph)} (check they display in ADO)")
        if not first:
            continue
        if "br" in (cases[0]["cols"] if cases else ()):
            nobr = [lab(d) for d in cases if not d["br"]]
            if nobr:
                notes.append(f"{tag}: no business requirement ID {lst(nobr)}")
        longt = [lab(d) for d in cases if d["title_full"]]
        if longt:
            notes.append(f"{tag}: description over 128 characters {lst(longt)}; the title was shortened to fit ADO's limit and the full text is in the Description")
        notitle = [lab(d) for d in cases if not d["title"]]
        if notitle:
            notes.append(f"{tag}: missing title {lst(notitle)} (ADO will reject)")
        joined = [lab(d) for d in cases if d["title_joined"]]
        if joined:
            notes.append(f"{tag}: title had line breaks, joined with spaces {lst(joined)}")
        noact = [lab(d) for d in cases if not d["actions"]]
        if noact:
            notes.append(f"{tag}: no steps (empty pre-condition and execution) {lst(noact)}")
        fb = [lab(d) for d in cases if d["pre_fallback"]]
        if fb:
            notes.append(f"{tag}: pre-condition is not a clean 1..n numbered list; split by line instead {lst(fb)} (check the steps)")
        rn = [lab(d) for d in cases if d["exec_numbered"] == "renumbered"]
        if rn:
            notes.append(f"{tag}: Execution numbering is not a clean 1..n run (repeated or skipped number); split by line instead {lst(rn)} (check the steps)")
        ml = [lab(d) for d in cases if d["exec_multiline"]]
        if ml:
            notes.append(f"{tag}: Execution has several lines but no numbering, split by sentence {lst(ml)} (check the steps)")
        manyx = [lab(d) for d in cases if d["n_exec"] > 3 and not d["exec_numbered"]]
        if manyx:
            notes.append(f"{tag}: Execution split into more than 3 steps by sentence {lst(manyx)} (check the sentence splitting)")
        xref = [lab(d) for d in cases if CROSSREF.search(" ".join(d["actions"]))]
        if xref:
            notes.append(f"{tag}: pre-condition/execution refers to another case {lst(xref)}; each ADO case stands alone, so copy the detail in or link the cases")
    if legacy and len(variants) == 2:
        en, fr = variants[0]["cases"], variants[1]["cases"]
        if len(en) != len(fr):
            notes.append(f"EN has {len(en)} cases but FR has {len(fr)}")
        else:
            bad = [lab(a) for a, b in zip(en, fr) if a["title"] != b["title"] or len(a["actions"]) != len(b["actions"])]
            if bad:
                notes.append(f"EN and FR differ in title or step count for {lst(bad)}")
    elif legacy and len(variants) == 1:
        notes.append("only one of the EN / FR sheets was found")
    if unanchored_total:
        notes.append(f"{unanchored_total} picture(s) not anchored to any cell were NOT carried over")
    return notes


# ---------- writing the import workbook ----------
def description(d):
    cols = d["cols"]
    lines = [f"Source scenario ID: {d['id'] or '(blank in source)'}"]
    if d.get("title_full"):
        lines.append(f"Full source description: {d['title_full']}")
    if "br" in cols:
        lines.append(f"Business requirement ID: {d['br'] or '(blank in source)'}")
    if "type" in cols:
        lines.append(f"Test scenario type: {d['type'] or '(blank in source)'}")
    if d["subject"]:
        lines.append(f"Subject: {d['subject']}")
    if "author" in cols:
        lines.append(f"Original author: {d['author'] or '(blank in source)'}")
    if "auto" in cols:
        lines.append(f"{d.get('auto_label', 'Automated')}: {d['auto'] or '(blank in source)'}")
    if d["notes"]:
        lines.append(f"Automation notes: {d['notes']}")
    if d.get("section"):
        lines.append(f"Section: {d['section']}")
    for label, text in d["extras"]:
        lines.append(f"{label}: {text}")
    if d.get("variant_note"):
        lines.append(d["variant_note"])
    if d.get("image_files"):
        many = len(d["image_files"]) > 1
        what = "a picture here as well as text" if d["exp"] else "a picture here instead of text"
        lines.append(f"Expected result image{'s' if many else ''}: {', '.join(d['image_files'])} (the source has {what}; images cannot be imported, so attach {'them' if many else 'it'} to the last step in ADO)")
    for col, fpath in d.get("other_files", []):
        lines.append(f"Picture in the {col} cell: {fpath} (images cannot be imported; attach it to the step it belongs to in ADO)")
    return "\n".join(lines)


def est_height(pairs):
    lines = 1
    for text, width in pairs:
        if not text:
            continue
        n = sum(max(1, -(-len(p) // max(1, int(width * 1.05)))) for p in str(text).split("\n"))
        lines = max(lines, n)
    return min(409, 15 * lines + 4)


def write_sheet(wb, name, cases):
    ws = wb.create_sheet(name)
    ws.append(HEADERS)
    for i, w in enumerate(WIDTHS, 1):
        ws.column_dimensions[get_column_letter(i)].width = w
    for cell in ws[1]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="1F3864")
        cell.alignment = Alignment(vertical="center", wrap_text=True)
    wrap = Alignment(wrap_text=True, vertical="top")
    for d in cases:
        desc = description(d)
        ws.append([None, "Test Case", d["title"], None, None, None, AREA, None, STATE, desc])
        ws.row_dimensions[ws.max_row].height = est_height([(d["title"], 42), (desc, 55)])
        last = len(d["actions"])
        for n, act in enumerate(d["actions"], 1):
            exp = d["exp"] if n == last else None
            ws.append([None, None, None, n, act, exp, None, None, None, None])
            ws.row_dimensions[ws.max_row].height = est_height([(act, 85), (exp, 75)])
    for row in ws.iter_rows(min_row=2):
        for cell in row:
            cell.alignment = wrap
    ws.freeze_panes = "A2"


def read_me(wb, feature, src_name, variants, legacy, bilingual, has_images):
    ws = wb.active
    ws.title = "Read Me"
    names = [v["name"] for v in variants]
    summary = "Each sheet contains " + " / ".join(f"{len(v['cases'])} test cases ({v['name']})" for v in variants) + "."
    if legacy:
        purpose = f"Prepared from the EN and FR worksheets in {src_name}."
        imp = "Import EN Import and FR Import separately in Azure DevOps. " + summary
        important = "Import only the language sheet you want in the selected suite. Importing both creates EN and FR test cases. Delete earlier imports of the same file first to avoid duplicates."
    else:
        srcs = sorted({v["src_sheet"] for v in variants})
        purpose = f"Prepared from the worksheet(s) {', '.join(repr(s) for s in srcs)} in {src_name}."
        imp = "Import each sheet separately in Azure DevOps (one sheet per target suite). " + summary
        important = "Import only the sheet you want in the selected suite. Delete earlier imports of the same file first to avoid duplicates."
    rows = [
        (f"Azure DevOps Test Case Import Workbook: {feature}", None),
        ("Purpose", purpose),
        ("Import sheets", imp),
        ("Required headers", "ID, Work Item Type, Title, Test Step, Step Action, Step Expected, Area Path, Assigned To, State (Description is an extra column; untick it in the mapping screen if ADO rejects it)."),
        ("New test cases", "ID is blank so ADO creates new test cases. Do not enter existing IDs unless you intend to update those cases."),
        ("Assigned To", "Blank. Enter a valid ADO identity if your organization requires an assignee."),
        ("Layout", "Two kinds of rows per test case. Title row: Work Item Type, Title, Area Path, State, Description. Step rows beneath it: Test Step, Step Action, Step Expected only. Test Step, Step Action and Step Expected must be on the same row."),
        ("Test steps", "Source pre-condition items are steps 1..n (one per step). The source Execution text follows: one step per number when it is a numbered list, otherwise one step per sentence. The Expected Result sits on the last step only. Source wording is unchanged."),
        ("Area Path", AREA),
        ("State", STATE),
        ("Important", important),
        ("Source mapping", "Title = the source description; Description = scenario ID, business requirement ID, scenario type, author, automated flag and automation notes where the source has them, plus the section heading and any other source columns (notes, comments...); Step Expected = source Expected Result."),
    ]
    if bilingual:
        rows.append(("English / French", "The source has one set of steps with the expected result in English and in French. EN Import carries the English expected result and FR Import the French one. The steps are the same in both because the source has no French steps."))
    if has_images:
        rows.append(("Images", "Some source cells contain pictures, not text. Those cases are named in the Description and the picture files are saved under attachments/ next to this workbook. Attach them in ADO after importing (Expected Result pictures to the last step)."))
    for r in rows:
        ws.append(list(r))
    ws["A1"].font = Font(bold=True, size=14)
    for r in range(2, ws.max_row + 1):
        ws.cell(r, 1).font = Font(bold=True)
        ws.cell(r, 2).alignment = Alignment(wrap_text=True, vertical="top")
        ws.cell(r, 1).alignment = Alignment(vertical="top")
    ws.column_dimensions["A"].width = 22
    ws.column_dimensions["B"].width = 120


def has_label(path):
    try:
        with zipfile.ZipFile(path) as z:
            return LABEL in z.namelist()
    except (OSError, zipfile.BadZipFile):
        return False


def label_bytes(label_from, src):
    """The Microsoft sensitivity label to put on a new workbook, in order of preference: the workbook named by --label-from
    (or the first labelled workbook in imports/), the source's own label, else the copy bundled next to this script / inside the exe."""
    for path in (label_from, src):
        if path and has_label(path):
            with zipfile.ZipFile(path) as z:
                return z.read(LABEL)
    for base in (getattr(sys, "_MEIPASS", None), os.path.dirname(os.path.abspath(__file__))):
        if base and os.path.isfile(os.path.join(base, "LabelInfo.xml")):
            with open(os.path.join(base, "LabelInfo.xml"), "rb") as fh:
                return fh.read()
    return None


class NotATestDocument(Exception):
    pass


# ---------- planning: which sheets, which columns, which language variants ----------
def plan_variants(wb, notes):
    """Decide which worksheets are test sheets and which import sheets to build from them."""
    found, diag = [], []
    for ws in wb.worksheets:
        hdr = find_header(ws)
        if hdr["ok"]:
            if ws.sheet_state != "visible":
                notes.append(f"hidden sheet {ws.title!r} looks like a test sheet and was ignored")
                continue
            fix_swapped_type_author(ws, hdr, notes)
            for _h, _f in hdr.get("fuzzy", []):
                if _f in hdr["cols"] or _f == "exp":
                    notes.append(f"{ws.title}: header {_h!r} looks misspelled; read it as {FIELD_NAMES.get(_f, _f)} (check column_map)")
            if hdr.get("id_guess"):
                notes.append(f"{ws.title}: no column is named like a test case ID; used {hdr['id_guess']!r} as the ID column (check column_map)")
            found.append((ws, hdr))
        else:
            diag.append(f"{ws.title!r} (best header row matched {hdr['score']} known column(s); missing: {', '.join(FIELD_NAMES[k] for k in hdr['missing'])})")
            if hdr["score"] >= 2 and ws.sheet_state == "visible":   # looks like a test sheet with unfamiliar headers: never drop it silently
                notes.append(f"sheet {ws.title!r} was NOT imported: it has some test-case headers but is missing {', '.join(FIELD_NAMES[k] for k in hdr['missing'])}")
    legacy = [(ws, h) for ws, h in found if ws.title in dict(LANGS)]
    variants = []
    if legacy:
        for lang, sheet in LANGS:
            m = next(((ws, h) for ws, h in legacy if ws.title == lang), None)
            if m is None:
                notes.append(f"sheet {lang} not found")
                continue
            variants.append(dict(name=sheet, tag=lang, ws=m[0], hdr=m[1], src_sheet=lang, exp_key="exp", skip=(), first=True, prefix=lang))
        for ws, h in found:
            if ws.title not in dict(LANGS):
                notes.append(f"sheet {ws.title!r} looks like a test sheet but was not used (this workbook has EN/FR sheets)")
        return variants, True, False, diag
    if not found:
        return [], False, False, diag
    multi = len(found) > 1
    bilingual, taken = False, set()

    def unique(n):
        n = re.sub(r"[\[\]:*?/\\]", " ", n).strip()[:31]
        base, k = n, 2
        while n.lower() in taken:
            n = f"{base[:28]} {k}"
            k += 1
        taken.add(n.lower())
        return n

    for ws, h in found:
        title = ws.title.strip()
        c = h["cols"]
        fr = c.get("exp_fr")
        if fr is not None and not has_content(ws, h, fr):
            notes.append(f"{title}: the French expected-result column is empty, so only one import sheet was built")
            fr = None
        if fr is not None:
            bilingual = True
            en_name = unique(f"{title[:20]} EN" if multi else "EN Import")
            fr_name = unique(f"{title[:20]} FR" if multi else "FR Import")
            pre = (slug(title, 16) + "_") if multi else ""
            variants.append(dict(name=en_name, tag=f"{title} (EN)", ws=ws, hdr=h, src_sheet=title, exp_key="exp", skip=(fr,), first=True, prefix=pre + "EN",
                                 variant_note="Expected result language: English (the source has English and French expected results; this is the English case)"))
            variants.append(dict(name=fr_name, tag=f"{title} (FR)", ws=ws, hdr=h, src_sheet=title, exp_key="exp_fr", skip=(c["exp"],), first=False, prefix=pre + "FR",
                                 variant_note="Expected result language: French (same steps as the English case; the source has no French steps)"))
        else:
            variants.append(dict(name=unique(f"{title[:24]} Import" if multi else "Import"), tag=title, ws=ws, hdr=h, src_sheet=title, exp_key="exp", skip=(), first=True,
                                 prefix=slug(title, 24) if multi else slug(title, 24)))
    return variants, False, bilingual, diag


def column_map(variants):
    out, seen = [], set()
    for v in variants:
        if v["src_sheet"] in seen:
            continue
        seen.add(v["src_sheet"])
        h = v["hdr"]
        pairs = [f"{k}={h['headers'][i]!r}" for k, i in h["cols"].items() if i is not None and i < len(h["headers"])]
        out.append(f"{v['src_sheet']} (header row {h['row']}): " + ", ".join(pairs))
    return " || ".join(out)


# ---------- converting one workbook ----------
def convert(src, out, feature, label_from=None, dry_run=False):
    """Convert one source workbook. Returns a dict describing what was built, including review notes."""
    swb = openpyxl.load_workbook(src)
    imgs, unanchored = extract_images(src)
    notes = []
    variants, legacy, bilingual, diag = plan_variants(swb, notes)
    if not variants:
        shown = diag[:4] + ([f"... and {len(diag) - 4} more sheet(s)"] if len(diag) > 4 else [])
        raise NotATestDocument("no test sheet recognised (if this IS a test document, send this message and the document to the person who maintains the tool). Sheets looked at: " + ("; ".join(shown) if shown else "none"))
    for v in variants:
        v["cases"] = read_cases(v["ws"], v["hdr"], v["tag"], imgs.get(v["src_sheet"], []), notes,
                                v["exp_key"], v["skip"], v["first"])
        for d in v["cases"]:
            if d["auto"] is not None or "auto" in d["cols"]:
                d["auto_label"] = "Automatable" if re.match(r"automatable", v["hdr"]["headers"][v["hdr"]["cols"]["auto"]].lower()) else "Automated"
            if v.get("variant_note"):
                d["variant_note"] = v["variant_note"]
    used_sheets = {v["src_sheet"] for v in variants}
    ref_pics = [(sh, data, ext) for sh, lst_ in imgs.items() if sh not in used_sheets for (_, _, data, ext) in lst_]
    notes += analyse(variants, declared_counts(src), legacy, sum(unanchored.values()))
    if AREA == AREA_PLACEHOLDER:
        notes.append("Area Path is still the placeholder 'Project\\Area\\Path': copy scripts/local_config.example.json to local_config.json and set area_path, then convert again")
    if ref_pics:
        names = sorted({sh for sh, _, _ in ref_pics})
        notes.append(f"{len(ref_pics)} picture(s) on non-test sheet(s) {names} saved to attachments/ as reference screenshots; attach where they belong")
    info = dict(variants=variants, result={v["name"]: v["cases"] for v in variants}, notes=notes, out=out, legacy=legacy,
                sheets=sorted(used_sheets), column_map=column_map(variants))
    if dry_run:
        return info

    att_root = os.path.join(os.path.dirname(os.path.abspath(out)), "attachments", os.path.splitext(os.path.basename(out))[0])

    def save(name, data):
        os.makedirs(att_root, exist_ok=True)
        with open(os.path.join(att_root, name), "wb") as fh:
            fh.write(data)
        return f"attachments/{os.path.basename(att_root)}/{name}"

    for v in variants:
        for d in v["cases"]:
            base = f"{v['prefix']}_{slug(d['id'], 120) if d['id'] else 'row' + str(d['row'])}"
            d["image_files"] = [save(f"{base}{'_' + str(k) if len(d['images']) > 1 else ''}.{ext}", data)
                                for k, (data, ext) in enumerate(d["images"], 1)]
            d["other_files"] = []
            for k, (col, data, ext) in enumerate(d["other_images"], 1):
                s = re.sub(r"[^a-z0-9]+", "_", col.lower()).strip("_")
                d["other_files"].append((col, save(f"{base}_{s}{'_' + str(k) if len(d['other_images']) > 1 else ''}.{ext}", data)))
    for n, (sh, data, ext) in enumerate(ref_pics, 1):
        save(f"reference_sheet_{slug(sh, 30)}_{n}.{ext}", data)
    wb = openpyxl.Workbook()
    read_me(wb, feature, os.path.basename(src), variants, legacy, bilingual,
            any(d["images"] or d["other_images"] for v in variants for d in v["cases"]) or bool(ref_pics))
    for v in variants:
        write_sheet(wb, v["name"], v["cases"])
    fd, tmp = tempfile.mkstemp(suffix=".xlsx", prefix="ado_import_build_")
    os.close(fd)
    wb.save(tmp)
    label_data = label_bytes(label_from, src)
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    with zipfile.ZipFile(tmp) as zt, zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zo:
        for item in zt.infolist():
            data = zt.read(item.filename)
            if label_data:
                if item.filename == "[Content_Types].xml":
                    data = data.replace(b"</Types>", b'<Override PartName="/docMetadata/LabelInfo.xml" ContentType="application/vnd.ms-office.classificationlabels+xml"/></Types>')
                if item.filename == "_rels/.rels":
                    data = data.replace(b"</Relationships>", b'<Relationship Id="rIdLbl" Type="http://schemas.microsoft.com/office/2020/02/relationships/classificationlabels" Target="docMetadata/LabelInfo.xml"/></Relationships>')
            zo.writestr(item, data)
        if label_data:
            zo.writestr(LABEL, label_data)
    try:
        os.remove(tmp)
    except OSError:
        pass
    info["label"] = bool(label_data)
    return info


# ---------- batch mode ----------
def slugify(stem):
    return re.sub(r"[^A-Za-z0-9]+", "_", stem).strip("_")


def source_files(source_dir):
    """Everything in source/ except Excel lock files (~$...) and hidden files."""
    return [fn for fn in sorted(os.listdir(source_dir))
            if os.path.isfile(os.path.join(source_dir, fn)) and not fn.startswith(("~$", "."))]


def existing_versions(imports_dir, fn):
    """Version numbers of the import workbooks already built from source file fn."""
    slug_ = slugify(os.path.splitext(fn)[0])
    return [int(re.search(r"_V(\d+)\.xlsx$", e).group(1))
            for e in glob.glob(os.path.join(imports_dir, f"{slug_}_AzureDevOps_Import_V*.xlsx"))]


def default_label(imports_dir):
    """The first workbook in imports/ that carries the Microsoft sensitivity label (new workbooks copy it)."""
    if os.path.isdir(imports_dir):
        return next((f for f in sorted(glob.glob(os.path.join(imports_dir, "*.xlsx")))
                     if not os.path.basename(f).startswith("~$") and has_label(f)), None)
    return None


def convert_file(fn, source_dir, imports_dir, force=False, dry_run=False, label_from=None):
    """Convert one file from source/. Never raises: always returns a report row (see write_report for the columns)."""
    path = os.path.join(source_dir, fn)
    row = dict(source=fn, import_file="", area_path=AREA, status="", cases="", steps_per_case="", review="", sheets_used="", column_map="", notes="")
    if not fn.lower().endswith(".xlsx"):
        row["status"] = "skipped: not an .xlsx file (save older .xls / .xlsm files as .xlsx first)"
        return row
    versions = existing_versions(imports_dir, fn)
    if versions and not force:
        row["status"] = f"skipped: already converted (V{max(versions)}); use --force for a new version"
        return row
    slug_ = slugify(os.path.splitext(fn)[0])
    out_name = f"{slug_}_AzureDevOps_Import_V{max(versions, default=0) + 1}.xlsx"
    feature = re.sub(r"\s+", " ", os.path.splitext(fn)[0].replace("_", " ")).strip()
    try:
        info = convert(path, os.path.join(imports_dir, out_name), feature, label_from, dry_run)
    except NotATestDocument as e:
        row["status"] = f"skipped: {e}. This is not a test document, or its headers are not recognised (move it out of source/ if it never will be)"
        row["review"] = "yes"
        return row
    except PermissionError:
        row["status"] = "FAILED: cannot open the file (is it open in Excel? close it and run again)"
        row["review"] = "yes"
        return row
    except Exception as e:  # keep going: one bad file must not stop the batch
        row["status"] = f"FAILED: {type(e).__name__}: {e}"
        row["review"] = "yes"
        return row
    vs = info["variants"]
    row["import_file"] = out_name
    row["status"] = "analysed only (dry run)" if dry_run else "built"
    row["cases"] = "; ".join(f"{v['name']}: {len(v['cases'])}" for v in vs)
    row["steps_per_case"] = "/".join(str(x) for x in sorted({len(d["actions"]) for v in vs for d in v["cases"]}))
    row["sheets_used"] = ", ".join(info["sheets"])
    row["column_map"] = info["column_map"]
    row["review"] = "yes" if info["notes"] else "no"
    row["notes"] = " | ".join(info["notes"])
    return row


def run_all(source_dir, imports_dir, force, dry_run, label_from, only=None, progress=None):
    """Convert every file in source/ (or just the names in `only`). progress(i, n, row) is called after each file."""
    rows = []
    label_from = label_from or default_label(imports_dir)
    names = [fn for fn in source_files(source_dir) if only is None or fn in only]
    for i, fn in enumerate(names, 1):
        row = convert_file(fn, source_dir, imports_dir, force, dry_run, label_from)
        rows.append(row)
        if progress:
            progress(i, len(names), row)
    return rows


def write_report(rows, folder):
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, "conversion_report_" + datetime.datetime.now().strftime("%Y%m%d_%H%M%S") + ".csv")
    cols = ["source", "import_file", "area_path", "status", "cases", "steps_per_case", "review", "sheets_used", "column_map", "notes"]
    with open(path, "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    return path


def main():
    try:
        sys.stdout.reconfigure(errors="replace")
    except Exception:
        pass
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("source", nargs="?")
    ap.add_argument("output", nargs="?")
    ap.add_argument("feature", nargs="?")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--label-from")
    ap.add_argument("--area", help="ADO Area Path to write on every test case (default: scripts/local_config.json)")
    ap.add_argument("--source-dir")
    ap.add_argument("--imports-dir")
    ap.add_argument("--reports-dir")
    a = ap.parse_args()
    if a.area:
        set_area(a.area)
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    if a.all:
        sdir = a.source_dir or os.path.join(root, "source")
        idir = a.imports_dir or os.path.join(root, "imports")
        rows = run_all(sdir, idir, a.force, a.dry_run, a.label_from)
        for r in rows:
            print(f"{r['source']}\n    -> {r['status']}" + (f" | {r['cases']}; steps per case {r['steps_per_case']}" if r["cases"] else ""))
            if r["notes"]:
                for n in r["notes"].split(" | "):
                    print("       note:", n)
        built = sum(1 for r in rows if r["status"] == "built")
        print(f"\n{len(rows)} file(s) found: {built} built, {sum(1 for r in rows if r['status'].startswith('skipped'))} skipped, "
              f"{sum(1 for r in rows if r['status'].startswith('FAILED'))} failed, {sum(1 for r in rows if r['review'] == 'yes')} need review.")
        if rows and not a.dry_run:
            print("Review report:", write_report(rows, a.reports_dir or os.path.join(root, "reports")))
        return
    if not (a.source and a.output and a.feature):
        ap.error("give <source.xlsx> <output.xlsx> \"<Feature title>\", or use --all")
    info = convert(a.source, a.output, a.feature, a.label_from, a.dry_run)
    for v in info["variants"]:
        cases = v["cases"]
        print(f"{v['name']}: {len(cases)} cases, {sum(len(d['actions']) for d in cases)} step rows, steps per case {sorted({len(d['actions']) for d in cases})}")
    for n in info["notes"]:
        print("  note:", n)
    print("label carried over:", info.get("label"))


if __name__ == "__main__":
    main()
