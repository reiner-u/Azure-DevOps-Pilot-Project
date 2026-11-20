"""Made-up test documents for the tests. Nothing here is real OSAP content: the cases are invented.

write_workbook(path, {"Sheet name": [header row, case row, ...]}) builds an ALM-style workbook;
add_picture(path, row0, col0) puts a tiny picture in a cell of its first sheet (without Pillow, by editing the zip);
add_label(path) gives the workbook a fake sensitivity label part.
"""
import base64
import zipfile

import openpyxl

HEADERS = ["Test Scenario ID", "Business Requirement ID", "Description", "Pre-condition", "Execution", "Expected Result",
           "Type", "Author", "Automated"]
TINY_PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==")
LABEL_XML = b'<?xml version="1.0"?><clbl:labelList xmlns:clbl="http://schemas.microsoft.com/office/2020/mipLabelMetadata"/>'


def case(number, **changes):
    """A row for HEADERS. Pass column values by these names: id, br, title, pre, exe, exp, type, author, auto."""
    values = dict(id=f"DEMO_Login_{number:03d}", br=f"BR_{number:03d}", title=f"Sign in, variant {number}",
                  pre="1. Open the sign-in page 2. Have an active account",
                  exe="1. Enter the user name 2. Enter the password 3. Click Sign in",
                  exp="The home page is shown", type="Manual", author="A. Tester", auto="No")
    values.update(changes)
    return [values[k] for k in ("id", "br", "title", "pre", "exe", "exp", "type", "author", "auto")]


def write_workbook(path, sheets, hidden=()):
    """Write a workbook with one sheet per entry of `sheets` ({name: rows}); names in `hidden` are hidden sheets."""
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    for name, rows in sheets.items():
        ws = wb.create_sheet(name)
        for row in rows:
            ws.append(row)
        if name in hidden:
            ws.sheet_state = "hidden"
    wb.save(path)
    return path


def simple_document(path, *cases, sheet="Test Cases"):
    """A one-sheet document with the standard headers and the given case rows."""
    return write_workbook(path, {sheet: [HEADERS, *cases]})


def _rewrite(path, extra_parts):
    """Rewrite the xlsx zip with extra parts added (a dict {part name: bytes})."""
    with zipfile.ZipFile(path) as source:
        kept = {item.filename: source.read(item.filename) for item in source.infolist()}
    kept.update(extra_parts)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as target:
        for name, data in kept.items():
            target.writestr(name, data)


def add_picture(path, row0, col0, png=TINY_PNG):
    """Put a picture at a 0-based row and column of the workbook's first sheet."""
    drawing = (
        '<xdr:wsDr xmlns:xdr="http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing" '
        'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><xdr:oneCellAnchor><xdr:from>'
        f'<xdr:col>{col0}</xdr:col><xdr:colOff>0</xdr:colOff><xdr:row>{row0}</xdr:row><xdr:rowOff>0</xdr:rowOff></xdr:from>'
        '<xdr:ext cx="95250" cy="95250"/><xdr:pic><xdr:nvPicPr><xdr:cNvPr id="2" name="Picture 1"/><xdr:cNvPicPr/></xdr:nvPicPr>'
        '<xdr:blipFill><a:blip r:embed="rId1"/><a:stretch><a:fillRect/></a:stretch></xdr:blipFill><xdr:spPr><a:xfrm>'
        '<a:off x="0" y="0"/><a:ext cx="95250" cy="95250"/></a:xfrm><a:prstGeom prst="rect"><a:avLst/></a:prstGeom></xdr:spPr>'
        '</xdr:pic><xdr:clientData/></xdr:oneCellAnchor></xdr:wsDr>').encode()
    relationships = ('<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                     '<Relationship Id="rId1" Type="%s" Target="%s"/></Relationships>')
    base = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/"
    _rewrite(path, {
        "xl/worksheets/_rels/sheet1.xml.rels": (relationships % (base + "drawing", "../drawings/drawing1.xml")).encode(),
        "xl/drawings/drawing1.xml": drawing,
        "xl/drawings/_rels/drawing1.xml.rels": (relationships % (base + "image", "../media/image1.png")).encode(),
        "xl/media/image1.png": png,
    })


def add_label(path):
    """Give the workbook a (fake) sensitivity label part, as workbooks from SharePoint have."""
    _rewrite(path, {"docMetadata/LabelInfo.xml": LABEL_XML})
