"""Historical status, migration and permanent-entry integration; synthetic DBs only."""
import json
from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from get_data import get_daily as daily
from get_data import daily_tables as trading
from get_data import stock_tags as tags
from get_data import add_tag
from test_update_daily import FakeClient, metadata, calendar_rows, bars, index_bar, updater


class StatusTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "fixture.db"
        self.store = daily.Store(self.path)
        self.addCleanup(self.store.close)
        self.db = self.store.db
        self.store.start_run("20261116", "20261124")
        with self.db:
            self.db.executemany("INSERT INTO stock_basic VALUES(?,?,?,?,?,?,?,?)", [
                tuple(r[f] for f in daily.STOCK_FIELDS) + ("fixture",) for r in metadata()])
            for exchange in ("SSE", "SZSE"):
                self.db.executemany("INSERT INTO trade_cal VALUES(?,?,?,?)", calendar_rows(exchange, "20261101", "20261210"))
            for day in ("20261116", "20261117", "20261118", "20261119", "20261120", "20261123", "20261124"):
                daily.upsert_daily_rows(self.db, bars(day)[1])
                tags.apply_batch(self.db, tags.Batch("suspend_d", day, day, []), "fixture")
            for record in metadata():
                tags.apply_batch(self.db, tags.Batch("namechange", record["ts_code"], "20261124", [
                    (record["ts_code"], "普通股份", record["list_date"], None, None, "initial")]), "fixture")

    def source(self, history, code="600000.SH"):
        with self.db:
            tags.apply_batch(self.db, tags.Batch("namechange", code, "20261124",
                [(code, name, start, end, None, "test") for name, start, end in history]), "fixture")

    def build(self):
        with self.db:
            return trading.build(self.db, SimpleNamespace(db=self.path, start_date=None, end_date=None,
                calendar_padding=5, fetch_calendar=False, rules=None))

    def status(self, day, code="600000.SH"):
        row = self.db.execute("SELECT tags,tags_unknown,is_tradable,reason,data_available FROM tradable_stock WHERE trade_date=? AND ts_code=?", (day, code)).fetchone()
        return json.loads(row[0]), json.loads(row[1]), *row[2:]

    def test_risk_transitions_use_historical_names_not_current_snapshot(self):
        self.source([("普通", "20000101", "20261116"), ("ST股份", "20261117", "20261118"),
                     ("*ST股份", "20261119", "20261120"), ("普通", "20261121", None)])
        self.db.execute("UPDATE stock_basic SET name='*ST今天' WHERE ts_code='600000.SH'")
        self.build()
        for day, expected in (("20261116", []), ("20261117", ["ST"]), ("20261119", ["*ST"]), ("20261123", [])):
            self.assertEqual(self.status(day)[:2], (expected, []))
            raw = self.db.execute("SELECT tags FROM daily WHERE ts_code='600000.SH' AND trade_date=?", (day,)).fetchone()[0]
            self.assertEqual(json.loads(raw), expected)

    def test_legacy_sst_and_s_star_st_are_distinguished(self):
        self.assertEqual(tags.risk_tag("SST股份"), "ST")
        self.assertEqual(tags.risk_tag("S*ST股份"), "*ST")
        self.assertEqual(tags.risk_tag("＊ST股份"), "*ST")
        self.assertIsNone(tags.risk_tag("中ST测试"))

    def test_share_reform_prefixes_and_unicode_names(self):
        for name, expected in (
            ("GST星源", "ST"), ("G*ST国农", "*ST"),
            (" g ＊ s t 国农 ", "*ST"), ("ＧＳＴ星源", "ST"),
            ("Ｇ＊ＳＴ国农", "*ST"), ("SST股份", "ST"),
            ("S*ST股份", "*ST"), ("G普通股份", None),
            ("中国GST科技", None), ("GSGST测试", None),
        ):
            with self.subTest(name=name):
                self.assertEqual(tags.risk_tag(name), expected)

    def test_g_prefix_boundaries_conflicts_and_expired_coverage(self):
        self.source([("GST股份", "20000101", "20261118"),
                     ("G*ST股份", "20261119", "20261120"),
                     ("普通股份", "20261123", None)])
        self.build()
        for day, expected in (("20261118", ["ST"]), ("20261119", ["*ST"]),
                              ("20261120", ["*ST"]), ("20261123", [])):
            self.assertEqual(self.status(day)[:2], (expected, []))
        self.source([("GST股份", "20000101", None), ("G*ST股份", "20261120", None)])
        self.build()
        self.assertEqual(self.status("20261120")[:2], ([], ["*ST", "ST"]))
        self.source([("GST股份", "20000101", None)])
        with self.db:
            self.db.execute("UPDATE status_fetch_state SET as_of_date='20261119' WHERE api='namechange'")
        self.build()
        self.assertEqual(self.status("20261120")[:2], ([], ["*ST", "ST"]))

    def test_add_tag_offline_repairs_v2_without_touching_prices_or_sources(self):
        self.source([("GST股份", "20000101", "20261118"),
                     ("G*ST股份", "20261119", "20261120"),
                     ("普通股份", "20261121", None)])
        self.build()
        with self.db:
            self.db.execute("UPDATE daily SET tags='[]'")
            self.db.execute("UPDATE tradable_stock SET tags='[]'")
            tags.set_meta(self.db, "tag_version", "2")
        prices = [tuple(r) for r in self.db.execute('SELECT '+','.join(daily.DAILY_FIELDS)+' FROM daily ORDER BY 1,2')]
        sources = [tuple(r) for r in self.db.execute('SELECT * FROM stock_name_history ORDER BY 1,3')]
        rules = tags.get_meta(self.db, "eligibility_rules")
        args = ["--db", str(self.path), "--report-dir", str(self.path.parent / "reports"),
                "--token-file", str(self.path.parent / "absent-token")]
        with patch.object(daily, "TushareClient", side_effect=AssertionError("network forbidden")):
            for _ in range(2):
                self.assertIn(add_tag.main(args), (0, 2))
                self.assertEqual(self.status("20261118")[:2], (["ST"], []))
                self.assertEqual(self.status("20261120")[:2], (["*ST"], []))
                self.assertEqual(self.status("20261123")[:2], ([], []))
                self.assertEqual([tuple(r) for r in self.db.execute('SELECT '+','.join(daily.DAILY_FIELDS)+' FROM daily ORDER BY 1,2')], prices)
                self.assertEqual([tuple(r) for r in self.db.execute('SELECT * FROM stock_name_history ORDER BY 1,3')], sources)
                self.assertEqual(tags.get_meta(self.db, "eligibility_rules"), rules)
                self.assertTrue(tags.ready(self.db))
        self.assertEqual(self.db.execute('SELECT count(*) FROM request_log').fetchone()[0], 0)

    def test_offline_rebuild_failure_does_not_publish_new_version(self):
        self.build()
        with self.db:
            tags.set_meta(self.db, "tag_version", "2")
        before = [tuple(r) for r in self.db.execute('SELECT * FROM tradable_stock ORDER BY 1,2')]
        with patch.object(trading, "assess", side_effect=RuntimeError("synthetic rebuild failure")):
            code = add_tag.main(["--db", str(self.path), "--report-dir", str(self.path.parent / "reports")])
        self.assertEqual(code, 1)
        self.assertEqual(tags.get_meta(self.db, "tag_version"), "2")
        self.assertEqual([tuple(r) for r in self.db.execute('SELECT * FROM tradable_stock ORDER BY 1,2')], before)

    def test_unchanged_daily_tags_do_not_issue_per_row_updates(self):
        self.build()
        statements = []
        self.db.set_trace_callback(statements.append)
        try:
            self.build()
        finally:
            self.db.set_trace_callback(None)
        self.assertFalse(any(s.startswith('UPDATE daily SET tags=') and 'trade_date=' in s for s in statements))

    def test_empty_or_overlapping_history_is_unknown(self):
        self.source([])
        self.build()
        self.assertEqual(self.status("20261120")[:2], ([], ["*ST", "ST"]))
        self.source([("ST股份", "20000101", None), ("普通", "20261120", None)])
        self.build()
        self.assertEqual(self.status("20261120")[:2], ([], ["*ST", "ST"]))

    def test_missing_bar_is_not_suspension_and_suspension_without_bar_is_preserved(self):
        with self.db:
            self.db.execute("DELETE FROM daily WHERE ts_code='600000.SH' AND trade_date IN ('20261119','20261120')")
            tags.apply_batch(self.db, tags.Batch("suspend_d", "20261120", "20261120",
                [("600000.SH", "20261120", "", "S")]), "fixture")
        self.build()
        self.assertEqual(self.status("20261119"), ([], [], None, "NO_DAILY_DATA", 0))
        self.assertEqual(self.status("20261120"), (["停牌"], [], 0, "FULL_DAY_SUSPENDED", 0))
        self.assertEqual(self.db.execute("SELECT count(*) FROM daily WHERE ts_code='600000.SH' AND trade_date='20261120'").fetchone()[0], 0)

    def test_intraday_halt_keeps_trade_evidence_but_full_day_bar_conflicts(self):
        self.source([("*ST股份", "20000101", None)])
        with self.db:
            for day, timing in (("20261119", "09:30-10:00"), ("20261120", "")):
                tags.apply_batch(self.db, tags.Batch("suspend_d", day, day, [("600000.SH", day, timing, "S")]), "fixture")
        self.build()
        self.assertEqual(self.status("20261119")[:4], (["停牌", "*ST"], [], 1, "TRADED"))
        self.assertEqual(self.status("20261120")[:4], (["停牌", "*ST"], [], None, "SUSPENSION_BAR_CONFLICT"))

    def test_delisting_is_effective_from_date_and_exists_without_price(self):
        with self.db:
            self.db.execute("UPDATE stock_basic SET list_status='D',delist_date='20261120' WHERE ts_code='600000.SH'")
            self.db.execute("DELETE FROM daily WHERE ts_code='600000.SH' AND trade_date>='20261120'")
        self.build()
        self.assertEqual(self.status("20261119")[:2], ([], []))
        self.assertEqual(self.status("20261120"), (["退市"], [], 0, "DELISTED", 0))
        self.assertEqual(self.status("20261124"), (["退市"], [], 0, "DELISTED", 0))

    def test_source_failure_unknown_is_not_normal(self):
        with self.db:
            self.db.execute("DELETE FROM status_fetch_state WHERE api='suspend_d' AND scope='20261120'")
            self.db.execute("DELETE FROM stock_name_history WHERE ts_code='600000.SH'")
        self.build()
        self.assertEqual(self.status("20261120")[:2], ([], ["停牌", "*ST", "ST"]))

    def test_index_is_exempt_from_all_stock_tags(self):
        with self.db:
            daily.upsert_daily_rows(self.db, daily.validate_index(*index_bar("20261120"), ["20261120"]).rows)
        self.build()
        self.assertEqual(tuple(self.db.execute("SELECT tags,tags_unknown FROM daily WHERE ts_code='000001.SH'").fetchone()), ("[]", "[]"))
        self.assertEqual(self.db.execute("SELECT count(*) FROM tradable_stock WHERE ts_code='000001.SH'").fetchone()[0], 0)

    def test_invalid_source_does_not_replace_previous_cache_and_next_batch_continues(self):
        warnings = []
        def query(api, params, fields):
            if params.get("ts_code"):
                return tags.NAME_FIELDS, [["600000.SH", "ST错误", "20260101", "20250101", None, "bad"]]
            return tags.SUSPEND_FIELDS, []
        batches = list(tags.fetch_batches(query, lambda *a, **kw: warnings.append((a, kw)),
            [("namechange", "600000.SH", "20261124"), ("suspend_d", "20261124", "20261124")]))
        self.assertEqual([b.api for b in batches], ["suspend_d"])
        self.assertEqual(warnings[0][1]["ts_code"], "600000.SH")
        self.assertEqual(self.db.execute("SELECT name FROM stock_name_history WHERE ts_code='600000.SH'").fetchone()[0], "普通股份")

    def test_truncated_suspension_response_is_not_marked_complete(self):
        warnings = []
        query = lambda *args: (tags.SUSPEND_FIELDS, [["600000.SH", "20261120", "", "S"]] * 5000)
        self.assertEqual(list(tags.fetch_batches(query, lambda *a, **k: warnings.append(a), [("suspend_d", "20261120", "20261120")])), [])
        self.assertIn("truncation", warnings[0][1])

    def test_known_legacy_suspension_code_preserves_the_whole_day_and_raw_code(self):
        warnings = []
        rows = [("600000.SH", "20050318", "", "S"), ("T00018.SH", "20050318", "", "S")]
        batches = list(tags.fetch_batches(lambda *args: (tags.SUSPEND_FIELDS, rows),
            lambda *a, **kw: warnings.append((a, kw)), [("suspend_d", "20050318", "20050318")]))
        self.assertEqual(warnings, [])
        self.assertEqual(len(batches), 1)
        self.assertEqual(batches[0].rows, rows)
        with self.db:
            tags.apply_batch(self.db, batches[0], "fixture")
        self.assertEqual(self.db.execute("SELECT count(*) FROM stock_suspensions WHERE trade_date='20050318'").fetchone()[0], 2)
        self.assertEqual(self.db.execute("SELECT row_count FROM status_fetch_state WHERE api='suspend_d' AND scope='20050318'").fetchone()[0], 2)

    def test_unknown_short_code_is_still_rejected(self):
        warnings = []
        response = tags.SUSPEND_FIELDS, [("T99999.SH", "20050318", "", "S")]
        result = list(tags.fetch_batches(lambda *args: response,
            lambda *a, **kw: warnings.append(a), [("suspend_d", "20050318", "20050318")]))
        self.assertEqual(result, [])
        self.assertEqual(warnings[0][0], "INVALID_STATUS_SOURCE")

    def test_legacy_source_halt_applies_only_to_matching_historical_identity(self):
        old = trading.Instrument("T600018.SH", "600018.SH", "SSE", "20000719", "20061019")
        new = trading.Instrument("600018.SH", "600018.SH", "SSE", "20061026")
        with self.db:
            self.db.execute("INSERT INTO stock_basic VALUES(?,?,?,?,?,?,?,?)",
                (old.security_id, "上港集箱(退)", "SSE", None, "D", old.start_date, "20061020", "fixture"))
            self.db.execute("INSERT INTO stock_basic VALUES(?,?,?,?,?,?,?,?)",
                (new.security_id, "上港集团", "SSE", None, "L", new.start_date, None, "fixture"))
            for day in ("20050318", "20061027"):
                tags.apply_batch(self.db, tags.Batch("suspend_d", day, day,
                    [("T00018.SH", day, "", "S")]), "fixture")
        context = tags.Context(self.db)
        self.assertTrue(context.full_day_suspension("600018.SH", "20050318", old))
        self.assertIn("停牌", json.loads(context.resolve("600018.SH", "20050318", old)[0]))
        self.assertFalse(context.full_day_suspension("600018.SH", "20061027", new))
        self.assertNotIn("停牌", json.loads(context.resolve("600018.SH", "20061027", new)[0]))
        self.assertFalse(context.full_day_suspension("600018.SH", "20061027", old))

    def test_builder_uses_legacy_halt_for_no_bar_old_quote(self):
        with self.db:
            self.db.execute("INSERT INTO stock_basic VALUES(?,?,?,?,?,?,?,?)",
                ("T600018.SH", "上港集箱(退)", "SSE", None, "D", "20000719", "20061020", "fixture"))
            self.db.execute("INSERT INTO stock_basic VALUES(?,?,?,?,?,?,?,?)",
                ("600018.SH", "上港集团", "SSE", None, "L", "20061026", None, "fixture"))
            for exchange in ("SSE", "SZSE"):
                self.db.executemany("INSERT INTO trade_cal VALUES(?,?,?,?)", calendar_rows(exchange, "20050317", "20050321"))
            tags.apply_batch(self.db, tags.Batch("suspend_d", "20050318", "20050318",
                [("T00018.SH", "20050318", "", "S")]), "fixture")
            trading.build(self.db, SimpleNamespace(db=self.path, start_date="20050318", end_date="20050318",
                calendar_padding=1, fetch_calendar=False, rules=None))
        status = self.status("20050318", "600018.SH")
        self.assertEqual(status, (["停牌"], ["*ST", "ST"], 0, "FULL_DAY_SUSPENDED", 0))

    def test_old_canonical_identity_source_code_is_also_resolved(self):
        old = trading.Instrument("T600018.SH", "600018.SH", "SSE", "20000719", "20061019")
        with self.db:
            tags.apply_batch(self.db, tags.Batch("suspend_d", "20050318", "20050318",
                [("T600018.SH", "20050318", "09:30-10:00", "S")]), "fixture")
        context = tags.Context(self.db)
        self.assertEqual(context.suspension_timings("600018.SH", "20050318", old), ["09:30-10:00"])
        self.assertFalse(context.full_day_suspension("600018.SH", "20050318", old))

    def test_empty_refresh_does_not_erase_previously_valid_history(self):
        warnings = []
        batches = list(tags.fetch_batches(lambda *args: (tags.NAME_FIELDS, []),
            lambda *a, **kw: warnings.append(a), [("namechange", "600000.SH", "20261125")], self.db))
        self.assertEqual(batches, [])
        self.assertIn("STATUS_SOURCE_SHRANK", [item[0] for item in warnings])
        self.assertEqual(self.db.execute("SELECT name FROM stock_name_history WHERE ts_code='600000.SH'").fetchone()[0], "普通股份")

    def test_invalid_falsy_timing_is_not_converted_to_full_day_halt(self):
        for value in (0, False, []):
            with self.subTest(value=value):
                warnings = []
                response = (tags.SUSPEND_FIELDS, [["600000.SH", "20261120", value, "S"]])
                result = list(tags.fetch_batches(lambda *a: response, lambda *a, **k: warnings.append(a),
                    [("suspend_d", "20261120", "20261120")]))
                self.assertEqual(result, [])
                self.assertEqual(warnings[0][0], "INVALID_STATUS_SOURCE")

    def test_name_repair_locates_old_st_change_but_ordinary_rename_does_not(self):
        ordinary = tags.Batch("namechange", "600000.SH", "20261125", [("600000.SH", "新名字", "20000101", None, None, "rename")])
        self.assertEqual(tags.affected_from(self.db, ordinary), "20261125")
        repair = tags.Batch("namechange", "600000.SH", "20261125", [("600000.SH", "ST旧名", "20000101", None, None, "repair")])
        self.assertEqual(tags.affected_from(self.db, repair), "20000101")

    def test_source_cache_resume_and_force(self):
        stocks = {r["ts_code"]: r for r in metadata()}
        self.assertEqual(tags.plan(self.db, stocks, ["20261120"], "20261116", "20261124"), [])
        self.assertEqual(len(tags.plan(self.db, stocks, ["20261120"], "20261116", "20261124", True)), 4)

    def test_migration_failure_rolls_back_tags_and_derived_rows(self):
        self.build()
        before = list(self.db.iterdump())
        with patch.object(trading, "assess", side_effect=RuntimeError("synthetic failure")):
            with self.assertRaisesRegex(RuntimeError, "synthetic failure"):
                self.build()
        self.assertEqual(list(self.db.iterdump()), before)

    def test_interrupted_metadata_or_calendar_refresh_leaves_rebuild_marker(self):
        client = FakeClient()
        client.token = "synthetic"
        self.build()
        self.assertTrue(tags.ready(self.db))
        daily.load_stocks(client, self.store)
        self.assertFalse(tags.ready(self.db))
        self.build()
        self.assertTrue(tags.ready(self.db))
        daily.load_calendar(client, self.store, "20261120", "20261124")
        self.assertFalse(tags.ready(self.db))


