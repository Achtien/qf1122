"""Shuffle full holding-day price relatives within each continuous position."""

import random
import sys
from collections import defaultdict
from contextlib import closing
from dataclasses import dataclass, field
from decimal import Decimal, localcontext

from backtest.data import Market, readonly
from backtest.metrics import Accumulator
from backtest.model import number
from .baseline import METRICS
from .summary import tied


@dataclass(frozen=True)
class Quote:
    previous: Decimal
    opening: Decimal | None
    closing: Decimal

    def at(self, previous):
        # Preserve exact recorded marks on the identity path, including after write-off.
        if previous == self.previous:
            return self.opening, self.closing
        scale = previous / self.previous
        return (None if self.opening is None else scale * self.opening), scale * self.closing


@dataclass
class Holding:
    code: str
    identity: str
    entry: Decimal
    previous: Decimal
    shares: int = 0
    prior_regular: bool = True
    pool: list = field(default_factory=list)


@dataclass
class Day:
    date: str
    cash: Decimal
    equity: Decimal
    # (holding index, quote index, ending shares) and (holding index, fill)
    marks: list
    trades: list


def grouped(db, sql):
    groups = defaultdict(list)
    for row in db.execute(sql):
        groups[row["trade_date"]].append(row)
    return groups


def build_plan(baseline):
    with closing(readonly(baseline.path)) as db, closing(readonly(baseline.snapshot)) as src:
        market = Market(src, baseline.config)
        positions = grouped(db, "SELECT * FROM daily_positions ORDER BY trade_date,security_id")
        fills = grouped(db, """SELECT f.*, o.security_id, l.delta FROM fills f
                            JOIN orders o ON o.id=f.order_id LEFT JOIN cash_ledger l ON l.order_id=o.id
                            ORDER BY f.trade_date, CASE f.session WHEN 'OPEN' THEN 0 ELSE 1 END, f.id""")
        accounts = db.execute("SELECT * FROM daily_account ORDER BY trade_date")
        active, holdings, quotes, timeline = {}, [], [], []
        for account in accounts:
            day = account["trade_date"]
            started, exits, trades = set(), {}, []
            touched = list(active.values())
            for trade in fills[day]:
                key = trade["ts_code"], trade["security_id"]
                if key not in active:
                    if trade["side"] != "BUY":
                        raise ValueError(f"{day} 持仓不足 {key}")
                    price = number(trade["price"])
                    index = len(holdings)
                    holdings.append(Holding(*key, entry=price, previous=price))
                    active[key] = index
                    started.add(index)
                    touched.append(index)
                index = active[key]
                sign = 1 if trade["side"] == "BUY" else -1
                if trade["delta"] is None or number(trade["delta"]) != -sign * number(trade["amount"]):
                    raise ValueError(f"{day} 成交与现金流水不符 #{trade['id']}")
                holdings[index].shares += sign * trade["shares"]
                if holdings[index].shares < 0:
                    raise ValueError(f"{day} 持仓股数为负 {key}")
                if holdings[index].shares == 0:
                    exits[index] = trade
                    del active[key]
                trades.append((index, trade))
            recorded = {(r["ts_code"], r["security_id"]): r for r in positions[day]}
            if recorded.keys() != active.keys():
                raise ValueError(f"{day} 收盘持仓身份不符")
            marks = []
            for index in touched:
                h = holdings[index]
                # Look up only the exposed security instead of loading the entire cross-section.
                bar = src.execute(
                    f"""SELECT d.open,d.close FROM tradable_stock s JOIN {market.table} d
                        USING(trade_date,ts_code) WHERE s.trade_date=? AND s.ts_code=?
                        AND s.security_id=? AND s.is_tradable=1""", (day, h.code, h.identity)
                ).fetchone()
                opening = number(bar["open"]) if bar and bar["open"] and bar["open"] > 0 else None
                exit_trade = exits.get(index)
                if exit_trade is None:
                    row = recorded[h.code, h.identity]
                    price_date, close = market.mark(h.code, h.identity, day)
                    if close is None or row["close"] is None:
                        raise ValueError(f"{day} {h.code} 缺少持仓估值")
                    closing_price = number(close)
                    if (h.shares != row["shares"] or number(row["close"]) != closing_price
                            or row["price_date"] != price_date):
                        raise ValueError(f"{day} {h.code} 股数或估值与快照不符")
                else:
                    price_date = day
                    quote = opening if exit_trade["session"] == "OPEN" else (bar["close"] if bar else None)
                    if quote is None:
                        raise ValueError(f"{day} {h.code} 缺少平仓报价")
                    closing_price = number(quote)
                regular = price_date == day and closing_price > 0 and opening is not None
                full = index not in started and (exit_trade is None or exit_trade["session"] == "CLOSE")
                if full and regular and h.prior_regular:
                    h.pool.append(len(quotes))
                quotes.append(Quote(h.previous, opening, closing_price))
                marks.append((index, len(quotes) - 1, h.shares))
                h.previous, h.prior_regular = closing_price, regular
            timeline.append(Day(day, number(account["cash"]), number(account["equity"]), marks, trades))
    return timeline, holdings, quotes


