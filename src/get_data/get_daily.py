#!/usr/bin/env python3
"""Download stocks and SSE Composite into one SQLite daily table, with audit logs.

Only Python's standard library is needed. curl (if installed) is used for HTTPS;
otherwise urllib is used. No credential is sent over HTTP or logged.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
import json
import logging
import math
import os
from pathlib import Path
import re
import shutil
import sqlite3
import subprocess
import sys
import time
import urllib.request
import uuid
from types import SimpleNamespace
from zoneinfo import ZoneInfo

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

ROOT = Path(__file__).resolve().parents[2]
TZ = ZoneInfo("Asia/Shanghai")
DAILY_FIELDS = (
    "ts_code", "trade_date", "open", "high", "low", "close", "pre_close",
    "change", "pct_chg", "vol", "amount", "ah_vol", "ah_amount",
)
BENCHMARK_CODE = "000001.SH"  # 上证综指; 000001.SZ remains an ordinary stock.
INDEX_FIELDS = DAILY_FIELDS[:-2]
STOCK_FIELDS = ("ts_code", "name", "exchange", "market", "list_status", "list_date", "delist_date")
CALENDAR_FIELDS = ("exchange", "cal_date", "is_open", "pretrade_date")
AH_START = "20260706"
BSE_OPEN_DATE = "20211115"  # https://www.bse.cn/company/introduce.html
ROW_LIMIT = 6000
LOG = logging.getLogger("get_daily")


def stamp():
    return datetime.now(TZ).isoformat(timespec="seconds")


def parse_date(value):
    parsed = datetime.strptime(value, "%Y%m%d").date()
    if parsed.strftime("%Y%m%d") != value:
        raise ValueError("Date must be YYYYMMDD")
    return parsed


def dates_between(start, end):
    cursor, stop = parse_date(start), parse_date(end)
    while cursor <= stop:
        yield cursor.strftime("%Y%m%d")
        cursor += timedelta(days=1)


class RateLimiter:
    """Space request STARTS, including failures; idle time earns no burst credit."""
    def __init__(self, global_rpm=200, fraction=0.75, endpoint_limits=None,
                 clock=time.monotonic, sleep=time.sleep):
        if global_rpm <= 0 or not 0 < fraction <= 0.75:
            raise ValueError("rpm must be positive and fraction within (0, 0.75]")
        self.interval = 60 / (global_rpm * fraction)
        limits = {"stock_basic": 50}
        limits.update(endpoint_limits or {})
        if any(value <= 0 for value in limits.values()):
            raise ValueError("endpoint limits must be positive")
        self.intervals = {api: 60 / (rpm * fraction) for api, rpm in limits.items()}
        self.clock, self.sleep = clock, sleep
        self.last = None
        self.api_last = {}

    def wait(self, api):
        deadline = self.clock()
        if self.last is not None:
            deadline = max(deadline, self.last + self.interval)
        if api in self.api_last:
            deadline = max(deadline, self.api_last[api] + self.intervals.get(api, self.interval))
        remaining = deadline - self.clock()
        while remaining > 0:
            self.sleep(remaining)
            remaining = deadline - self.clock()
        self.last = self.clock()
        self.api_last[api] = self.last


class TushareClient:
    def __init__(self, token, limiter, timeout=30, transport="auto"):
        self.token, self.limiter, self.timeout = token, limiter, timeout
        self.use_curl = transport == "curl" or (transport == "auto" and shutil.which("curl"))

    def query(self, api, params, fields):
        self.limiter.wait(api)
        body = json.dumps(dict(api_name=api, token=self.token, params=params,
                               fields=",".join(fields))).encode()
        if self.use_curl:
            # Credential goes via stdin, never process arguments. No automatic retry.
            process = subprocess.run([
                "curl", "--silent", "--show-error", "--fail-with-body",
                "--proto", "=https", "--max-time", str(self.timeout),
                "--connect-timeout", str(min(10, self.timeout)),
                "https://api.tushare.pro", "-H", "Content-Type: application/json",
                "--data-binary", "@-",
            ], input=body, capture_output=True, timeout=self.timeout + 5)
            if process.returncode:
                raise RuntimeError(f"HTTPS transport failed ({process.returncode}): "
                                   + process.stderr.decode(errors="replace")[:800])
            response = json.loads(process.stdout)
        else:
            request = urllib.request.Request("https://api.tushare.pro", data=body,
                                             headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(request, timeout=self.timeout) as stream:
                response = json.load(stream)
        if not isinstance(response, dict) or response.get("code") != 0:
            raise RuntimeError(f"Tushare API error: {response}")
        data = response.get("data")
        if not isinstance(data, dict) or not isinstance(data.get("fields"), list) or not isinstance(data.get("items"), list):
            raise ValueError("Malformed API response: expected data.fields and data.items lists")
        if not all(isinstance(column, str) and column for column in data["fields"]):
            raise ValueError("Malformed API response: field names must be non-empty strings")
        return data["fields"], data["items"]


@dataclass
class ValidationResult:
    rows: list = field(default_factory=list)
    issues: list = field(default_factory=list)
    rejected: list = field(default_factory=list)
    raw_count: int = 0


def validate_daily(fields, items, trade_date, expected_count=None, previous_count=None, *, allow_benchmark=False):
    result = ValidationResult(raw_count=len(items))
    def issue(kind, message, code=None, column=None):
        result.issues.append(dict(kind=kind, message=message, ts_code=code, field=column))
    if not all(isinstance(column, str) and column for column in fields):
        issue("MALFORMED_COLUMNS", "Field names must be non-empty strings")
        result.rejected = list(items)
        return result
    missing = set(DAILY_FIELDS) - set(fields)
    if trade_date < AH_START:
        missing -= {"ah_vol", "ah_amount"}
    if missing:
        issue("MISSING_COLUMNS", ",".join(sorted(missing)))
    if len(fields) != len(set(fields)):
        issue("DUPLICATE_COLUMNS", "API returned repeated field names")
        result.rejected = list(items)
        return result
    if not items:
        issue("EMPTY_DAILY", "No rows returned for an open trading day")
    if len(items) >= ROW_LIMIT:
        issue("POSSIBLE_TRUNCATION", f"Returned {len(items)} rows; endpoint cap is {ROW_LIMIT}. Re-fetch this date in smaller requests.")
    seen = set()
    for index, item in enumerate(items):
        if not isinstance(item, (list, tuple)) or len(item) != len(fields):
            issue("MALFORMED_ROW", f"row={index}: field/value lengths differ")
            result.rejected.append(item)
            continue
        record = dict(zip(fields, item))
        code = record.get("ts_code")
        if (not isinstance(code, str) or not re.fullmatch(r"\d{6}\.(SH|SZ|BJ)", code)
                or record.get("trade_date") != trade_date or (code == BENCHMARK_CODE and not allow_benchmark)):
            issue("INVALID_KEY", f"row={index}, returned date={record.get('trade_date')!r}", str(code))
            result.rejected.append(record)
            continue
        if code in seen:
            issue("DUPLICATE_KEY", f"Duplicate row={index}; first occurrence retained", code)
            result.rejected.append(record)
            continue
        bad_number = False
        for column in DAILY_FIELDS[2:]:
            value = record.get(column)
            if value is None:
                if column not in ("ah_vol", "ah_amount"):
                    issue("NULL_VALUE", "Required daily value is NULL; retained for repair", code, column)
                record[column] = None
                continue
            try:
                numeric = float(value)
                if isinstance(value, bool) or not math.isfinite(numeric):
                    raise ValueError("not a finite number")
                record[column] = numeric
            except (TypeError, ValueError, OverflowError):
                issue("INVALID_NUMBER", f"Invalid numeric value {value!r}; row quarantined", code, column)
                bad_number = True
        if bad_number:
            result.rejected.append(dict(zip(fields, item)))
            continue
        seen.add(code)
        if all(record.get(c) is not None for c in ("open", "high", "low", "close")):
            if not (0 < record["low"] <= min(record["open"], record["close"]) <= max(record["open"], record["close"]) <= record["high"]):
                issue("OHLC_INCONSISTENT", "Expected 0 < low <= open/close <= high; values retained", code, "open,high,low,close")
        for column in ("pre_close", "vol", "amount", "ah_vol", "ah_amount"):
            if record.get(column) is not None and record[column] < 0:
                issue("NEGATIVE_VALUE", "Unexpected negative value; retained", code, column)
        if (record.get("ah_vol") is None) != (record.get("ah_amount") is None):
            issue("AH_PAIR_INCOMPLETE", "Only one after-hours value is available", code, "ah_vol,ah_amount")
        result.rows.append(tuple(record.get(c) for c in DAILY_FIELDS))
    count = len(result.rows)
    if expected_count and count < expected_count * 0.60:
        issue("LOW_ROW_COUNT", f"Saved {count}; listed-interval estimate {expected_count}. Heuristic only: suspensions/code changes may explain differences.")
    if previous_count and count < previous_count * 0.75:
        issue("ROW_COUNT_DROP", f"Saved {count}; preceding successful day {previous_count}. Check market coverage and suspensions.")
    return result


def validate_index(fields, items, expected_days):
    """Validate one benchmark row per expected SSE date, preserving stock schema.

    Index points use the OHLC columns; unsupported after-hours columns are NULL.
    Invalid index rows are NOT committed, so missing-date detection retries them.
    """
    expected = set(expected_days)
    result = ValidationResult(raw_count=len(items))
    def issue(kind, message, day=None, field=None):
        result.issues.append(dict(kind=kind, message=message, trade_date=day,
                                  ts_code=BENCHMARK_CODE, field=field))
    if (not all(isinstance(key, str) for key in fields) or len(fields) != len(set(fields))
            or not set(INDEX_FIELDS).issubset(fields)):
        issue("INDEX_SCHEMA", "Missing/duplicate index_daily columns")
        result.rejected = list(items)
        return result
    by_date = {}
    for item in items:
        if not isinstance(item, (list, tuple)) or len(item) != len(fields):
            issue("INDEX_ROW", "Malformed index row")
            result.rejected.append(item)
            continue
        record = dict(zip(fields, item))
        day = record.get("trade_date")
        if record.get("ts_code") != BENCHMARK_CODE or not isinstance(day, str) or day not in expected:
            issue("INDEX_KEY", f"Unexpected index key: {record.get('ts_code')!r}, {day!r}")
            result.rejected.append(record)
            continue
        by_date.setdefault(day, []).append(record)
    for day in sorted(expected):
        records = by_date.get(day, [])
        if len(records) != 1:
            issue("INDEX_MISSING_DATE" if not records else "INDEX_DUPLICATE_DATE",
                  f"Expected one index bar, received {len(records)}", day)
            result.rejected.extend(records)
            continue
        record = records[0]
        values = [record[key] for key in INDEX_FIELDS] + [None, None]
        checked = validate_daily(DAILY_FIELDS, [values], day, allow_benchmark=True)
        if checked.issues or checked.rejected:
            for problem in checked.issues:
                issue("INDEX_" + problem["kind"], problem["message"], day, problem.get("field"))
            result.rejected.append(record)
        else:
            result.rows.extend(checked.rows)
    return result


def index_results(query, expected_days, pending_days):
    """Yield validated yearly slices. query must log/rate-limit and return None on failure."""
    pending = set(pending_days)
    for year in sorted({day[:4] for day in pending}):
        selected = sorted(day for day in pending if day.startswith(year))
        lower, upper = selected[0], selected[-1]
        params = dict(ts_code=BENCHMARK_CODE, start_date=lower, end_date=upper)
        response = query("index_daily", params, INDEX_FIELDS)
        if response is None:
            yield params, None
            continue
        result = validate_index(*response, [day for day in expected_days if lower <= day <= upper])
        result.rows = [row for row in result.rows if row[1] in pending]
        result.issues = [issue for issue in result.issues
                         if issue["kind"] != "INDEX_MISSING_DATE" or issue["trade_date"] in pending]
        yield params, result


def upsert_daily_rows(db, rows):
    """No commit here: caller owns the transaction for either asset's rows."""
    rows = list(rows)
    columns = ",".join('"' + key + '"' for key in DAILY_FIELDS)
    updates = ",".join(f'"{key}"=excluded."{key}"' for key in DAILY_FIELDS[2:])
    db.executemany(f"INSERT INTO daily({columns}) VALUES({','.join('?' for _ in DAILY_FIELDS)}) "
                   f"ON CONFLICT(trade_date,ts_code) DO UPDATE SET {updates}", rows)
    from get_data import stock_tags
    if "dataset_meta" in stock_tags.tables(db):
        if any(row[0] != BENCHMARK_CODE for row in rows):
            stock_tags.set_meta(db, "tags_dirty", "1")
        db.execute("UPDATE daily SET tags='[]',tags_unknown='[]' WHERE ts_code=? AND (tags<>'[]' OR tags_unknown<>'[]')", (BENCHMARK_CODE,))


