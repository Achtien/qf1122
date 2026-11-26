#!/usr/bin/env python3
"""Update prices, historical status sources and derived tables in one SQLite DB.

Uses only the standard library and permanent src modules. No pending price,
status, schema or explicit-rule work means no database write.
Daily publication: https://tushare.pro/document/2?doc_id=27 (15:00–16:00 Shanghai).
Today's responses before --settle-hour are observed but not committed as final.
The benchmark has independent coverage and --index-settle-hour (default 18).
"""
from __future__ import annotations

import argparse
from datetime import datetime
import json
import logging
import math
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
from types import SimpleNamespace
import uuid

ROOT = Path(__file__).resolve().parents[2]
if __package__ in (None, ""):
    sys.path.insert(0, str(ROOT / "src"))
from get_data import get_daily as daily
from get_data import daily_tables as trading
from get_data import stock_tags

LOG = logging.getLogger("update_daily")


class Audit:
    def __init__(self, token=""):
        self.token = token
        self.requests = []
        self.warnings = []
        self.result = {"run_id": datetime.now(daily.TZ).strftime("update_%Y%m%d_%H%M%S_") + uuid.uuid4().hex[:8],
                       "database_changed": False, "status": "checking"}

    def warn(self, kind, message, **location):
        message = str(message).replace(self.token, "[REDACTED]") if self.token else str(message)
        item = dict(kind=kind, message=message, **location)
        self.warnings.append(item)
        LOG.warning("%s %s: %s", kind, json.dumps(location, ensure_ascii=False), message)

    def query(self, client, api, params, fields):
        record = dict(api=api, params=params, requested_at=daily.stamp())
        try:
            response = client.query(api, params, fields)
            record.update(status="success", returned_rows=len(response[1]), error=None)
            return response
        except Exception as exc:
            error = str(exc).replace(self.token, "[REDACTED]") if self.token else str(exc)
            record.update(status="failed", returned_rows=0, error=error)
            self.warn("REQUEST_FAILED", error, api=api, params=params)
            return None
        finally:
            self.requests.append(record)

    def write(self, directory):
        directory.mkdir(parents=True, exist_ok=True)
        payload = dict(self.result, finished_at=daily.stamp(), requests=self.requests, warnings=self.warnings)
        base = directory / self.result["run_id"]
        for suffix, content in (
            (".json", json.dumps(payload, ensure_ascii=False, indent=2) + "\n"),
            (".md", "# 日线增量更新报告\n\n" +
             "\n".join(f"- {key}: `{value}`" for key, value in self.result.items()) +
             "\n\n## 异常定位\n\n" + ("\n\n".join(
                 "```json\n" + json.dumps(item, ensure_ascii=False, indent=2).replace("```", "` ` `") + "\n```"
                 for item in self.warnings) or "无本次异常。") +
             "\n\n同名 JSON 保存接口、请求参数、返回数量和完整状态。无更新时报告仍会生成，但数据库不写入。\n"),
        ):
            destination = base.with_suffix(suffix)
            temporary = destination.with_suffix(suffix + ".tmp")
            temporary.write_text(content, encoding="utf-8")
            temporary.replace(destination)
        LOG.info("Report: %s", base.with_suffix(".md"))


