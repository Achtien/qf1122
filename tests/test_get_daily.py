"""Offline behavioral checks for the Tushare daily ingestion pipeline."""

import math
from pathlib import Path
import unittest
import tempfile
from types import SimpleNamespace
from unittest.mock import patch


from get_data import get_daily as daily


EXPECTED_FIELDS = (
    "ts_code", "trade_date", "open", "high", "low", "close", "pre_close",
    "change", "pct_chg", "vol", "amount", "ah_vol", "ah_amount",
)
CALENDAR_FIELDS = ("exchange", "cal_date", "is_open", "pretrade_date")


def daily_payload(trade_date="20240102", **changes):
    record = dict(zip(EXPECTED_FIELDS, (
        "600000.SH", trade_date, 10.0, 11.0, 9.0, 10.5, 10.0,
        0.5, 5.0, 12345.67, 129629.535, None, None,
    )))
    record.update(changes)
    return list(EXPECTED_FIELDS), [[record[field] for field in EXPECTED_FIELDS]]


class FakeClock:
    def __init__(self):
        self.now = 0.0
        self.sleeps = []

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        if seconds < 0:
            raise AssertionError("The rate limiter requested a negative sleep")
        self.sleeps.append(seconds)
        self.now += seconds


class RateLimitTests(unittest.TestCase):
    def test_requests_are_spaced_at_three_quarters_of_the_global_quota(self):
        clock = FakeClock()
        limiter = daily.RateLimiter(
            global_rpm=200, fraction=0.75, clock=clock, sleep=clock.sleep,
        )
        starts = []
        for _ in range(170):
            limiter.wait("daily")
            starts.append(clock())
        self.assertTrue(all(
            right - left >= 0.4 - 1e-9
            for left, right in zip(starts, starts[1:])
        ))
        self.assertGreaterEqual(starts[150] - starts[0], 60.0 - 1e-8)

    def test_endpoint_and_global_limits_share_one_clock(self):
        clock = FakeClock()
        limiter = daily.RateLimiter(
            global_rpm=200, endpoint_limits={"stock_basic": 50},
            fraction=0.75, clock=clock, sleep=clock.sleep,
        )
        starts = []
        for api in ("stock_basic", "daily", "stock_basic", "daily"):
            limiter.wait(api)
            starts.append(clock())
        self.assertGreaterEqual(starts[2] - starts[0], 1.6 - 1e-9)
        self.assertTrue(all(
            right - left >= 0.4 - 1e-9
            for left, right in zip(starts, starts[1:])
        ))

    def test_an_idle_interval_does_not_accumulate_burst_credit(self):
        clock = FakeClock()
        limiter = daily.RateLimiter(
            global_rpm=200, fraction=0.75, clock=clock, sleep=clock.sleep,
        )
        limiter.wait("daily")
        clock.now += 600.0
        limiter.wait("daily")
        after_idle = clock()
        limiter.wait("daily")
        self.assertGreaterEqual(clock() - after_idle, 0.4 - 1e-9)


