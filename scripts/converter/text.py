"""Small text helpers shared by the whole converter."""
import re

MAX_TITLE_LENGTH = 128        # ADO rejects test case titles longer than this


def norm(s):
    """Collapse every run of whitespace (line breaks included) to one space."""
    return re.sub(r"\s+", " ", str(s)).strip()


def clean(value):
    """A cell value as stripped text, or None for an empty cell."""
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def tidy_lines(value):
    """Keep a multi-line value's line breaks, but drop blank lines and the spaces around each line."""
    return "\n".join(line.strip() for line in str(value).splitlines() if line.strip())


def slug(text, limit=None):
    """Letters and digits only, other runs become '_' (for file names). `limit` cuts the result to that many characters."""
    return re.sub(r"[^A-Za-z0-9]+", "_", str(text)).strip("_")[:limit]


def short_id(scenario_id):
    """The last part of a scenario ID ('Module_Screen_001' -> '001'), which is how review notes name a case."""
    return str(scenario_id).rsplit("_", 1)[-1]


def list_for_note(items, limit=12):
    """A list as shown in a review note, cut after `limit` items: ['001', '002', ... +5 more]."""
    items = list(items)
    text = repr(items[:limit])
    return text if len(items) <= limit else text[:-1] + f", ... +{len(items) - limit} more]"


def shorten_title(title, limit=MAX_TITLE_LENGTH):
    """Cut a title to fit ADO's limit at a word boundary and add '...' (the full text is kept in the Description)."""
    if len(title) <= limit:
        return title
    cut = title[:limit - 3]
    last_space = cut.rfind(" ")
    if last_space > limit * 0.6:       # only cut at a space if that does not throw away too much
        cut = cut[:last_space]
    return cut.rstrip(" ,;:-") + "..."
