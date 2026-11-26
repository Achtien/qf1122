"""Read the frozen stk_limit observations used by a run."""

import sqlite3
from decimal import Decimal
from pathlib import Path

HERE = Path(__file__).resolve().parent
START, END = "20160101", "20260701"
LIMITS = HERE / "limits_20160101_20260701.db"


# Historical identifiers documented and sourced in docs/database/querying.md, section 1.10.
RENAMES = {
    "001872.SZ": ("000022.SZ", "20181226"),
    "001914.SZ": ("000043.SZ", "20191216"),
    "302132.SZ": ("300114.SZ", "20250217"),
}


def historical_code(day, code):
    old, since = RENAMES.get(code, (code, ""))
    return old if day < since else code


class LimitData:
    def __init__(self, path=LIMITS):
        self.db = sqlite3.connect(Path(path).resolve().as_uri() + "?mode=ro", uri=True)

    def day(self, day):
        if not self.db.execute("SELECT 1 FROM batches WHERE kind='day' AND key=?", (day,)).fetchone():
            raise ValueError(f"missing stk_limit day {day}; run prepare_run_limits.py")
        values = {
            code: Decimal(up) if up else None
            for code, up in self.db.execute(
                "SELECT ts_code,up_limit FROM limits WHERE trade_date=?", (day,)
            )
        }

        for code in RENAMES:
            old = historical_code(day, code)
            if old in values:
                values[code] = values[old]
        return values

    def lower(self, day, code):
        old = historical_code(day, code)
        if (
            old != code
            and self.db.execute(
                "SELECT 1 FROM limits WHERE trade_date=? AND ts_code=?", (day, old)
            ).fetchone()
        ):
            code = old
        row = self.db.execute(
            "SELECT down_limit FROM limits WHERE trade_date=? AND ts_code=?", (day, code)
        ).fetchone()
        if row is None:
            raise ValueError(f"missing stk_limit for {code} on {day}")
        return Decimal(row[0]) if row[0] else None
