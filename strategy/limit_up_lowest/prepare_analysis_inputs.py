"""Build an isolated, frozen strategy copy covering the original and ten cold starts."""

import argparse
import os
import shutil
import sqlite3
from contextlib import closing
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory

from analyse.segments import split_days
from backtest import run
from backtest.data import Market, readonly
from get_data.get_daily import RateLimiter, TushareClient
from input_data import INPUTS
from prepare_run_limits import Collector, ROOT
from strategy import SmallestCapLimitUp, make_config


def prepare(snapshot, directory):
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / INPUTS.name
    if target.exists():
        raise FileExistsError(target)
    config = make_config()
    with closing(readonly(snapshot)) as src:
        market = Market(src, config)
        periods = list(split_days(market.days))
        previous = market.prev[market.days[0]]
    # The original archive covers the continuous run. Collect additional inputs
    # in a separate SQLite backup; an interrupted collection can reuse its batches.
    partial = directory / (INPUTS.name + ".partial")
    if not partial.exists():
        with closing(readonly(INPUTS)) as origin, closing(sqlite3.connect(partial)) as dest:
            origin.backup(dest)
    token = os.getenv("TUSHARE_TOKEN") or (ROOT / ".tushare_token").read_text().strip()
    collector = Collector(partial, TushareClient(token, RateLimiter()), previous, config.end)
    try:
        with TemporaryDirectory(dir=directory) as tmp:
            for index, days in enumerate(periods, 1):
                print(f"准备区间 {index}/10 {days[0]}–{days[-1]}", flush=True)
                strategy = SmallestCapLimitUp(collector)
                strategy.input_files = ()
                run(strategy, replace(config, start=days[0], end=days[-1]), snapshot, tmp)
    except Exception as exc:
        raise SystemExit(str(exc).replace(token, "[redacted]")) from None
    finally:
        collector.db.close()
    for name in ("strategy.py", "limit_data.py", "input_data.py"):
        shutil.copyfile(Path(__file__).with_name(name), directory / name)
    partial.rename(target)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--directory", type=Path, required=True)
    args = parser.parse_args()
    prepare(args.snapshot, args.directory)
