#!/usr/bin/env python3
"""Permanent calendar/eligibility/tag builder shared by both ingestion entries.

Default: local-only, no API requests. --fetch-calendar optionally fills calendar
padding from Tushare at 75% of the 200/min account limit. Price fields are never
changed; daily tags and derived tables are rebuilt in the caller's transaction.
Use get_daily.py --migrate-only to fetch status sources before a full rebuild.

is_tradable is a retrospective, conservative evidence flag, NOT an executable
order guarantee or a point-in-time pre-open universe:
  1 = eligible identity/market interval + valid prices + positive volume;
  0 = explicit market/listing/suspension exclusion;
  NULL = insufficient evidence, including a missing daily bar.
Use WHERE is_tradable=1 for the confirmed pool; retain NULL rows for investigation.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta
import hashlib
import json
import logging
import math
import os
from pathlib import Path
import sqlite3
import uuid
from zoneinfo import ZoneInfo
if __package__ in (None, ""):
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from get_data.get_daily import BENCHMARK_CODE
from get_data import stock_tags

ROOT = Path(__file__).resolve().parents[2]
RULE_VERSION = "2026-11-26-tags-v3"
BSE_OPEN_DATE = "20211115"
EXCHANGES = ("SSE", "SZSE", "BSE")
LOG = logging.getLogger("daily_tables")

CALENDAR_COLUMNS = (
    "exchange", "cal_date", "is_open", "weekday", "boundary_tag",
    "prev_trade_date", "next_trade_date", "days_since_prev_trade",
    "days_until_next_trade", "source", "build_id",
)
STOCK_COLUMNS = (
    "trade_date", "ts_code", "exchange", "security_id", "data_available",
    "is_tradable", "reason", "tags", "tags_unknown",
)

CALENDAR_DDL = '''CREATE TABLE IF NOT EXISTS market_calendar (
    exchange TEXT NOT NULL CHECK(exchange IN ('SSE','SZSE','BSE')),
    cal_date TEXT NOT NULL CHECK(length(cal_date)=8),
    is_open INTEGER CHECK(is_open IN (0,1)),
    weekday INTEGER NOT NULL CHECK(weekday BETWEEN 1 AND 7),
    boundary_tag INTEGER CHECK(boundary_tag BETWEEN 0 AND 3),
    prev_trade_date TEXT,
    next_trade_date TEXT,
    days_since_prev_trade INTEGER CHECK(days_since_prev_trade > 0),
    days_until_next_trade INTEGER CHECK(days_until_next_trade > 0),
    source TEXT NOT NULL,
    build_id TEXT NOT NULL,
    PRIMARY KEY(exchange,cal_date),
    CHECK(boundary_tag IS NULL OR is_open=1)
) WITHOUT ROWID'''

STOCK_DDL = '''CREATE TABLE IF NOT EXISTS tradable_stock (
    trade_date TEXT NOT NULL CHECK(length(trade_date)=8),
    ts_code TEXT NOT NULL,
    exchange TEXT NOT NULL CHECK(exchange IN ('SSE','SZSE','BSE')),
    security_id TEXT,
    data_available INTEGER NOT NULL CHECK(data_available IN (0,1)),
    is_tradable INTEGER CHECK(is_tradable IN (0,1)),
    reason TEXT NOT NULL,
    PRIMARY KEY(trade_date,ts_code),
    FOREIGN KEY(exchange,trade_date) REFERENCES market_calendar(exchange,cal_date),
    CHECK(is_tradable IS NOT 1 OR (data_available=1 AND security_id IS NOT NULL))
) WITHOUT ROWID'''

# Explicitly researched exceptions. Never strip a T prefix globally. These are
# partial history rules, not a claim to contain every historical suspension.
BUILTIN_RULES = {
    "aliases": {"T600018.SH": "600018.SH"},
    "alias_sources": {
        "T600018.SH": "https://static.cninfo.com.cn/finalpage/2006-02-16/16450034.PDF",
    },
    "blocked_intervals": [
        {"security_id": "000765.SZ", "start_date": "20040322", "end_date": "20050704",
         "reason": "LISTING_SUSPENDED", "source": "https://static.cninfo.com.cn/finalpage/2025-01-14/1222322626.PDF"},
        {"security_id": "000033.SZ", "start_date": "20150521", "end_date": "20170523",
         "reason": "LISTING_SUSPENDED", "source": "https://disc.static.szse.cn/disc/disk01/finalpage/2017-07-07/f4f799b7-4f94-4f48-a8f3-950e14e116f3.PDF"},
        {"security_id": "000520.SZ", "start_date": "20140516", "end_date": "20151217",
         "reason": "LISTING_SUSPENDED_OR_HALTED", "source": "https://static.cninfo.com.cn/finalpage/2015-12-18/1201844007.PDF"},
        {"security_id": "002506.SZ", "start_date": "20140528", "end_date": "20150811",
         "reason": "LISTING_SUSPENDED", "source": "https://static.cninfo.com.cn/finalpage/2015-08-18/1201449950.PDF"},
        {"security_id": "600656.SH", "start_date": "20150528", "end_date": "20160328",
         "reason": "LISTING_SUSPENDED", "source": "https://static.cninfo.com.cn/finalpage/2016-04-29/1202274622.PDF"},
    ],
}


def parse_day(value):
    day = datetime.strptime(value, "%Y%m%d").date()
    if day.strftime("%Y%m%d") != value:
        raise ValueError(f"Invalid YYYYMMDD date: {value!r}")
    return day


def shifted(day, count):
    return (parse_day(day) + timedelta(days=count)).strftime("%Y%m%d")


def day_range(start, end):
    cursor, end_day = parse_day(start), parse_day(end)
    while cursor <= end_day:
        yield cursor.strftime("%Y%m%d")
        cursor += timedelta(days=1)


@dataclass(frozen=True)
class CalendarDay:
    is_open: int | None
    pretrade_date: str | None = None
    source: str = "trade_cal"


@dataclass(frozen=True)
class Instrument:
    security_id: str
    ts_code: str  # Quote code, distinct from old corporate/security identity.
    exchange: str
    start_date: str
    end_date: str | None = None  # Inclusive last eligible calendar date.


def exchange_for(code):
    return {"SH": "SSE", "SZ": "SZSE", "BJ": "BSE"}.get(code.rsplit(".", 1)[-1])


def complete_calendars(calendars, start, end):
    """Fill unknown explicitly; proxy BSE only when both SH/SZ calendars agree."""
    result = {exchange: dict(calendars.get(exchange, {})) for exchange in EXCHANGES}
    unknown = CalendarDay(None, None, "UNKNOWN")
    for day in day_range(start, end):
        for exchange in ("SSE", "SZSE"):
            result[exchange].setdefault(day, unknown)
        if day < BSE_OPEN_DATE:
            result["BSE"][day] = CalendarDay(0, None, "BEFORE_BSE_OPEN")
        elif day not in result["BSE"] or result["BSE"][day].is_open is None:
            sh, sz = result["SSE"][day], result["SZSE"][day]
            if sh.is_open is not None and sh.is_open == sz.is_open:
                previous = sh.pretrade_date if sh.pretrade_date == sz.pretrade_date else None
                if previous and previous < BSE_OPEN_DATE:
                    previous = None
                result["BSE"][day] = CalendarDay(sh.is_open, previous, "SSE_SZSE_PROXY")
            else:
                result["BSE"][day] = CalendarDay(None, None, "BSE_CALENDAR_UNKNOWN")
    return result


def calendar_rows(calendars, start, end):
    """Return ten columns (build_id is added by the writer).

    The label concerns adjacent NATURAL days: prev closed + 2 * next closed.
    A missing day is unknown, never automatically a weekend/holiday.
    """
    output = []
    for exchange in EXCHANGES:
        records = calendars[exchange]
        days = sorted(records)
        previous, following, last = {}, {}, None
        for day in days:
            info = records[day]
            previous[day] = last
            supplied = info.pretrade_date
            if supplied and supplied < day and not (exchange == "BSE" and supplied < BSE_OPEN_DATE):
                if previous[day] is None:
                    previous[day] = supplied
            if info.is_open is None:
                last = None  # Do not jump across an unknown calendar segment.
            elif info.is_open == 1:
                last = day
        last = None
        for day in reversed(days):
            following[day] = last
            if records[day].is_open is None:
                last = None
            elif records[day].is_open == 1:
                last = day
        for day in day_range(start, end):
            info = records.get(day, CalendarDay(None, None, "UNKNOWN"))
            prior_day, next_day = shifted(day, -1), shifted(day, 1)
            prior = records.get(prior_day, CalendarDay(None)).is_open
            after = records.get(next_day, CalendarDay(None)).is_open
            prev_date, next_date = previous.get(day), following.get(day)
            # An authoritative pretrade_date can establish the missing left edge.
            if prior is None and info.pretrade_date and info.pretrade_date < day:
                prior = int(info.pretrade_date == prior_day)
            tag = (1 - prior) + 2 * (1 - after) if info.is_open == 1 and prior is not None and after is not None else None
            prev_gap = (parse_day(day) - parse_day(prev_date)).days if prev_date else None
            next_gap = (parse_day(next_date) - parse_day(day)).days if next_date else None
            output.append((exchange, day, info.is_open, parse_day(day).isoweekday(), tag,
                           prev_date, next_date, prev_gap, next_gap, info.source))
    return output


def load_rules(path=None):
    rules = json.loads(json.dumps(BUILTIN_RULES))
    if path:
        custom = json.loads(Path(path).read_text(encoding="utf-8"))
        if not isinstance(custom, dict):
            raise ValueError("Rules file must be a JSON object")
        if custom.get("disable_builtin"):
            rules = {"aliases": {}, "alias_sources": {}, "blocked_intervals": []}
        rules["aliases"].update(custom.get("aliases", {}))
        rules["alias_sources"].update(custom.get("alias_sources", {}))
        rules["blocked_intervals"].extend(custom.get("blocked_intervals", []))
    for identity, quote in rules["aliases"].items():
        if not isinstance(identity, str) or not isinstance(quote, str) or exchange_for(quote) is None:
            raise ValueError("Each alias must map a security_id to a valid SH/SZ/BJ quote code")
    for interval in rules["blocked_intervals"]:
        if not interval.get("security_id") or not interval.get("source"):
            raise ValueError("Blocked intervals need security_id and source")
        if parse_day(interval["start_date"]) > parse_day(interval["end_date"]):
            raise ValueError("Invalid blocked interval")
        interval.setdefault("reason", "FULL_DAY_SUSPENDED")
    return rules


def load_instruments(db, rules):
    by_code = defaultdict(list)
    for row in db.execute("SELECT ts_code,exchange,list_date,delist_date FROM stock_basic"):
        identity = row["ts_code"]
        quote = rules["aliases"].get(identity, identity)
        exchange = row["exchange"] or exchange_for(quote)
        if exchange not in EXCHANGES or exchange_for(quote) != exchange:
            raise ValueError(f"Invalid exchange for security {identity}")
        parse_day(row["list_date"])
        end = shifted(row["delist_date"], -1) if row["delist_date"] else None
        if end and end < row["list_date"]:
            raise ValueError(f"Invalid listing interval for {identity}")
        by_code[quote].append(Instrument(identity, quote, exchange, row["list_date"], end))
    for instruments in by_code.values():
        instruments.sort(key=lambda item: item.start_date)
    return dict(by_code)


def select_instrument(instruments, day):
    active = [item for item in instruments if item.start_date <= day and (item.end_date is None or day <= item.end_date)]
    if len(active) == 1:
        return active[0], False
    if len(active) > 1:
        return None, True
    # Keep a known outside-window identity for diagnosis of observed raw bars.
    if not instruments:
        return None, False
    past = [item for item in instruments if item.start_date <= day]
    nearest = max(past, key=lambda item: item.start_date) if past else min(instruments, key=lambda item: item.start_date)
    return nearest, False


def assess(day, exchange_open, instrument, bar, blocked_reason=None, identity_conflict=False):
    if exchange_open == 0:
        return 0, "MARKET_CLOSED"
    if identity_conflict:
        return None, "IDENTITY_CONFLICT"
    if instrument is None:
        return None, "UNKNOWN_IDENTITY"
    if instrument.exchange == "BSE" and day < BSE_OPEN_DATE:
        return 0, "BEFORE_BSE_OPEN"
    if day < instrument.start_date or (instrument.end_date and day > instrument.end_date):
        return 0, "OUTSIDE_LISTING_INTERVAL"
    if blocked_reason:
        # A real bar contradicting a full-day exclusion requires review, not suppression.
        return (None, "SUSPENSION_BAR_CONFLICT") if bar is not None else (0, blocked_reason)
    if exchange_open is None:
        return None, "CALENDAR_UNKNOWN"
    if bar is None:
        return None, "NO_DAILY_DATA"
    try:
        values = [bar[column] for column in ("open", "high", "low", "close", "vol", "amount")]
        if any(value is None or isinstance(value, bool) or not math.isfinite(float(value)) for value in values):
            return None, "INVALID_BAR"
        opening, high, low, close, volume, amount = map(float, values)
        if not 0 < low <= min(opening, close) <= max(opening, close) <= high or volume < 0 or amount < 0:
            return None, "INVALID_BAR"
        if volume == 0:
            return None, "ZERO_VOLUME"
    except (TypeError, ValueError, KeyError, OverflowError):
        return None, "INVALID_BAR"
    return 1, "TRADED"


def missing_spans(records, start, end):
    first, previous = None, None
    for day in day_range(start, end):
        if day not in records or records[day].is_open is None:
            if first is None:
                first = day
            previous = day
        elif first:
            yield first, previous
            first = previous = None
    if first:
        yield first, previous


def load_calendars(db, start, end, args):
    calendars = {exchange: {} for exchange in EXCHANGES}
    for row in db.execute("SELECT exchange,cal_date,is_open,pretrade_date FROM trade_cal WHERE cal_date BETWEEN ? AND ?", (start, end)):
        if row["exchange"] not in EXCHANGES:
            continue
        parse_day(row["cal_date"])
        if row["is_open"] not in (0, 1):
            raise ValueError(f"Invalid trade_cal.is_open: {dict(row)}")
        previous = row["pretrade_date"] or None
        if previous:
            parse_day(previous)
            if previous >= row["cal_date"]:
                raise ValueError(f"Invalid trade_cal.pretrade_date: {dict(row)}")
        calendars[row["exchange"]][row["cal_date"]] = CalendarDay(row["is_open"], previous, "trade_cal:" + row["exchange"])
    if args.fetch_calendar:
        from get_data.get_daily import RateLimiter, TushareClient, validate_calendar
        token = os.environ.get("TUSHARE_TOKEN", "").strip()
        if not token and args.token_file.exists():
            token = args.token_file.read_text(encoding="utf-8").strip()
        if not token:
            raise ValueError("--fetch-calendar requires TUSHARE_TOKEN or --token-file")
        client = TushareClient(token, RateLimiter(global_rpm=args.limit_rpm), args.timeout)
        for exchange in ("SSE", "SZSE"):
            for lower, upper in missing_spans(calendars[exchange], start, end):
                # At most one calendar year per call, far below row limits.
                for year in range(int(lower[:4]), int(upper[:4]) + 1):
                    left, right = max(lower, f"{year}0101"), min(upper, f"{year}1231")
                    try:
                        fields, items = client.query("trade_cal", dict(exchange=exchange, start_date=left, end_date=right),
                                                     ("exchange", "cal_date", "is_open", "pretrade_date"))
                        rows, _, issues = validate_calendar(fields, items, left, right, exchange)
                        if issues:
                            raise ValueError("; ".join(issues))
                        validated = {}
                        for _, day, opened, previous in rows:
                            if previous:
                                parse_day(previous)
                                if previous >= day:
                                    raise ValueError("Invalid previous trading date in fetched calendar")
                            validated[day] = CalendarDay(opened, previous or None, "tushare:trade_cal:" + exchange)
                        calendars[exchange].update(validated)
                    except Exception as exc:
                        LOG.warning("Calendar %s %s..%s: %s; unknown values retained", exchange, left, right, str(exc).replace(token, "[REDACTED]"))
    return complete_calendars(calendars, start, end)


def require_columns(db, table, required):
    existing = {row["name"] for row in db.execute(f'PRAGMA table_info("{table}")')}
    if not set(required).issubset(existing):
        raise ValueError(f"{table}: missing required columns {sorted(set(required) - existing)}")


def create_tables(db):
    db.execute(CALENDAR_DDL)
    db.execute(STOCK_DDL)
    stock_tags.ensure_schema(db)
    for table, columns, primary in (
        ("market_calendar", CALENDAR_COLUMNS, ("exchange", "cal_date")),
        ("tradable_stock", STOCK_COLUMNS, ("trade_date", "ts_code")),
    ):
        info = list(db.execute(f'PRAGMA table_info("{table}")'))
        if {row["name"] for row in info} != set(columns):
            raise ValueError(f"Existing {table} schema differs; refusing to overwrite it")
        actual = tuple(row["name"] for row in sorted(info, key=lambda row: row["pk"]) if row["pk"])
        if actual != primary:
            raise ValueError(f"Existing {table} primary key differs")
    db.execute("CREATE INDEX IF NOT EXISTS idx_market_calendar_date ON market_calendar(cal_date,exchange)")
    db.execute("CREATE INDEX IF NOT EXISTS idx_tradable_stock_code_date ON tradable_stock(ts_code,trade_date)")
    db.execute("CREATE INDEX IF NOT EXISTS idx_tradable_confirmed ON tradable_stock(trade_date,ts_code) WHERE is_tradable=1")


def resolve_rules(db, path=None, report_dir=None, database=None):
    """Persisted rules travel with the DB; old databases recover their manifests once."""
    if path:
        return load_rules(path)
    stored = stock_tags.get_meta(db, "eligibility_rules")
    if stored:
        return json.loads(stored)
    if "market_calendar" not in stock_tags.tables(db):
        return load_rules()
    ids = [r[0] for r in db.execute("SELECT DISTINCT build_id FROM market_calendar")]
    previous = []
    for build_id in ids:
        directories = [Path(report_dir)] if report_dir else []
        if database:
            directories.append(Path(database).resolve().parent / "reports")
        candidate = next((d / f"trading_tables_{build_id}.json" for d in directories
                          if (d / f"trading_tables_{build_id}.json").is_file()), None)
        if candidate is None:
            raise ValueError(f"Cannot recover rules for build {build_id}; supply --rules explicitly")
        previous.append(json.loads(candidate.read_text(encoding="utf-8"))["rules"])
    if previous and any(item != previous[0] for item in previous):
        raise ValueError("Existing ranges use different rules; supply --rules for a full rebuild")
    return previous[0] if previous else load_rules()


def build(db, args):
    require_columns(db, "daily", ("ts_code", "trade_date", "open", "high", "low", "close", "vol", "amount"))
    require_columns(db, "stock_basic", ("ts_code", "exchange", "list_date", "delist_date"))
    require_columns(db, "trade_cal", ("exchange", "cal_date", "is_open", "pretrade_date"))
    bounds = db.execute("SELECT min(trade_date),max(trade_date) FROM daily WHERE ts_code<>?", (BENCHMARK_CODE,)).fetchone()
    start, end = args.start_date or bounds[0], args.end_date or bounds[1]
    if not start or not end or parse_day(start) > parse_day(end):
        raise ValueError("daily has no date range; supply valid --start-date and --end-date")
    rules = resolve_rules(db, args.rules, getattr(args, "report_dir", None), args.db)
    previous_rules = stock_tags.get_meta(db, "eligibility_rules")
    if (args.rules and previous_rules and json.loads(previous_rules) != rules and bounds[0]
            and (start > bounds[0] or end < bounds[1])):
        raise ValueError("Changing eligibility rules requires a full stock-history rebuild")
    instruments = load_instruments(db, rules)
    blocks = defaultdict(list)
    for interval in rules["blocked_intervals"]:
        blocks[interval["security_id"]].append(interval)
    padded_start, padded_end = shifted(start, -args.calendar_padding), shifted(end, args.calendar_padding)
    calendars = load_calendars(db, padded_start, padded_end, args)
    rows = calendar_rows(calendars, start, end)
    build_id = datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y%m%d_%H%M%S_") + uuid.uuid4().hex[:8]
    create_tables(db)
    context = stock_tags.Context(db)
    # Only derived rows within the selected date range are replaced.
    db.execute("DELETE FROM tradable_stock WHERE trade_date BETWEEN ? AND ?", (start, end))
    db.execute("DELETE FROM market_calendar WHERE cal_date BETWEEN ? AND ?", (start, end))
    db.executemany(f"INSERT INTO market_calendar({','.join(CALENDAR_COLUMNS)}) VALUES({','.join('?' for _ in CALENDAR_COLUMNS)})",
                   [row + (build_id,) for row in rows])
    summary = Counter()
    samples = defaultdict(list)
    tag_unknown_counts = Counter()
    tag_unknown_samples = defaultdict(list)
    sql = f"INSERT INTO tradable_stock({','.join(STOCK_COLUMNS)}) VALUES({','.join('?' for _ in STOCK_COLUMNS)})"
    for index, day in enumerate(day_range(start, end), 1):
        bars = {row["ts_code"]: dict(row) for row in db.execute("SELECT ts_code,open,high,low,close,vol,amount,tags,tags_unknown FROM daily WHERE trade_date=? AND ts_code<>?", (day, BENCHMARK_CODE))}
        candidates = set(bars)
        for code, entries in instruments.items():
            if any(item.start_date <= day
                   and not (item.exchange == "BSE" and day < BSE_OPEN_DATE)
                   and calendars[item.exchange][day].is_open != 0 for item in entries):
                candidates.add(code)
        batch, tag_updates = [], []
        for code in sorted(candidates):
            instrument, conflict = select_instrument(instruments.get(code, []), day)
            exchange = instrument.exchange if instrument else exchange_for(code)
            if exchange not in EXCHANGES:
                raise ValueError(f"Unsupported quote code {code}; supply identity mapping before building")
            blocked = None
            if instrument:
                for interval in blocks[instrument.security_id]:
                    if interval["start_date"] <= day <= interval["end_date"]:
                        blocked = interval["reason"]
                        break
            bar = bars.get(code)
            if not blocked and context.full_day_suspension(code, day, instrument):
                blocked = "FULL_DAY_SUSPENDED"
            eligible, reason = assess(day, calendars[exchange][day].is_open, instrument, bar, blocked, conflict)
            tags, unknown = context.resolve(code, day, instrument, blocked, conflict)
            if '"退市"' in tags:
                eligible, reason = 0, "DELISTED"
            batch.append((day, code, exchange, instrument.security_id if instrument else None, int(bar is not None), eligible, reason, tags, unknown))
            if bar is not None and (bar["tags"] != tags or bar["tags_unknown"] != unknown):
                tag_updates.append((tags, unknown, day, code, tags, unknown))
            for tag in json.loads(unknown):
                tag_unknown_counts[tag] += 1
                if len(tag_unknown_samples[tag]) < 20:
                    tag_unknown_samples[tag].append({"trade_date": day, "ts_code": code})
            summary[reason] += 1
            if eligible is None and len(samples[reason]) < 20:
                samples[reason].append({"trade_date": day, "ts_code": code})
        db.executemany(sql, batch)
        db.executemany("UPDATE daily SET tags=?,tags_unknown=? WHERE trade_date=? AND ts_code=? "
                       "AND (tags<>? OR tags_unknown<>?)", tag_updates)
        if index % 100 == 0:
            LOG.info("Processed through %s: %d candidates (not yet committed)", day, sum(summary.values()))
    db.execute("UPDATE daily SET tags='[]',tags_unknown='[]' WHERE ts_code=? AND (tags<>'[]' OR tags_unknown<>'[]')", (BENCHMARK_CODE,))
    stock_tags.set_meta(db, "eligibility_rules", json.dumps(rules, ensure_ascii=False, sort_keys=True))
    if bounds[0] and start <= bounds[0] and end >= bounds[1]:
        stock_tags.set_meta(db, "tag_version", stock_tags.VERSION)
    stock_tags.set_meta(db, "tags_dirty", "0")
    calendar_unknown = sum(row[2] is None for row in rows)
    open_without_tag = sum(row[2] == 1 and row[4] is None for row in rows)
    open_without_gaps = sum(row[2] == 1 and (row[7] is None or row[8] is None) for row in rows)
    unknown_stock = db.execute("SELECT count(*) FROM tradable_stock WHERE trade_date BETWEEN ? AND ? AND is_tradable IS NULL", (start, end)).fetchone()[0]
    manifest = {
        "build_id": build_id, "rule_version": RULE_VERSION, "built_at": datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(timespec="seconds"),
        "database": str(args.db.resolve()), "start_date": start, "end_date": end,
        "rules_sha256": hashlib.sha256(json.dumps(rules, ensure_ascii=False, sort_keys=True).encode()).hexdigest(),
        "rules": rules, "calendar_rows": len(rows), "unknown_calendar_rows": calendar_unknown,
        "open_days_without_boundary_tag": open_without_tag, "open_days_without_neighbor_gap": open_without_gaps,
        "stock_rows": sum(summary.values()), "unknown_stock_rows": unknown_stock,
        "counts_by_reason": dict(summary), "unknown_samples": dict(samples),
        "tag_unknown_counts": dict(tag_unknown_counts), "tag_unknown_samples": dict(tag_unknown_samples),
        "tag_version": stock_tags.VERSION, "suspension_source_aliases": stock_tags.SUSPENSION_SOURCE_ALIASES,
        "source_summary": {"daily_min_date": bounds[0], "daily_max_date": bounds[1],
                           "stock_basic_rows": db.execute("SELECT count(*) FROM stock_basic").fetchone()[0]},
        "calendar_fetch_enabled": args.fetch_calendar,
        "limitations": ["Retrospective trade evidence, not a pre-open universe or order-fill guarantee.",
                        "No daily bar means unknown, not proof of suspension.",
                        "Built-in suspension rules are partial; add audited full-day exclusions via --rules.",
                        "Daily/calendar revisions require rebuilding affected ranges.",
                        "Source summary is not a cryptographic snapshot of historical data."],
    }
    return manifest, bool(unknown_stock or calendar_unknown or open_without_tag or open_without_gaps or tag_unknown_counts)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=ROOT / "data/daily_data/daily_data.db")
    parser.add_argument("--start-date", help="YYYYMMDD; default earliest stock date (benchmark excluded)")
    parser.add_argument("--end-date", help="YYYYMMDD; default latest stock date (benchmark excluded)")
    parser.add_argument("--rules", type=Path, help="JSON: aliases, alias_sources, blocked_intervals; disable_builtin optional")
    parser.add_argument("--fetch-calendar", action="store_true", help="Fill missing padded SH/SZ calendar dates via Tushare")
    parser.add_argument("--calendar-padding", type=int, default=31)
    parser.add_argument("--token-file", type=Path, default=ROOT / ".tushare_token")
    parser.add_argument("--limit-rpm", type=float, default=200, help="Raw API quota, multiplied by 0.75")
    parser.add_argument("--timeout", type=float, default=30)
    parser.add_argument("--report-dir", type=Path, default=ROOT / "data/daily_data/reports")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    if not args.db.is_file():
        parser.error("Existing daily_data.db required; refusing to create an empty database")
    if args.calendar_padding < 1 or not 0 < args.limit_rpm <= 200 or args.timeout <= 0:
        parser.error("padding >= 1, 0 < limit-rpm <= 200 and timeout > 0 required")
    for value in (args.start_date, args.end_date):
        if value:
            try:
                parse_day(value)
            except ValueError as exc:
                parser.error(str(exc))
    db = sqlite3.connect(args.db.resolve().as_uri() + "?mode=rw", uri=True, timeout=60, isolation_level=None)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    committed = False
    temporary = None
    try:
        # One writer and one consistent source snapshot. Reads remain available
        # under the source database's existing WAL mode. No executescript commits.
        db.execute("BEGIN IMMEDIATE")
        manifest, has_unknown = build(db, args)
        args.report_dir.mkdir(parents=True, exist_ok=True)
        destination = args.report_dir / f"trading_tables_{manifest['build_id']}.json"
        temporary = destination.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        db.commit()
        committed = True
        temporary.replace(destination)
        LOG.info("Committed calendar=%d stock_rows=%d unknown_stock=%d manifest=%s", manifest["calendar_rows"], manifest["stock_rows"], manifest["unknown_stock_rows"], destination)
        if has_unknown:
            LOG.warning("Unknown eligibility/calendar values retained; inspect manifest. This is not a fully verified tradability history.")
        return 2 if has_unknown else 0
    except KeyboardInterrupt:
        db.rollback()
        if committed:
            LOG.warning("Interrupted after database commit; check pending manifest: %s", temporary)
        else:
            LOG.warning("Interrupted; derived-table transaction rolled back")
        return 130
    except Exception as exc:
        db.rollback()
        LOG.error("%s: %s", type(exc).__name__, exc)
        if committed:
            LOG.error("Database committed, but manifest finalization failed; pending manifest: %s", temporary)
        else:
            LOG.error("No derived-table changes committed")
        return 1
    finally:
        db.close()
        if temporary is not None and not committed:
            temporary.unlink(missing_ok=True)


if __name__ == "__main__":
    raise SystemExit(main())
