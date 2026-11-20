"""Splitting a Pre-condition or Execution cell into steps.

A cell can hold "1. Open the page 2. Click Save" on one line, one numbered item per line, or plain sentences. The rules:

  * A clean numbered list runs 1, 2, 3... from the start of the cell. It gives one step per number, numbers removed.
  * Several lines that each start with a number, but not as a clean 1..n run (a repeated or skipped number), give one step
    per line. The review notes flag these so a person checks the steps ("renumbered").
  * Anything else: Pre-conditions give one step per line, Execution gives one step per sentence.

Bullets and dashes are not structure; they stay inside the step they sit under.
"""
import re
from typing import NamedTuple

from .text import norm

# A step number is digits plus "." or ")", followed by a space, or directly by a letter, quote or bracket ("1.User clicks...").
# "1.5" and "1.1 Check" are not step numbers. The list must still run 1, 2, 3... from the start of the cell to count as
# numbered, which is what keeps version numbers and decimals inside a sentence from splitting it.
NUMBER = re.compile(r"(?:^|\s)(\d+)[.)](?:\s+|(?=[A-Za-z\"“‘'(<\[]))")
LEADING_NUMBER = re.compile(r"^\s*\d+[.)]\s*")

# How an Execution cell was split (ExecutionSplit.numbering)
NUMBERED = "numbered"            # a clean 1..n list
RENUMBERED = "renumbered"        # every line starts with a number but the run is not a clean 1..n
NOT_NUMBERED = "not numbered"    # split by sentence (or the cell is empty)


class PreconditionSplit(NamedTuple):
    steps: list
    fell_back: bool              # True when the cell was not a clean numbered list and was split by line instead


class ExecutionSplit(NamedTuple):
    steps: list
    numbering: str               # NUMBERED, RENUMBERED or NOT_NUMBERED
    multiline: bool              # True when an unnumbered cell had several lines (and was still split by sentence)


def split_numbered_lines(text):
    """One step per line when several lines each start with a number but are not a clean 1..n run, else None."""
    lines = [line for line in str(text).splitlines() if line.strip()]
    if len(lines) >= 2 and all(LEADING_NUMBER.match(line) for line in lines):
        return [norm(LEADING_NUMBER.sub("", line)) for line in lines]
    return None


def split_numbered(text):
    """The items of a clean '1. ... 2. ...' or '1) ... 2) ...' list (1..n in order), else None."""
    parts = NUMBER.split(str(text).strip())      # ['', '1', 'first item', '2', 'second item', ...]
    if len(parts) >= 3 and parts[0] == "":
        numbers, items = parts[1::2], parts[2::2]
        if numbers == [str(i) for i in range(1, len(numbers) + 1)]:
            return [norm(item) for item in items]
    return None


def split_precondition(text):
    """Numbered items become steps; otherwise one step per line (fell_back is True if that gave several steps)."""
    if not text or not str(text).strip():
        return PreconditionSplit([], False)
    items = split_numbered(text)
    if items is not None:
        return PreconditionSplit(items, False)
    items = split_numbered_lines(text)
    if items is not None:
        return PreconditionSplit(items, True)
    lines = [norm(line) for line in str(text).splitlines() if line.strip()]
    return PreconditionSplit(lines, len(lines) > 1)


def split_execution(text):
    """A numbered list gives one step per number; otherwise one step per sentence."""
    if not text or not str(text).strip():
        return ExecutionSplit([], NOT_NUMBERED, False)
    items = split_numbered(text)
    if items is not None:
        return ExecutionSplit(items, NUMBERED, False)
    items = split_numbered_lines(text)
    if items is not None:
        return ExecutionSplit(items, RENUMBERED, False)
    text = str(text).strip()
    sentences = [norm(part) for part in re.split(r"(?<=[.!?])\s+", text) if part.strip()]
    several_lines = len([line for line in text.splitlines() if line.strip()]) > 1
    return ExecutionSplit(sentences, NOT_NUMBERED, several_lines)
