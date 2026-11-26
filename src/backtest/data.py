"""Immutable SQLite snapshots, exchange calendars and historical security identities."""

import hashlib
import sqlite3
import tempfile
from contextlib import closing
from datetime import datetime
from functools import lru_cache
from pathlib import Path

from .model import date_key
from .prices import relation
from .status import StatusData, tag_version


def digest(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def readonly(path):
    db = sqlite3.connect(Path(path).resolve().as_uri() + "?mode=ro", uri=True)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA query_only=ON")
    return db


def snapshot(source, directory):
    """Use SQLite backup so committed WAL pages are included in the fingerprint."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=directory, suffix=".db", delete=False) as tmp:
        temp = Path(tmp.name)
    try:
        with closing(readonly(source)) as src, closing(sqlite3.connect(temp)) as dest:
            tag_version(src)
            src.backup(dest)
            tag_version(dest)
            dest.execute("PRAGMA journal_mode=DELETE")
        target = directory / (digest(temp) + ".db")
        if not target.exists():
            temp.chmod(0o444)
            temp.replace(target)
        return target
    finally:
        temp.unlink(missing_ok=True)


class Market:
    def __init__(self, db, config):
        self.db = db
        self.config = config
        self.status_data = StatusData(db)
        self.table = relation(db, config.price_basis)
        self.delist_dates = dict(db.execute(
            "SELECT ts_code,delist_date FROM stock_basic WHERE delist_date IS NOT NULL AND delist_date<>''"
        ))
        self.marks = ",".join("?" for _ in config.exchanges)
        self.days, self.prev = self._calendar()
        self.frame = lru_cache(maxsize=3)(self._frame)

    def _calendar(self):
        c = self.config
        rows = self.db.execute(
            f"""SELECT cal_date,is_open,prev_trade_date FROM market_calendar
             WHERE exchange IN ({self.marks}) AND cal_date BETWEEN ? AND ? ORDER BY cal_date""",
            (*c.exchanges, c.start, c.end),
        )
        counts, prev = {}, {}
        for day, opened, prior in rows:
            if opened is None:
                raise ValueError(f"unknown calendar on {day}")
            counts[day] = counts.get(day, 0) + 1
            if opened:
                prev[day] = max(filter(None, (prev.get(day), prior)), default=None)
        n = (datetime.strptime(c.end, "%Y%m%d") - datetime.strptime(c.start, "%Y%m%d")).days + 1
        if len(counts) != n or any(v != len(set(c.exchanges)) for v in counts.values()) or not prev:
            raise ValueError("empty or incomplete market calendar")
        days = sorted(prev)
        for i in range(1, len(days)):
            prev[days[i]] = days[i - 1]
        return days, prev

    def _frame(self, day):
        # Metadata and prices come from the same day. Exclude ambiguous identities.
        rows = self.db.execute(
            f"""SELECT s.ts_code,s.security_id,d.*,{self.status_data.price_columns} FROM tradable_stock s
            LEFT JOIN {self.table} d USING(trade_date, ts_code)
            WHERE s.trade_date=? AND s.exchange IN ({self.marks}) AND s.is_tradable=1
            AND s.security_id IS NOT NULL AND s.ts_code <> '000001.SH' ORDER BY s.ts_code""",
            (date_key(day), *self.config.exchanges),
        )
        by_id = {}
        for r in rows:
            identity = r["security_id"]
            if self.delisted(r["ts_code"], identity, day):
                continue
            if identity in by_id:
                raise ValueError(f"ambiguous security identity {identity} on {day}")
            by_id[identity] = self.status_data.price_tags(r)
        return {r["ts_code"]: r for r in by_id.values()}

    def history(self, code, identity, start, end):
        sql = f"""SELECT d.*,{self.status_data.price_columns} FROM {self.table} d JOIN tradable_stock s USING(trade_date,ts_code)
           WHERE d.ts_code=? AND s.security_id=? AND d.trade_date BETWEEN ? AND ? ORDER BY d.trade_date"""
        return [self.status_data.price_tags(r) for r in self.db.execute(sql, (code, identity, start, end))]

    def status(self, code, identity, day):
        state = self.status_data.get(code, identity, day)
        effective = self.delist_dates.get(identity)
        if effective and effective <= day:
            state.update(tags=("退市",), tags_unknown=(), is_tradable=0, reason="DELISTED")
        return state

    def delisted(self, code, identity, day):
        effective = self.delist_dates.get(identity)
        if effective and effective <= day:
            return effective
        if "退市" in self.status_data.get(code, identity, day)["tags"]:
            return self.db.execute(
                """SELECT min(trade_date) FROM tradable_stock
                WHERE ts_code=? AND security_id=? AND trade_date<=?
                AND EXISTS (SELECT 1 FROM json_each(tags) WHERE value='退市')""",
                (code, identity, day),
            ).fetchone()[0]
        return None

    def mark(self, code, identity, day, carry=None):
        # The zero is a valuation rule effective on this date, not a market quote.
        if self.delisted(code, identity, day):
            return day, 0
        state = self.status(code, identity, day)
        if carry is None:
            suspended = "停牌" in state["tags"] and state["is_tradable"] == 0
            carry = self.config.valuation == "last_close" or (
                self.config.valuation == "suspension" and (suspended or state["market_open"] == 0)
            )
        op = "<=" if carry else "="
        qualification = "AND s.is_tradable=1" if self.status_data.version else ""
        row = self.db.execute(
            f"""SELECT d.trade_date,d.close FROM {self.table} d
            JOIN tradable_stock s USING(trade_date,ts_code)
            WHERE d.ts_code=? AND s.security_id=? AND d.trade_date {op} ? AND d.close>0
            {qualification}
            ORDER BY d.trade_date DESC LIMIT 1""",
            (code, identity, day),
        ).fetchone()
        return tuple(row) if row else (None, None)

    def reference(self, scenario, day):
        if scenario.benchmark_returns is not None:
            return scenario.benchmark_returns.get(day), None
        if scenario.benchmark is None:
            return None, None
        prior = self.prev[day]
        rows = dict(
            self.db.execute(
                "SELECT trade_date,close FROM daily WHERE ts_code=? AND trade_date IN (?,?)",
                (scenario.benchmark, prior, day),
            )
        )
        close, base = rows.get(day), rows.get(prior)
        return (close / base - 1 if close and base and base > 0 else None), close