def validate_calendar(fields, items, start, end, exchange):
    issues, records, opened = [], [], set()
    expected = set(dates_between(start, end))
    if not all(isinstance(column, str) and column for column in fields) or set(CALENDAR_FIELDS) - set(fields) or len(set(fields)) != len(fields):
        return [], set(), ["Calendar field schema is incomplete/duplicated"]
    seen = set()
    for item in items:
        if not isinstance(item, (list, tuple)) or len(item) != len(fields):
            issues.append("Malformed calendar row")
            continue
        record = dict(zip(fields, item))
        day = record.get("cal_date")
        if not isinstance(day, str) or day not in expected or day in seen or record.get("exchange") != exchange or record.get("is_open") not in (0, 1, "0", "1"):
            issues.append(f"Invalid/duplicate calendar row: {record}")
            continue
        seen.add(day)
        is_open = int(record["is_open"])
        records.append((exchange, day, is_open, record.get("pretrade_date")))
        if is_open:
            opened.add(day)
    missing = expected - seen
    if missing:
        issues.append("Missing calendar dates: " + ",".join(sorted(missing)))
    return records, (set() if issues else opened), issues


class Store:
    def __init__(self, path):
        self.path = Path(path).resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.path, timeout=30)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=FULL")
        self.db.executescript('''
            CREATE TABLE IF NOT EXISTS daily (
                ts_code TEXT NOT NULL, trade_date TEXT NOT NULL,
                open REAL, high REAL, low REAL, close REAL, pre_close REAL,
                change REAL, pct_chg REAL, vol REAL, amount REAL, ah_vol REAL, ah_amount REAL,
                PRIMARY KEY(trade_date, ts_code)
            ) WITHOUT ROWID;
            CREATE INDEX IF NOT EXISTS idx_daily_code_date ON daily(ts_code, trade_date);
            CREATE TABLE IF NOT EXISTS stock_basic (
                ts_code TEXT PRIMARY KEY, name TEXT, exchange TEXT, market TEXT,
                list_status TEXT, list_date TEXT, delist_date TEXT, updated_at TEXT
            );
            CREATE TABLE IF NOT EXISTS trade_cal (
                exchange TEXT, cal_date TEXT, is_open INTEGER, pretrade_date TEXT,
                PRIMARY KEY(exchange, cal_date)
            ) WITHOUT ROWID;
            CREATE TABLE IF NOT EXISTS runs (
                run_id TEXT PRIMARY KEY, started_at TEXT, ended_at TEXT,
                start_date TEXT, end_date TEXT, status TEXT, config_json TEXT
            );
            CREATE TABLE IF NOT EXISTS request_log (
                id INTEGER PRIMARY KEY, run_id TEXT, api TEXT, params_json TEXT,
                requested_at TEXT, status TEXT, returned_rows INTEGER, error TEXT
            );
            CREATE TABLE IF NOT EXISTS date_status (
                trade_date TEXT PRIMARY KEY, status TEXT, returned_rows INTEGER,
                saved_rows INTEGER, run_id TEXT, updated_at TEXT
            );
            CREATE TABLE IF NOT EXISTS warnings (
                id INTEGER PRIMARY KEY, run_id TEXT, created_at TEXT, api TEXT,
                trade_date TEXT, ts_code TEXT, field TEXT, kind TEXT,
                message TEXT, params_json TEXT
            );
            CREATE TABLE IF NOT EXISTS rejected_rows (
                id INTEGER PRIMARY KEY, run_id TEXT, trade_date TEXT, payload_json TEXT
            );
        ''')
        from get_data.daily_tables import create_tables
        with self.db:
            create_tables(self.db)
        self.run_id = None

    def start_run(self, start, end, config=None):
        self.run_id = datetime.now(TZ).strftime("%Y%m%d_%H%M%S_") + uuid.uuid4().hex[:8]
        with self.db:
            self.db.execute("INSERT INTO runs VALUES(?,?,?,?,?,?,?)",
                            (self.run_id, stamp(), None, start, end, "running", json.dumps(config or {}, ensure_ascii=False)))
        return self.run_id

    def warn(self, api, kind, message, params=None, trade_date=None, ts_code=None, field=None):
        params = params or {}
        day = trade_date or params.get("trade_date")
        ts_code = ts_code or params.get("ts_code")
        with self.db:
            self.db.execute("INSERT INTO warnings(run_id,created_at,api,trade_date,ts_code,field,kind,message,params_json) VALUES(?,?,?,?,?,?,?,?,?)",
                            (self.run_id, stamp(), api, day, ts_code, field, kind, str(message), json.dumps(params, ensure_ascii=False)))
        LOG.warning("%s %s date=%s code=%s field=%s: %s", api, kind, day, ts_code, field, message)

    def should_skip(self, day, retry_warnings=False, force=False):
        if force:
            return False
        row = self.db.execute("SELECT status FROM date_status WHERE trade_date=?", (day,)).fetchone()
        has_stock = self.db.execute("SELECT 1 FROM daily WHERE trade_date=? AND ts_code<>? LIMIT 1", (day, BENCHMARK_CODE)).fetchone()
        return bool(has_stock and row and (row["status"] == "success" or (row["status"] == "warning" and not retry_warnings)))

    def mark_failed(self, day):
        with self.db:
            self.db.execute("INSERT INTO date_status VALUES(?,?,?,?,?,?) ON CONFLICT(trade_date) DO UPDATE SET status=excluded.status,returned_rows=0,saved_rows=0,run_id=excluded.run_id,updated_at=excluded.updated_at",
                            (day, "failed", 0, 0, self.run_id, stamp()))

    def save_daily(self, day, result):
        existing = {row[0] for row in self.db.execute("SELECT ts_code FROM daily WHERE trade_date=? AND ts_code<>?", (day, BENCHMARK_CODE))}
        omitted = existing - {row[0] for row in result.rows}
        if omitted:
            result.issues.append(dict(kind="EXISTING_CODES_OMITTED", message="Previously saved codes absent from this response; old rows retained pending investigation: " + ",".join(sorted(omitted))))
        with self.db:
            upsert_daily_rows(self.db, result.rows)
            self.db.executemany("INSERT INTO rejected_rows(run_id,trade_date,payload_json) VALUES(?,?,?)",
                                [(self.run_id, day, json.dumps(row, ensure_ascii=False, default=str)) for row in result.rejected])
            self.db.execute("INSERT INTO date_status VALUES(?,?,?,?,?,?) ON CONFLICT(trade_date) DO UPDATE SET status=excluded.status,returned_rows=excluded.returned_rows,saved_rows=excluded.saved_rows,run_id=excluded.run_id,updated_at=excluded.updated_at",
                            (day, "warning" if result.issues else "success", result.raw_count, len(result.rows), self.run_id, stamp()))
        for problem in result.issues:
            self.warn("daily", params={"trade_date": day}, **problem)

    def close(self):
        self.db.close()


