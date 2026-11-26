"""Public configuration and extension declarations."""

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from math import isfinite


def number(value):
    value = Decimal(str(value))
    if not value.is_finite():
        raise ValueError("expected a finite decimal")
    return value


def date_key(day):
    if datetime.strptime(day, "%Y%m%d").strftime("%Y%m%d") != day:
        raise ValueError(f"invalid date: {day}")
    return day


@dataclass(frozen=True)
class Scenario:
    name: str = "default"
    benchmark: str | None = "000001.SH"
    annual_rf: float = 0.0
    periods: int = 252
    benchmark_returns: dict | None = None
    daily_rf: dict | None = None
    parameters: dict = field(default_factory=dict)

    def __post_init__(self):
        if not self.name or self.periods <= 0 or not isfinite(self.annual_rf) or self.annual_rf <= -1:
            raise ValueError("invalid metric scenario")
        for series in (self.benchmark_returns, self.daily_rf):
            for day, value in (series or {}).items():
                date_key(day)
                if not isfinite(value) or value < -1:
                    raise ValueError(f"invalid return on {day}")


@dataclass(frozen=True)
class Config:
    start: str
    end: str
    initial_cash: str = "1000000"
    lot_size: int = 100
    exchanges: tuple = ("SSE", "SZSE", "BSE")
    price_basis: str = "raw"
    valuation: str = "suspension"
    scenarios: tuple = field(default_factory=lambda: (Scenario(),))
    report_scenario: str = "default"
    report_metrics: tuple = (
        "total_return",
        "excess_return",
        "sharpe",
        "information_ratio",
        "max_drawdown_amount",
        "longest_drawdown_days",
    )

    def __post_init__(self):
        if date_key(self.start) > date_key(self.end) or number(self.initial_cash) <= 0:
            raise ValueError("invalid interval or initial capital")
        if type(self.lot_size) is not int or self.lot_size < 1:
            raise ValueError("lot_size must be a positive integer")
        if not self.exchanges or not set(self.exchanges) <= {"SSE", "SZSE", "BSE"}:
            raise ValueError("invalid exchanges")
        if self.price_basis not in ("raw", "adjusted") or self.valuation not in ("strict", "last_close", "suspension"):
            raise ValueError("invalid price or valuation mode")
        ids = [s.name for s in self.scenarios]
        if len(set(ids)) != len(ids) or self.report_scenario not in ids:
            raise ValueError("scenario names must be unique and include report_scenario")


@dataclass(frozen=True)
class Field:
    scope: str = "daily"
    kind: str = "number"
    unit: str = ""
    version: str = "1"


@dataclass(frozen=True)
class Metric:
    label: str
    unit: str
    compute: object
    version: str = "1"


class Strategy:
    version = "1"
    fields = {}
    metrics = {}
    parameters = {}
    input_files = ()

    def before_open(self, ctx):
        pass

    def on_open(self, ctx):
        pass

    def after_close(self, ctx):
        pass