class DailyValidationTests(unittest.TestCase):
    def test_malformed_field_names_become_issues_instead_of_stopping_run(self):
        result = daily.validate_daily([["ts_code"]], [["600000.SH"]], "20240102")
        self.assertTrue(result.issues)
        self.assertTrue(result.rejected)

    def test_all_thirteen_fields_are_preserved_without_unit_conversion(self):
        fields, items = daily_payload(
            "20260706", ah_vol=123.45, ah_amount=1296.225,
        )
        result = daily.validate_daily(fields, items, "20260706")
        self.assertEqual(tuple(daily.DAILY_FIELDS), EXPECTED_FIELDS)
        self.assertEqual(result.rows, [tuple(items[0])])
        self.assertEqual(result.rejected, [])
        self.assertEqual(result.issues, [])

    def test_historic_null_after_hours_values_are_valid(self):
        fields, items = daily_payload()
        result = daily.validate_daily(fields, items, "20240102")
        self.assertEqual(result.rows[0][-2:], (None, None))
        self.assertEqual(result.issues, [])

    def test_legacy_payload_without_after_hours_columns_is_accepted(self):
        fields, items = daily_payload()
        result = daily.validate_daily(fields[:-2], [items[0][:-2]], "20240102")
        self.assertEqual(result.rows, [tuple(items[0])])
        self.assertEqual(result.rejected, [])
        self.assertEqual(result.issues, [])

    def test_missing_after_hours_columns_after_introduction_are_reported(self):
        fields, items = daily_payload("20260706")
        result = daily.validate_daily(fields[:-2], [items[0][:-2]], "20260706")
        self.assertTrue(result.issues)

    def test_one_wrong_date_does_not_discard_the_valid_stock(self):
        fields, good = daily_payload()
        _, bad = daily_payload("20240103", ts_code="000001.SZ")
        result = daily.validate_daily(fields, good + bad, "20240102")
        self.assertEqual(result.rows, [tuple(good[0])])
        self.assertEqual(len(result.rejected), 1)
        self.assertTrue(result.issues)

    def test_non_finite_prices_are_never_written_as_market_data(self):
        for invalid in (math.nan, math.inf, -math.inf):
            with self.subTest(price=invalid):
                fields, items = daily_payload(close=invalid)
                result = daily.validate_daily(fields, items, "20240102")
                self.assertFalse(result.rows)
                self.assertTrue(result.rejected)
                self.assertTrue(result.issues)


class BenchmarkTests(unittest.TestCase):
    def payload(self, day="20261123"):
        fields, rows = daily_payload(day, ts_code=daily.BENCHMARK_CODE)
        return fields[:-2], [rows[0][:-2]]

    def test_index_fields_are_normalized_to_daily_and_after_hours_stays_null(self):
        fields, rows = self.payload()
        result = daily.validate_index(fields, rows, ["20261123"])
        self.assertEqual(result.rows, [tuple(rows[0]) + (None, None)])
        self.assertEqual(result.issues, [])
        self.assertTrue(daily.validate_daily(*daily_payload("20261123", ts_code=daily.BENCHMARK_CODE), "20261123").rejected)

    def test_bad_index_keys_duplicates_and_missing_values_remain_unfilled(self):
        fields, rows = self.payload()
        wrong_code = list(rows[0]); wrong_code[0] = "000001.SZ"
        null_close = list(rows[0]); null_close[fields.index("close")] = None
        for bad in ([wrong_code], rows + rows, [null_close], []):
            with self.subTest(bad=bad):
                result = daily.validate_index(fields, bad, ["20261123"])
                self.assertEqual(result.rows, [])
                self.assertTrue(result.issues)

    def test_index_ranges_are_split_by_year_and_continue_after_failure(self):
        calls = []
        def query(api, params, fields):
            calls.append((api, params))
            return None if params["start_date"] == "20251231" else self.payload("20260105")
        result = list(daily.index_results(query, ["20251231", "20260105"], ["20251231", "20260105"]))
        self.assertEqual(len(calls), 2)
        self.assertIsNone(result[0][1])
        self.assertEqual(len(result[1][1].rows), 1)

    def test_fresh_download_and_resume_both_populate_benchmark(self):
        with tempfile.TemporaryDirectory() as directory:
            store = daily.Store(Path(directory) / "test.db")
            self.addCleanup(store.close)
            store.start_run("20261123", "20261123")
            with store.db:
                store.db.execute("INSERT INTO trade_cal VALUES('SSE','20261123',1,'20261120')")
            calls = []
            class Client:
                token = "fake"
                def query(client, api, params, fields):
                    calls.append(api)
                    return self.payload() if api == "index_daily" else daily_payload("20261123")
            args = SimpleNamespace(start_date="20261123", end_date="20261123", force=False, retry_warnings=False, max_days=None)
            with patch.object(daily, "load_stocks", return_value=[]), patch.object(daily, "load_calendar", return_value=["20261123"]):
                daily.run_download(Client(), store, args)
                self.assertEqual(calls, ["daily", "index_daily"])
                self.assertEqual(store.db.execute("SELECT count(*) FROM daily").fetchone()[0], 2)
                self.assertEqual(store.db.execute("SELECT saved_rows FROM date_status").fetchone()[0], 1)
                with store.db:
                    store.db.execute("DELETE FROM daily WHERE ts_code=?", (daily.BENCHMARK_CODE,))
                calls.clear()
                daily.run_download(Client(), store, args)
                self.assertEqual(calls, ["index_daily"])
                fields, rows = daily_payload("20261123")
                store.save_daily("20261123", daily.validate_daily(fields, rows, "20261123"))
                self.assertEqual(store.db.execute("SELECT count(*) FROM warnings WHERE kind='EXISTING_CODES_OMITTED'").fetchone()[0], 0)
                self.assertEqual(store.db.execute("SELECT count(*) FROM daily WHERE ts_code=?", (daily.BENCHMARK_CODE,)).fetchone()[0], 1)