def fetch(client, store, api, params, fields):
    requested_at = stamp()
    try:
        fields, items = client.query(api, params, fields)
        status, error = "success", None
    except Exception as exc:
        # Some upstream exceptions may include request JSON. Always redact token.
        error = str(exc).replace(client.token, "[REDACTED]") if client.token else str(exc)
        fields, items, status = [], [], "failed"
        store.warn(api, "REQUEST_FAILED", error, params)
    with store.db:
        store.db.execute("INSERT INTO request_log(run_id,api,params_json,requested_at,status,returned_rows,error) VALUES(?,?,?,?,?,?,?)",
                         (store.run_id, api, json.dumps(params), requested_at, status, len(items), error))
    return None if error else (fields, items)


def load_stocks(client, store):
    from get_data import stock_tags
    for exchange in ("SSE", "SZSE", "BSE"):
        for status in ("L", "D", "P"):
            params = dict(exchange=exchange, list_status=status)
            response = fetch(client, store, "stock_basic", params, STOCK_FIELDS)
            if response is None:
                continue
            fields, items = response
            if set(STOCK_FIELDS) - set(fields):
                store.warn("stock_basic", "MISSING_COLUMNS", "Missing fields: " + str(set(STOCK_FIELDS) - set(fields)), params)
                continue
            if len(items) >= ROW_LIMIT or (not items and status == "L"):
                store.warn("stock_basic", "UNEXPECTED_COUNT", f"Returned {len(items)} records", params)
            rows = []
            for item in items:
                try:
                    if len(item) != len(fields):
                        raise ValueError("Field/value lengths differ")
                    row = dict(zip(fields, item))
                    if not row.get("ts_code") or row.get("list_status") != status or row.get("exchange") != exchange:
                        raise ValueError("Invalid code/status/exchange")
                    parse_date(row["list_date"])
                    if row.get("delist_date"):
                        parse_date(row["delist_date"])
                    rows.append(tuple(row.get(c) or None for c in STOCK_FIELDS) + (stamp(),))
                except (TypeError, ValueError, KeyError) as exc:
                    store.warn("stock_basic", "INVALID_ROW", f"{exc}: {item}", params)
            with store.db:
                store.db.executemany("INSERT INTO stock_basic VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(ts_code) DO UPDATE SET name=excluded.name,exchange=excluded.exchange,market=excluded.market,list_status=excluded.list_status,list_date=excluded.list_date,delist_date=excluded.delist_date,updated_at=excluded.updated_at", rows)
                if rows:
                    stock_tags.set_meta(store.db, "tags_dirty", "1")
    return list(store.db.execute("SELECT * FROM stock_basic"))


