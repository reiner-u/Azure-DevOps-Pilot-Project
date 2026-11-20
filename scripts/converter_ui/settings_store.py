"""The window's remembered choices: the three folders and the editable part of the Area Path (gui_settings.json)."""
import json
import os

from converter import area

from .paths import DEFAULT_FOLDERS, ROOT, SETTINGS_FILE


def load():
    """The saved choices, or {} when there is no readable settings file."""
    try:
        with open(SETTINGS_FILE, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def save(source, imports, reports, area_rest):
    try:
        with open(SETTINGS_FILE, "w", encoding="utf-8") as fh:
            json.dump(dict(source=source, imports=imports, reports=reports, area_rest=area_rest), fh, indent=1)
    except OSError:
        pass


def remembered_folder(saved, key):
    """A remembered folder, unless it no longer exists (e.g. the tool was copied to another computer): then the default."""
    folder = saved.get(key)
    return folder if folder and os.path.isdir(folder) else os.path.join(ROOT, DEFAULT_FOLDERS[key])


def remembered_area_rest(saved):
    """The editable part of the Area Path to start with."""
    rest = saved.get("area_rest")
    if rest is None and saved.get("area"):          # an older settings file kept the whole path
        rest = area.rest_of(saved["area"])
    return area.DEFAULT_REST if rest is None else rest