def read_state(db):
    for table, columns in (
        ("daily", daily.DAILY_FIELDS), ("stock_basic", daily.STOCK_FIELDS),
        ("trade_cal", daily.CALENDAR_FIELDS), ("date_status", ("trade_date", "status")),
    ):
        trading.require_columns(db, table, columns)
    counts = dict(db.execute("SELECT trade_date,count(*) FROM daily WHERE ts_code<>? GROUP BY trade_date", (daily.BENCHMARK_CODE,)))
    if not counts:
        raise ValueError("Database has no daily history; initialize it with src/get_data/get_daily.py first")
    for day in counts:
        daily.parse_date(day)
    calendars = {exchange: {} for exchange in ("SSE", "SZSE")}
    for row in db.execute("SELECT exchange,cal_date,is_open,pretrade_date FROM trade_cal"):
        if row["exchange"] in calendars:
            calendars[row["exchange"]][row["cal_date"]] = trading.CalendarDay(row["is_open"], row["pretrade_date"])
    index_dates = {row[0] for row in db.execute("SELECT trade_date FROM daily WHERE ts_code=?", (daily.BENCHMARK_CODE,))}
    return SimpleNamespace(first=min(counts), last=max(counts), counts=counts, index_dates=index_dates,
                           failed={row[0] for row in db.execute("SELECT trade_date FROM date_status WHERE status='failed'")},
                           stocks={row["ts_code"]: dict(row) for row in db.execute("SELECT * FROM stock_basic")},
                           calendars=calendars)


def fetch_calendar(client, audit, calendars, start, end):
    """Only fully validated exchange/year batches replace the in-memory calendar."""
    for year in range(int(start[:4]), int(end[:4]) + 1):
        lower, upper = max(start, f"{year}0101"), min(end, f"{year}1231")
        for exchange in ("SSE", "SZSE"):
            params = dict(exchange=exchange, start_date=lower, end_date=upper)
            response = audit.query(client, "trade_cal", params, daily.CALENDAR_FIELDS)
            if response is None:
                continue
            rows, _, issues = daily.validate_calendar(*response, lower, upper, exchange)
            try:
                if issues:
                    raise ValueError("; ".join(issues))
                for _, day, _, previous in rows:
                    if previous and (daily.parse_date(previous) >= daily.parse_date(day)):
                        raise ValueError(f"Invalid pretrade_date on {day}")
                calendars[exchange].update({day: trading.CalendarDay(opened, previous or None)
                                           for _, day, opened, previous in rows})
            except (TypeError, ValueError) as exc:
                audit.warn("INVALID_CALENDAR", exc, api="trade_cal", params=params)


def calendar_plan(client, audit, state, today):
    calendars = {exchange: dict(rows) for exchange, rows in state.calendars.items()}
    # Refresh the recent portion to see special closures; fill any older missing spans.
    recent = max(state.first, trading.shifted(min(state.last, today), -31))
    fetch_calendar(client, audit, calendars, recent, today)
    for exchange in ("SSE", "SZSE"):
        for start, end in list(trading.missing_spans(calendars[exchange], state.first, trading.shifted(recent, -1))):
            fetch_calendar(client, audit, calendars, start, end)
    missing = [(exchange, span) for exchange in calendars
               for span in trading.missing_spans(calendars[exchange], state.first, today)]
    if missing:
        raise ValueError(f"Cannot establish trading-date coverage: {missing[:10]}")
    opened = sorted({day for records in calendars.values() for day, info in records.items()
                     if state.first <= day <= today and info.is_open == 1})
    return calendars, opened


def probe_latest(client, audit, opened, cache, limit, *, benchmark=False):
    api = "index_daily" if benchmark else "daily"
    requested_fields = daily.INDEX_FIELDS if benchmark else daily.DAILY_FIELDS
    for day in list(reversed(opened))[:limit]:
        params = dict(trade_date=day)
        if benchmark:
            params["ts_code"] = daily.BENCHMARK_CODE
        response = audit.query(client, api, params, requested_fields)
        cache[day] = response
        if response is None:
            continue
        fields, items = response
        if not set(requested_fields).issubset(fields) or len(fields) != len(set(fields)):
            audit.warn("INVALID_PROBE", "Missing/duplicate fields; latest date remains unverified", trade_date=day, api=api)
            continue
        if not items:
            continue  # Calendar open does not imply publication has happened.
        result = daily.validate_index(fields, items, [day]) if benchmark else daily.validate_daily(fields, items, day)
        if result.rejected or not result.rows or (benchmark and result.issues):
            audit.warn("INVALID_PROBE", "Response contains invalid rows/keys", trade_date=day, api=api)
            continue
        return day
    raise ValueError(f"No usable nonempty {api} response in the last {limit} open dates; cannot claim up-to-date")


