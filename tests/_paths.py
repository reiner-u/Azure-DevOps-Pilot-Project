"""Imported first by every test file: makes the converter packages importable and keeps tests from writing .pyc files."""
import os
import sys

sys.dont_write_bytecode = True
SCRIPTS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts")
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)
