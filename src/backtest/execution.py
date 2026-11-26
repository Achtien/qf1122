from .model import number


class Broker:
    def __init__(self, db, market, account, frame, next_day):
        self.db, self.account, self.frame = db, account, frame
        self.lot_size = market.config.lot_size
        self.day, self.next_day = account.day, next_day

    def submit(self, phase, side, code, lots, session, touch_low=None):
        if phase not in {"before_open", "on_open", "after_close"}:
            raise ValueError("orders require an active trading callback")
        if side not in ("BUY", "SELL") or session not in ("OPEN", "CLOSE"):
            raise ValueError("invalid side or session")
        if type(lots) is not int or not 0 < lots <= (2**63 - 1) // self.lot_size:
            raise ValueError("lots must be a positive integer within SQLite range")
        if touch_low is not None and (side != "SELL" or session != "CLOSE" or number(touch_low) <= 0):
            raise ValueError("a low trigger requires a positive threshold and SELL/CLOSE")
        target = self.next_day if phase == "after_close" else self.day
        identity = self.frame.get(code, {}).get("security_id")
        reason = "OUTSIDE_INTERVAL" if target is None else None
        if identity is None:
            reason = "OUTSIDE_UNIVERSE"
        order_id = self.db.execute(
            """INSERT INTO orders(created,phase,target,session,ts_code,security_id,
            side,lots,touch_low,status,reason) VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
            (
                self.day,
                phase,
                target,
                session,
                code,
                identity,
                side,
                lots,
                str(touch_low) if touch_low is not None else None,
                "rejected" if reason else "pending",
                reason,
            ),
        ).lastrowid
        if reason:
            self.db.execute(
                "INSERT INTO events(trade_date,kind,message) VALUES(?,?,?)",
                (self.day, "order_rejected", f"{order_id}: {reason}"),
            )
        elif phase == "on_open" and session == "OPEN":
            self.execute(order_id)
        return order_id

    def execute(self, order_id):
        order = self.db.execute(
            "SELECT * FROM orders WHERE id=? AND status='pending'", (order_id,)
        ).fetchone()
        bar = self.frame.get(order["ts_code"])
        status, reason = "filled", None
        if not bar or bar["security_id"] != order["security_id"]:
            reason = "NOT_TRADABLE"
        elif order["touch_low"] is not None and bar["low"] is None:
            reason = "MISSING_LOW"
        elif order["touch_low"] is not None and number(bar["low"]) > number(order["touch_low"]):
            status = "expired"
        elif not bar[order["session"].lower()] or bar[order["session"].lower()] <= 0:
            reason = "MISSING_PRICE"
        else:
            reason = self.account.apply(
                order, order["lots"] * self.lot_size, number(bar[order["session"].lower()])
            )
        if reason:
            status = "rejected"
            self.db.execute(
                "INSERT INTO events(trade_date,kind,message) VALUES(?,?,?)",
                (self.day, "order_rejected", f"{order_id}: {reason}"),
            )
        self.db.execute("UPDATE orders SET status=?,reason=? WHERE id=?", (status, reason, order_id))

    def match(self, session):
        due = self.db.execute(
            "SELECT id FROM orders WHERE target=? AND session=? AND status='pending' ORDER BY id",
            (self.day, session),
        ).fetchall()
        for order in due:
            self.execute(order[0])