def fetch_stocks(client, audit):
    stocks = {}
    for exchange in ("SSE", "SZSE", "BSE"):
        for status in ("L", "D", "P"):
            params = dict(exchange=exchange, list_status=status)
            response = audit.query(client, "stock_basic", params, daily.STOCK_FIELDS)
            if response is None:
                raise ValueError("Stock metadata refresh incomplete; no changes committed")
            fields, items = response
            if (not set(daily.STOCK_FIELDS).issubset(fields) or len(fields) != len(set(fields))
                    or len(items) >= daily.ROW_LIMIT or (status == "L" and not items)):
                raise ValueError(f"Incomplete stock_basic response: {params}")
            for item in items:
                if len(item) != len(fields):
                    raise ValueError(f"Malformed stock_basic row: {params}")
                record = dict(zip(fields, item))
                code = record.get("ts_code")
                if (not code or code in stocks or record.get("exchange") != exchange
                        or record.get("list_status") != status):
                    raise ValueError(f"Invalid/duplicate stock_basic identity: {code}")
                daily.parse_date(record["list_date"])
                if record.get("delist_date"):
                    daily.parse_date(record["delist_date"])
                    if record["delist_date"] <= record["list_date"]:
                        raise ValueError(f"Invalid listing interval: {code}")
                stocks[code] = record
    return stocks


def historical_metadata_changed(old, new, last):
    keys = ("exchange", "list_date", "delist_date")
    for code, row in new.items():
        previous = old.get(code)
        if previous is None:
            if row["list_date"] <= last:
                return True
        elif any((previous.get(key) or None) != (row.get(key) or None) for key in keys):
            # A new delisting strictly after the old cutoff affects only the tail.
            if (previous["exchange"] == row["exchange"] and previous["list_date"] == row["list_date"]
                    and not previous.get("delist_date") and (row.get("delist_date") or "") > last):
                continue
            return True
    return False


def stage_days(client, audit, db, state, stocks, pending, cache, staging, allow_low_count):
    accepted, failed = [], []
    counts = dict(state.counts)
    structural = {"MISSING_COLUMNS", "DUPLICATE_COLUMNS", "MALFORMED_COLUMNS", "EMPTY_DAILY", "POSSIBLE_TRUNCATION"}
    for day in pending:
        response = cache[day] if day in cache else audit.query(client, "daily", {"trade_date": day}, daily.DAILY_FIELDS)
        if response is None:
            failed.append(day)
            continue
        previous_dates = [date for date in counts if date < day]
        expected = sum(row["list_date"] <= day and (not row.get("delist_date") or day < row["delist_date"])
                       and not (row["exchange"] == "BSE" and day < daily.BSE_OPEN_DATE) for row in stocks.values())
        result = daily.validate_daily(*response, day, expected_count=expected,
                                      previous_count=counts[max(previous_dates)] if previous_dates else None)
        existing = {row[0] for row in db.execute("SELECT ts_code FROM daily WHERE trade_date=? AND ts_code<>?", (day, daily.BENCHMARK_CODE))}
        omitted = existing - {row[0] for row in result.rows}
        if omitted:
            result.issues.append(dict(kind="EXISTING_CODES_OMITTED", message=",".join(sorted(omitted))))
        for issue in result.issues:
            audit.warn(issue["kind"], issue["message"], trade_date=day,
                       ts_code=issue.get("ts_code"), field=issue.get("field"))
        kinds = {issue["kind"] for issue in result.issues}
        if (result.rejected or omitted or kinds & structural or
                (not allow_low_count and kinds & {"LOW_ROW_COUNT", "ROW_COUNT_DROP"})):
            audit.warn("DAY_SKIPPED", "Incomplete/suspect response; this date remains pending", trade_date=day)
            failed.append(day)
            continue
        (staging / f"{day}.json").write_text(json.dumps(dict(rows=result.rows, issues=result.issues,
                                                             raw_count=result.raw_count)), encoding="utf-8")
        counts[day] = len(result.rows)
        accepted.append(day)
    return accepted, failed


