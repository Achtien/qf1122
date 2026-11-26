"""Offline checks for calendar, eligibility, and transactional table builds.

Uses synthetic in-memory databases only; no network or existing database access.

"""

import math
from pathlib import Path
import sqlite3
from types import SimpleNamespace
import unittest


from get_data import daily_tables as builder


def calendar_day(is_open, previous=None):
    return builder.CalendarDay(
        is_open=is_open, pretrade_date=previous, source="unit_test",
    )


def calendar_result(days, start, end, exchange="SSE"):
    lower = min([start, *days])
    upper = max([end, *days])
    calendars = builder.complete_calendars({exchange: days}, lower, upper)
    rows = builder.calendar_rows(calendars, start, end)
    return {row[1]: row for row in rows if row[0] == exchange}


def instrument(start="19991110", end=None):
    return builder.Instrument(
        security_id="SSE:600000.SH:19991110", ts_code="600000.SH",
        exchange="SSE", start_date=start, end_date=end,
    )


def bar(**changes):
    values = {
        "ts_code": "600000.SH", "trade_date": "20240103",
        "open": 10.0, "high": 11.0, "low": 9.0, "close": 10.5,
        "pre_close": 10.0, "change": 0.5, "pct_chg": 5.0,
        "vol": 12345.0, "amount": 129622.5,
        "ah_vol": None, "ah_amount": None,
    }
    values.update(changes)
    return values


class CalendarDecisionTests(unittest.TestCase):
    def test_weekday_uses_monday_one_through_sunday_seven(self):
        days = {
            "20240101": calendar_day(1),
            "20240102": calendar_day(1),
            "20240103": calendar_day(1),
            "20240104": calendar_day(1),
            "20240105": calendar_day(1),
            "20240106": calendar_day(0),
            "20240107": calendar_day(0),
        }
        rows = calendar_result(days, "20240101", "20240107")
        self.assertEqual([rows[day][3] for day in sorted(days)], list(range(1, 8)))

    def test_boundary_tag_distinguishes_both_sides_of_a_closed_day(self):
        scenarios = (
            (1, 1, 0),  # Both neighbors are open.
            (0, 1, 1),  # First session after a closure.
            (1, 0, 2),  # Last session before a closure.
            (0, 0, 3),  # Isolated session between closures.
        )
        for previous, following, expected in scenarios:
            with self.subTest(previous=previous, following=following):
                rows = calendar_result({
                    "20240102": calendar_day(previous),
                    "20240103": calendar_day(1),
                    "20240104": calendar_day(following),
                }, "20240103", "20240103")
                self.assertEqual(rows["20240103"][4], expected)

    def test_unknown_neighbor_does_not_become_a_holiday_boundary(self):
        for days in (
            {"20240103": calendar_day(1), "20240104": calendar_day(1)},
            {"20240102": calendar_day(1), "20240103": calendar_day(1)},
        ):
            with self.subTest(days=days):
                rows = calendar_result(days, "20240103", "20240103")
                self.assertIsNone(rows["20240103"][4])

    def test_calendar_day_gaps_include_weekends_and_holidays(self):
        rows = calendar_result({
            "20240402": calendar_day(1),
            "20240403": calendar_day(1, "20240402"),
            "20240404": calendar_day(0, "20240403"),
            "20240405": calendar_day(0, "20240403"),
            "20240406": calendar_day(0, "20240403"),
            "20240407": calendar_day(0, "20240403"),
            "20240408": calendar_day(1, "20240403"),
            "20240409": calendar_day(1, "20240408"),
        }, "20240408", "20240408")
        row = rows["20240408"]
        self.assertEqual(row[4], 1)
        self.assertEqual(row[5:9], ("20240403", "20240409", 5, 1))

    def test_missing_calendar_date_is_unknown_even_if_it_is_a_weekday(self):
        rows = calendar_result({
            "20240102": calendar_day(1),
            "20240104": calendar_day(1),
        }, "20240103", "20240103")
        self.assertIsNone(rows["20240103"][2])
        self.assertIsNone(rows["20240103"][4])

    def test_previous_trade_date_can_resolve_left_calendar_edge(self):
        rows = calendar_result({
            "20240108": calendar_day(1, "20240105"),
            "20240109": calendar_day(1, "20240108"),
        }, "20240108", "20240108")
        self.assertEqual(rows["20240108"][4], 1)
        self.assertEqual(rows["20240108"][5:9], ("20240105", "20240109", 3, 1))

    def test_unknown_segment_prevents_inventing_next_trading_date(self):
        rows = calendar_result({
            "20240102": calendar_day(1),
            "20240104": calendar_day(1),
        }, "20240102", "20240102")
        self.assertIsNone(rows["20240102"][6])

    def test_bse_proxy_requires_agreement_and_respects_opening_date(self):
        calendars = builder.complete_calendars({
            "SSE": {"20211112": calendar_day(1), "20211115": calendar_day(1),
                    "20211116": calendar_day(1)},
            "SZSE": {"20211112": calendar_day(1), "20211115": calendar_day(1),
                     "20211116": calendar_day(0)},
        }, "20211112", "20211116")
        self.assertEqual(calendars["BSE"]["20211112"].is_open, 0)
        self.assertEqual(calendars["BSE"]["20211115"].is_open, 1)
        self.assertEqual(calendars["BSE"]["20211115"].source, "SSE_SZSE_PROXY")
        self.assertIsNone(calendars["BSE"]["20211116"].is_open)