def load_calendar(client, store, start, end):
    from get_data import stock_tags
    opened = set()
    for year in range(int(start[:4]), int(end[:4]) + 1):
        lower, upper = max(start, f"{year}0101"), min(end, f"{year}1231")
        calendars = []
        for exchange in ("SSE", "SZSE"):
            params = dict(exchange=exchange, start_date=lower, end_date=upper)
            response = fetch(client, store, "trade_cal", params, CALENDAR_FIELDS)
            if response is None:
                continue
            records, days, issues = validate_calendar(*response, lower, upper, exchange)
            for problem in issues:
                store.warn("trade_cal", "INCOMPLETE_CALENDAR", problem, params)
            if issues:
                continue
            with store.db:
                store.db.executemany("INSERT INTO trade_cal VALUES(?,?,?,?) ON CONFLICT(exchange,cal_date) DO UPDATE SET is_open=excluded.is_open,pretrade_date=excluded.pretrade_date", records)
                if records:
                    stock_tags.set_meta(store.db, "tags_dirty", "1")
            calendars.append(days)
        if len(calendars) < 2:
            store.warn("trade_cal", "CALENDAR_COVERAGE", f"{year}: {len(calendars)}/2 exchange calendars usable; " + ("using the available calendar (BSE follows SH/SZ)" if calendars else "year skipped; rerun this date range"), {"start_date": lower, "end_date": upper})
        if len(calendars) == 2 and calendars[0] != calendars[1]:
            store.warn("trade_cal", "CALENDAR_MISMATCH", "Exchange open days differ; querying their union", {"start_date": lower, "end_date": upper})
        for days in calendars:
            opened.update(days)
    return sorted(opened)