def rules_for_build(db, args, staging):
    rules = trading.resolve_rules(db, args.rules, args.report_dir, args.db)
    path = staging / "eligibility_rules.json"
    path.write_text(json.dumps(dict(rules, disable_builtin=True)), encoding="utf-8")
    return path


def commit_update(read_db, version, state, args, audit, calendars, stocks, accepted, failed, staging, rules, index_rows,
                  status_batches=(), status_start=None, schema_pending=False):
    db = sqlite3.connect(args.db.resolve().as_uri() + "?mode=rw", uri=True, timeout=60, isolation_level=None)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    manifest_tmp = None
    manifest_path = None
    try:
        db.execute("BEGIN IMMEDIATE")
        if read_db.execute("PRAGMA data_version").fetchone()[0] != version:
            raise RuntimeError("Database changed during download; rerun to replan (no changes committed)")
        trading.create_tables(db)
        run_id = audit.result["run_id"]
        changed_dates = accepted + [row[1] for row in index_rows] or [state.first, state.last]
        db.execute("INSERT INTO runs VALUES(?,?,?,?,?,?,?)", (run_id, daily.stamp(), None, min(changed_dates), max(changed_dates),
                                                            "running", json.dumps({"updater": True})))
        for record in stocks.values():
            db.execute("INSERT INTO stock_basic VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(ts_code) DO UPDATE SET "
                       "name=excluded.name,exchange=excluded.exchange,market=excluded.market,list_status=excluded.list_status,"
                       "list_date=excluded.list_date,delist_date=excluded.delist_date,updated_at=excluded.updated_at",
                       tuple(record.get(key) or None for key in daily.STOCK_FIELDS) + (daily.stamp(),))
        # Missing historical identities are retained, never deleted by a current list refresh.
        changed_calendar = False
        for exchange, records in calendars.items():
            for day, info in records.items():
                previous = state.calendars[exchange].get(day)
                if info != previous:
                    changed_calendar |= day <= state.last
                    db.execute("INSERT INTO trade_cal VALUES(?,?,?,?) ON CONFLICT(exchange,cal_date) DO UPDATE SET "
                               "is_open=excluded.is_open,pretrade_date=excluded.pretrade_date",
                               (exchange, day, info.is_open, info.pretrade_date))
        daily.upsert_daily_rows(db, index_rows)
        for batch in status_batches:
            stock_tags.apply_batch(db, batch, daily.stamp())
        for day in accepted:
            batch = json.loads((staging / f"{day}.json").read_text(encoding="utf-8"))
            daily.upsert_daily_rows(db, batch["rows"])
            db.execute("INSERT INTO date_status VALUES(?,?,?,?,?,?) ON CONFLICT(trade_date) DO UPDATE SET "
                       "status=excluded.status,returned_rows=excluded.returned_rows,saved_rows=excluded.saved_rows,"
                       "run_id=excluded.run_id,updated_at=excluded.updated_at",
                       (day, "warning" if batch["issues"] else "success", batch["raw_count"], len(batch["rows"]), run_id, daily.stamp()))
        for day in failed:
            db.execute("INSERT INTO date_status VALUES(?,?,?,?,?,?) ON CONFLICT(trade_date) DO UPDATE SET "
                       "status='failed',run_id=excluded.run_id,updated_at=excluded.updated_at",
                       (day, "failed", 0, 0, run_id, daily.stamp()))
        full = bool(schema_pending or args.rules or changed_calendar or historical_metadata_changed(state.stocks, stocks, state.last))
        tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        full |= not {"market_calendar", "tradable_stock"}.issubset(tables)
        first_affected = min(min(accepted, default=state.last), state.last, status_start or state.last)
        predecessors = [day for rows in calendars.values() for day, info in rows.items() if info.is_open == 1 and day < first_affected]
        start = state.first if full else max(state.first, max(predecessors, default=first_affected))
        end = max(state.last, max(accepted, default=state.last))
        # Adding only a benchmark does not change stock eligibility. If calendar
        # corrections affect history, however, rebuild it with inherited rules.
        rebuild = bool(accepted or full or status_batches)
        if rebuild:
            manifest, unknown = trading.build(db, SimpleNamespace(db=args.db, start_date=start, end_date=end,
                                                                  rules=rules, calendar_padding=31, fetch_calendar=False))
            if unknown:
                audit.warn("DERIVED_UNKNOWN", "Unknown eligibility/calendar/tags retained; inspect the derived manifest",
                           start_date=start, end_date=end)
            args.report_dir.mkdir(parents=True, exist_ok=True)
            manifest_path = args.report_dir / f"trading_tables_{manifest['build_id']}.json"
            manifest_tmp = manifest_path.with_suffix(".json.tmp")
            manifest_tmp.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        for request in audit.requests:
            db.execute("INSERT INTO request_log(run_id,api,params_json,requested_at,status,returned_rows,error) VALUES(?,?,?,?,?,?,?)",
                       (run_id, request["api"], json.dumps(request["params"]), request["requested_at"], request["status"], request["returned_rows"], request["error"]))
        for item in audit.warnings:
            db.execute("INSERT INTO warnings(run_id,created_at,api,trade_date,ts_code,field,kind,message,params_json) VALUES(?,?,?,?,?,?,?,?,?)",
                       (run_id, daily.stamp(), item.get("api", "update"), item.get("trade_date"), item.get("ts_code"),
                        item.get("field"), item["kind"], item["message"], json.dumps(item.get("params", {}))))
        db.execute("UPDATE runs SET ended_at=?,status=? WHERE run_id=?", (daily.stamp(), "completed_with_warnings" if audit.warnings else "completed", run_id))
        # Publish rules before committing rows that refer to their build_id. A
        # crash before commit may leave an unused report, never a missing report
        # for a committed build. Only database-referenced reports are inherited.
        if manifest_tmp:
            manifest_tmp.replace(manifest_path)
        db.commit()
        audit.result.update(database_changed=True, status="updated", local_latest_after=end,
                            updated_dates=accepted, failed_dates=failed,
                            index_updated_dates=sorted(row[1] for row in index_rows),
                            index_latest_after=max(state.index_dates | {row[1] for row in index_rows}, default=None),
                            derived_range=[start, end] if rebuild else None,
                            derived_manifest=str(manifest_path) if manifest_path else None)
        audit.result["status_batches_saved"] = len(status_batches)
    except BaseException:
        db.rollback()
        if manifest_tmp and not audit.result["database_changed"]:
            manifest_tmp.unlink(missing_ok=True)
        raise
    finally:
        db.close()


