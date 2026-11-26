"""Prepare version 2 limit prices and daily_basic.total_mv in one frozen input DB.

Run with --snapshot <market_snapshot.db>, or use the normal backtest CLI, which
calls prepare_inputs when this strategy's input archive is absent. This downloads the needed
inputs and simulates the strategy to discover its data dependencies. Completed
batches survive interruption in the .partial.db file. The final input archive
is published only after the simulation succeeds.
"""

import argparse
import os
import sqlite3
import sys
import tempfile
import time
from contextlib import closing
from pathlib import Path

from limit_data import historical_code
from input_data import INPUTS, StrategyData

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from backtest import run
from get_data.get_daily import RateLimiter, TushareClient

FIELDS = ("trade_date", "ts_code", "up_limit", "down_limit")
CAP_FIELDS = ("trade_date", "ts_code", "total_mv")


class Collector(StrategyData):
    def __init__(self, path, client, previous, end):
        self.db = sqlite3.connect(path)
        self.client, self.previous, self.end = client, previous, end
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS limits(trade_date TEXT, ts_code TEXT, up_limit TEXT, down_limit TEXT,
                PRIMARY KEY(trade_date,ts_code)) WITHOUT ROWID;
            CREATE TABLE IF NOT EXISTS batches(kind TEXT,key TEXT,PRIMARY KEY(kind,key)) WITHOUT ROWID;
            CREATE TABLE IF NOT EXISTS market_caps(trade_date TEXT,ts_code TEXT,total_mv TEXT,
                PRIMARY KEY(trade_date,ts_code)) WITHOUT ROWID;
        """)

    def fetch(self, kind, key):
        if self.db.execute("SELECT 1 FROM batches WHERE kind=? AND key=?", (kind, key)).fetchone():
            return
        params = (
            {"trade_date": key}
            if kind in ("day", "market_cap")
            else {"ts_code": key, "start_date": self.previous, "end_date": self.end}
        )
        api = "daily_basic" if kind == "market_cap" else "stk_limit"
        expected_fields = CAP_FIELDS if kind == "market_cap" else FIELDS
        row_limit = 6000 if kind == "market_cap" else 5800
        for attempt in range(4):
            try:
                fields, rows = self.client.query(api, params, expected_fields)
                break
            except (RuntimeError, OSError, ValueError):
                if attempt == 3:
                    raise
                time.sleep(2**attempt)
        if tuple(fields) != expected_fields or not rows or len(rows) >= row_limit:
            raise ValueError(f"incomplete {api} response for {params}: {len(rows)} rows")
        keys = set()
        for row in rows:
            if len(row) != len(expected_fields):
                raise ValueError(f"invalid {api} row length for {params}")
            day, code = row[:2]
            if (day, code) in keys or (code if kind == "code" else day) != key:
                raise ValueError(f"invalid {api} response for {params}")
            keys.add((day, code))
        with self.db:
            if kind == "market_cap":
                self.db.executemany("INSERT OR REPLACE INTO market_caps VALUES(?,?,?)", rows)
            else:
                self.db.executemany("INSERT OR REPLACE INTO limits VALUES(?,?,?,?)", rows)
            self.db.execute("INSERT INTO batches VALUES(?,?)", (kind, key))
        print(f"{kind} {key}   {len(rows)}", flush=True)

    def day(self, day):
        self.fetch("day", day)
        return super().day(day)

    def lower(self, day, code):
        if not self.db.execute(
            "SELECT 1 FROM limits WHERE trade_date=? AND ts_code=?", (day, code)
        ).fetchone():
            self.fetch("code", historical_code(day, code))
        return super().lower(day, code)

    def market_caps(self, day, codes):
        self.fetch("market_cap", day)
        return super().market_caps(day, codes)


def prepare_inputs(snapshot_path, strategy_class, config):
    """Publish inputs after a successful preparation pass against the same snapshot/config."""
    snapshot_path = Path(snapshot_path).resolve()
    partial = INPUTS.with_suffix(".partial.db")
    with closing(sqlite3.connect(snapshot_path.as_uri() + "?mode=ro", uri=True)) as db:
        row = db.execute(
            """SELECT prev_trade_date FROM market_calendar WHERE exchange='SSE'
             AND cal_date BETWEEN ? AND ? AND is_open=1 ORDER BY cal_date LIMIT 1""",
            (config.start, config.end),
        ).fetchone()
        if row is None or row[0] is None:
            raise ValueError("strategy input preparation requires a preceding trading day")
        previous = row[0]
    token = os.getenv("TUSHARE_TOKEN") or (ROOT / ".tushare_token").read_text().strip()
    collector = Collector(partial, TushareClient(token, RateLimiter()), previous, config.end)
    try:
        strategy = strategy_class(collector)
        strategy.input_files = ()
        with tempfile.TemporaryDirectory() as output:
            run(strategy, config, snapshot_path, output)
        collector.db.close()
        partial.replace(INPUTS)
        print(INPUTS)
        return INPUTS
    except Exception as err:
        raise SystemExit(f"{type(err).__name__}: " + str(err).replace(token, "[redacted]")) from None
    finally:
        collector.db.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", type=Path, required=True)
    args = parser.parse_args()
    from strategy import SmallestCapLimitUp, make_config

    prepare_inputs(args.snapshot, SmallestCapLimitUp, make_config())


if __name__ == "__main__":
    main()
