"""Read the historical status contract maintained by stock_tags and daily_tables."""

import json
from functools import lru_cache

from get_data import stock_tags


def tag_version(db):
    """Accept complete tagged snapshots and legacy snapshots without tag columns."""
    columns = [
        {r[1] for r in db.execute(f"PRAGMA table_info({table})")}
        for table in ("daily", "tradable_stock")
    ]
    if stock_tags.get_meta(db, "tags_dirty") == "1":
        raise ValueError("market tags_dirty=1: status rebuild is in progress; use a completed snapshot")
    version = stock_tags.get_meta(db, "tag_version")
    if not version and not any({"tags", "tags_unknown"} & c for c in columns):
        return None
    if not stock_tags.ready(db):
        raise ValueError("incomplete or unsupported market status schema; finish the status migration")
    return version


def decode_tags(confirmed, unknown):
    confirmed, unknown = json.loads(confirmed), json.loads(unknown)
    for values in (confirmed, unknown):
        if not isinstance(values, list) or any(value not in stock_tags.TAGS for value in values):
            raise ValueError("invalid market status tags")
    if set(confirmed) & set(unknown) or {"ST", "*ST"} <= set(confirmed):
        raise ValueError("conflicting market status tags")
    return tuple(confirmed), tuple(unknown)


class StatusData:
    def __init__(self, db):
        self.db = db
        self.version = tag_version(db)
        self.rows = lru_cache(maxsize=3)(self._rows)

    def _rows(self, day):
        rows = self.db.execute(
            """SELECT s.*,c.is_open AS market_open FROM tradable_stock s
            LEFT JOIN market_calendar c ON c.exchange=s.exchange AND c.cal_date=s.trade_date
            WHERE s.trade_date=?""", (day,)
        )
        result = {}
        for row in rows:
            state = dict(row)
            if self.version:
                state["tags"], state["tags_unknown"] = decode_tags(state["tags"], state["tags_unknown"])
            else:
                state["tags"], state["tags_unknown"] = (), stock_tags.TAGS
            state.setdefault("reason", "LEGACY_STATUS")
            state.setdefault("data_available", None)
            result[state["ts_code"]] = state
        return result

    def get(self, code, identity, day):
        state = self.rows(day).get(code)
        if state is not None and state["security_id"] == identity:
            return dict(state)
        exchange = {"SH": "SSE", "SZ": "SZSE", "BJ": "BSE"}.get(code.rsplit(".", 1)[-1])
        calendar = self.db.execute(
            "SELECT is_open FROM market_calendar WHERE exchange=? AND cal_date=?", (exchange, day)
        ).fetchone()
        return {
            "trade_date": day, "ts_code": code, "security_id": identity, "exchange": exchange,
            "is_tradable": None, "data_available": None,
            "reason": "IDENTITY_MISMATCH" if state else "MISSING_STATUS",
            "tags": (), "tags_unknown": stock_tags.TAGS,
            "market_open": calendar[0] if calendar else None,
        }

    def price_tags(self, row):
        """Use qualification-table tags for raw and adjusted historical prices alike."""
        row = dict(row)
        row["tags"], row["tags_unknown"] = decode_tags(row.pop("status_tags"), row.pop("status_unknown"))
        return row

    @property
    def price_columns(self):
        if self.version:
            return "s.tags AS status_tags,s.tags_unknown AS status_unknown"
        return f"'[]' AS status_tags,'{stock_tags.UNKNOWN}' AS status_unknown"
