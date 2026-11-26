"""Audit the demonstration from raw inputs independently of the backtest package."""

import argparse
import csv
import gzip
import json
import math
import sqlite3
from contextlib import closing
from decimal import Decimal
from pathlib import Path
from statistics import mean, stdev

from limit_data import LimitData
from input_data import StrategyData

RISK_TAGS = {"ST", "*ST"}


def read_db(path):
    return sqlite3.connect(Path(path).resolve().as_uri() + "?mode=ro", uri=True)


def money(value):
    return Decimal(str(value))


def audit(src, result):
    (cfg,) = result.execute("SELECT config FROM run_info").fetchone()
    cfg = json.loads(cfg)
    cash = money(cfg["initial_cash"])
    initial = cash
    settings = json.loads(result.execute("SELECT settings FROM run_info").fetchone()[0])
    rank_by_cap = "market_cap" in settings["parameters"]
    tagged = bool(settings.get("market_status", {}).get("tag_version"))
    if rank_by_cap:
        name = next(name for name in settings["inputs"] if name.startswith("inputs_non_st_smallest_cap_"))
        limits = StrategyData(Path(__file__).with_name(name))
        upper_on, lower_on = limits.day, limits.lower
    elif "limits.csv.gz" in settings["inputs"]:
        legacy = {}
        with gzip.open(Path(__file__).with_name("limits.csv.gz"), "rt") as stream:
            for r in csv.DictReader(stream):
                legacy.setdefault(r["trade_date"], {})[r["ts_code"]] = tuple(
                    money(r[k]) if r[k] else None for k in ("up_limit", "down_limit")
                )
        upper_on = lambda date: {code: pair[0] for code, pair in legacy[date].items()}
        lower_on = lambda date, code: legacy[date][code][1]
    else:
        limits = LimitData()
        upper_on, lower_on = limits.day, limits.lower
    expected = []
    original_index = None
    prior_equity = peak = cash
    max_loss = Decimal(0)
    duration = longest = 0
    path_complete = True
    return_path_complete = True
    returns, active = [], []
    held, held_identity, shares, exit_next = None, None, 0, False
    days = src.execute(
        """SELECT cal_date,prev_trade_date FROM market_calendar WHERE exchange='SSE' AND is_open=1
        AND cal_date BETWEEN ? AND ? ORDER BY cal_date""",
        (cfg["start"], cfg["end"]),
    ).fetchall()
    for day, prior in days:
        universe = {
            r[0]: r[1:]
            for r in src.execute(
                """SELECT s.ts_code,d.open,d.low,d.close
            FROM tradable_stock s JOIN daily d USING(trade_date,ts_code)
            WHERE s.trade_date=? AND s.is_tradable=1""",
                (day,),
            )
        }
        identities = dict(src.execute(
            "SELECT ts_code,security_id FROM tradable_stock WHERE trade_date=?", (day,)
        ))
        states = {}
        if tagged or rank_by_cap:
            states = {
                code: (json.loads(tags), json.loads(unknown), tradable, exchange)
                for code, tags, unknown, tradable, exchange in src.execute(
                    "SELECT ts_code,tags,tags_unknown,is_tradable,exchange FROM tradable_stock WHERE trade_date=?",
                    (day,),
                )
            }
        if rank_by_cap and held and identities.get(held) == held_identity:
            if RISK_TAGS.intersection(states[held][0]):
                exit_next = True

        def sale(session, price):
            nonlocal cash, held, shares, exit_next
            expected.append((day, session, held, "SELL", shares, price))
            cash += shares * price
            held, shares, exit_next = None, 0, False

        if held in universe and identities.get(held) == held_identity:
            price = money(universe[held][0])
            lower = None if exit_next else lower_on(day, held)
            if exit_next or (lower and price <= lower):
                sale("OPEN", price)
        if held is None:
            closes = src.execute(
                """SELECT d.ts_code,d.close,s.security_id FROM daily d JOIN tradable_stock s USING(trade_date,ts_code)
                WHERE d.trade_date=? AND s.is_tradable=1""",
                (prior,),
            )
            uppers = upper_on(prior)
            eligible = {}
            for code, close, identity in closes:
                if code not in universe or identities.get(code) != identity:
                    continue
                if rank_by_cap and (
                    RISK_TAGS.intersection(states[code][0]) or RISK_TAGS.intersection(states[code][1])
                ):
                    continue
                if uppers[code] and money(close) == uppers[code]:
                    eligible[code] = money(universe[code][0])
            if eligible:
                ranks = limits.market_caps(prior, eligible) if rank_by_cap else eligible
                code = min(eligible, key=lambda candidate: (ranks[candidate], candidate))
                price = eligible[code]
                qty = int(cash // (price * cfg["lot_size"])) * cfg["lot_size"]
                if qty:
                    held, shares = code, qty
                    (held_identity,) = src.execute(
                        "SELECT security_id FROM tradable_stock WHERE trade_date=? AND ts_code=?",
                        (day, code),
                    ).fetchone()
                    expected.append((day, "OPEN", code, "BUY", qty, price))
                    cash -= qty * price
                    lower = lower_on(day, code)
                    exit_next = bool(lower and money(universe[code][1]) <= lower)
        elif held in universe and identities.get(held) == held_identity:
            lower = lower_on(day, held)
            if lower and money(universe[held][1]) <= lower:
                sale("CLOSE", money(universe[held][2]))
        carry = cfg.get("valuation") == "last_close"
        state = states.get(held) if identities.get(held) == held_identity else None
        if held and cfg.get("valuation") == "suspension":
            exchange = {"SH": "SSE", "SZ": "SZSE", "BJ": "BSE"}[held.rsplit(".", 1)[-1]]
            calendar = src.execute(
                "SELECT is_open FROM market_calendar WHERE exchange=? AND cal_date=?", (exchange, day)
            ).fetchone()
            carry = bool(state and "停牌" in state[0] and state[2] == 0) or bool(calendar and calendar[0] == 0)
        operator = "<=" if carry else "="
        qualification = "AND s.is_tradable=1" if tagged else ""
        mark = (
            src.execute(
                "SELECT d.close FROM daily d JOIN tradable_stock s USING(trade_date,ts_code) "
                f"WHERE d.trade_date{operator}? AND d.ts_code=? AND s.security_id=? AND d.close>0 "
                f"{qualification} ORDER BY d.trade_date DESC LIMIT 1",
                (day, held, held_identity),
            ).fetchone()
            if held
            else None
        )
        if held and "delisting" in settings:
            if "market_status" in settings:
                ended = src.execute(
                    "SELECT 1 FROM stock_basic WHERE ts_code=? AND delist_date<>'' AND delist_date<=?",
                    (held_identity, day),
                ).fetchone() or bool(state and "退市" in state[0])
            else:
                ended = src.execute(
                    "SELECT 1 FROM stock_basic WHERE ts_code IN (?,?) AND delist_date<>'' AND delist_date<=?",
                    (held, held_identity, day),
                ).fetchone()
            if ended:
                mark = (0,)
        equity = cash if not held else (cash + shares * money(mark[0]) if mark else None)
        balance = result.execute(
            "SELECT cash,equity FROM daily_account WHERE trade_date=?", (day,)
        ).fetchone()
        assert (money(balance[0]), money(balance[1]) if balance[1] is not None else None) == (
            cash,
            equity,
        ), day
        stock = dict(
            result.execute("SELECT ts_code,shares FROM daily_positions WHERE trade_date=?", (day,))
        )
        assert stock == ({held: shares} if held else {}), (day, stock)

        indices = dict(
            src.execute(
                "SELECT trade_date,close FROM daily WHERE ts_code='000001.SH' AND trade_date IN (?,?)",
                (day, prior),
            )
        )
        if original_index is None:
            original_index = indices[prior]
        if equity is None or (not prior_equity and equity != 0):
            return_path_complete = False
        elif return_path_complete:
            returns.append(float(equity / prior_equity - 1) if prior_equity else 0.0)
            active.append(returns[-1] - (indices[day] / indices[prior] - 1))
        prior_equity = equity
        if equity is None:
            path_complete = False
        if path_complete:
            peak = max(peak, equity)
            max_loss = max(max_loss, peak - equity)
            duration = duration + 1 if peak > equity else 0
            longest = max(longest, duration)
        total = float(equity / initial - 1) if equity is not None else None
        reference = indices[day] / original_index - 1
        metrics = dict(
            result.execute(
                "SELECT metric_name,value FROM daily_metrics WHERE scenario_id='default' AND trade_date=?",
                (day,),
            )
        )
        checks = dict(
            total_return=total,
            benchmark_return=reference,
            excess_return=total - reference if total is not None else None,
            max_drawdown_amount=float(max_loss) if path_complete else None,
            longest_drawdown_days=longest if path_complete else None,
        )
        for key, series in (("sharpe", returns), ("information_ratio", active)):
            if return_path_complete and len(series) > 1 and stdev(series):
                checks[key] = math.sqrt(252) * mean(series) / stdev(series)
            else:
                assert metrics[key] is None
        for key, value in checks.items():
            if value is None:
                assert metrics[key] is None, (day, key)
                continue
            assert math.isclose(metrics[key], value, rel_tol=1e-9, abs_tol=1e-10), (
                day,
                key,
                value,
                metrics[key],
            )
    fills = [
        (*r[:-1], money(r[-1]))
        for r in result.execute(
            "SELECT trade_date,session,ts_code,side,shares,price FROM fills ORDER BY id"
        )
    ]
    assert fills == expected
    assert not result.execute("PRAGMA foreign_key_check").fetchall()
    print(f"Verified {len(days)} daily accounts, positions and metric series, {len(fills)} fills.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("snapshot")
    parser.add_argument("result")
    args = parser.parse_args()
    with closing(read_db(args.snapshot)) as market, closing(read_db(args.result)) as result:
        audit(market, result)