def update(args, client, audit, now=None):
    now = now or datetime.now(daily.TZ)
    today = now.astimezone(daily.TZ).strftime("%Y%m%d")
    db = sqlite3.connect(args.db.resolve().as_uri() + "?mode=ro", uri=True, timeout=60)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA query_only=ON")
    try:
        version = db.execute("PRAGMA data_version").fetchone()[0]
        state = read_state(db)
        audit.result.update(database=str(args.db.resolve()), local_latest_before=state.last, today=today,
                            index_local_latest_before=max(state.index_dates, default=None))
        if state.last > today:
            raise ValueError("Local cutoff is later than Shanghai today; check system time/database")
        calendars, opened = calendar_plan(client, audit, state, today)
        cache = {}
        def observe(days, cache, benchmark=False):
            try:
                return probe_latest(client, audit, days, cache, args.probe_days, benchmark=benchmark)
            except ValueError as exc:
                audit.warn("LATEST_UNVERIFIED", exc, api="index_daily" if benchmark else "daily")
                return None
        latest = observe(opened, cache)
        audit.result["remote_latest_observed"] = latest
        if latest is not None and latest < state.last:
            audit.warn("REMOTE_BEHIND_LOCAL", "Latest observed response predates the local cutoff; existing data retained",
                       local_latest=state.last, remote_latest_observed=latest)
        ready = latest
        if latest == today and now.astimezone(daily.TZ).hour < args.settle_hour:
            audit.warn("PUBLICATION_IN_PROGRESS", "Today's daily response is not final before the configured settle hour", trade_date=today)
            ready = observe([day for day in opened if day < today], cache)
        audit.result["remote_latest_usable"] = ready
        pending = [day for day in opened if ready is not None and day <= ready and (day not in state.counts or day in state.failed)]
        audit.result["pending_dates"] = pending
        LOG.info("Local cutoff=%s; remote observed=%s usable=%s; pending=%d", state.last, latest, ready, len(pending))
        index_days = sorted(day for day, info in calendars["SSE"].items() if info.is_open == 1 and state.first <= day <= today)
        index_cache = {}
        index_latest = observe(index_days, index_cache, True)
        index_ready = index_latest
        if index_latest == today and now.astimezone(daily.TZ).hour < getattr(args, "index_settle_hour", 18):
            audit.warn("INDEX_PUBLICATION_IN_PROGRESS", "Today's index is deferred until its settle hour", api="index_daily", trade_date=today)
            index_ready = observe([day for day in index_days if day < today], index_cache, True)
        index_pending = [day for day in index_days if index_ready is not None and day <= index_ready and day not in state.index_dates]
        deferred = [day for day in index_days if ready is not None and day <= ready and day not in state.index_dates
                    and (index_ready is None or day > index_ready)]
        if deferred:
            audit.warn("INDEX_NOT_YET_AVAILABLE", "Stock dates still awaiting index data: " + ",".join(deferred), api="index_daily")
        audit.result.update(index_remote_latest_observed=index_latest, index_remote_latest_usable=index_ready,
                            index_pending_dates=index_pending, index_deferred_dates=deferred)
        LOG.info("Index cutoff=%s; remote observed=%s usable=%s; pending=%d", max(state.index_dates, default=None), index_latest, index_ready, len(index_pending))
        schema_pending = not stock_tags.ready(db)
        status_end = max(state.last, max(pending, default=state.last))
        work = stock_tags.plan(db, state.stocks, opened, state.first, status_end, getattr(args, "refresh_status", False))
        audit.result.update(schema_pending=schema_pending, status_requests_pending=len(work))
        if not pending and not index_pending and not work and not schema_pending and not args.rules:
            audit.result["status"] = "no_change" if not audit.warnings else "no_change_with_warnings"
            LOG.info("Prices, schema and status sources are current; database left unchanged")
            return 2 if audit.warnings else 0
        stocks = fetch_stocks(client, audit) if pending or schema_pending or getattr(args, "refresh_status", False) else {}
        merged_stocks = dict(state.stocks, **stocks)
        with tempfile.TemporaryDirectory(prefix="tushare_update_") as temporary:
            staging = Path(temporary)
            rules = rules_for_build(db, args, staging)
            accepted, failed = stage_days(client, audit, db, state, merged_stocks, pending, cache, staging, args.allow_low_count)
            index_rows = []
            query = lambda api, params, fields: audit.query(client, api, params, fields)
            for params, result in daily.index_results(query, index_days, index_pending):
                if result is None:
                    continue
                index_rows.extend(result.rows)
                for problem in result.issues:
                    audit.warn(**problem, api="index_daily", params=params)
            received = {row[1] for row in index_rows}
            audit.result["index_failed_dates"] = sorted(set(index_pending) - received)
            audit.result.update(updated_dates=[], failed_dates=failed)
            status_end = max(state.last, max(accepted, default=state.last))
            work = stock_tags.plan(db, merged_stocks, opened, state.first, status_end, getattr(args, "refresh_status", False))
            LOG.info("Status enrichment: %d requests", len(work))
            status_batches = list(stock_tags.fetch_batches(query, audit.warn, work, db))
            affected = [stock_tags.affected_from(db, batch) for batch in status_batches]
            status_start = min((day for day in affected if day), default=None)
            if not accepted and not index_rows and not status_batches and not schema_pending and not args.rules:
                audit.result["status"] = "no_usable_update"
                return 2
            # Neighbor dates support correct end-of-range labels and gaps. Failure is nonfatal.
            fetch_calendar(client, audit, calendars, trading.shifted(today, 1), trading.shifted(today, 31))
            commit_update(db, version, state, args, audit, calendars, stocks, accepted, failed, staging, rules, index_rows,
                          status_batches, status_start, schema_pending)
        return 2 if audit.warnings else 0
    finally:
        db.close()