class EligibilityDecisionTests(unittest.TestCase):
    def decision(self, quote=None, opened=1, security=None, **options):
        return builder.assess(
            "20240103", opened, security or instrument(), quote, **options,
        )

    def test_valid_bar_on_an_open_day_has_positive_trading_evidence(self):
        eligible, reason = self.decision(bar())
        self.assertEqual(eligible, 1)
        self.assertTrue(reason)

    def test_missing_bar_is_unknown_not_a_proven_suspension(self):
        eligible, reason = self.decision(None)
        self.assertIsNone(eligible)
        self.assertTrue(reason)

    def test_zero_volume_remains_unknown(self):
        eligible, reason = self.decision(bar(vol=0.0))
        self.assertIsNone(eligible)
        self.assertTrue(reason)

    def test_missing_calendar_does_not_become_a_closed_market(self):
        eligible, reason = self.decision(bar(), opened=None)
        self.assertIsNone(eligible)
        self.assertTrue(reason)

    def test_confirmed_closed_market_is_ineligible(self):
        eligible, reason = self.decision(None, opened=0)
        self.assertEqual(eligible, 0)
        self.assertTrue(reason)

    def test_suspension_conflicting_with_a_bar_requires_investigation(self):
        eligible, reason = self.decision(
            bar(), blocked_reason="CONFIRMED_LISTING_SUSPENSION",
        )
        self.assertIsNone(eligible)
        self.assertEqual(reason, "SUSPENSION_BAR_CONFLICT")

    def test_explicit_full_day_suspension_without_bar_is_ineligible(self):
        eligible, reason = self.decision(
            None, blocked_reason="CONFIRMED_LISTING_SUSPENSION",
        )
        self.assertEqual(eligible, 0)
        self.assertEqual(reason, "CONFIRMED_LISTING_SUSPENSION")

    def test_identity_conflict_is_not_silently_resolved_by_a_bar(self):
        eligible, reason = self.decision(bar(), identity_conflict=True)
        self.assertIsNone(eligible)
        self.assertTrue(reason)

    def test_outside_confirmed_listing_interval_is_ineligible(self):
        for security in (
            instrument(start="20240104"),
            instrument(end="20240102"),
        ):
            with self.subTest(security=security):
                eligible, reason = self.decision(None, security=security)
                self.assertEqual(eligible, 0)
                self.assertTrue(reason)

    def test_listing_interval_boundaries_are_inclusive(self):
        eligible, _ = self.decision(
            bar(), security=instrument(start="20240103", end="20240103"),
        )
        self.assertEqual(eligible, 1)

    def test_invalid_market_values_do_not_create_positive_eligibility(self):
        invalid_bars = (
            bar(close=None),
            bar(close=math.nan),
            bar(high=math.inf),
            bar(low=-1),
            bar(high=8),
            bar(vol=-1),
        )
        for quote in invalid_bars:
            with self.subTest(quote=quote):
                eligible, reason = self.decision(quote)
                self.assertIsNone(eligible)
                self.assertTrue(reason)


class HistoricalIdentityTests(unittest.TestCase):
    def test_reused_quote_code_resolves_to_historical_security(self):
        old = builder.Instrument("T600018.SH", "600018.SH", "SSE", "20000719", "20061019")
        new = builder.Instrument("600018.SH", "600018.SH", "SSE", "20061026")
        self.assertEqual(builder.select_instrument([old, new], "20050920"), (old, False))
        self.assertEqual(builder.select_instrument([old, new], "20061026"), (new, False))

    def test_overlapping_identities_are_not_resolved_arbitrarily(self):
        one = instrument()
        two = builder.Instrument("OLD_ID", one.ts_code, "SSE", "20000101")
        self.assertEqual(builder.select_instrument([one, two], "20240103"), (None, True))

    def test_bse_quote_before_market_open_is_excluded_despite_early_list_date(self):
        stock = builder.Instrument("830001.BJ", "830001.BJ", "BSE", "20180101")
        self.assertEqual(builder.assess("20211112", 1, stock, bar()), (0, "BEFORE_BSE_OPEN"))


class DatabaseBuildTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(":memory:", isolation_level=None)
        self.addCleanup(self.db.close)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.executescript('''
            CREATE TABLE daily (
                ts_code TEXT, trade_date TEXT, open REAL, high REAL, low REAL,
                close REAL, vol REAL, amount REAL, PRIMARY KEY(trade_date,ts_code)
            );
            CREATE TABLE stock_basic (
                ts_code TEXT PRIMARY KEY, exchange TEXT, list_date TEXT, delist_date TEXT
            );
            CREATE TABLE trade_cal (
                exchange TEXT, cal_date TEXT, is_open INTEGER, pretrade_date TEXT,
                PRIMARY KEY(exchange,cal_date)
            );
        ''')
        self.db.executemany("INSERT INTO stock_basic VALUES(?,?,?,?)", [
            ("600000.SH", "SSE", "19991110", None),
            ("600001.SH", "SSE", "20000101", None),
        ])
        self.db.executemany("INSERT INTO daily VALUES(?,?,?,?,?,?,?,?)", [
            ("600000.SH", day, 10, 11, 9, 10.5, 100, 1000)
            for day in ("20240103", "20240104")
        ])
        self.db.executemany("INSERT INTO trade_cal VALUES(?,?,?,?)", [
            (exchange, day, 1, builder.shifted(day, -1))
            for exchange in ("SSE", "SZSE")
            for day in ("20240102", "20240103", "20240104", "20240105")
        ])
        self.args = SimpleNamespace(
            db=Path("synthetic_in_memory.db"), start_date="20240103", end_date="20240104",
            rules=None, calendar_padding=1, fetch_calendar=False,
        )

    def snapshot(self, table):
        columns = "ts_code,trade_date,open,high,low,close,vol,amount" if table == "daily" else "*"
        return [tuple(row) for row in self.db.execute(f"SELECT {columns} FROM {table} ORDER BY 1,2")]

    def test_range_rebuild_preserves_sources_and_other_dates(self):
        before = {table: self.snapshot(table) for table in ("daily", "stock_basic", "trade_cal")}
        self.db.execute("BEGIN IMMEDIATE")
        manifest, has_unknown = builder.build(self.db, self.args)
        self.db.commit()
        self.assertEqual(manifest["stock_rows"], 4)
        self.assertEqual(manifest["unknown_stock_rows"], 2)
        self.assertTrue(has_unknown)
        self.assertEqual(self.db.execute("SELECT count(*) FROM market_calendar").fetchone()[0], 6)
        self.assertEqual(self.db.execute("SELECT count(*) FROM tradable_stock WHERE is_tradable=1").fetchone()[0], 2)
        untouched_build = self.db.execute("SELECT build_id FROM market_calendar WHERE exchange='SSE' AND cal_date='20240104'").fetchone()[0]
        self.args.end_date = "20240103"
        self.db.execute("BEGIN IMMEDIATE")
        builder.build(self.db, self.args)
        self.db.commit()
        self.assertEqual(self.db.execute("SELECT count(*) FROM tradable_stock").fetchone()[0], 4)
        self.assertEqual(self.db.execute("SELECT build_id FROM market_calendar WHERE exchange='SSE' AND cal_date='20240104'").fetchone()[0], untouched_build)
        for table, original in before.items():
            self.assertEqual(self.snapshot(table), original)

    def test_uncommitted_build_rolls_back_tables_and_rows(self):
        self.db.execute("BEGIN IMMEDIATE")
        builder.build(self.db, self.args)
        self.db.rollback()
        tables = {row[0] for row in self.db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        self.assertNotIn("tradable_stock", tables)
        self.assertNotIn("market_calendar", tables)
        self.assertEqual(self.db.execute("SELECT count(*) FROM daily").fetchone()[0], 2)

    def test_foreign_key_rejects_stock_date_without_calendar(self):
        self.db.execute("BEGIN IMMEDIATE")
        builder.build(self.db, self.args)
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.execute("INSERT INTO tradable_stock(trade_date,ts_code,exchange,security_id,data_available,is_tradable,reason) VALUES(?,?,?,?,?,?,?)",
                            ("20240106", "600000.SH", "SSE", "600000.SH", 0, None, "NO_DAILY_DATA"))
        self.db.rollback()

    def test_benchmark_does_not_become_unknown_stock_or_extend_stock_date_range(self):
        self.db.executemany("INSERT INTO daily VALUES(?,?,?,?,?,?,?,?)", [
            ("000001.SH", day, 3000, 3100, 2900, 3050, 1000, 10000)
            for day in ("20240103", "20240105")
        ])
        self.args.start_date = self.args.end_date = None
        self.db.execute("BEGIN IMMEDIATE")
        manifest, _ = builder.build(self.db, self.args)
        self.assertEqual(manifest["end_date"], "20240104")
        self.assertEqual(manifest["stock_rows"], 4)
        self.assertEqual(self.db.execute("SELECT count(*) FROM tradable_stock WHERE ts_code='000001.SH'").fetchone()[0], 0)
        self.db.rollback()


if __name__ == "__main__":
    unittest.main()