class PermanentEntryTests(unittest.TestCase):
    def test_get_daily_alone_builds_g_prefix_tags_from_empty_database(self):
        class HistoricalNames(FakeClient):
            token = "synthetic"
            def query(self, api, params, fields):
                returned, rows = super().query(api, params, fields)
                if api == "namechange":
                    rows[0][1] = "GST股份" if params["ts_code"] == "600000.SH" else "G*ST股份"
                return returned, rows
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "fresh.db"
            client = HistoricalNames({"20261120": bars("20261120")})
            with patch.object(daily, "TushareClient", return_value=client), patch.dict('os.environ', {'TUSHARE_TOKEN': 'synthetic'}):
                code = daily.main(["--db", str(path), "--start-date", "20261120", "--end-date", "20261120",
                                   "--report-dir", str(Path(directory) / "reports")])
            self.assertIn(code, (0, 2))
            with closing(sqlite3.connect(path)) as db:
                self.assertTrue(tags.ready(db))
                for table in ('daily', 'tradable_stock'):
                    self.assertEqual(db.execute(f"SELECT tags FROM {table} WHERE ts_code='600000.SH'").fetchone()[0], '["ST"]')
                    self.assertEqual(db.execute(f"SELECT tags FROM {table} WHERE ts_code='000001.SZ'").fetchone()[0], '["*ST"]')

    def test_fresh_and_legacy_migration_have_same_schema_and_content(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            snapshots = []
            for legacy in (False, True):
                path = root / ("legacy.db" if legacy else "fresh.db")
                store = daily.Store(path)
                try:
                    store.start_run("20261120", "20261120")
                    args = daily.build_parser().parse_args(["--db", str(path), "--start-date", "20261120", "--end-date", "20261120", "--report-dir", str(root / "reports")])
                    client = FakeClient({"20261120": bars("20261120")})
                    client.token = "synthetic"
                    daily.run_download(client, store, args)
                    if legacy:
                        with store.db:
                            for table in ("tradable_stock", "market_calendar", "stock_name_history", "stock_suspensions", "status_fetch_state", "dataset_meta"):
                                store.db.execute(f"DROP TABLE {table}")
                            for column in ("tags", "tags_unknown"):
                                store.db.execute(f"ALTER TABLE daily DROP COLUMN {column}")
                        store.close()
                        store = daily.Store(path)
                        store.start_run("20261120", "20261120")
                        args.migrate_only = True
                    daily.finalize_dataset(client, store, args)
                    snapshot = {}
                    for table in ("daily", "tradable_stock", "market_calendar", "stock_name_history", "stock_suspensions", "status_fetch_state", "dataset_meta"):
                        snapshot[table + "_schema"] = [tuple(r) for r in store.db.execute(f"PRAGMA table_info({table})")]
                    for table in ("daily", "tradable_stock", "stock_name_history", "stock_suspensions"):
                        snapshot[table] = [tuple(r) for r in store.db.execute(f"SELECT * FROM {table} ORDER BY 1,2")]
                    snapshots.append(snapshot)
                    self.assertTrue(tags.ready(store.db))
                finally:
                    store.close()
            self.assertEqual(*snapshots)


if __name__ == "__main__":
    unittest.main()
