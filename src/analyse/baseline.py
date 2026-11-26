"""Read and validate the frozen inputs shared by both analyses."""

import json
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path

from backtest.data import Market, readonly
from backtest.engine import _fingerprint
from backtest.model import Config, Scenario

METRICS = ("sharpe", "total_return")


def final_metrics(db, day, scenario):
    rows = db.execute(
        """SELECT metric_name, value, reason FROM daily_metrics
           WHERE trade_date=? AND scenario_id=? AND metric_name IN ('sharpe','total_return')""",
        (day, scenario),
    )
    result = {}
    for name, value, reason in rows:
        result[name] = value
        result[name + "_reason"] = reason
    if any(name not in result for name in METRICS):
        raise ValueError(f"{day}: 缺少末日指标")
    return result


@dataclass
class Baseline:
    path: Path
    snapshot: Path
    config: Config
    scenario: Scenario
    days: list
    rf: dict
    actual: dict
    meta: dict
    tag_version: str | None


def load_baseline(result_db, snapshot, scenario=None):
    path, snapshot = Path(result_db).resolve(), Path(snapshot).resolve()
    with closing(readonly(path)) as db, closing(readonly(snapshot)) as src:
        meta = dict(db.execute("SELECT * FROM run_info").fetchone())
        if meta["status"] != "completed" or _fingerprint(snapshot) != meta["snapshot_sha256"]:
            raise ValueError("需要已完成的回测和摘要一致的行情快照")
        settings = json.loads(meta["config"])
        config = Config(**(settings | {"scenarios": tuple(Scenario(**s) for s in settings["scenarios"])}))
        scenario = scenario or config.report_scenario
        selected = next((s for s in config.scenarios if s.name == scenario), None)
        if selected is None:
            raise ValueError(f"原配置中无指标情境 {scenario}")
        market = Market(src, config)
        accounts = [r[0] for r in db.execute("SELECT trade_date FROM daily_account ORDER BY trade_date")]
        rf = dict(db.execute("SELECT trade_date,rf_return FROM scenario_daily_inputs WHERE scenario_id=?",
                             (scenario,)))
        if accounts != market.days or set(rf) != set(accounts):
            raise ValueError("日历、原账户或指标情境日期不完整")
        return Baseline(path, snapshot, config, selected, accounts, rf,
                        final_metrics(db, accounts[-1], scenario), meta, market.status_data.version)
