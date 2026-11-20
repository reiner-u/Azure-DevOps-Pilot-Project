"""Pictures embedded in a test document.

An .xlsx file is a zip of XML parts. Pictures are found by following the chain
    workbook.xml -> sheet -> drawing -> picture anchor (which cell it sits in) -> media file
so no imaging library (Pillow) is needed. ADO cannot import pictures, so the converter saves them next to the import workbook
and the Description names them; the person attaches them in ADO by hand.
"""
import posixpath
import xml.etree.ElementTree as ET
import zipfile

NS_SHEET = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
NS_REL = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
NS_DRAWING = "{http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing}"
NS_MAIN = "{http://schemas.openxmlformats.org/drawingml/2006/main}"


class _Package:
    """Read access to the parts of an xlsx zip and the relationships between them."""

    def __init__(self, archive):
        self.archive = archive
        self.names = set(archive.namelist())

    def read(self, part):
        return self.archive.read(part)

    def relationships(self, part):
        """{relationship id: (type, full path of the target part)} for one part (empty when it has none)."""
        folder, filename = part.rsplit("/", 1)
        rels_part = f"{folder}/_rels/{filename}.rels"
        if rels_part not in self.names:
            return {}
        found = {}
        for rel in ET.fromstring(self.read(rels_part)):
            if rel.get("TargetMode") == "External":
                continue
            target = rel.get("Target")
            full = target.lstrip("/") if target.startswith("/") else posixpath.normpath(posixpath.join(folder, target))
            found[rel.get("Id")] = (rel.get("Type"), full)
        return found

    def drawings_of_sheets(self):
        """Yield (sheet name, drawing part) for every drawing attached to a sheet."""
        workbook_rels = self.relationships("xl/workbook.xml")
        for sheet in ET.fromstring(self.read("xl/workbook.xml")).find(NS_SHEET + "sheets"):
            name, rel_id = sheet.get("name"), sheet.get(NS_REL + "id")
            if rel_id not in workbook_rels:
                continue
            for rel_type, target in self.relationships(workbook_rels[rel_id][1]).values():
                if rel_type.endswith("/drawing") and target in self.names:
                    yield name, target

    def pictures_in_drawing(self, drawing_part):
        """Yield (row0, col0, media part) for each picture; row0/col0 are None when the picture is not tied to a cell."""
        media_by_id = self.relationships(drawing_part)
        for anchor in ET.fromstring(self.read(drawing_part)):
            start = anchor.find(NS_DRAWING + "from")
            for blip in anchor.iter(NS_MAIN + "blip"):
                embed_id = blip.get(NS_REL + "embed")
                if embed_id not in media_by_id or media_by_id[embed_id][1] not in self.names:
                    continue
                media = media_by_id[embed_id][1]
                if start is None:
                    yield None, None, media
                else:
                    yield int(start.find(NS_DRAWING + "row").text), int(start.find(NS_DRAWING + "col").text), media


def extract_images(path):
    """Read the pictures of a workbook.

    Returns (anchored, unanchored):
      anchored   {sheet name: [(row0, col0, picture bytes, file extension)]} with 0-based row and column of the anchor cell
      unanchored {sheet name: how many pictures are not tied to any cell}
    """
    anchored, unanchored = {}, {}
    with zipfile.ZipFile(path) as archive:
        package = _Package(archive)
        if "xl/workbook.xml" not in package.names:
            return anchored, unanchored
        for sheet_name, drawing in package.drawings_of_sheets():
            for row0, col0, media in package.pictures_in_drawing(drawing):
                if row0 is None:
                    unanchored[sheet_name] = unanchored.get(sheet_name, 0) + 1
                else:
                    anchored.setdefault(sheet_name, []).append(
                        (row0, col0, package.read(media), media.rsplit(".", 1)[-1].lower()))
    return anchored, unanchored
