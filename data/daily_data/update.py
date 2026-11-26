#!/usr/bin/env python3
"""Compatibility entry for the permanent get_data.update implementation."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from get_data.update import main

if __name__ == "__main__":
    raise SystemExit(main())
