import hashlib
import inspect
import json
import sqlite3
from get_data import stock_tags
from dataclasses import asdict
from pathlib import Path

from .data import digest
from .metrics import BUILTINS


def encode(obj):
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, allow_nan=False)


def identity(strategy, config, market_hash, tag_version=None):
    module = Path(inspect.getfile(type(strategy)))
    package = Path(__file__).parent
    settings = {
        "strategy": type(strategy).__name__,
        "version": strategy.version,
        "parameters": strategy.parameters,
        "strategy_sha256": digest(module),
        "inputs": {Path(p).name: digest(p) for p in strategy.input_files},
        "execution": "tradable_stock retrospective; OPEN/CLOSE; zero costs; T+1; integer lots",
        "delisting": "zero value from identity-matched delisting date or tag; retain shares; zero sellable shares",
        "market_status": {"tag_version": tag_version, "legacy": tag_version is None},
        "status_reader_sha256": digest(inspect.getfile(stock_tags)),
        "engine": {p.name: digest(p) for p in sorted(package.glob("*.py")) if p.name != "report.py"},
        "schema": digest(package / "schema.sql"),
    }
    sign = hashlib.sha256(encode([asdict(config), settings, market_hash]).encode()).hexdigest()
    return sign, settings


def connect(path):
    db = sqlite3.connect(path)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    return db


def initialize(db, run_id, strategy, config, fingerprint, signature, settings):
    db.executescript((Path(__file__).with_name("schema.sql")).read_text())
    with db:
        db.execute(
            """INSERT INTO run_info(run_id,strategy,config,signature,snapshot_sha256,settings,status)
                   VALUES(?,?,?,?,?,?,'running')""",
            (
                run_id,
                type(strategy).__name__,
                encode(asdict(config)),
                signature,
                fingerprint,
                encode(settings),
            ),
        )
        db.execute(
            "INSERT INTO cash_ledger(trade_date,delta) VALUES(?,?)", (None, str(config.initial_cash))
        )
        db.executemany(
            "INSERT INTO metric_scenarios VALUES(?,?)",
            ((s.name, encode(asdict(s))) for s in config.scenarios),
        )
        db.executemany(
            "INSERT INTO metric_definitions VALUES(?,?,?,'1')",
            ((key, *v) for key, v in BUILTINS.items()),
        )
        for key, m in strategy.metrics.items():
            if not key.startswith("strategy.") or not callable(m.compute):
                raise ValueError(f"invalid custom metric {key}")
            db.execute(
                "INSERT INTO metric_definitions VALUES(?,?,?,?)", (key, m.label, m.unit, m.version)
            )
        for key, f in strategy.fields.items():
            if (
                not key.startswith("strategy.")
                or f.scope not in {"run", "daily", "position"}
                or f.kind not in {"integer", "number", "boolean", "text", "json"}
            ):
                raise ValueError(f"invalid custom field {key}")
            db.execute(
                "INSERT INTO data_definitions VALUES(?,?,?,?,?)",
                (key, f.scope, f.kind, f.unit, f.version),
            )
        unknown = set(config.report_metrics) - (set(BUILTINS) | set(strategy.metrics))
        if unknown:
            raise ValueError(f"undefined report metrics: {unknown}")
