"""Historical status sources and JSON tags, shared by initial load and updates.

Only source-confirmed facts produce tags. Empty/failed name history never means
normal. No OHLC row is manufactured for a suspended or delisted security.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta
from functools import lru_cache
import json
import logging
import re
import unicodedata

TAGS = ("停牌", "*ST", "ST", "退市")
UNKNOWN = json.dumps(TAGS, ensure_ascii=False, separators=(",", ":"))
VERSION = "3"
# Exact provider legacy identity, not a general rule for repairing short codes.
# Tushare's historical listing record identifies T00018.SH as 上港集箱(退),
# listed 20000719 and delisted 20061020. Current stock_basic uses T600018.SH.
# https://github.com/waditu/tushare/issues/1683
# The quote code was 600018, but the later 上港集团 is a different identity:
# https://static.cninfo.com.cn/finalpage/2006-02-16/16450034.PDF
SUSPENSION_SOURCE_ALIASES = {"T00018.SH": "T600018.SH"}
NAME_FIELDS = ("ts_code", "name", "start_date", "end_date", "ann_date", "change_reason")
SUSPEND_FIELDS = ("ts_code", "trade_date", "suspend_timing", "suspend_type")
LOG = logging.getLogger("stock_tags")


def pack(values):
    return _pack(tuple(tag for tag in TAGS if tag in values))


@lru_cache(maxsize=16)
def _pack(values):
    return json.dumps(values, ensure_ascii=False, separators=(",", ":"))


def tables(db):
    return {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def ensure_schema(db):
    # No executescript: callers own the transaction, including ALTER TABLE.
    for table in ("daily", "tradable_stock"):
        columns = {row[1] for row in db.execute(f'PRAGMA table_info("{table}")')}
        if not columns:
            continue
        for name, default in (("tags", "[]"), ("tags_unknown", UNKNOWN)):
            if name not in columns:
                db.execute(f"ALTER TABLE {table} ADD COLUMN {name} TEXT NOT NULL DEFAULT '{default}' "
                           f"CHECK(json_valid({name}) AND json_type({name})='array')")
    for sql in (
        "CREATE TABLE IF NOT EXISTS dataset_meta(key TEXT PRIMARY KEY,value TEXT NOT NULL) WITHOUT ROWID",
        "CREATE TABLE IF NOT EXISTS stock_name_history(ts_code TEXT NOT NULL,name TEXT NOT NULL,"
        "start_date TEXT NOT NULL,end_date TEXT,ann_date TEXT,change_reason TEXT,"
        "PRIMARY KEY(ts_code,start_date,name)) WITHOUT ROWID",
        "CREATE TABLE IF NOT EXISTS stock_suspensions(ts_code TEXT NOT NULL,trade_date TEXT NOT NULL,"
        "suspend_timing TEXT NOT NULL,suspend_type TEXT NOT NULL,"
        "PRIMARY KEY(trade_date,ts_code,suspend_type,suspend_timing)) WITHOUT ROWID",
        "CREATE TABLE IF NOT EXISTS status_fetch_state(api TEXT NOT NULL,scope TEXT NOT NULL,"
        "as_of_date TEXT NOT NULL,fetched_at TEXT NOT NULL,row_count INTEGER NOT NULL,"
        "PRIMARY KEY(api,scope)) WITHOUT ROWID",
    ):
        db.execute(sql)


def get_meta(db, key):
    if "dataset_meta" not in tables(db):
        return None
    row = db.execute("SELECT value FROM dataset_meta WHERE key=?", (key,)).fetchone()
    return row[0] if row else None


def set_meta(db, key, value):
    db.execute("INSERT INTO dataset_meta VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, value))


def ready(db):
    required = {"daily", "tradable_stock", "market_calendar", "stock_name_history", "stock_suspensions", "status_fetch_state", "dataset_meta"}
    return (required.issubset(tables(db)) and get_meta(db, "tag_version") == VERSION and get_meta(db, "tags_dirty") != "1" and
            all({"tags", "tags_unknown"}.issubset({r[1] for r in db.execute(f'PRAGMA table_info("{table}")')})
                for table in ("daily", "tradable_stock")))


def _day(value):
    if not isinstance(value, str) or len(value) != 8 or datetime.strptime(value, "%Y%m%d").strftime("%Y%m%d") != value:
        raise ValueError(f"Invalid date: {value!r}")
    return value


def plan(db, stocks, days, start, end, force=False):
    cached = dict(((r[0], r[1]), r[2]) for r in db.execute("SELECT api,scope,as_of_date FROM status_fetch_state")) if "status_fetch_state" in tables(db) else {}
    work = []
    for code, record in sorted(stocks.items()):
        if record["list_date"] > end or (record.get("delist_date") and record["delist_date"] < start):
            continue
        target = min(end, record.get("delist_date") or end)
        if force or cached.get(("namechange", code), "") < target:
            work.append(("namechange", code, target))
    for day in sorted(set(days)):
        if start <= day <= end and (force or ("suspend_d", day) not in cached):
            work.append(("suspend_d", day, day))
    return work


@dataclass
class Batch:
    api: str
    scope: str
    as_of: str
    rows: list


def fetch_batches(query, warn, work, db=None):
    """A failed/invalid batch is skipped, preserving the previous cache for retry."""
    for number, (api, scope, as_of) in enumerate(work, 1):
        fields = NAME_FIELDS if api == "namechange" else SUSPEND_FIELDS
        params = {"ts_code": scope} if api == "namechange" else {"trade_date": scope}
        response = query(api, params, fields)
        if response is None:
            continue  # query owns the request-failure warning.
        try:
            returned, items = response
            if len(returned) != len(set(returned)) or not set(fields).issubset(returned):
                raise ValueError("Missing or duplicate response fields")
            # One security's entire name history is small. The 1000 threshold is
            # a conservative sanity bound, not an advertised namechange quota.
            if len(items) >= (1000 if api == "namechange" else 5000):
                raise ValueError(f"Possible truncation: {len(items)} rows; batch not accepted")
            rows, seen = [], set()
            for item in items:
                if len(item) != len(returned):
                    raise ValueError("Field/value length mismatch")
                record = dict(zip(returned, item))
                code = record["ts_code"]
                if not isinstance(code, str) or not (re.fullmatch(r"T?\d{6}\.(SH|SZ|BJ)", code)
                        or (api == "suspend_d" and code in SUSPENSION_SOURCE_ALIASES)):
                    raise ValueError(f"Invalid stock code: {code!r}")
                if api == "namechange":
                    if code != scope or not isinstance(record["name"], str) or not record["name"].strip():
                        raise ValueError("Wrong security or empty historical name")
                    start = _day(record["start_date"])
                    end = _day(record["end_date"]) if record["end_date"] not in (None, "") else None
                    announced = _day(record["ann_date"]) if record["ann_date"] not in (None, "") else None
                    if record["change_reason"] is not None and not isinstance(record["change_reason"], str):
                        raise ValueError("Invalid name change reason")
                    if end and end < start:
                        raise ValueError("Reversed name interval")
                    row = (code, record["name"], start, end, announced, record["change_reason"])
                    key = (code, start, record["name"])
                else:
                    if _day(record["trade_date"]) != scope or record["suspend_type"] not in ("S", "R"):
                        raise ValueError("Wrong date or suspension type")
                    timing = record["suspend_timing"] if record["suspend_timing"] is not None else ""
                    if not isinstance(timing, str):
                        raise ValueError("Invalid suspension timing")
                    row = (code, scope, timing.strip(), record["suspend_type"])
                    key = row
                if key in seen:
                    raise ValueError(f"Duplicate source row: {key}")
                seen.add(key)
                rows.append(row)
            if api == "namechange" and not rows:
                warn("EMPTY_NAME_HISTORY", "No historical names returned; ST state remains unknown", api=api, params=params, ts_code=scope)
                if (db is not None and "stock_name_history" in tables(db) and
                        db.execute("SELECT 1 FROM stock_name_history WHERE ts_code=? LIMIT 1", (scope,)).fetchone()):
                    warn("STATUS_SOURCE_SHRANK", "Empty response would erase existing history; old source retained, request remains pending",
                         api=api, params=params, ts_code=scope)
                    continue
            yield Batch(api, scope, as_of, rows)
        except (ValueError, TypeError, KeyError) as exc:
            warn("INVALID_STATUS_SOURCE", str(exc), api=api, params=params,
                 ts_code=scope if api == "namechange" else None,
                 trade_date=scope if api == "suspend_d" else None)
        if number % 100 == 0:
            LOG.info("Status source requests: %d/%d", number, len(work))


def apply_batch(db, batch, fetched_at):
    set_meta(db, "tags_dirty", "1")
    if batch.api == "namechange":
        db.execute("DELETE FROM stock_name_history WHERE ts_code=?", (batch.scope,))
        db.executemany("INSERT INTO stock_name_history VALUES(?,?,?,?,?,?)", batch.rows)
    else:
        db.execute("DELETE FROM stock_suspensions WHERE trade_date=?", (batch.scope,))
        db.executemany("INSERT INTO stock_suspensions VALUES(?,?,?,?)", batch.rows)
    db.execute("INSERT INTO status_fetch_state VALUES(?,?,?,?,?) ON CONFLICT(api,scope) DO UPDATE SET "
               "as_of_date=excluded.as_of_date,fetched_at=excluded.fetched_at,row_count=excluded.row_count",
               (batch.api, batch.scope, batch.as_of, fetched_at, len(batch.rows)))


def affected_from(db, batch):
    """Earliest possibly changed tag date (including newly verified coverage)."""
    if "status_fetch_state" not in tables(db):
        return "00000000"
    state = db.execute("SELECT as_of_date FROM status_fetch_state WHERE api=? AND scope=?", (batch.api, batch.scope)).fetchone()
    if batch.api == "suspend_d":
        old = list(map(tuple, db.execute("SELECT ts_code,trade_date,suspend_timing,suspend_type FROM stock_suspensions WHERE trade_date=?", (batch.scope,))))
        return batch.scope if not state or sorted(old) != sorted(batch.rows) else None
    old = list(map(tuple, db.execute("SELECT ts_code,name,start_date,end_date,ann_date,change_reason FROM stock_name_history WHERE ts_code=?", (batch.scope,))))
    if not state:
        return min((r[2] for r in batch.rows), default="00000000")
    # Compare the risk state at every interval boundary; an ordinary rename
    # need not rebuild twenty-two years, while a corrected old ST period must.
    boundaries = {r[2] for r in old + batch.rows}
    boundaries.update((datetime.strptime(r[3], "%Y%m%d") + timedelta(days=1)).strftime("%Y%m%d")
                      for r in old + batch.rows if r[3] and r[3] < "99991231")
    def state_at(rows, day):
        active = [r for r in rows if r[2] <= day and (not r[3] or day <= r[3])]
        return risk_tag(active[0][1]) if len(active) == 1 else "UNKNOWN"
    changed = [day for day in boundaries if state_at(old, day) != state_at(batch.rows, day)]
    if batch.as_of > state[0]:
        changed.append((datetime.strptime(state[0], "%Y%m%d") + timedelta(days=1)).strftime("%Y%m%d"))
    return min(changed, default=None)


@lru_cache(maxsize=16384)
def risk_tag(name):
    """Match historical risk prefixes, including share-reform G/S prefixes."""
    normalized = re.sub(r"\s+", "", unicodedata.normalize("NFKC", name)).upper()
    if normalized.startswith(("*ST", "S*ST", "G*ST")):
        return "*ST"
    if normalized.startswith(("ST", "SST", "GST")):
        return "ST"
    return None


class Context:
    def __init__(self, db):
        self.names = defaultdict(list)
        self.coverage = {(r[0], r[1]): r[2] for r in db.execute("SELECT api,scope,as_of_date FROM status_fetch_state")}
        self.basic = {r["ts_code"]: dict(r) for r in db.execute("SELECT * FROM stock_basic")}
        for row in db.execute("SELECT * FROM stock_name_history ORDER BY ts_code,start_date"):
            self.names[row["ts_code"]].append(dict(row))
        self.db = db
        self.suspensions = {}
        self.day = None

    def on_day(self, day):
        if self.day != day:
            rows = self.db.execute("SELECT ts_code,suspend_timing FROM stock_suspensions WHERE trade_date=? AND suspend_type='S'", (day,))
            self.suspensions = defaultdict(list)
            for code, timing in rows:
                self.suspensions[code].append(timing)
            self.day = day

    def suspension_timings(self, code, day, instrument=None):
        """Match raw source codes through the date-selected security identity.

        Keep the upstream code unchanged in stock_suspensions for audit. Never
        assign an old entity's event to a later entity that reused its quote.
        """
        self.on_day(day)
        source_codes = {code}
        if instrument is not None and instrument.start_date <= day and (not instrument.end_date or day <= instrument.end_date):
            source_codes.add(instrument.security_id)
            source_codes.update(source for source, identity in SUSPENSION_SOURCE_ALIASES.items()
                                if identity == instrument.security_id)
        return [timing for source in source_codes for timing in self.suspensions.get(source, ())]

    def full_day_suspension(self, code, day, instrument=None):
        return "" in self.suspension_timings(code, day, instrument)

    def resolve(self, code, day, instrument, blocked=None, conflict=False):
        self.on_day(day)
        tags, unknown = set(), set()
        if self.suspension_timings(code, day, instrument) or blocked:
            tags.add("停牌")
        elif ("suspend_d", day) not in self.coverage:
            unknown.add("停牌")
        if instrument is None or conflict:
            unknown.update(("*ST", "ST", "退市"))
            return pack(tags), pack(unknown)
        record = self.basic[instrument.security_id]
        delist = record.get("delist_date")
        if delist and day >= delist:
            # Terminal listing state; do not carry an obsolete ST name forever.
            return pack({"退市"}), "[]"
        if not delist and record.get("list_status") == "D":
            unknown.add("退市")
        history = [r for r in self.names[instrument.security_id]
                   if r["start_date"] <= day and (not r["end_date"] or day <= r["end_date"])]
        covered = self.coverage.get(("namechange", instrument.security_id), "") >= day
        if len(history) != 1 or not covered or day < instrument.start_date:
            unknown.update(("*ST", "ST"))
        else:
            tag = risk_tag(history[0]["name"])
            if tag:
                tags.add(tag)
        return pack(tags), pack(unknown)