def replay(baseline, timeline, holdings, path, *, audit=False):
    cash = number(baseline.config.initial_cash)
    initial = float(cash)
    state = Accumulator(initial, initial)
    previous = [h.entry for h in holdings]
    for day in timeline:
        prices = {}
        value = Decimal(0)
        for index, slot, shares in day.marks:
            opening, close = path[slot].at(previous[index])
            prices[index] = opening, close
            previous[index] = close
            value += shares * close
        for index, trade in day.trades:
            price = prices[index][0 if trade["session"] == "OPEN" else 1]
            amount = price * trade["shares"]
            if audit and amount != number(trade["amount"]):
                raise ValueError(f"{day.date} 成交金额不符 #{trade['id']}")
            cash += amount if trade["side"] == "SELL" else -amount
            if cash < 0:
                # Multiplication of permuted Decimal ratios has finite precision.
                if abs(cash) <= Decimal("1e-35") * max(amount, 1):
                    cash = Decimal(0)
                else:
                    return dict(status="infeasible", error=f"{day.date} {trade['ts_code']} 成交 #{trade['id']} 现金不足")
        equity = cash + value
        if audit and (cash != day.cash or equity != day.equity):
            raise ValueError(f"{day.date} 现金或总资本未能还原")
        metrics = state.update(day.date, float(equity), initial, None, baseline.rf[day.date],
                               baseline.scenario.periods)
    result = dict(status="ok")
    for key in METRICS:
        result[key], result[key + "_reason"] = metrics[key][:2]
    return result


def run_permutation(baseline, n=1000, seed=0):
    if n < 2:
        raise ValueError("置换次数至少为 2")
    timeline, holdings, quotes = build_plan(baseline)
    pools = [h.pool for h in holdings if len(h.pool) > 1]
    actual = replay(baseline, timeline, holdings, quotes, audit=True)
    for key in METRICS:
        x, y = actual.get(key), baseline.actual[key]
        if ((x is None) != (y is None) or (x is not None and not tied(x, y))
                or actual.get(key + "_reason") != baseline.actual[key + "_reason"]
                or actual["status"] != "ok"):
            raise ValueError(f"原顺序回放末日 {key} 不一致")
    with localcontext() as ctx:
        ctx.prec = 60
        results = []
        for index in range(1, n + 1):
            rng = random.Random(f"{seed}/{index}")
            path = quotes.copy()
            for pool in pools:
                sampled = [quotes[slot] for slot in pool]
                rng.shuffle(sampled)
                for slot, quote in zip(pool, sampled):
                    path[slot] = quote
            results.append(dict(index=index, **replay(baseline, timeline, holdings, path)))
    return results, dict(n=n, seed=seed, rng="Python random.Random (MT19937), seed/index",
                         python=sys.version.split()[0], holding_periods=len(holdings),
                         shuffled_periods=len(pools), shuffled_days=sum(map(len, pools)),
                         audited_days=len(timeline))
