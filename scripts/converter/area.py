"""The ADO Area Path written on every test case.

An Area Path is ROOT\\rest. The root (the ADO project's own area, the same for everyone) is fixed in the window and comes from
local_config.json ("area_root"); the rest is typed per run, and local_config.json ("area_rest") gives its default. An older
config with only "area_path" is split at its first backslash. The Area Path must already exist in ADO or the import rejects it.
"""
import re

from . import settings

PLACEHOLDER = "Project\\Area\\Path"       # what you get when there is no local_config.json


def tidy(path):
    """Area Paths use backslashes: turn forward slashes into backslashes and remove doubled or edge backslashes."""
    return re.sub(r"\\+", r"\\", (path or "").strip().replace("/", "\\")).strip("\\")


_config = settings.LOCAL_CONFIG
_old_style_path = tidy(_config.get("area_path"))

ROOT = tidy(_config.get("area_root")) or (_old_style_path.split("\\")[0] if _old_style_path else "Project")
DEFAULT_REST = (tidy(_config.get("area_rest")) if "area_rest" in _config
                else (_old_style_path.partition("\\")[2] if _old_style_path else "Area\\Path"))


def compose(rest):
    """ROOT, or ROOT\\rest. A copy of the root typed at the start of the box is not repeated."""
    rest = tidy(rest)
    if rest.lower() == ROOT.lower():
        rest = ""
    elif rest.lower().startswith(ROOT.lower() + "\\"):
        rest = rest[len(ROOT) + 1:]
    return ROOT + ("\\" + rest if rest else "")


DEFAULT = compose(DEFAULT_REST)


def resolve(path):
    """The full Area Path for a path given on the command line: blank means the configured default; a path that does not
    start with the root gets the root put in front."""
    path = tidy(path)
    return compose(path) if path else DEFAULT


def rest_of(full_path):
    """The part after the root (what the window's editable box holds) for a full Area Path."""
    return compose(full_path)[len(ROOT) + 1:]
