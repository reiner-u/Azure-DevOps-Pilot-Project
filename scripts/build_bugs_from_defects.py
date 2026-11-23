"""ALM defect exports to Azure DevOps Bug import CSVs. Run with --help for the usage and the warnings.

This file only starts things: the work is in the `defects` package (see its __init__.py for the module map).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from defects.cli import main      # noqa: E402  (the path above has to be set first)

if __name__ == "__main__":
    sys.exit(main())
