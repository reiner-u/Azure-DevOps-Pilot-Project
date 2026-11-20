"""The Microsoft sensitivity label on the workbooks, and saving a finished workbook.

Test documents carry a Government of Ontario sensitivity label (a small XML part inside the .xlsx zip). openpyxl does not
know about it, so it is added to the saved file afterwards by rewriting the zip. New workbooks get the label from, in order:
  1. the workbook named by --label-from, or the first labelled workbook already in the Converted to ADO folder;
  2. the source document's own label;
  3. a copy bundled next to the scripts (scripts/LabelInfo.xml) or inside the exe, so a colleague with empty folders
     still gets labelled output.
"""
import glob
import os
import tempfile
import zipfile

from .settings import bundled_file

LABEL_PART = "docMetadata/LabelInfo.xml"
_CONTENT_TYPE_OVERRIDE = (b'<Override PartName="/docMetadata/LabelInfo.xml" '
                          b'ContentType="application/vnd.ms-office.classificationlabels+xml"/>')
_RELATIONSHIP = (b'<Relationship Id="rIdLbl" Type="http://schemas.microsoft.com/office/2020/02/relationships/'
                 b'classificationlabels" Target="docMetadata/LabelInfo.xml"/>')


def has_label(path):
    """True if this .xlsx carries a sensitivity label."""
    try:
        with zipfile.ZipFile(path) as archive:
            return LABEL_PART in archive.namelist()
    except (OSError, zipfile.BadZipFile):
        return False


def first_labelled_workbook(folder):
    """The first workbook in a folder that carries the label (new workbooks copy it), or None."""
    if not os.path.isdir(folder):
        return None
    return next((path for path in sorted(glob.glob(os.path.join(folder, "*.xlsx")))
                 if not os.path.basename(path).startswith("~$") and has_label(path)), None)


def label_bytes(label_from, source):
    """The label to put on a new workbook (see the module docstring for the order), or None when there is none."""
    for path in (label_from, source):
        if path and has_label(path):
            with zipfile.ZipFile(path) as archive:
                return archive.read(LABEL_PART)
    bundled = bundled_file("LabelInfo.xml")
    if bundled:
        with open(bundled, "rb") as fh:
            return fh.read()
    return None


def save_workbook(workbook, out_path, label_data):
    """Save an openpyxl workbook to out_path, adding the sensitivity label when label_data is given."""
    fd, temp_path = tempfile.mkstemp(suffix=".xlsx", prefix="ado_import_build_")
    os.close(fd)
    workbook.save(temp_path)
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    with zipfile.ZipFile(temp_path) as plain, zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as labelled:
        for item in plain.infolist():
            data = plain.read(item.filename)
            if label_data:
                if item.filename == "[Content_Types].xml":
                    data = data.replace(b"</Types>", _CONTENT_TYPE_OVERRIDE + b"</Types>")
                if item.filename == "_rels/.rels":
                    data = data.replace(b"</Relationships>", _RELATIONSHIP + b"</Relationships>")
            labelled.writestr(item, data)
        if label_data:
            labelled.writestr(LABEL_PART, label_data)
    try:
        os.remove(temp_path)
    except OSError:
        pass