class CalendarValidationTests(unittest.TestCase):
    def setUp(self):
        self.rows = [
            ["SSE", "20240101", 0, "20231229"],
            ["SSE", "20240102", 1, "20231229"],
            ["SSE", "20240103", 1, "20240102"],
        ]

    def test_complete_calendar_identifies_trading_days_only(self):
        records, open_dates, issues = daily.validate_calendar(
            CALENDAR_FIELDS, self.rows, "20240101", "20240103", "SSE",
        )
        self.assertEqual(len(records), 3)
        self.assertEqual(open_dates, {"20240102", "20240103"})
        self.assertEqual(issues, [])

    def test_missing_closed_day_still_makes_calendar_incomplete(self):
        _, open_dates, issues = daily.validate_calendar(
            CALENDAR_FIELDS, self.rows[1:], "20240101", "20240103", "SSE",
        )
        self.assertFalse(open_dates)
        self.assertTrue(issues)

    def test_nested_calendar_date_is_reported_without_crashing(self):
        self.rows[0][1] = ["20240101"]
        _, opened, issues = daily.validate_calendar(CALENDAR_FIELDS, self.rows, "20240101", "20240103", "SSE")
        self.assertFalse(opened)
        self.assertTrue(issues)


class PersistenceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = daily.Store(Path(self.tmp.name) / "test.db")
        self.store.start_run("20240102", "20240103")

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def test_repair_updates_existing_key_without_creating_duplicate(self):
        fields, items = daily_payload(close=10.5)
        self.store.save_daily("20240102", daily.validate_daily(fields, items, "20240102"))
        fields, items = daily_payload(close=10.6)
        self.store.save_daily("20240102", daily.validate_daily(fields, items, "20240102"))
        row = self.store.db.execute("SELECT count(*),max(close) FROM daily").fetchone()
        self.assertEqual(tuple(row), (1, 10.6))
        self.assertTrue(self.store.should_skip("20240102"))
        self.assertFalse(self.store.should_skip("20240102", force=True))

    def test_warning_resume_is_distinct_from_failure_and_success(self):
        fields, items = daily_payload(close=None)
        self.store.save_daily("20240102", daily.validate_daily(fields, items, "20240102"))
        self.assertTrue(self.store.should_skip("20240102"))
        self.assertFalse(self.store.should_skip("20240102", retry_warnings=True))
        self.store.mark_failed("20240103")
        self.assertFalse(self.store.should_skip("20240103"))
        report, count = daily.write_report(self.store, self.tmp.name, "completed_with_warnings")
        content = report.read_text()
        self.assertEqual(count, 1)
        for expected in ("20240102", "600000.SH", "close", "NULL_VALUE", "20240103", "failed"):
            self.assertIn(expected, content)

    def test_request_failure_is_redacted_logged_and_next_request_runs(self):
        class Client:
            token = "test-secret-do-not-log"
            def query(self, api, params, fields):
                if params["trade_date"] == "20240102":
                    raise RuntimeError("timeout with " + self.token)
                return daily_payload("20240103")
        client = Client()
        failed = daily.fetch(client, self.store, "daily", {"trade_date": "20240102"}, EXPECTED_FIELDS)
        self.assertIsNone(failed)
        response = daily.fetch(client, self.store, "daily", {"trade_date": "20240103"}, EXPECTED_FIELDS)
        self.assertIsNotNone(response)
        errors = self.store.db.execute("SELECT error FROM request_log WHERE status='failed'").fetchone()[0]
        self.assertNotIn(client.token, errors)
        self.assertIn("[REDACTED]", errors)

    def test_unknown_or_delisted_code_is_not_filtered_from_daily(self):
        fields, items = daily_payload(ts_code="600001.SH")
        result = daily.validate_daily(fields, items, "20240102")
        self.store.save_daily("20240102", result)
        self.assertEqual(self.store.db.execute("SELECT ts_code FROM daily").fetchone()[0], "600001.SH")

    def test_partial_valid_batch_keeps_invalid_raw_row_for_repair(self):
        fields, valid = daily_payload()
        _, invalid = daily_payload("20240103", ts_code="000001.SZ")
        result = daily.validate_daily(fields, valid + invalid, "20240102")
        self.store.save_daily("20240102", result)
        self.assertEqual(self.store.db.execute("SELECT count(*) FROM daily").fetchone()[0], 1)
        raw = self.store.db.execute("SELECT payload_json FROM rejected_rows").fetchone()[0]
        self.assertIn("000001.SZ", raw)
        self.assertIn("20240103", raw)

    def test_refresh_omitting_stored_code_retains_it_but_marks_warning(self):
        fields, first = daily_payload()
        _, second = daily_payload(ts_code="000001.SZ")
        self.store.save_daily("20240102", daily.validate_daily(fields, first + second, "20240102"))
        self.store.save_daily("20240102", daily.validate_daily(fields, first, "20240102"))
        self.assertEqual(self.store.db.execute("SELECT count(*) FROM daily").fetchone()[0], 2)
        self.assertEqual(self.store.db.execute("SELECT status FROM date_status").fetchone()[0], "warning")
        self.assertIn("000001.SZ", self.store.db.execute("SELECT message FROM warnings").fetchone()[0])

    def test_failed_refresh_resets_attempt_counts_but_keeps_saved_data(self):
        fields, items = daily_payload()
        self.store.save_daily("20240102", daily.validate_daily(fields, items, "20240102"))
        self.store.mark_failed("20240102")
        self.assertEqual(tuple(self.store.db.execute("SELECT status,returned_rows,saved_rows FROM date_status").fetchone()), ("failed", 0, 0))
        self.assertEqual(self.store.db.execute("SELECT count(*) FROM daily").fetchone()[0], 1)

    def test_history_before_current_listing_is_retained_and_flagged(self):
        fields, items = daily_payload(ts_code="920017.BJ")
        self.store.save_daily("20240102", daily.validate_daily(fields, items, "20240102"))
        with self.store.db:
            self.store.db.execute("INSERT INTO stock_basic VALUES(?,?,?,?,?,?,?,?)", ("920017.BJ", "Example", "BSE", "北交所", "L", "20250101", None, daily.stamp()))
        daily.audit_listing_intervals(self.store, "20240102", "20240103")
        warning = self.store.db.execute("SELECT ts_code,kind,message FROM warnings").fetchone()
        self.assertEqual(warning[0], "920017.BJ")
        self.assertEqual(warning[1], "OUTSIDE_LISTING_INTERVAL")
        self.assertIn("20240102", warning[2])
        self.assertEqual(self.store.db.execute("SELECT count(*) FROM daily").fetchone()[0], 1)

    def test_bse_former_market_listing_date_does_not_imply_bse_eligibility(self):
        fields, items = daily_payload("20210104", ts_code="920017.BJ")
        self.store.save_daily("20210104", daily.validate_daily(fields, items, "20210104"))
        with self.store.db:
            self.store.db.execute("INSERT INTO stock_basic VALUES(?,?,?,?,?,?,?,?)", ("920017.BJ", "Example", "BSE", "北交所", "L", "20200727", None, daily.stamp()))
        daily.audit_listing_intervals(self.store, "20210104", "20210104")
        self.assertIn("20211115", self.store.db.execute("SELECT message FROM warnings").fetchone()[0])


if __name__ == "__main__":
    unittest.main()
