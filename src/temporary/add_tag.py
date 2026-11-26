#!/usr/bin/env python3
"""One-time status migration. Implementation lives in permanent src modules."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from get_daily import main

if __name__ == "__main__":
    raise SystemExit(main(["--migrate-only", *sys.argv[1:]]))
