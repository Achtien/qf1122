"""Expanding daily statistics. State is transactionally checkpointed with the account."""

import json
from dataclasses import asdict, dataclass, field
from math import isfinite, sqrt
from types import MappingProxyType

BUILTINS = {
    "equity": ("账户总资本", "元"),
    "daily_return": ("当日收益率", "%"),
    "total_return": ("总收益率", "%"),
    "benchmark_return": ("参考累计收益率", "%"),
    "excess_return": ("超额收益率", "百分点"),
    "sharpe": ("夏普比率", ""),
    "information_ratio": ("信息比率", ""),
    "drawdown_amount": ("当日回撤额", "元"),
    "max_drawdown_amount": ("最大回撤额", "元"),
    "longest_drawdown_days": ("最长回撤时间", "交易日"),
}


@dataclass
class Moments:
    n: int = 0
    mean: float = 0.0
    m2: float = 0.0

    def add(self, x):
        self.n += 1
        diff = x - self.mean
        self.mean += diff / self.n
        self.m2 += diff * (x - self.mean)

    def sd(self):
        return sqrt(max(self.m2, 0) / (self.n - 1)) if self.n > 1 else None


@dataclass
class Accumulator:
    previous: float | None
    peak: float
    days: int = 0
    benchmark_wealth: float | None = 1.0
    drawdown_valid: bool = True
    duration: int = 0
    longest: int = 0
    max_loss: float = 0.0
    peak_day: str = "initial"
    max_peak_day: str | None = None
    trough_day: str | None = None
    portfolio: Moments = field(default_factory=Moments)
    excess_rf: Moments = field(default_factory=Moments)
    active: Moments = field(default_factory=Moments)

    @classmethod
    def restore(cls, db, scenario, initial):
        row = db.execute(
            "SELECT state FROM metric_checkpoints WHERE scenario_id=?", (scenario,)
        ).fetchone()
        if row is None:
            return cls(initial, initial)
        state = json.loads(row[0])
        for key in ("portfolio", "excess_rf", "active"):
            state[key] = Moments(**state[key])
        return cls(**state)

    def update(self, date, equity, initial, benchmark, rf, periods):
        self.days += 1
        daily = None if equity is None or not self.previous else equity / self.previous - 1
        if equity == 0 and self.previous == 0:
            daily = 0.0
        self.previous = equity
        if daily is not None:
            self.portfolio.add(daily)
            if rf is not None:
                self.excess_rf.add(daily - rf)
            if benchmark is not None:
                self.active.add(daily - benchmark)
        if benchmark is None:
            self.benchmark_wealth = None
        elif self.benchmark_wealth is not None:
            self.benchmark_wealth *= 1 + benchmark
        total = equity / initial - 1 if equity is not None else None
        reference = self.benchmark_wealth - 1 if self.benchmark_wealth is not None else None
        loss = None
        if equity is None:
            self.drawdown_valid = False
        if self.drawdown_valid:
            if equity >= self.peak:
                self.peak, self.peak_day, self.duration = equity, date, 0
            else:
                self.duration += 1
            loss = self.peak - equity
            if loss > self.max_loss:
                self.max_loss, self.max_peak_day, self.trough_day = loss, self.peak_day, date
            self.longest = max(self.longest, self.duration)
        values = dict(
            equity=equity,
            daily_return=daily,
            total_return=total,
            benchmark_return=reference,
            excess_return=total - reference if total is not None and reference is not None else None,
            drawdown_amount=loss,
            max_drawdown_amount=self.max_loss if self.drawdown_valid else None,
            longest_drawdown_days=self.longest if self.drawdown_valid else None,
        )
        info = {
            k: (v, None if v is not None else "MISSING_INPUT", self.days, {}) for k, v in values.items()
        }
        info["max_drawdown_amount"] = (
            *info["max_drawdown_amount"][:3],
            {"peak": self.max_peak_day, "trough": self.trough_day},
        )
        for name, means, risk in (
            ("sharpe", self.excess_rf, self.portfolio),
            ("information_ratio", self.active, self.active),
        ):
            sd = risk.sd()
            reason = None
            if means.n < self.days:
                reason = "MISSING_INPUT"
            elif means.n < 2:
                reason = "INSUFFICIENT_SAMPLE"
            elif not sd:
                reason = "ZERO_VARIANCE"
            ratio = None if reason else sqrt(periods) * means.mean / sd
            info[name] = (ratio, reason, means.n, {"mean": means.mean, "sample_std": sd})
        return info


class MetricView:
    def __init__(self, db, date, scenario, values):
        self._db = db
        self.day = date
        self.scenario_id = scenario.name
        self.parameters = MappingProxyType(dict(scenario.parameters))
        self.values = MappingProxyType({k: v[0] for k, v in values.items()})

    def observations(self, key):
        return [
            dict(r)
            for r in self._db.execute(
                """SELECT trade_date,ts_code,value FROM strategy_data
            WHERE key=? AND trade_date<=? ORDER BY trade_date,ts_code""",
                (key, self.day),
            )
        ]

    def accounts(self):
        return [
            dict(r)
            for r in self._db.execute(
                "SELECT * FROM daily_account WHERE trade_date<=? ORDER BY trade_date", (self.day,)
            )
        ]

    def trades(self):
        return [
            dict(r)
            for r in self._db.execute("SELECT * FROM fills WHERE trade_date<=? ORDER BY id", (self.day,))
        ]


def settle_metrics(db, market, day, equity, scenario, custom):
    initial = float(market.config.initial_cash)
    state = Accumulator.restore(db, scenario.name, initial)
    bench, close = market.reference(scenario, day)
    rf = (
        (1 + scenario.annual_rf) ** (1 / scenario.periods) - 1
        if scenario.daily_rf is None
        else scenario.daily_rf.get(day)
    )
    db.execute(
        "INSERT INTO scenario_daily_inputs VALUES(?,?,?,?,?)", (scenario.name, day, rf, bench, close)
    )
    values = state.update(
        day, float(equity) if equity is not None else None, initial, bench, rf, scenario.periods
    )
    view = MetricView(db, day, scenario, values)
    for name, metric in custom.items():
        try:
            value = metric.compute(view)
            if value is not None and not isfinite(value):
                raise ValueError("non-finite value")
            values[name] = (
                float(value) if value is not None else None,
                None if value is not None else "MISSING_INPUT",
                state.days,
                {},
            )
        except Exception as exc:
            values[name] = (None, f"{type(exc).__name__}: {exc}", state.days, {})
    db.executemany(
        "INSERT INTO daily_metrics VALUES(?,?,?,?,?,?,?)",
        (
            (scenario.name, day, key, value, reason, n, json.dumps(details, allow_nan=False))
            for key, (value, reason, n, details) in values.items()
        ),
    )
    db.execute(
        "INSERT OR REPLACE INTO metric_checkpoints VALUES(?,?)",
        (scenario.name, json.dumps(asdict(state), allow_nan=False)),
    )