def audit_delisted(store, start, end):
    # One range scan, not a full-table query for every security.
    present = {row[0] for row in store.db.execute("SELECT DISTINCT ts_code FROM daily WHERE trade_date BETWEEN ? AND ?", (start, end))}
    rows = store.db.execute("SELECT ts_code,list_date,delist_date FROM stock_basic WHERE list_status='D' AND list_date<=? AND (delist_date IS NULL OR delist_date>=?)", (end, start))
    for row in rows:
        if row["ts_code"] not in present:
            store.warn("daily", "DELISTED_NO_ROWS", "No bars for a delisted security whose listing interval overlaps the run. Check suspensions, code changes, provider coverage and failed days.",
                       {"start_date": start, "end_date": end, "ts_code": row["ts_code"]}, ts_code=row["ts_code"])


def audit_listing_intervals(store, start, end):
    """Some current codes carry history from a different market/listing period."""
    rows = store.db.execute('''
        SELECT s.ts_code,s.exchange,s.list_date,s.delist_date,count(*) AS affected,
               min(d.trade_date) AS first_day,max(d.trade_date) AS last_day
        FROM stock_basic s JOIN daily d ON d.ts_code=s.ts_code
        WHERE d.trade_date BETWEEN ? AND ?
          AND (d.trade_date<s.list_date OR
               (s.exchange='BSE' AND d.trade_date<?) OR
               (s.delist_date IS NOT NULL AND d.trade_date>s.delist_date))
        GROUP BY s.ts_code
    ''', (start, end, BSE_OPEN_DATE)).fetchall()
    for row in rows:
        store.warn("daily", "OUTSIDE_LISTING_INTERVAL",
                   f"{row['affected']} bars in {row['first_day']}..{row['last_day']} lie outside the listing/market interval (stock_basic: {row['list_date']}..{row['delist_date']}; BSE market starts {BSE_OPEN_DATE}). Original bars retained; verify former-market history, relisting or code mapping before backtesting.",
                   {"start_date": row["first_day"], "end_date": row["last_day"], "ts_code": row["ts_code"]}, ts_code=row["ts_code"])


