import json
from decimal import Decimal

from .model import number


class Account:
    def __init__(self, db, cash, day):
        self.db = db
        self.opening_cash = number(cash)
        self.cash = number(cash)
        self.day = day

    def holdings(self):
        return {
            r[0]: r[1]
            for r in self.db.execute("SELECT ts_code,sum(shares) FROM position_lots GROUP BY ts_code")
        }

    def sellable(self, code, identity):
        return self.db.execute(
            """SELECT coalesce(sum(shares),0) FROM position_lots
            WHERE ts_code=? AND security_id=? AND bought<?""",
            (code, identity, self.day),
        ).fetchone()[0]

    def apply(self, order, shares, price):
        buying = order["side"] == "BUY"
        code, identity = order["ts_code"], order["security_id"]
        amount = shares * price
        if buying:
            other = self.db.execute(
                "SELECT 1 FROM position_lots WHERE ts_code=? AND security_id<>?", (code, identity)
            ).fetchone()
            if other:
                return "UNRESOLVED_IDENTITY_CHANGE"
            if amount > self.cash:
                return "INSUFFICIENT_CASH"
            self.db.execute(
                "INSERT INTO position_lots(ts_code,security_id,bought,shares) VALUES(?,?,?,?)",
                (code, identity, self.day, shares),
            )
        else:
            if shares > self.sellable(code, identity):
                return "INSUFFICIENT_SELLABLE"
            remaining = shares
            for lot in self.db.execute(
                """SELECT id,shares FROM position_lots
                    WHERE ts_code=? AND security_id=? AND bought<? ORDER BY id""",
                (code, identity, self.day),
            ).fetchall():
                take = min(remaining, lot["shares"])
                if take == lot["shares"]:
                    self.db.execute("DELETE FROM position_lots WHERE id=?", (lot["id"],))
                else:
                    self.db.execute(
                        "UPDATE position_lots SET shares=shares-? WHERE id=?", (take, lot["id"])
                    )
                remaining -= take
                if not remaining:
                    break
        delta = -amount if buying else amount
        self.cash += delta
        self.db.execute(
            "INSERT INTO cash_ledger(trade_date,order_id,delta) VALUES(?,?,?)",
            (self.day, order["id"], str(delta)),
        )
        self.db.execute(
            """INSERT INTO fills(order_id,trade_date,session,ts_code,side,shares,price,amount)
                         VALUES(?,?,?,?,?,?,?,?)""",
            (
                order["id"],
                self.day,
                order["session"],
                code,
                order["side"],
                shares,
                str(price),
                str(amount),
            ),
        )
        return None

    def reconcile(self):
        flows = self.db.execute("SELECT delta FROM cash_ledger WHERE trade_date=?", (self.day,))
        if self.opening_cash + sum(number(row[0]) for row in flows) != self.cash:
            raise ValueError(f"cash ledger mismatch on {self.day}")

    def mark(self, market):
        total = Decimal(0)
        status = "ok"
        rows = self.db.execute(
            "SELECT ts_code,security_id,sum(shares) FROM position_lots GROUP BY ts_code,security_id"
        )
        for code, identity, shares in rows:
            effective = market.delisted(code, identity, self.day)
            if effective:
                message = f"{code} ({identity}), effective {effective}, {shares} shares valued at zero"
                self.db.execute(
                    """INSERT INTO events(trade_date,kind,message)
                    SELECT ?, 'delisting_writeoff', ? WHERE NOT EXISTS
                    (SELECT 1 FROM events WHERE kind='delisting_writeoff' AND message=?)""",
                    (self.day, message, message),
                )
            state = market.status(code, identity, self.day)
            date, close = market.mark(code, identity, self.day)
            price = number(close) if close is not None else None
            value = shares * price if price is not None else None
            if value is None:
                status = "missing"
            else:
                total += value
                if date != self.day and status == "ok":
                    status = "stale"
            self.db.execute(
                """INSERT INTO daily_positions(trade_date,ts_code,security_id,shares,sellable,
                close,price_date,market_value,tags,tags_unknown,status_reason) VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    self.day,
                    code,
                    identity,
                    shares,
                    self.sellable(code, identity) if state["is_tradable"] == 1 and not effective else 0,
                    str(price) if price is not None else None,
                    date,
                    str(value) if value is not None else None,
                    json.dumps(state["tags"], ensure_ascii=False),
                    json.dumps(state["tags_unknown"], ensure_ascii=False),
                    state["reason"],
                ),
            )
        if status == "missing":
            return None, None, status
        return total, self.cash + total, status
