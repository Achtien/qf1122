"""Regression cases for historical status, missing quotes and reused quote codes."""

import json
import sqlite3
import unittest
from contextlib import closing
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory

from get_data import stock_tags
from backtest import Config, Strategy, run, snapshot
from backtest.data import Market, readonly
from backtest.model import number
from test_engine import CODE, DAYS, market_fixture


def add_status_schema(db):
    stock_tags.ensure_schema(db)
    db.execute("ALTER TABLE tradable_stock ADD COLUMN reason TEXT DEFAULT 'TRADED'")
    db.execute("ALTER TABLE tradable_stock ADD COLUMN data_available INTEGER DEFAULT 1")
    db.execute("UPDATE tradable_stock SET tags='[]',tags_unknown='[]'")
    db.execute("UPDATE daily SET tags='[]',tags_unknown='[]'")
    stock_tags.set_meta(db, "tag_version", stock_tags.VERSION)
    stock_tags.set_meta(db, "tags_dirty", "0")


class Hold(Strategy):
    def on_open(self, ctx):
        if ctx.day == DAYS[0]:
            ctx.order(CODE, "BUY", 1)


class StatusTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / "market.db"
        self.config = Config(DAYS[0], DAYS[-1], "2000", exchanges=("SSE",))
        market_fixture(self.source)
        with closing(sqlite3.connect(self.source)) as db, db:
            add_status_schema(db)

    def test_status_api_full_day_and_intraday_halts_and_adjusted_prices(self):
        case = self

        class Inspect(Hold):
            def before_open(self, ctx):
                with case.assertRaisesRegex(ValueError, "future"):
                    ctx.statuses("20240105")
                with case.assertRaises(KeyError):
                    ctx.status("999999.SH")
                if ctx.day == DAYS[0]:
                    case.assertEqual(ctx.status(CODE)["tags_unknown"], ("*ST", "ST"))
                if ctx.day == DAYS[1]:
                    case.assertNotIn(CODE, ctx.universe)
                    case.assertEqual(ctx.status(CODE)["tags"], ("停牌", "ST"))
                    case.assertEqual(ctx.sellable(CODE), 0)
                    case.assertEqual(ctx.statuses()[CODE]["is_tradable"], 0)

            def after_close(self, ctx):
                if ctx.day == DAYS[2]:
                    case.assertIn(CODE, ctx.universe)
                    case.assertEqual(ctx.bars(ctx.day)[CODE]["tags"], ("停牌", "*ST"))
                    case.assertEqual(ctx.history(CODE, DAYS[0], ctx.day)[-1]["tags"], ("停牌", "*ST"))
                    case.assertEqual(ctx.status(CODE, DAYS[1])["tags"], ("停牌", "ST"))
                    changed = ctx.status(CODE)
                    changed["tags"] = ()
                    case.assertEqual(ctx.status(CODE)["tags"], ("停牌", "*ST"))

        with closing(sqlite3.connect(self.source)) as db, db:
            db.execute("UPDATE tradable_stock SET tags_unknown='[\"*ST\",\"ST\"]' WHERE trade_date=?", (DAYS[0],))
            db.execute("DELETE FROM daily WHERE ts_code=? AND trade_date=?", (CODE, DAYS[1]))
            db.execute("""UPDATE tradable_stock SET tags='["停牌","ST"]',is_tradable=0,
                       data_available=0,reason='FULL_DAY_SUSPENDED' WHERE trade_date=?""", (DAYS[1],))
            db.execute("UPDATE tradable_stock SET tags='[\"停牌\",\"*ST\"]' WHERE trade_date=?", (DAYS[2],))
            db.execute("CREATE TABLE adj_factor(ts_code,trade_date,adj_factor,PRIMARY KEY(ts_code,trade_date))")
            db.executemany("INSERT INTO adj_factor VALUES(?,?,2)", [(CODE, d) for d in DAYS])
        for basis in ("raw", "adjusted"):
            path, _ = run(Inspect(), replace(self.config, price_basis=basis), self.source, self.root / basis)
            with closing(sqlite3.connect(path)) as db:
                equity, status = db.execute("SELECT equity,valuation_status FROM daily_account WHERE trade_date=?", (DAYS[1],)).fetchone()
                case.assertEqual((number(equity), status), (2100 if basis == "raw" else 2200, "stale"))
                row = db.execute("SELECT price_date,tags,tags_unknown,status_reason,sellable FROM daily_positions WHERE trade_date=?", (DAYS[1],)).fetchone()
                case.assertEqual((row[0], json.loads(row[1]), json.loads(row[2]), row[3], row[4]),
                                 (DAYS[0], ["停牌", "ST"], [], "FULL_DAY_SUSPENDED", 0))
                settings = json.loads(db.execute("SELECT settings FROM run_info").fetchone()[0])
                case.assertEqual(settings["market_status"], {"tag_version": stock_tags.VERSION, "legacy": False})

    def test_unknown_missing_prices_and_conflicting_halts_remain_missing(self):
        with closing(sqlite3.connect(self.source)) as db, db:
            db.execute("DELETE FROM daily WHERE ts_code=? AND trade_date=?", (CODE, DAYS[1]))
            db.execute("""UPDATE tradable_stock SET tags_unknown='["停牌"]',is_tradable=NULL,
                       data_available=0,reason='NO_DAILY_DATA' WHERE trade_date=?""", (DAYS[1],))
            db.execute("""UPDATE tradable_stock SET tags='["停牌"]',is_tradable=NULL,
                       reason='SUSPENSION_BAR_CONFLICT' WHERE trade_date=?""", (DAYS[2],))
        path, _ = run(Hold(), self.config, self.source, self.root / "out")
        with closing(sqlite3.connect(path)) as db:
            self.assertEqual(db.execute("SELECT equity,valuation_status FROM daily_account WHERE trade_date>?", (DAYS[0],)).fetchall(),
                             [(None, "missing"), (None, "missing")])
            self.assertEqual(db.execute("SELECT status_reason FROM daily_positions WHERE trade_date>?", (DAYS[0],)).fetchall(),
                             [("NO_DAILY_DATA",), ("SUSPENSION_BAR_CONFLICT",)])

    def test_delisting_tag_is_terminal_without_quotes_or_basic_date(self):
        with closing(sqlite3.connect(self.source)) as db, db:
            db.execute("DELETE FROM daily WHERE ts_code=? AND trade_date>?", (CODE, DAYS[0]))
            db.execute("""UPDATE tradable_stock SET tags='["退市"]',is_tradable=0,
                       data_available=0,reason='DELISTED' WHERE trade_date>?""", (DAYS[0],))
        path, _ = run(Hold(), self.config, self.source, self.root / "out")
        with closing(sqlite3.connect(path)) as db:
            equities = [number(r[0]) for r in db.execute("SELECT equity FROM daily_account ORDER BY trade_date")]
            self.assertEqual(equities, [2100, 1000, 1000])
            self.assertEqual(db.execute("SELECT count(*) FROM events WHERE kind='delisting_writeoff'").fetchone()[0], 1)

    def test_quote_code_reuse_does_not_transfer_prices_or_delisting(self):
        new_identity = "600002.SH"
        with closing(sqlite3.connect(self.source)) as db, db:
            db.execute("UPDATE stock_basic SET delist_date=? WHERE ts_code=?", (DAYS[1], CODE))
            db.execute("INSERT INTO stock_basic VALUES(?,NULL)", (new_identity,))
            db.execute("UPDATE tradable_stock SET security_id=?,tags='[\"ST\"]' WHERE trade_date>=?", (new_identity, DAYS[1]))
        with closing(readonly(self.source)) as db:
            market = Market(db, self.config)
            self.assertEqual(market.mark(CODE, CODE, DAYS[1]), (DAYS[1], 0))
            self.assertEqual(market.mark(CODE, new_identity, DAYS[1]), (DAYS[1], 12))
            self.assertEqual(market.frame(DAYS[1])[CODE]["security_id"], new_identity)
            self.assertEqual(market.status(CODE, new_identity, DAYS[0])["tags_unknown"], stock_tags.TAGS)
            self.assertEqual(market.status(CODE, CODE, DAYS[1])["tags"], ("退市",))

    def test_dirty_partial_and_unsupported_snapshots_are_rejected(self):
        for key, value in (("tags_dirty", "1"), ("tag_version", "999")):
            with closing(sqlite3.connect(self.source)) as db, db:
                stock_tags.set_meta(db, "tags_dirty", "0")
                stock_tags.set_meta(db, key, value)
            with self.assertRaises(ValueError):
                snapshot(self.source, self.root / "snapshots")
            self.assertEqual(list((self.root / "snapshots").glob("*.db")), [])
            with self.assertRaises(ValueError):
                run(Hold(), self.config, self.source, self.root / "out")
            self.assertEqual(list((self.root / "out").glob("*.db")), [])
        with closing(sqlite3.connect(self.source)) as db, db:
            stock_tags.set_meta(db, "tag_version", stock_tags.VERSION)
            db.execute("ALTER TABLE tradable_stock DROP COLUMN tags_unknown")
        with self.assertRaisesRegex(ValueError, "incomplete"):
            snapshot(self.source, self.root / "snapshots")

    def test_legacy_status_is_unknown_and_remains_readable(self):
        source = self.root / "legacy.db"
        market_fixture(source)
        with closing(readonly(source)) as db:
            market = Market(db, self.config)
            self.assertIsNone(market.status_data.version)
            self.assertEqual(market.frame(DAYS[0])[CODE]["tags_unknown"], stock_tags.TAGS)
            self.assertEqual(market.mark(CODE, CODE, DAYS[0]), (DAYS[0], 11))


if __name__ == "__main__":
    unittest.main()