def write_report(store, directory, status):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"warnings_{store.run_id}.md"
    run = store.db.execute("SELECT * FROM runs WHERE run_id=?", (store.run_id,)).fetchone()
    warnings = list(store.db.execute("SELECT * FROM warnings WHERE run_id=? ORDER BY id", (store.run_id,)))
    counts = dict(store.db.execute("SELECT status,count(*) FROM date_status WHERE trade_date BETWEEN ? AND ? GROUP BY status", (run["start_date"], run["end_date"])))
    unresolved = list(store.db.execute("SELECT trade_date,status,returned_rows,saved_rows FROM date_status WHERE trade_date BETWEEN ? AND ? AND status!='success' ORDER BY trade_date", (run["start_date"], run["end_date"])))
    lines = ["# Tushare 日线下载异常报告", "", f"- Run ID: `{store.run_id}`", f"- 范围：{run['start_date']}—{run['end_date']}（Asia/Shanghai）", f"- 状态：{status}", f"- 数据库：`{store.path}`", f"- 日期状态（含先前运行）：`{json.dumps(counts, ensure_ascii=False)}`", f"- 本次 warning 数：{len(warnings)}", "", "日线接口按交易日获取全市场，未按当前上市名单过滤。停牌日没有日线；数量检查是启发式，不是完整性证明。", "盘后字段 20260706 前通常为 NULL；之后不适用/未提供的值仍保留 NULL，不虚构为零。", "", "## 修复方式", "", "- 默认重新运行会补失败和未完成日期；`--retry-warnings` 也重抓 warning 日期。", "- 精确修复：`python src/get_data/get_daily.py --start-date YYYYMMDD --end-date YYYYMMDD --force`。", "- 6000 条截断必须按股票/更小请求补拉，不能只重跑同一全市场请求。", "- `request_log` 保存参数、失败原因；`warnings` 保存股票/字段定位；`rejected_rows` 保留未入库原始行。", "- 当前主库不是历史版本库；修正历史前如需复现实验，请用 SQLite backup API 备份。", "", "## 尚未通过检查的日期", "", "| 日期 | 状态 | 返回行 | 本次入库行 |", "| --- | --- | ---: | ---: |"]
    for row in unresolved:
        lines.append("| " + " | ".join(str(x) for x in row) + " |")
    if not unresolved:
        lines.append("| 无已记录异常日期 | — | — | — |")
    lines += ["", "## 本次异常明细", ""]
    for warning in warnings:
        detail = {key: warning[key] for key in ("api", "trade_date", "ts_code", "field", "kind", "message", "params_json")}
        LOG.warning("SUMMARY #%s %s", warning["id"], json.dumps(detail, ensure_ascii=False))
        lines.extend([f"### Warning {warning['id']}: {warning['kind']}", "", "```json", json.dumps(detail, ensure_ascii=False, indent=2).replace("```", "` ` `"), "```", ""])
    if not warnings:
        lines.append("本次未记录 warning；仍需结合请求日志及日期覆盖核验数据完整性。")
    temporary = path.with_suffix(".md.tmp")
    temporary.write_text("\n".join(lines) + "\n", encoding="utf-8")
    temporary.replace(path)
    return path, len(warnings)


