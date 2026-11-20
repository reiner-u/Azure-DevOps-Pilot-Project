#!/usr/bin/env python3
"""Command-line entry point of the converter: python scripts\\build_import_from_source.py --all   (or --help for everything).

The code itself is in the converter/ folder next to this file; see converter/__init__.py for a map of its modules. This file
only exists so the command (and convert_all.bat) keeps working.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from converter.cli import main

if __name__ == "__main__":
    main()
