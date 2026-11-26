"""Cold-start the original strategy on ten contiguous trading periods."""

import sys
from contextlib import closing
from dataclasses import replace
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

from backtest.data import readonly
from backtest.engine import run
from backtest.storage import identity
from .baseline import final_metrics


def split_days(days):
    size, extra = divmod(len(days), 10)
    if not size:
        raise ValueError("十个非空区间至少需要十个交易日")
    start = 0
    for index in range(10):
        stop = start + size + int(index < extra)
        yield days[start:stop]
        start = stop


def run_segments(baseline, strategy_path, output_dir):
    periods = list(split_days(baseline.days))
    spec = spec_from_file_location("analysis_user_strategy", Path(strategy_path).resolve())
    module = module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    results = []
    for index, days in enumerate(periods, 1):
        row = dict(index=index, start=days[0], end=days[-1], days=len(days), status="ok")
        directory = output_dir / f"segment-{index:02}"
        strategy, _ = module.build()
        signature, _ = identity(strategy, baseline.config, baseline.meta["snapshot_sha256"], baseline.tag_version)
        if signature != baseline.meta["signature"]:
            raise ValueError("策略、输入或引擎与全期基线不一致")
        config = replace(baseline.config, start=days[0], end=days[-1])
        try:
            path, _ = run(strategy, config, baseline.snapshot, directory)
        except Exception as error:
            # PDF/HTML export may fail after the engine already committed every day.
            files = sorted(directory.glob("*.db"))
            path = files[0] if len(files) == 1 else None
            row.update(status="failed", error=str(error))
        if path:
            row["database"] = str(path.relative_to(output_dir))
            with closing(readonly(path)) as db:
                if db.execute("SELECT status FROM run_info").fetchone()[0] == "completed":
                    dates = [r[0] for r in db.execute("SELECT trade_date FROM daily_account ORDER BY trade_date")]
                    if dates != days:
                        raise ValueError(f"第 {index} 段日历不一致")
                    row.update(final_metrics(db, days[-1], baseline.scenario.name), status="ok",
                               fills=db.execute("SELECT count(*) FROM fills").fetchone()[0])
        results.append(row)
    return results