def run_download(client, store, args):
    stocks = load_stocks(client, store)
    days = load_calendar(client, store, args.start_date, args.end_date)
    if not days:
        store.warn("daily", "NO_TRADING_DAYS", "No usable open days in range; inspect calendar warnings", {"start_date": args.start_date, "end_date": args.end_date})
        return
    pending = [day for day in days if not store.should_skip(day, args.retry_warnings, args.force)]
    if args.max_days is not None:
        pending = pending[:args.max_days]
    LOG.info("Calendar: %d open days; %d dates scheduled; historical/current stock metadata: %d", len(days), len(pending), len(stocks))
    for index, day in enumerate(pending, 1):
        response = fetch(client, store, "daily", {"trade_date": day}, DAILY_FIELDS)
        if response is None:
            store.mark_failed(day)
            continue
        expected = sum(bool(s["list_date"] and s["list_date"] <= day and (not s["delist_date"] or s["delist_date"] >= day)) for s in stocks)
        previous = store.db.execute("SELECT saved_rows FROM date_status WHERE trade_date<? AND status='success' ORDER BY trade_date DESC LIMIT 1", (day,)).fetchone()
        result = validate_daily(*response, day, expected or None, previous[0] if previous else None)
        store.save_daily(day, result)
        LOG.info("[%d/%d] %s returned=%d saved=%d warnings=%d", index, len(pending), day, result.raw_count, len(result.rows), len(result.issues))
    # Independent progress: an already successful stock date can still lack its index.
    index_days = [row[0] for row in store.db.execute(
        "SELECT cal_date FROM trade_cal WHERE exchange='SSE' AND is_open=1 AND cal_date BETWEEN ? AND ? ORDER BY cal_date",
        (args.start_date, args.end_date))]
    existing_index = {row[0] for row in store.db.execute("SELECT trade_date FROM daily WHERE ts_code=?", (BENCHMARK_CODE,))}
    index_pending = [day for day in index_days if args.force or day not in existing_index]
    if args.max_days is not None:
        index_pending = index_pending[:args.max_days]
    query = lambda api, params, fields: fetch(client, store, api, params, fields)
    for params, result in index_results(query, index_days, index_pending):
        if result is None:
            continue
        with store.db:
            upsert_daily_rows(store.db, result.rows)
            store.db.executemany("INSERT INTO rejected_rows(run_id,trade_date,payload_json) VALUES(?,?,?)",
                                [(store.run_id, None, json.dumps(row, ensure_ascii=False, default=str)) for row in result.rejected])
        for problem in result.issues:
            store.warn("index_daily", params=params, **problem)
        LOG.info("Index %s %s..%s saved=%d warnings=%d", BENCHMARK_CODE, params["start_date"], params["end_date"], len(result.rows), len(result.issues))
    if args.max_days is None:
        audit_delisted(store, args.start_date, args.end_date)
        audit_listing_intervals(store, args.start_date, args.end_date)
    unattempted = [day for day in days if store.db.execute("SELECT 1 FROM date_status WHERE trade_date=?", (day,)).fetchone() is None]
    if unattempted:
        store.warn("daily", "UNATTEMPTED_DATES", f"{len(unattempted)} trading dates not attempted: " + ",".join(unattempted), {"start_date": args.start_date, "end_date": args.end_date})


def build_parser():
    today = datetime.now(TZ).date()
    # Never mark an incomplete intraday bar as a finished day.
    end = today if datetime.now(TZ).hour >= 18 else today - timedelta(days=1)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start-date", default="20041122", help="Inclusive history start; fixed so migration retains the original history")
    parser.add_argument("--end-date", default=end.strftime("%Y%m%d"))
    parser.add_argument("--db", type=Path, default=ROOT / "data/daily_data/daily_data.db")
    parser.add_argument("--report-dir", type=Path, default=ROOT / "data/daily_data/reports")
    parser.add_argument("--token-file", type=Path, default=ROOT / ".tushare_token")
    parser.add_argument("--daily-limit-rpm", type=float, default=200, help="Declared limit before applying 0.75; 200 for this 2000-point account")
    parser.add_argument("--timeout", type=float, default=30)
    parser.add_argument("--transport", choices=("auto", "curl", "urllib"), default="auto")
    parser.add_argument("--retry-warnings", action="store_true")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--init-only", action="store_true")
    parser.add_argument("--migrate-only", action="store_true", help="Enrich an existing DB with historical status sources and rebuild derived tables; no price download")
    parser.add_argument("--offline", action="store_true", help="With --migrate-only, rebuild using cached sources without a token or network")
    parser.add_argument("--refresh-status", action="store_true", help="Refetch cached name histories and suspension dates (also repairs upstream revisions)")
    parser.add_argument("--rules", type=Path, help="Explicit eligibility rules; otherwise inherit rules stored in the database")
    parser.add_argument("--max-days", type=int, help="Only process this many pending trading days (smoke test)")
    return parser


