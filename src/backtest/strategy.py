"""The supported strategy interface; strategy modules are trusted Python code."""

import json
from math import isfinite
from types import MappingProxyType

from .model import date_key, number


class Context:
    def __init__(self, broker, market, strategy, state):
        self._broker = broker
        self._db = broker.db
        self._market = market
        self._day = broker.day
        self._strategy = strategy
        self._state = state
        self._phase = None
        self.universe = frozenset(broker.frame)

    @property
    def state(self):
        return self._state

    @property
    def day(self):
        return self._day

    @property
    def phase(self):
        return self._phase

    @property
    def previous_day(self):
        return self._market.prev[self.day]

    @property
    def cash(self):
        return self._broker.account.cash

    @property
    def lot_size(self):
        return self._broker.lot_size

    @property
    def positions(self):
        return MappingProxyType(self._broker.account.holdings())

    def sellable(self, code):
        identity = self._broker.frame.get(code, {}).get("security_id")
        return self._broker.account.sellable(code, identity)

    def open_price(self, code):
        if self.phase not in ("on_open", "after_close", "settlement"):
            raise ValueError("open price is unavailable before open")
        value = self._broker.frame[code]["open"]
        return number(value) if value is not None else None

    def _completed_date(self, date):
        if date_key(date) > self.day or (
            date == self.day and self.phase not in ("after_close", "settlement")
        ):
            raise ValueError("full bar is outside the current phase")

    def bars(self, date):
        """Complete confirmed cross-section on date, restricted to today's security identities."""
        self._completed_date(date)
        return {
            code: dict(row)
            for code, row in self._market.frame(date).items()
            if code in self.universe and self._broker.frame[code]["security_id"] == row["security_id"]
        }

    def history(self, code, start, end):
        self._completed_date(end)
        if date_key(start) > end:
            raise ValueError("reversed history interval")
        identity = self._broker.frame[code]["security_id"]
        return self._market.history(code, identity, start, end)

    def status(self, code, date=None):
        """Historical status for a current eligible or held security, including no-bar days."""
        date = self.day if date is None else date_key(date)
        if date > self.day:
            raise ValueError("status date is in the future")
        holding = self._db.execute(
            "SELECT security_id FROM position_lots WHERE ts_code=? LIMIT 1", (code,)
        ).fetchone()
        identity = holding[0] if holding else self._broker.frame[code]["security_id"]
        return self._market.status(code, identity, date)

    def statuses(self, date=None):
        """Status cross-section for today's universe and held securities."""
        date = self.day if date is None else date_key(date)
        if date > self.day:
            raise ValueError("status date is in the future")
        return {code: self.status(code, date) for code in sorted(self.universe | self.positions.keys())}

    def order(self, code, side, lots, session="OPEN", *, touch_low=None):
        return self._broker.submit(self.phase, side, code, lots, session, touch_low)

    def cancel(self, order_id):
        if self.phase not in ("before_open", "on_open", "after_close"):
            raise ValueError("orders require an active trading callback")
        return bool(
            self._db.execute(
                "UPDATE orders SET status='cancelled' WHERE id=? AND status='pending'", (order_id,)
            ).rowcount
        )

    def trades(self):
        return [dict(row) for row in self._db.execute("SELECT * FROM fills ORDER BY id")]

    def orders(self):
        return [dict(row) for row in self._db.execute("SELECT * FROM orders ORDER BY id")]

    def accounts(self):
        return [dict(row) for row in self._db.execute("SELECT * FROM daily_account ORDER BY trade_date")]

    def record(self, key, value, code=None):
        if self.phase not in ("before_open", "on_open", "after_close"):
            raise ValueError("record requires a trading callback")
        field = self._strategy.fields[key]
        if (field.scope == "position") != (code is not None):
            raise ValueError("stock code required only for position data")
        if code is not None and code not in self.universe and code not in self.positions:
            raise KeyError(code)
        types = {"integer": (int,), "number": (float, int), "boolean": (bool,), "text": (str,)}
        if field.kind == "json":
            value = json.dumps(value, ensure_ascii=False, allow_nan=False)
        elif type(value) not in types[field.kind] or (field.kind == "number" and not isfinite(value)):
            raise ValueError(f"invalid value for {key}")
        self._db.execute(
            """INSERT INTO strategy_data VALUES(?,?,?,?) ON CONFLICT(trade_date,key,ts_code)
                          DO UPDATE SET value=excluded.value""",
            (self.day, key, code or "", value),
        )

    def observations(self, key):
        return [
            dict(row)
            for row in self._db.execute(
                "SELECT trade_date,ts_code,value FROM strategy_data WHERE key=? ORDER BY trade_date,ts_code",
                (key,),
            )
        ]
