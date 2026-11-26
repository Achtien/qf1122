"""Buy yesterday's non-ST limit-up stock with the smallest total market cap.

Rank by the previous trading day's total_mv, then by code. Buy the maximum
whole-lot position at today's open. Exit on the first limit-down touch or a
confirmed ST/*ST label, carrying the exit signal through suspension and T+1.
The CLI calls prepare(snapshot_path) to create missing frozen inputs before build().
"""

import sys
from decimal import Decimal
from pathlib import Path

from backtest import Config, Field, Metric, Strategy

sys.path.insert(0, str(Path(__file__).resolve().parent))
from limit_data import END, START
from input_data import INPUTS, StrategyData


RISK_TAGS = frozenset({"ST", "*ST"})


class SmallestCapLimitUp(Strategy):
    version = "2"
    input_files = (
        INPUTS,
        Path(__file__).with_name("limit_data.py"),
        Path(__file__).with_name("input_data.py"),
    )
    parameters = {
        "selection": "previous close at up_limit; rank by previous total_mv, then code",
        "market_cap": "daily_basic.total_mv; previous trading day; unit 10000 CNY",
        "entry_risk": "entry-day ST and *ST must both be confirmed absent",
        "exit": "first down_limit touch or confirmed ST/*ST; OPEN or resting CLOSE; T+1",
    }
    fields = {
        "strategy.candidates": Field(kind="integer", unit="只"),
        "strategy.selected": Field(kind="text"),
        "strategy.selected_total_mv": Field(kind="number", unit="万元"),
        "strategy.exit_signal": Field(kind="text"),
        "strategy.exit_reason": Field(kind="text"),
    }
    metrics = {"strategy.fills": Metric("累计成交笔数", "笔", lambda v: len(v.trades()))}

    def __init__(self, data=None):
        self.data = data if data is not None else StrategyData()

    def remember_exit(self, ctx, code, reason):
        if ctx.state.get("exit_due") != code:
            ctx.state["exit_due"] = code
            ctx.state["exit_reason"] = reason
        ctx.record("strategy.exit_signal", code)
        ctx.record("strategy.exit_reason", ctx.state["exit_reason"])

    def before_open(self, ctx):
        for code in ctx.positions:
            if RISK_TAGS.intersection(ctx.status(code)["tags"]):
                self.remember_exit(ctx, code, "ST_OR_STAR_ST")
        # Persist either exit condition through suspended days until the stock is sellable.
        pending = ctx.state.get("exit_due")
        if pending in ctx.positions and pending in ctx.universe:
            qty = ctx.sellable(pending) // ctx.lot_size
            if qty:
                ctx.order(pending, "SELL", qty)

    def on_open(self, ctx):
        for code in ctx.positions:
            if code not in ctx.universe or ctx.state.get("exit_due") == code:
                continue
            lower = self.data.lower(ctx.day, code)
            qty = ctx.sellable(code) // ctx.lot_size
            if qty and lower:
                if ctx.open_price(code) <= lower:
                    self.remember_exit(ctx, code, "LIMIT_DOWN")
                    ctx.order(code, "SELL", qty)
                else:
                    # Known trigger and quantity. The engine checks the low at close.
                    ctx.order(code, "SELL", qty, "CLOSE", touch_low=lower)
        if ctx.positions:
            return

        ctx.state.pop("exit_due", None)
        ctx.state.pop("exit_reason", None)
        prior = self.data.day(ctx.previous_day)
        eligible = {}
        for code, bar in ctx.bars(ctx.previous_day).items():
            status = ctx.status(code)
            if RISK_TAGS.intersection(status["tags"]) or RISK_TAGS.intersection(status["tags_unknown"]):
                continue
            upper = prior[code]
            if upper and Decimal(str(bar["close"])) == upper:
                price = ctx.open_price(code)
                if price is not None and price > 0:
                    eligible[code] = price
        ctx.record("strategy.candidates", len(eligible))
        if eligible:
            market_caps = self.data.market_caps(ctx.previous_day, eligible)
            code = min(eligible, key=lambda candidate: (market_caps[candidate], candidate))
            price = eligible[code]
            lots = int(ctx.cash // (price * ctx.lot_size))
            if lots:
                ctx.record("strategy.selected", code)
                ctx.record("strategy.selected_total_mv", float(market_caps[code]))
                ctx.order(code, "BUY", lots)

    def after_close(self, ctx):
        for trade in ctx.trades():
            if trade["trade_date"] == ctx.day and trade["side"] == "SELL" and trade["session"] == "CLOSE":
                ctx.record("strategy.exit_signal", trade["ts_code"])
                ctx.record("strategy.exit_reason", "LIMIT_DOWN")
        # A purchase-day touch cannot be sold until a subsequent tradable open.
        for code in ctx.positions:
            if RISK_TAGS.intersection(ctx.status(code)["tags"]):
                self.remember_exit(ctx, code, "ST_OR_STAR_ST")
            if code not in ctx.universe:
                continue
            lower = self.data.lower(ctx.day, code)
            if lower and Decimal(str(ctx.history(code, ctx.day, ctx.day)[0]["low"])) <= lower:
                self.remember_exit(ctx, code, "LIMIT_DOWN")


def make_config():
    return Config(
        START, END, initial_cash="200000", report_metrics=Config.report_metrics + ("strategy.fills",)
    )


def prepare(snapshot_path):
    """Create missing inputs when invoked by a fresh backtest CLI run."""
    if INPUTS.is_file():
        return
    from prepare_run_limits import prepare_inputs

    print("首次运行，正在准备历史涨跌停价和总市值，完成后将开始正式回测。", flush=True)
    prepare_inputs(snapshot_path, SmallestCapLimitUp, make_config())


def build():
    return SmallestCapLimitUp(), make_config()
