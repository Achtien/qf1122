"""Frozen limit prices and previous-day total market capitalizations for version 2."""

from decimal import Decimal
from pathlib import Path

from limit_data import END, START, LimitData, historical_code

INPUTS = Path(__file__).with_name(f"inputs_non_st_smallest_cap_{START}_{END}.db")


class StrategyData(LimitData):
    def __init__(self, path=INPUTS):
        if not Path(path).is_file():
            raise FileNotFoundError(
                f"missing strategy inputs {path}; prepare them with "
                "prepare_run_limits.py --snapshot <market_snapshot.db>"
            )
        super().__init__(path)

    def market_caps(self, day, codes):
        """Return total_mv in 10,000 CNY for exactly this completed trading day."""
        if not self.db.execute(
            "SELECT 1 FROM batches WHERE kind='market_cap' AND key=?", (day,)
        ).fetchone():
            raise ValueError(f"missing daily_basic batch on {day}; run prepare_run_limits.py")
        values = dict(self.db.execute(
            "SELECT ts_code,total_mv FROM market_caps WHERE trade_date=?", (day,)
        ))
        result = {}
        for code in codes:
            source_code = historical_code(day, code)
            value = values.get(source_code, values.get(code))
            if value is None:
                raise ValueError(f"missing total_mv for candidate {code} on {day}")
            value = Decimal(str(value))
            if not value.is_finite() or value <= 0:
                raise ValueError(f"invalid total_mv for candidate {code} on {day}")
            result[code] = value
        return result
