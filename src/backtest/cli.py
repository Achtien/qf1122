import argparse
import sys
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

from .data import snapshot
from .engine import run
from .report import export_html, export_pdf, export_reports


def main(argv=None):
    parser = argparse.ArgumentParser(prog="backtest")
    commands = parser.add_subparsers(dest="action", required=True)
    freeze = commands.add_parser("snapshot", help="create a reusable immutable market snapshot")
    freeze.add_argument("source", type=Path)
    freeze.add_argument("directory", type=Path)
    report = commands.add_parser("report", help="export interactive HTML and PDF from a completed database")
    report.add_argument("database", type=Path)
    report.add_argument("--scenario")
    report.add_argument("--format", choices=("all", "html", "pdf"), default="all")
    runner = commands.add_parser("run", help="run a strategy file defining build()")
    runner.add_argument("strategy", type=Path)
    runner.add_argument(
        "--snapshot",
        type=Path,
        help="frozen market database; default: back up the project market database",
    )
    runner.add_argument("--resume", type=Path)
    args = parser.parse_args(argv)
    if args.action == "snapshot":
        print(snapshot(args.source, args.directory))
    elif args.action == "report":
        if args.format == "all":
            for path in export_reports(args.database, args.scenario):
                print(path)
        else:
            export = export_html if args.format == "html" else export_pdf
            print(export(args.database, args.scenario))
    else:
        spec = spec_from_file_location("user_strategy", args.strategy.resolve())
        module = module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        root = Path(__file__).resolve().parents[2]
        market = args.snapshot or snapshot(
            root / "data/daily_data/daily_data.db", root / "data/backtest_snapshots"
        )
        # Preparation may need the frozen market before the strategy opens its inputs.
        # A resumed run must use its original input files and fingerprints.
        prepare = getattr(module, "prepare", None)
        if prepare is not None and args.resume is None:
            prepare(market)
        strategy, config = module.build()
        for path in run(
            strategy, config, market, args.strategy.resolve().parent / "results", resume=args.resume
        ):
            print(path)
        print(path.with_suffix(".html"))


if __name__ == "__main__":
    main()
