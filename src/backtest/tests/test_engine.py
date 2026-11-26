"""A hand-priced market where trade timing and rollback change the answer."""

import sqlite3
import json
import unittest
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory

from backtest import (
    Config,
    Field,
    Metric,
    Scenario,
    Strategy,
    add_scenario,
    export_pdf,
    export_html,
    run,
)
from backtest.metrics import Accumulator
from backtest.model import number

DAYS = ("20240102", "20240103", "20240104")
CODE = "600001.SH"


def market_fixture(path):
    with closing(sqlite3.connect(path)) as db:
        db.executescript("""
        CREATE TABLE daily(ts_code,trade_date,open,high,low,close,pre_close,change,pct_chg,vol,amount,ah_vol,ah_amount,
          PRIMARY KEY(ts_code,trade_date));
        CREATE TABLE tradable_stock(ts_code,trade_date,exchange,security_id,is_tradable);
        CREATE TABLE market_calendar(exchange,cal_date,is_open,prev_trade_date);
        CREATE TABLE stock_basic(ts_code PRIMARY KEY,delist_date);
        """)
        previous = "20231229"
        db.execute("INSERT INTO stock_basic VALUES(?,NULL)", (CODE,))
        db.execute("INSERT INTO daily(ts_code,trade_date,close) VALUES('000001.SH',?,100)", (previous,))
        for index, day in enumerate(DAYS):
            db.execute("INSERT INTO market_calendar VALUES('SSE',?,1,?)", (day, previous))
            db.execute("INSERT INTO tradable_stock VALUES(?,?,'SSE',?,1)", (CODE, day, CODE))
            db.execute(
                "INSERT INTO daily(ts_code,trade_date,open,high,low,close) VALUES(?,?,?,?,?,?)",
                (CODE, day, 10 + index, 14, 9, 11 + index),
            )
            db.execute(
                "INSERT INTO daily(ts_code,trade_date,close) VALUES('000001.SH',?,?)", (day, 101 + index)
            )
            previous = day
        db.commit()


class Probe(Strategy):
    fields = {"strategy.age": Field(kind="integer")}
    metrics = {"strategy.days": Metric("记录日数", "日", lambda v: len(v.accounts()))}
    fail = False

    def before_open(self, ctx):
        if ctx.day == DAYS[0]:
            ctx.order(CODE, "BUY", 1)
            try:
                ctx.bars(ctx.day)
            except ValueError:
                pass
            else:
                raise AssertionError("pre-open full bar leak")

    def on_open(self, ctx):
        if ctx.day == DAYS[0]:
            assert len(ctx.trades()) == 1 and ctx.cash == 1000
            ctx.order(CODE, "BUY", 1)
            ctx.order(CODE, "SELL", 1)
            ctx.order(CODE, "BUY", 1)
        elif ctx.day == DAYS[1]:
            ctx.order(CODE, "SELL", 1, "CLOSE", touch_low=9)
            if self.fail:
                raise RuntimeError("simulated interruption")

    def after_close(self, ctx):
        ctx.state["days"] = ctx.state.get("days", 0) + 1
        ctx.record("strategy.age", ctx.state["days"])
        if ctx.day == DAYS[1]:
            ctx.order(CODE, "SELL", 1)
        if ctx.day == DAYS[-1]:
            ctx.order(CODE, "BUY", 1)


class LifecycleTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / "market.db"
        market_fixture(self.source)
        self.config = Config(DAYS[0], DAYS[-1], "2000", exchanges=("SSE",))

    def test_trade_phases_ledger_prefix_metrics_and_report_replay(self):
        path, pdf = run(Probe(), self.config, self.source, self.root / "out")
        self.assertTrue(pdf.read_bytes().startswith(b"%PDF"))
        html = path.with_suffix(".html").read_text()
        payload = html.split('<script id="report-data" type="application/json">')[1].split('</script>')[0]
        report = json.loads(payload)
        self.assertEqual(report["config"]["initial_cash"], "2000")
        self.assertEqual(report["dates"], ["期初", *DAYS])
        self.assertAlmostEqual(report["series"][0][-1], 0.2)
        with closing(sqlite3.connect(path)) as db:
            accounts = db.execute("SELECT cash,equity FROM daily_account ORDER BY trade_date").fetchall()
            self.assertEqual(
                [(number(c), number(e)) for c, e in accounts], [(0, 2200), (1200, 2400), (2400, 2400)]
            )
            self.assertEqual(
                db.execute("SELECT reason FROM orders WHERE status='rejected' ORDER BY id").fetchall(),
                [("INSUFFICIENT_SELLABLE",), ("INSUFFICIENT_CASH",), ("OUTSIDE_INTERVAL",)],
            )
            self.assertEqual(
                db.execute("SELECT trade_date,session FROM fills ORDER BY id").fetchall(),
                [(DAYS[0], "OPEN"), (DAYS[0], "OPEN"), (DAYS[1], "CLOSE"), (DAYS[2], "OPEN")],
            )
            self.assertIsNone(
                db.execute(
                    "SELECT value FROM daily_metrics WHERE trade_date=? AND metric_name='sharpe'",
                    (DAYS[0],),
                ).fetchone()[0]
            )
            self.assertEqual(db.execute("PRAGMA foreign_key_check").fetchall(), [])
        add_scenario(
            path, self.source, Probe(), Scenario("flat", benchmark_returns=dict.fromkeys(DAYS, 0.0))
        )
        with closing(sqlite3.connect(path)) as db:
            self.assertEqual(
                db.execute(
                    "SELECT value FROM daily_metrics WHERE scenario_id='flat' AND metric_name='strategy.days' ORDER BY trade_date"
                ).fetchall(),
                [(1.0,), (2.0,), (3.0,)],
            )
        export_pdf(path, "flat")
        export_html(path, "flat")

    def test_suspension_then_delisting_with_zero_equity_and_retained_shares(self):
        from dataclasses import replace

        class Hold(Strategy):
            def on_open(self, ctx):
                if ctx.day == DAYS[0]:
                    ctx.order(CODE, "BUY", 2)
                if ctx.day >= DAYS[2]:
                    assert CODE not in ctx.universe

        with closing(sqlite3.connect(self.source)) as db:
            db.execute("UPDATE stock_basic SET delist_date=?", (DAYS[2],))
            db.execute("DELETE FROM daily WHERE ts_code=? AND trade_date=?", (CODE, DAYS[1]))
            db.execute("UPDATE tradable_stock SET is_tradable=0 WHERE trade_date=?", (DAYS[1],))
            # A stale positive quote on the delisting date must not override zero valuation.
            db.execute("INSERT INTO market_calendar VALUES('SSE','20240105',1,?)", (DAYS[2],))
            db.execute("INSERT INTO daily(ts_code,trade_date,close) VALUES('000001.SH','20240105',104)")
            db.commit()
        path, _ = run(Hold(), replace(self.config, end="20240105", valuation="last_close"), self.source, self.root / "out")
        with closing(sqlite3.connect(path)) as db:
            accounts = db.execute("SELECT equity,valuation_status FROM daily_account ORDER BY trade_date").fetchall()
            self.assertEqual([(number(e), s) for e, s in accounts],
                             [(2200, "ok"), (2200, "stale"), (0, "ok"), (0, "ok")])
            positions = db.execute(
                "SELECT shares,sellable,close,price_date,market_value FROM daily_positions ORDER BY trade_date"
            ).fetchall()
            self.assertEqual(positions[1][3], DAYS[0])
            self.assertEqual(positions[-1], (200, 0, "0", "20240105", "0"))
            self.assertEqual(db.execute("SELECT count(*) FROM events WHERE kind='delisting_writeoff'").fetchone()[0], 1)
            self.assertEqual(db.execute("SELECT count(*) FROM cash_ledger").fetchone()[0], 2)
            returns = db.execute("SELECT value FROM daily_metrics WHERE metric_name='daily_return' ORDER BY trade_date").fetchall()
            self.assertEqual([round(r[0], 8) for r in returns], [0.1, 0, -1, 0])
            self.assertIsNotNone(db.execute(
                "SELECT value FROM daily_metrics WHERE metric_name='sharpe' AND trade_date='20240105'"
            ).fetchone()[0])

    def test_interrupted_day_rolls_back_and_resume_matches_clean_run(self):
        strategy = Probe()
        strategy.fail = True
        with self.assertRaisesRegex(RuntimeError, "interruption"):
            run(strategy, self.config, self.source, self.root / "partial")
        path = next((self.root / "partial").glob("*.db"))
        with closing(sqlite3.connect(path)) as db:
            self.assertEqual(db.execute("SELECT trade_date FROM daily_account").fetchall(), [(DAYS[0],)])
            self.assertEqual(
                db.execute("SELECT count(*) FROM orders WHERE created=?", (DAYS[1],)).fetchone()[0], 0
            )
        run(Probe(), self.config, self.source, path.parent, resume=path)
        other, _ = run(Probe(), self.config, self.source, self.root / "clean")
        with closing(sqlite3.connect(path)) as db:
            db.execute("ATTACH ? AS clean", (str(other),))
            for table in (
                "daily_account",
                "daily_positions",
                "orders",
                "fills",
                "daily_metrics",
                "strategy_data",
            ):
                for left, right in (("main", "clean"), ("clean", "main")):
                    self.assertFalse(
                        db.execute(
                            f"SELECT * FROM {left}.{table} EXCEPT SELECT * FROM {right}.{table}"
                        ).fetchall()
                    )

    def test_missing_marked_stock_and_fixed_factor_prices(self):
        from dataclasses import replace

        class Hold(Strategy):
            def on_open(self, ctx):
                if ctx.day == DAYS[0]:
                    ctx.order(CODE, "BUY", 1)

        with closing(sqlite3.connect(self.source)) as db:
            db.execute("UPDATE tradable_stock SET is_tradable=0 WHERE trade_date=?", (DAYS[1],))
            db.execute("DELETE FROM daily WHERE ts_code=? AND trade_date=?", (CODE, DAYS[1]))
            db.execute(
                "CREATE TABLE adj_factor(ts_code,trade_date,adj_factor,PRIMARY KEY(ts_code,trade_date))"
            )
            db.executemany("INSERT INTO adj_factor VALUES(?,?,?)", [(CODE, d, 2) for d in DAYS])
            db.commit()
        for valuation in ("strict", "last_close", "suspension"):
            config = replace(self.config, price_basis="adjusted", valuation=valuation)
            path, _ = run(Hold(), config, self.source, self.root / valuation)
            with closing(sqlite3.connect(path)) as db:
                self.assertEqual(number(db.execute("SELECT price FROM fills").fetchone()[0]), 20)
                equity, status = db.execute(
                    "SELECT equity,valuation_status FROM daily_account WHERE trade_date=?", (DAYS[1],)
                ).fetchone()
                if valuation != "last_close":
                    self.assertEqual((equity, status), (None, "missing"))
                else:
                    self.assertEqual((number(equity), status), (2200, "stale"))
                    self.assertEqual(
                        db.execute(
                            "SELECT price_date FROM daily_positions WHERE trade_date=?", (DAYS[1],)
                        ).fetchone()[0],
                        DAYS[0],
                    )

    def test_different_risk_and_benchmark_series_drawdown_and_missing_marks(self):
        state = Accumulator(100.0, 100.0)
        for day, equity, bench, rf in zip(
            DAYS, [110.0, 88.0, 99.0], [0.02, -0.01, 0.02], [0.001, 0.002, 0.003]
        ):
            vals = state.update(day, equity, 100.0, bench, rf, 252)
        from math import sqrt
        from statistics import mean, stdev

        returns = [0.1, -0.2, 0.125]
        active = [0.08, -0.19, 0.105]
        self.assertAlmostEqual(vals["sharpe"][0], sqrt(252) * (mean(returns) - 0.002) / stdev(returns))
        self.assertAlmostEqual(vals["information_ratio"][0], sqrt(252) * mean(active) / stdev(active))
        self.assertEqual(vals["longest_drawdown_days"][0], 2)
        self.assertEqual(vals["max_drawdown_amount"][0], 22)
        missing = state.update("20240105", None, 100.0, 0, 0, 252)
        self.assertIsNone(missing["max_drawdown_amount"][0])
        self.assertIsNotNone(missing["benchmark_return"][0])


if __name__ == "__main__":
    unittest.main()
