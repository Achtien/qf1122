"""Freeze exchange limit prices supplied by Tushare for the demonstration."""

import argparse
import csv
import gzip
import os
import sqlite3
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from get_data.get_daily import RateLimiter, TushareClient

FIELDS = ("trade_date", "ts_code", "up_limit", "down_limit")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", default="20240102")
    parser.add_argument("--end", default="20240229")
    parser.add_argument("--output", type=Path, default=Path(__file__).with_name("limits.csv.gz"))
    args = parser.parse_args()
    uri = (ROOT / "data/daily_data/daily_data.db").as_uri() + "?mode=ro"
    with sqlite3.connect(uri, uri=True) as db:
        days = [
            r[0]
            for r in db.execute(
                "SELECT cal_date FROM market_calendar WHERE exchange='SSE' AND is_open=1 "
                "AND cal_date BETWEEN ? AND ? ORDER BY cal_date",
                (args.start, args.end),
            )
        ]
        if not days:
            raise ValueError("empty date range")
        (prev,) = db.execute(
            "SELECT prev_trade_date FROM market_calendar WHERE exchange='SSE' AND cal_date=?", (days[0],)
        ).fetchone()
    token = os.environ.get("TUSHARE_TOKEN") or (ROOT / ".tushare_token").read_text().strip()
    client = TushareClient(token, RateLimiter())
    with tempfile.NamedTemporaryFile(dir=args.output.parent, suffix=".gz", delete=False) as temp:
        path = Path(temp.name)
    try:
        with gzip.open(path, "wt", newline="") as out:
            writer = csv.writer(out)
            writer.writerow(FIELDS)
            for day in [prev, *days]:
                fields, rows = client.query("stk_limit", {"trade_date": day}, FIELDS)
                if tuple(fields) != FIELDS or not rows or len(rows) >= 10000:
                    raise ValueError(f"incomplete limit response for {day}")
                codes = set()
                for row in rows:
                    if row[0] != day or row[1] in codes:
                        raise ValueError(f"invalid limit key on {day}")
                    codes.add(row[1])
                writer.writerows(sorted(rows, key=lambda row: row[1]))
        path.replace(args.output)
    except Exception as err:
        raise SystemExit(str(err).replace(token, "[redacted]")) from None
    finally:
        path.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
