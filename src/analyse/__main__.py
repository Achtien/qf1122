"""CLI entry points for reproducible backtest diagnostics."""

import argparse
import csv
import json
from dataclasses import asdict
from pathlib import Path
from tempfile import mkdtemp

from .baseline import load_baseline
from .permutation import run_permutation
from .segments import run_segments
from .summary import TOLERANCE, summarize


def write_csv(path, records):
    keys = list(dict.fromkeys(k for row in records for k in row))
    with path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, keys)
        writer.writeheader()
        writer.writerows(records)


def main(argv=None):
    parser = argparse.ArgumentParser(description="回测稳健性检验与离线交互报告")
    commands = parser.add_subparsers(dest="action", required=True)
    for action in ("all", "permute", "segments"):
        sub = commands.add_parser(action)
        sub.add_argument("database", type=Path)
        sub.add_argument("--snapshot", type=Path, required=True)
        sub.add_argument("--scenario")
        sub.add_argument("--output-dir", type=Path, required=True, help="每次运行创建独立子目录")
        if action != "segments":
            sub.add_argument("-n", "--n", type=int, default=1000)
            sub.add_argument("--seed", type=int, default=0)
        if action != "permute":
            sub.add_argument("--strategy", type=Path, required=True)
    args = parser.parse_args(argv)
    base = load_baseline(args.database, args.snapshot, args.scenario)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    out = Path(mkdtemp(prefix=f"{base.meta['run_id']}-", dir=args.output_dir))
    manifest = dict(version=1, method=args.action, strategy=base.meta["strategy"], run_id=base.meta["run_id"],
                    signature=base.meta["signature"], snapshot_sha256=base.meta["snapshot_sha256"],
                    inputs=json.loads(base.meta["settings"])["inputs"], scenario=asdict(base.scenario),
                    config=asdict(base.config), days=len(base.days), start=base.days[0], end=base.days[-1],
                    baseline=str(base.path), snapshot=str(base.snapshot), tolerance=TOLERANCE)
    results, summaries, errors = {}, {}, {}
    for method in ("permute", "segments"):
        if args.action not in ("all", method):
            continue
        print(f"{method} …", flush=True)
        try:
            if method == "permute":
                rows, manifest["permutation"] = run_permutation(base, args.n, args.seed)
            else:
                manifest["strategy_file"] = str(args.strategy.resolve())
                rows = run_segments(base, args.strategy, out)
            results[method] = rows
            summaries[method] = summarize(rows, base.actual, method == "permute")
        except (ValueError, OSError, RuntimeError) as exc:
            errors[method] = str(exc)
    manifest["errors"] = errors
    manifest["status"] = "partial" if errors or any(
        row["status"] == "failed" for rows in results.values() for row in rows
    ) else "completed"
    for name, records in (("details", results), ("summary", summaries)):
        write_csv(out / f"{name}.csv", [dict(method=m, **r) for m, rows in records.items() for r in rows])
    (out / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    payload = dict(manifest=manifest, results=results, summaries=summaries, actual=base.actual)
    html = Path(__file__).with_name("report.html").read_text(encoding="utf-8")
    # Escape '<' even inside embedded errors, paths or user-defined strategy names.
    data = json.dumps(payload, ensure_ascii=False, allow_nan=False).replace("<", r"\u003c")
    report = out / "report.html"
    report.write_text(html.replace("/*ANALYSIS_DATA*/", data), encoding="utf-8")
    print(report.resolve(), flush=True)
    return int(manifest["status"] != "completed")


if __name__ == "__main__":
    raise SystemExit(main())