def parser():
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--db", type=Path, default=ROOT / "data/daily_data/daily_data.db")
    result.add_argument("--report-dir", type=Path, default=ROOT / "data/daily_data/reports")
    result.add_argument("--token-file", type=Path, default=ROOT / ".tushare_token")
    result.add_argument("--limit-rpm", type=float, default=200, help="Raw quota; requests use 75%% of this value")
    result.add_argument("--timeout", type=float, default=30)
    result.add_argument("--transport", choices=("auto", "curl", "urllib"), default="auto")
    result.add_argument("--probe-days", type=int, default=20, help="Maximum recent open dates to probe for nonempty daily data")
    result.add_argument("--settle-hour", type=int, default=16, choices=range(16, 24), help="Shanghai hour after which today's daily data may be committed")
    result.add_argument("--index-settle-hour", type=int, default=18, choices=range(18, 24), help="Shanghai hour after which today's SSE Composite data may be committed")
    result.add_argument("--rules", type=Path, help="Explicit eligibility rules; forces full derived-table rebuild")
    result.add_argument("--refresh-status", action="store_true", help="Refetch historical names and suspension dates to repair upstream revisions")
    result.add_argument("--allow-low-count", action="store_true", help="Accept low-count heuristics only after investigating suspensions; never bypass structural/truncation checks")
    return result


