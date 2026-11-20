"""Version, default folder names and the organisation-specific settings from scripts/local_config.json.

local_config.json is git-ignored on purpose: the ADO Area Path root and the work item State belong to one organisation and
must not end up in the code repository. scripts/local_config.example.json is the template. Inside the packaged exe the file
is bundled next to the code (build_exe.bat adds it when it exists).
"""
import json
import os
import sys

# Shown in the window's title bar. Bump it for every release (see CHANGELOG.md). build_exe.bat reads this exact line, so keep
# it as TOOL_VERSION = "..." on a line of its own, with no comment after it.
TOOL_VERSION = "2026.11.20"

# Folders used by default, next to the scripts' project folder or next to the exe.
SOURCE_DIRNAME = "To Convert"
IMPORTS_DIRNAME = "Converted to ADO"
REPORTS_DIRNAME = "reports"

SCRIPTS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))     # .../scripts
PROJECT_DIR = os.path.dirname(SCRIPTS_DIR)


def bundled_file(name):
    """Path of a support file (local_config.json, LabelInfo.xml): inside the exe's bundle when packaged, else in scripts/.
    None when it does not exist."""
    for base in (getattr(sys, "_MEIPASS", None), SCRIPTS_DIR):
        if base and os.path.isfile(os.path.join(base, name)):
            return os.path.join(base, name)
    return None


def load_local_config():
    """The settings from local_config.json, or {} when the file is missing or unreadable."""
    path = bundled_file("local_config.json")
    if path is None:
        return {}
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


LOCAL_CONFIG = load_local_config()
STATE = LOCAL_CONFIG.get("state") or "Design"        # the work item State written on every test case
