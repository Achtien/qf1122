#!/usr/bin/env python3
"""Repair historical tags and derived tables without downloading price history.

Defaults to cached sources, with no network or token requirement. Pass
--refresh-status to refresh historical names and suspensions from Tushare.
"""
from pathlib import Path
import sys

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from get_data.get_daily import main as get_daily_main


def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    defaults = ["--migrate-only"]
    if "--refresh-status" not in args:
        defaults.append("--offline")
    return get_daily_main([*defaults, *args])


if __name__ == "__main__":
    raise SystemExit(main())
