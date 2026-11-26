"""Updater behavior against temporary databases and an entirely simulated API.

No test reads the production database, token file, or network.
"""
from datetime import datetime, timedelta
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch


from get_data import update as updater
daily = updater.daily
trading = updater.trading


CODES = (("600000.SH", "SSE"), ("000001.SZ", "SZSE"), ("920001.BJ", "BSE"))


def metadata():
    return [dict(zip(daily.STOCK_FIELDS, (code, "Synthetic " + code, exchange,
                "测试", "L", "20211115" if exchange == "BSE" else "20000101", None)))
            for code, exchange in CODES]


def previous_weekday(day):
    parsed = daily.parse_date(day) - timedelta(days=1)
    while parsed.weekday() >= 5:
        parsed -= timedelta(days=1)
    return parsed.strftime("%Y%m%d")


def calendar_rows(exchange, start, end):
    return [[exchange, day, int(daily.parse_date(day).weekday() < 5), previous_weekday(day)]
            for day in daily.dates_between(start, end)]


def bars(day, codes=None):
    return (list(daily.DAILY_FIELDS), [
        [code, day, 10.0, 11.0, 9.0, 10.5, 10.0, 0.5, 5.0,
         100.25, 105.2625, 3.25, 3.4125]
        for code in (codes if codes is not None else [code for code, _ in CODES])
    ])


def index_bar(day):
    return list(daily.INDEX_FIELDS), [[daily.BENCHMARK_CODE, day, 3000.0, 3100.0,
                                     2900.0, 3050.0, 3000.0, 50.0, 1.6667, 1000.0, 2000.0]]


class FakeClient:
    def __init__(self, responses=None, stocks=None, on_query=None, index_responses=None):
        self.responses = responses or {}
        self.stocks = stocks if stocks is not None else metadata()
        self.calls = []
        self.on_query = on_query
        self.index_responses = index_responses
        if index_responses is None:
            # A separate index feed, available for ordinary valid three-stock fixtures.
            self.index_responses = {day: index_bar(day) for day, payload in self.responses.items()
                                    if isinstance(payload, tuple) and payload[0] == list(daily.DAILY_FIELDS)
                                    and len(payload[1]) == len(CODES) and all(row[1] == day for row in payload[1])}

    def query(self, api, params, fields):
        self.calls.append((api, dict(params)))
        if self.on_query:
            self.on_query(api, params)
        if api == "trade_cal":
            return list(daily.CALENDAR_FIELDS), calendar_rows(
                params["exchange"], params["start_date"], params["end_date"])
        if api == "stock_basic":
            return list(daily.STOCK_FIELDS), [
                [record[field] for field in daily.STOCK_FIELDS] for record in self.stocks
                if record["exchange"] == params["exchange"] and record["list_status"] == params["list_status"]
            ]
        if api == "namechange":
            record = next(record for record in self.stocks if record["ts_code"] == params["ts_code"])
            return list(updater.stock_tags.NAME_FIELDS), [[record["ts_code"], record["name"], record["list_date"], None, None, "initial"]]
        if api == "suspend_d":
            return list(updater.stock_tags.SUSPEND_FIELDS), []
        if api == "daily":
            result = self.responses.get(params["trade_date"], (list(daily.DAILY_FIELDS), []))
            if isinstance(result, Exception):
                raise result
            return result
        if api == "index_daily":
            selected = [params["trade_date"]] if "trade_date" in params else list(daily.dates_between(params["start_date"], params["end_date"]))
            items = []
            for day in selected:
                payload = self.index_responses.get(day, (list(daily.INDEX_FIELDS), []))
                if isinstance(payload, Exception):
                    raise payload
                items.extend(payload[1])
            return list(daily.INDEX_FIELDS), items
        raise AssertionError("Unexpected API: " + api)


class UpdateTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="test_update_daily_")
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.path = self.root / "fixture.db"
        self.args = SimpleNamespace(db=self.path, report_dir=self.root / "reports", rules=None,
                                    probe_days=20, settle_hour=16, allow_low_count=False)
        store = daily.Store(self.path)
        try:
            with store.db:
                store.db.executemany("INSERT INTO stock_basic VALUES(?,?,?,?,?,?,?,?)", [
                    tuple(record[field] for field in daily.STOCK_FIELDS) + ("fixture",)
                    for record in metadata()
                ])
                store.db.executemany("INSERT INTO daily(ts_code,trade_date,open,high,low,close,pre_close,change,pct_chg,vol,amount,ah_vol,ah_amount) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)", bars("20261120")[1])
                daily.upsert_daily_rows(store.db, daily.validate_index(*index_bar("20261120"), ["20261120"]).rows)
                store.db.execute("INSERT INTO date_status VALUES(?,?,?,?,?,?)",
                                 ("20261120", "success", 3, 3, "fixture", "fixture"))
                for exchange in ("SSE", "SZSE"):
                    store.db.executemany("INSERT INTO trade_cal VALUES(?,?,?,?)",
                                         calendar_rows(exchange, "20261120", "20261122"))
                for record in metadata():
                    updater.stock_tags.apply_batch(store.db, updater.stock_tags.Batch("namechange", record["ts_code"], "20261120",
                        [(record["ts_code"], record["name"], record["list_date"], None, None, "initial")]), "fixture")
                updater.stock_tags.apply_batch(store.db, updater.stock_tags.Batch("suspend_d", "20261120", "20261120", []), "fixture")
        finally:
            store.close()
        self.install_derived()

    def now(self, day="20261123", hour=18):
        return datetime.strptime(day, "%Y%m%d").replace(hour=hour, tzinfo=daily.TZ)

    def run_update(self, responses=None, day="20261123", hour=18, client=None):
        responses = {"20261120": bars("20261120"), **(responses or {})}
        client = client or FakeClient(responses)
        audit = updater.Audit()
        code = updater.update(self.args, client, audit, self.now(day, hour))
        return code, audit, client

    def read(self, sql, parameters=()):
        db = sqlite3.connect(self.path.as_uri() + "?mode=ro", uri=True)
        try:
            return db.execute(sql, parameters).fetchall()
        finally:
            db.close()

    def fingerprint(self):
        return hashlib.sha256(self.path.read_bytes()).hexdigest(), self.path.stat().st_mtime_ns

    def dump(self):
        db = sqlite3.connect(self.path.as_uri() + "?mode=ro", uri=True)
        try:
            return tuple(db.iterdump())
        finally:
            db.close()

    def install_derived(self, rules=None):
        db = sqlite3.connect(self.path)
        db.row_factory = sqlite3.Row
        try:
            db.execute("BEGIN IMMEDIATE")
            first, last = db.execute("SELECT min(trade_date),max(trade_date) FROM daily").fetchone()
            manifest, _ = trading.build(db, SimpleNamespace(
                db=self.path, start_date=first, end_date=last, rules=rules,
                calendar_padding=31, fetch_calendar=False))
            db.commit()
        finally:
            db.close()
        self.args.report_dir.mkdir(exist_ok=True)
        manifest_path = self.args.report_dir / f"trading_tables_{manifest['build_id']}.json"
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        return manifest, manifest_path

    def add_prior_week(self):
        db = sqlite3.connect(self.path)
        try:
            with db:
                for day in daily.dates_between("20261116", "20261119"):
                    db.executemany("INSERT INTO daily(ts_code,trade_date,open,high,low,close,pre_close,change,pct_chg,vol,amount,ah_vol,ah_amount) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)", bars(day)[1])
                    daily.upsert_daily_rows(db, daily.validate_index(*index_bar(day), [day]).rows)
                    updater.stock_tags.apply_batch(db, updater.stock_tags.Batch("suspend_d", day, day, []), "fixture")
                    db.execute("INSERT INTO date_status VALUES(?,?,?,?,?,?)",
                               (day, "success", 3, 3, "fixture", "fixture"))
                for exchange in ("SSE", "SZSE"):
                    db.executemany("INSERT INTO trade_cal VALUES(?,?,?,?)",
                                   calendar_rows(exchange, "20261116", "20261119"))
        finally:
            db.close()

    def test_equal_cutoff_does_not_touch_database_or_refresh_metadata(self):
        before = self.fingerprint()
        code, audit, client = self.run_update(day="20261120")
        self.assertEqual(code, 0)
        self.assertEqual(audit.result["status"], "no_change")
        self.assertFalse(audit.result["database_changed"])
        self.assertEqual(self.fingerprint(), before)
        self.assertEqual(self.read("SELECT count(*) FROM runs"), [(0,)])
        self.assertFalse(any(api == "stock_basic" for api, _ in client.calls))

    def test_weekend_uses_actual_last_published_trade_date(self):
        before = self.fingerprint()
        code, audit, client = self.run_update(day="20261122")
        self.assertEqual(code, 0)
        self.assertEqual(audit.result["remote_latest_observed"], "20261120")
        self.assertEqual([params["trade_date"] for api, params in client.calls if api == "daily"], ["20261120"])
        self.assertEqual(self.fingerprint(), before)

    def test_open_day_with_empty_response_is_not_assumed_published(self):
        before = self.fingerprint()
        code, audit, _ = self.run_update()
        self.assertEqual(code, 0)
        self.assertEqual(audit.result["remote_latest_observed"], "20261120")
        self.assertEqual(self.fingerprint(), before)

    def test_failed_latest_probe_cannot_claim_clean_up_to_date(self):
        before = self.fingerprint()
        code, audit, _ = self.run_update({"20261123": RuntimeError("simulated API timeout")})
        self.assertEqual(code, 2)
        self.assertEqual(audit.result["status"], "no_change_with_warnings")
        self.assertIn("REQUEST_FAILED", [warning["kind"] for warning in audit.warnings])
        self.assertEqual(self.fingerprint(), before)

    def test_today_is_observed_but_deferred_during_publication_window(self):
        before = self.fingerprint()
        code, audit, _ = self.run_update({"20261123": bars("20261123")}, hour=15)
        self.assertEqual(code, 2)
        self.assertEqual(audit.result["remote_latest_observed"], "20261123")
        self.assertEqual(audit.result["remote_latest_usable"], "20261120")
        self.assertIn("PUBLICATION_IN_PROGRESS", [warning["kind"] for warning in audit.warnings])
        self.assertEqual(self.fingerprint(), before)

    def test_new_day_preserves_all_fields_and_updates_derived_neighbors(self):
        self.install_derived()
        code, audit, _ = self.run_update({"20261123": bars("20261123")})
        self.assertEqual(code, 0)
        self.assertTrue(audit.result["database_changed"])
        self.assertEqual(self.read("SELECT ts_code,trade_date,open,high,low,close,pre_close,change,pct_chg,vol,amount,ah_vol,ah_amount FROM daily WHERE trade_date=? AND ts_code<>'000001.SH' ORDER BY ts_code", ("20261123",)),
                         sorted(map(tuple, bars("20261123")[1])))
        self.assertEqual(self.read("SELECT count(*) FROM tradable_stock WHERE trade_date='20261123' AND is_tradable=1"), [(3,)])
        self.assertEqual(self.read("SELECT next_trade_date,days_until_next_trade,boundary_tag FROM market_calendar WHERE exchange='SSE' AND cal_date='20261120'"),
                         [("20261123", 3, 2)])
        self.assertEqual(self.read("SELECT weekday,boundary_tag FROM market_calendar WHERE exchange='SSE' AND cal_date='20261123'"), [(1, 1)])
        self.assertTrue(Path(audit.result["derived_manifest"]).is_file())
        self.assertEqual(self.read("PRAGMA foreign_key_check"), [])

    def test_middle_failure_is_retried_even_after_later_day_commits(self):
        code, first, _ = self.run_update({"20261123": RuntimeError("temporary failure"),
                                        "20261124": bars("20261124")}, day="20261124")
        self.assertEqual(code, 2)
        self.assertEqual(first.result["updated_dates"], ["20261124"])
        self.assertEqual(self.read("SELECT status FROM date_status WHERE trade_date='20261123'"), [("failed",)])
        code, second, _ = self.run_update({"20261123": bars("20261123"), "20261124": bars("20261124")}, day="20261124")
        self.assertEqual(code, 0)
        self.assertEqual(second.result["updated_dates"], ["20261123"])
        self.assertEqual(self.read("SELECT count(*) FROM daily WHERE ts_code<>'000001.SH'"), [(9,)])
        self.assertEqual(self.read("SELECT status FROM date_status WHERE trade_date='20261123'"), [("success",)])

    def test_bad_dates_and_missing_columns_do_not_advance_cutoff(self):
        bad_responses = [bars("20261124"), (list(daily.DAILY_FIELDS[:-1]), [row[:-1] for row in bars("20261123")[1]])]
        for bad in bad_responses:
            with self.subTest(response=bad):
                before = self.fingerprint()
                code, audit, _ = self.run_update({"20261123": bad})
                self.assertEqual(code, 2)
                self.assertFalse(audit.result["database_changed"])
                self.assertEqual(self.fingerprint(), before)

    def test_truncation_never_gets_accepted_even_with_low_count_override(self):
        self.args.allow_low_count = True
        before = self.fingerprint()
        payload = bars("20261123", [f"{600000 + index:06d}.SH" for index in range(daily.ROW_LIMIT)])
        code, audit, _ = self.run_update({"20261123": payload})
        self.assertEqual(code, 2)
        self.assertFalse(audit.result["database_changed"])
        self.assertIn("POSSIBLE_TRUNCATION", [warning["kind"] for warning in audit.warnings])
        self.assertEqual(self.fingerprint(), before)

    def test_low_count_requires_explicit_override(self):
        before = self.fingerprint()
        payload = bars("20261123", ["600000.SH"])
        code, audit, _ = self.run_update({"20261123": payload})
        self.assertEqual(code, 2)
        self.assertEqual(audit.result["status"], "no_usable_update")
        self.assertEqual(self.fingerprint(), before)
        self.args.allow_low_count = True
        _, audit, _ = self.run_update({"20261123": payload})
        self.assertTrue(audit.result["database_changed"])
        self.assertEqual(self.read("SELECT count(*) FROM daily WHERE trade_date='20261123' AND ts_code<>'000001.SH'"), [(1,)])

    def test_derived_build_failure_rolls_back_entire_update(self):
        before = self.dump()
        with patch.object(trading, "build", side_effect=RuntimeError("synthetic derived failure")):
            with self.assertRaisesRegex(RuntimeError, "derived failure"):
                self.run_update({"20261123": bars("20261123")})
        self.assertEqual(self.dump(), before)
        self.assertEqual(self.read("SELECT count(*) FROM runs"), [(0,)])

    def test_manifest_finalization_failure_rolls_back_entire_update(self):
        before = self.dump()
        with patch.object(Path, "replace", side_effect=PermissionError("synthetic manifest rename failure")):
            with self.assertRaisesRegex(PermissionError, "manifest rename failure"):
                self.run_update({"20261123": bars("20261123")})
        self.assertEqual(self.dump(), before)
        self.assertEqual(self.read("SELECT max(trade_date) FROM daily"), [("20261120",)])
        self.assertEqual(self.read("SELECT count(*) FROM runs"), [(0,)])

    def test_concurrent_external_commit_rejects_stale_download_plan(self):
        changed = False
        def other_writer(api, params):
            nonlocal changed
            if api == "daily" and not changed:
                changed = True
                db = sqlite3.connect(self.path)
                try:
                    with db:
                        db.execute("UPDATE stock_basic SET name='external writer' WHERE ts_code='600000.SH'")
                finally:
                    db.close()
        client = FakeClient({"20261120": bars("20261120"), "20261123": bars("20261123")}, on_query=other_writer)
        with self.assertRaisesRegex(RuntimeError, "changed during download"):
            self.run_update(client=client)
        self.assertEqual(self.read("SELECT max(trade_date) FROM daily"), [("20261120",)])
        self.assertEqual(self.read("SELECT count(*) FROM runs"), [(0,)])
        self.assertEqual(self.read("SELECT name FROM stock_basic WHERE ts_code='600000.SH'"), [("external writer",)])

    def test_rules_are_inherited_from_existing_derived_manifest(self):
        custom = self.root / "custom_rules.json"
        custom.write_text(json.dumps({"disable_builtin": True, "blocked_intervals": [
            {"security_id": "000001.SZ", "start_date": "20280101", "end_date": "20280102",
             "reason": "SYNTHETIC_RULE", "source": "test fixture"}
        ]}), encoding="utf-8")
        previous, _ = self.install_derived(custom)
        _, audit, _ = self.run_update({"20261123": bars("20261123")})
        current = json.loads(Path(audit.result["derived_manifest"]).read_text(encoding="utf-8"))
        self.assertEqual(current["rules"], previous["rules"])

    def test_missing_rules_manifest_does_not_silently_reset_rules(self):
        _, path = self.install_derived()
        path.unlink()
        db = sqlite3.connect(self.path)
        with db:
            db.execute("DELETE FROM dataset_meta WHERE key='eligibility_rules'")
        db.close()
        before = self.fingerprint()
        with self.assertRaisesRegex(ValueError, "recover rules"):
            self.run_update({"20261123": bars("20261123")})
        self.assertEqual(self.fingerprint(), before)

    def test_changing_report_output_directory_preserves_existing_rules(self):
        previous, _ = self.install_derived()
        self.args.report_dir = self.root / "alternate_reports"
        _, audit, _ = self.run_update({"20261123": bars("20261123")})
        manifest_path = Path(audit.result["derived_manifest"])
        self.assertEqual(manifest_path.parent, self.args.report_dir)
        current = json.loads(manifest_path.read_text(encoding="utf-8"))
        self.assertEqual(current["rules"], previous["rules"])

    def test_metadata_refresh_failure_leaves_database_unchanged(self):
        before = self.fingerprint()
        client = FakeClient({"20261120": bars("20261120"), "20261123": bars("20261123")}, stocks=metadata()[:2])
        with self.assertRaisesRegex(ValueError, "Incomplete stock_basic"):
            self.run_update(client=client)
        self.assertEqual(self.fingerprint(), before)

    def test_historical_listing_change_rebuilds_affected_old_eligibility(self):
        self.add_prior_week()
        self.install_derived()
        stocks = metadata()
        stocks[0]["list_date"] = "20261118"
        client = FakeClient({"20261123": bars("20261123")}, stocks=stocks)
        _, audit, _ = self.run_update(client=client)
        self.assertEqual(audit.result["derived_range"], ["20261116", "20261123"])
        self.assertEqual(self.read("SELECT is_tradable,reason FROM tradable_stock WHERE trade_date='20261116' AND ts_code='600000.SH'"),
                         [(0, "OUTSIDE_LISTING_INTERVAL")])
        self.assertEqual(self.read("SELECT count(*) FROM daily WHERE trade_date='20261116' AND ts_code<>'000001.SH'"), [(3,)])

    def test_name_only_change_preserves_older_derived_ranges(self):
        self.add_prior_week()
        old, _ = self.install_derived()
        stocks = metadata()
        stocks[0]["name"] = "A new display name"
        client = FakeClient({"20261123": bars("20261123")}, stocks=stocks)
        _, audit, _ = self.run_update(client=client)
        self.assertEqual(audit.result["derived_range"], ["20261119", "20261123"])
        self.assertEqual(self.read("SELECT build_id FROM market_calendar WHERE exchange='SSE' AND cal_date='20261116'"),
                         [(old["build_id"],)])
        self.assertEqual(self.read("SELECT name FROM stock_basic WHERE ts_code='600000.SH'"), [("A new display name",)])

    def test_credential_is_redacted_in_failed_request_and_written_report(self):
        audit = updater.Audit("TEST_SECRET_NEVER_REAL")
        client = FakeClient({"20261123": RuntimeError("request failed TEST_SECRET_NEVER_REAL")})
        self.assertIsNone(audit.query(client, "daily", {"trade_date": "20261123"}, daily.DAILY_FIELDS))
        audit.write(self.args.report_dir)
        for path in self.args.report_dir.glob(audit.result["run_id"] + ".*"):
            text = path.read_text(encoding="utf-8")
            self.assertNotIn("TEST_SECRET_NEVER_REAL", text)
            self.assertIn("[REDACTED]", text)

    def test_benchmark_is_same_table_row_but_not_a_tradable_stock(self):
        _, audit, _ = self.run_update({"20261123": bars("20261123")})
        record = self.read("SELECT * FROM daily WHERE ts_code=? AND trade_date=?", (daily.BENCHMARK_CODE, "20261123"))
        self.assertEqual(record, [tuple(index_bar("20261123")[1][0]) + (None, None, '[]', '[]')])
        self.assertEqual(self.read("SELECT count(*) FROM tradable_stock WHERE ts_code=?", (daily.BENCHMARK_CODE,)), [(0,)])
        self.assertEqual(self.read("SELECT returned_rows,saved_rows FROM date_status WHERE trade_date='20261123'"), [(3, 3)])
        self.assertEqual(audit.result["index_updated_dates"], ["20261123"])

    def test_old_schema_migrates_even_when_price_cutoff_is_current(self):
        db = sqlite3.connect(self.path)
        with db:
            for table in ("daily", "tradable_stock"):
                for column in ("tags", "tags_unknown"):
                    db.execute(f"ALTER TABLE {table} DROP COLUMN {column}")
            for table in ("stock_name_history", "stock_suspensions", "status_fetch_state", "dataset_meta"):
                db.execute(f"DROP TABLE {table}")
        db.close()
        code, audit, _ = self.run_update(day="20261120")
        self.assertEqual(code, 0)
        self.assertEqual(audit.result["updated_dates"], [])
        self.assertTrue(audit.result["database_changed"])
        self.assertEqual(self.read("SELECT DISTINCT tags,tags_unknown FROM daily"), [('[]', '[]')])
        before = self.fingerprint()
        code, audit, _ = self.run_update(day="20261120")
        self.assertEqual(code, 0)
        self.assertFalse(audit.result["database_changed"])
        self.assertEqual(self.fingerprint(), before)

    def test_status_failure_keeps_prices_then_repairs_on_next_run(self):
        class FailedStatus(FakeClient):
            def query(self, api, params, fields):
                if api == "suspend_d":
                    raise RuntimeError("simulated suspension failure")
                return super().query(api, params, fields)
        client = FailedStatus({"20261123": bars("20261123")})
        code, audit, _ = self.run_update(client=client)
        self.assertEqual(code, 2)
        self.assertTrue(audit.result["database_changed"])
        self.assertEqual(self.read("SELECT DISTINCT tags_unknown FROM daily WHERE trade_date='20261123' AND ts_code<>'000001.SH'"), [('["停牌"]',)])
        code, audit, _ = self.run_update({"20261123": bars("20261123")})
        self.assertEqual(code, 0)
        self.assertEqual(audit.result["updated_dates"], [])
        self.assertEqual(self.read("SELECT DISTINCT tags_unknown FROM daily WHERE trade_date='20261123'"), [('[]',)])

    def test_persisted_rules_survive_report_removal(self):
        previous, path = self.install_derived()
        path.unlink()
        code, audit, _ = self.run_update({"20261123": bars("20261123")})
        self.assertEqual(code, 0)
        current = json.loads(Path(audit.result["derived_manifest"]).read_text())
        self.assertEqual(current["rules"], previous["rules"])

    def test_force_status_refresh_retags_old_history_without_price_download(self):
        class RevisedHistory(FakeClient):
            def query(self, api, params, fields):
                result = super().query(api, params, fields)
                if api == "namechange" and params["ts_code"] == "600000.SH":
                    result[1][0][1] = "*ST历史"
                return result
        self.args.refresh_status = True
        code, audit, _ = self.run_update(day="20261120", client=RevisedHistory({"20261120": bars("20261120")}))
        self.assertEqual(code, 0)
        self.assertEqual(audit.result["updated_dates"], [])
        self.assertEqual(self.read("SELECT tags FROM daily WHERE ts_code='600000.SH'"), [('["*ST"]',)])

    def test_stock_latest_can_be_complete_while_old_benchmark_history_needs_backfill(self):
        self.add_prior_week()
        self.install_derived()
        db = sqlite3.connect(self.path)
        with db:
            db.execute("DELETE FROM daily WHERE ts_code=?", (daily.BENCHMARK_CODE,))
        db.close()
        stocks_before = self.read("SELECT * FROM daily ORDER BY trade_date,ts_code")
        responses = {day: bars(day) for day in daily.dates_between("20261116", "20261120")}
        code, audit, client = self.run_update(day="20261120", client=FakeClient(responses))
        self.assertEqual(code, 0)
        self.assertEqual(audit.result["updated_dates"], [])
        self.assertEqual(len(audit.result["index_updated_dates"]), 5)
        self.assertEqual(self.read("SELECT * FROM daily WHERE ts_code<>? ORDER BY trade_date,ts_code", (daily.BENCHMARK_CODE,)), stocks_before)
        self.assertFalse(any(api == "stock_basic" for api, _ in client.calls))
        before = self.fingerprint()
        code, again, _ = self.run_update(day="20261120", client=FakeClient(responses))
        self.assertEqual(code, 0)
        self.assertFalse(again.result["database_changed"])
        self.assertEqual(self.fingerprint(), before)

    def test_index_publication_lag_does_not_block_stocks_and_can_be_filled_later(self):
        self.install_derived()
        client = FakeClient({"20261120": bars("20261120"), "20261123": bars("20261123")},
                            index_responses={"20261120": index_bar("20261120")})
        code, first, _ = self.run_update(client=client)
        self.assertEqual(code, 2)
        self.assertEqual(first.result["updated_dates"], ["20261123"])
        self.assertEqual(first.result["index_updated_dates"], [])
        self.assertEqual(first.result["index_deferred_dates"], ["20261123"])
        code, second, _ = self.run_update({"20261123": bars("20261123")})
        self.assertEqual(code, 0)
        self.assertEqual(second.result["updated_dates"], [])
        self.assertEqual(second.result["index_updated_dates"], ["20261123"])

    def test_index_at_17_is_deferred_while_stocks_can_commit(self):
        _, first, _ = self.run_update({"20261123": bars("20261123")}, hour=17)
        self.assertEqual(first.result["updated_dates"], ["20261123"])
        self.assertEqual(first.result["index_remote_latest_observed"], "20261123")
        self.assertEqual(first.result["index_remote_latest_usable"], "20261120")
        self.assertEqual(first.result["index_updated_dates"], [])

    def test_index_only_day_does_not_hide_missing_stock_day(self):
        self.install_derived()
        db = sqlite3.connect(self.path)
        with db:
            daily.upsert_daily_rows(db, daily.validate_index(*index_bar("20261123"), ["20261123"]).rows)
        db.close()
        code, audit, _ = self.run_update({"20261123": bars("20261123")})
        self.assertEqual(code, 0)
        self.assertEqual(audit.result["local_latest_before"], "20261120")
        self.assertEqual(audit.result["pending_dates"], ["20261123"])
        self.assertEqual(audit.result["index_updated_dates"], [])

    def test_index_permission_failure_does_not_rollback_good_stock_download(self):
        client = FakeClient({"20261120": bars("20261120"), "20261123": bars("20261123")},
                            index_responses={"20261120": index_bar("20261120"), "20261123": RuntimeError("permission denied")})
        code, audit, _ = self.run_update(client=client)
        self.assertEqual(code, 2)
        self.assertEqual(audit.result["updated_dates"], ["20261123"])
        self.assertEqual(audit.result["index_updated_dates"], [])

    def test_failed_index_batch_can_resume_without_refetching_stocks(self):
        self.install_derived()
        class FailingBatch(FakeClient):
            def query(self, api, params, fields):
                if api == "index_daily" and "start_date" in params:
                    raise RuntimeError("range download failed")
                return super().query(api, params, fields)
        client = FailingBatch({"20261120": bars("20261120"), "20261123": bars("20261123")})
        _, audit, _ = self.run_update(client=client)
        self.assertEqual(audit.result["index_failed_dates"], ["20261123"])
        self.assertEqual(audit.result["updated_dates"], ["20261123"])
        _, retry, _ = self.run_update({"20261123": bars("20261123")})
        self.assertEqual(retry.result["updated_dates"], [])
        self.assertEqual(retry.result["index_updated_dates"], ["20261123"])


if __name__ == "__main__":
    unittest.main()