def main(argv=None):
    arguments = parser()
    args = arguments.parse_args(argv)
    if not args.db.is_file():
        arguments.error("Existing database required; refusing to create an empty database")
    if not math.isfinite(args.timeout) or args.timeout <= 0 or not 0 < args.limit_rpm <= 200 or args.probe_days < 1:
        arguments.error("timeout > 0, 0 < limit-rpm <= 200, probe-days >= 1 required")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    token = os.environ.get("TUSHARE_TOKEN", "").strip()
    if not token and args.token_file.is_file():
        token = args.token_file.read_text(encoding="utf-8").strip()
    audit = Audit(token)
    try:
        if not token:
            raise ValueError("Set TUSHARE_TOKEN or provide --token-file")
        client = daily.TushareClient(token, daily.RateLimiter(global_rpm=args.limit_rpm), args.timeout, args.transport)
        code = update(args, client, audit)
    except KeyboardInterrupt:
        audit.warn("INTERRUPTED", "Interrupted; check database_changed to see whether commit already completed")
        audit.result["status"] = "interrupted"
        code = 130
    except Exception as exc:
        audit.warn("FATAL_ERROR", f"{type(exc).__name__}: {exc}")
        audit.result["status"] = "failed_after_commit" if audit.result["database_changed"] else "failed_no_commit"
        code = 1
    try:
        audit.write(args.report_dir)
    except Exception as exc:
        message = str(exc).replace(token, "[REDACTED]") if token else str(exc)
        LOG.error("Report failed (database_changed=%s): %s", audit.result["database_changed"], message)
        return 1
    return code


if __name__ == "__main__":
    raise SystemExit(main())
