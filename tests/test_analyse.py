import json
import sqlite3
import unittest
from contextlib import closing
from dataclasses import replace
from datetime import date, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory

from analyse.baseline import load_baseline
from analyse.permutation import run_permutation
from analyse.segments import run_segments, split_days
from analyse.summary import summarize
from backtest import Config, Strategy, run
from backtest.tests.test_engine import CODE, DAYS, market_fixture


class Ladder(Strategy):
    def on_open(self, ctx):
        age = ctx.state.get("age", 0)
        if age in (0, 1):
            ctx.order(CODE, "BUY", 1)
        if age == 2:
            ctx.order(CODE, "SELL", 1, "CLOSE")
        if age == 3:
            ctx.order(CODE, "SELL", 1)
            ctx.order(CODE, "BUY", 1, "CLOSE")
        ctx.state["age"] = age + 1


def build():
    return Ladder(), Config("20240102", "20240122", "2000", exchanges=("SSE",))


class AnalysisTests(unittest.TestCase):
    def setUp(self):
        temp = TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.snapshot = self.root / "market.db"
        market_fixture(self.snapshot)
        with closing(sqlite3.connect(self.snapshot)) as db, db:
            db.execute("UPDATE daily SET open=10,close=10 WHERE ts_code=? AND trade_date<=?", (CODE, DAYS[1]))
            db.execute("UPDATE daily SET open=20,close=20 WHERE ts_code=? AND trade_date=?", (CODE, DAYS[2]))
            prev = DAYS[-1]
            for i in range(18):
                day = (date(2024,1,5)+timedelta(days=i)).strftime("%Y%m%d")
                db.execute("INSERT INTO market_calendar VALUES('SSE',?,1,?)", (day,prev))
                db.execute("INSERT INTO tradable_stock VALUES(?,?,'SSE',?,1)", (CODE,day,CODE))
                db.execute("INSERT INTO daily(ts_code,trade_date,open,close) VALUES(?,?,?,?)", (CODE,day,18+i,19+i))
                db.execute("INSERT INTO daily(ts_code,trade_date,close) VALUES('000001.SH',?,100)", (day,))
                prev = day

    def baseline(self, strategy, config):
        db, _ = run(strategy, config, self.snapshot, self.root / "original")
        return load_baseline(db, self.snapshot)

    def test_cash_infeasible_same_day_reentry_and_cold_starts(self):
        base = self.baseline(*build())
        rows, settings = run_permutation(base, 16, seed=4)
        self.assertEqual(rows, run_permutation(base, 16, seed=4)[0])
        self.assertEqual(settings["holding_periods"], 2)
        self.assertEqual({r["status"] for r in rows}, {"infeasible", "ok"})
        self.assertTrue(all("20240103" in r["error"] for r in rows if r["status"]=="infeasible"))
        self.assertIsNone(summarize(rows, base.actual, True)[0]["above2"])
        out = self.root / "segments"
        rows = run_segments(base, __file__, out)
        self.assertEqual([r["days"] for r in rows], [3]+[2]*9)
        for row in rows:
            self.assertEqual(row["status"], "ok")
            with closing(sqlite3.connect(out / row["database"])) as db:
                state, = db.execute("SELECT strategy_state FROM daily_account ORDER BY trade_date LIMIT 1").fetchone()
                self.assertEqual(json.loads(state)["age"], 1)
        cfg = replace(base.config, start=rows[2]["start"], end=rows[2]["end"])
        control = self.baseline(Ladder(), cfg)
        self.assertEqual(control.actual["total_return"], rows[2]["total_return"])

    def test_suspension_writeoff_and_zero_equity(self):
        class Hold(Strategy):
            def on_open(self, ctx):
                if ctx.day == DAYS[0]:
                    ctx.order(CODE, "BUY", 2)
        with closing(sqlite3.connect(self.snapshot)) as db, db:
            db.execute("UPDATE stock_basic SET delist_date='20240110'")
            db.execute("UPDATE tradable_stock SET is_tradable=0 WHERE trade_date='20240105'")
            db.execute("DELETE FROM daily WHERE ts_code=? AND trade_date='20240105'", (CODE,))
        base = self.baseline(Hold(), replace(build()[1], valuation="last_close"))
        rows, settings = run_permutation(base, 6)
        self.assertLess(settings["shuffled_days"], 7)
        self.assertTrue(all(r["total_return"] == -1 for r in rows))
        self.assertIsNone(summarize(rows, base.actual, True)[1]["above2"])
        with closing(sqlite3.connect(base.path)) as db, db:
            db.execute("UPDATE daily_account SET cash='9999' WHERE trade_date=?", (DAYS[1],))
        with self.assertRaisesRegex(ValueError, DAYS[1]):
            run_permutation(base, 2)

    def test_calendar_and_upper_limits(self):
        self.assertEqual(list(map(len,split_days(range(20)))), [2]*10)
        with self.assertRaises(ValueError):
            list(split_days(range(9)))
        rows = [dict(status="ok",sharpe=i,total_return=None) for i in (0,1,2)]
        result,missing = summarize(rows,dict(sharpe=3,total_return=None),True)
        self.assertEqual((result["mean"],result["sd"],result["upper2"]),(1,1,3))
        self.assertFalse(result["above2"])
        self.assertEqual(missing["valid"],0)
        self.assertIsNone(missing["mean"])