def finalize_dataset(client, store, args):
    """Shared finalization for fresh downloads and standalone tag repairs."""
    from get_data import daily_tables as trading
    from get_data import stock_tags
    db = store.db
    start, end = db.execute("SELECT min(trade_date),max(trade_date) FROM daily WHERE ts_code<>?", (BENCHMARK_CODE,)).fetchone()
    if not start:
        store.warn("derived", "NO_STOCK_HISTORY", "No stock rows available to build the dataset")
        return
    # Recover old rules before doing thousands of requests; future runs need
    # only the DB's dataset_meta, not development scripts or report files.
    rules = trading.resolve_rules(db, args.rules, args.report_dir, args.db)
    offline = getattr(args, "offline", False)
    if args.migrate_only and not offline:
        load_stocks(client, store)
    for lower, upper in ((trading.shifted(start, -31), trading.shifted(start, -1)),
                         (trading.shifted(end, 1), trading.shifted(end, 31))):
        if not offline:
            load_calendar(client, store, lower, upper)
    stocks = {r["ts_code"]: dict(r) for r in db.execute("SELECT * FROM stock_basic")}
    days = [r[0] for r in db.execute("SELECT DISTINCT cal_date FROM trade_cal WHERE is_open=1 AND cal_date BETWEEN ? AND ?", (start, end))]
    days.extend(r[0] for r in db.execute("SELECT DISTINCT trade_date FROM daily WHERE ts_code<>?", (BENCHMARK_CODE,)))
    work = stock_tags.plan(db, stocks, days, start, end, args.refresh_status)
    LOG.info("Status enrichment %s..%s: %d requests; successful batches are resumable", start, end, len(work))
    query = lambda api, params, fields: fetch(client, store, api, params, fields)
    def warn(kind, message, **location):
        store.warn(location.pop("api", "status"), kind, message, **location)
    if offline and work:
        store.warn("status", "OFFLINE_STATUS_PENDING", f"{len(work)} source batches are missing or stale; rerun add_tag.py --refresh-status to fetch them")
    for batch in stock_tags.fetch_batches(query, warn, work if not offline else [], db):
        with db:
            stock_tags.apply_batch(db, batch, stamp())
    # Sources are checkpointed above; all derived replacements and daily tags
    # commit together. A failed build leaves old derived data intact.
    with db:
        stock_tags.set_meta(db, "eligibility_rules", json.dumps(rules, ensure_ascii=False, sort_keys=True))
        manifest, unknown = trading.build(db, SimpleNamespace(db=args.db, start_date=start, end_date=end,
                                           rules=None, calendar_padding=31, fetch_calendar=False, report_dir=args.report_dir))
        args.report_dir.mkdir(parents=True, exist_ok=True)
        path = args.report_dir / f"trading_tables_{manifest['build_id']}.json"
        temporary = path.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temporary.replace(path)
    if unknown:
        store.warn("derived", "DERIVED_UNKNOWN", "Unverified eligibility/calendar/tags retained; locations and counts: " + str(path),
                   {"start_date": start, "end_date": end})
    LOG.info("Unified dataset built; manifest=%s", path)


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.migrate_only and not args.db.is_file():
            raise ValueError("--migrate-only requires an existing database")
        if args.migrate_only and args.init_only:
            raise ValueError("--migrate-only and --init-only are mutually exclusive")
        if args.offline and (not args.migrate_only or args.refresh_status):
            raise ValueError("--offline requires --migrate-only and cannot be used with --refresh-status")
        if args.migrate_only:
            source = sqlite3.connect(args.db.resolve().as_uri() + "?mode=ro", uri=True)
            try:
                first, last = source.execute("SELECT min(trade_date),max(trade_date) FROM daily WHERE ts_code<>?", (BENCHMARK_CODE,)).fetchone()
                if not first:
                    raise ValueError("--migrate-only requires existing stock history")
                args.start_date, args.end_date = first, last
            finally:
                source.close()
        if parse_date(args.start_date) > parse_date(args.end_date):
            raise ValueError("start-date must be <= end-date")
        if args.timeout <= 0 or not 0 < args.daily_limit_rpm <= 200:
            raise ValueError("timeout > 0 and 0 < daily-limit-rpm <= 200 required for this account")
        if args.max_days is not None and args.max_days < 1:
            raise ValueError("max-days must be positive")
    except ValueError as exc:
        parser.error(str(exc))
    args.report_dir.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", stream=sys.stdout)
    store = Store(args.db)
    config = {key: str(value) for key, value in vars(args).items() if key != "token_file"}
    store.start_run(args.start_date, args.end_date, config)
    status, exit_code, token = "completed", 0, ""
    try:
        if args.init_only:
            status = "initialized_only"
        elif args.offline:
            finalize_dataset(None, store, args)
        else:
            token = os.environ.get("TUSHARE_TOKEN", "").strip()
            if not token and args.token_file.exists():
                token = args.token_file.read_text(encoding="utf-8").strip()
            if not token:
                raise ValueError("Set TUSHARE_TOKEN or provide --token-file; no token found")
            limiter = RateLimiter(global_rpm=args.daily_limit_rpm)
            client = TushareClient(token, limiter, args.timeout, args.transport)
            LOG.info("Run=%s range=%s..%s effective daily limit=%.1f/min interval>=%.3fs", store.run_id, args.start_date, args.end_date, args.daily_limit_rpm * .75, limiter.interval)
            if not args.migrate_only:
                run_download(client, store, args)
            finalize_dataset(client, store, args)
    except KeyboardInterrupt:
        status, exit_code = "interrupted", 130
        store.warn("runner", "INTERRUPTED", "User interrupted; committed dates retained; rerun to resume")
    except Exception as exc:
        status, exit_code = "failed", 1
        message = str(exc).replace(token, "[REDACTED]") if token else str(exc)
        store.warn("runner", "FATAL_ERROR", f"{type(exc).__name__}: {message}")
    finally:
        warning_count = store.db.execute("SELECT count(*) FROM warnings WHERE run_id=?", (store.run_id,)).fetchone()[0]
        unresolved = store.db.execute("SELECT count(*) FROM date_status WHERE trade_date BETWEEN ? AND ? AND status!='success'", (args.start_date, args.end_date)).fetchone()[0]
        if status == "completed" and (warning_count or unresolved):
            status, exit_code = "completed_with_warnings", 2
        with store.db:
            store.db.execute("UPDATE runs SET ended_at=?,status=? WHERE run_id=?", (stamp(), status, store.run_id))
        try:
            report, count = write_report(store, args.report_dir, status)
            LOG.info("Finished status=%s warnings=%d report=%s", status, count, report)
        finally:
            store.close()
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
