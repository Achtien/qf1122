"""Public runner and replay of additional performance scenarios."""

import json
import uuid
from contextlib import closing
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from .data import Market, digest, readonly
from .execution import Broker
from .metrics import settle_metrics
from .model import Config, Scenario, number
from .portfolio import Account
from .report import export_reports
from .storage import connect, encode, identity, initialize
from .strategy import Context


def _callback(strategy, ctx, phase):
    ctx._phase = phase
    try:
        getattr(strategy, phase)(ctx)
    finally:
        ctx._phase = None


def _day(db, market, strategy, index, day):
    prior = db.execute(
        "SELECT cash,strategy_state FROM daily_account ORDER BY trade_date DESC LIMIT 1"
    ).fetchone()
    cash, state = (
        (prior["cash"], json.loads(prior["strategy_state"]))
        if prior
        else (market.config.initial_cash, {})
    )
    account = Account(db, cash, day)
    following = market.days[index + 1] if index + 1 < len(market.days) else None
    broker = Broker(db, market, account, market.frame(day), following)
    ctx = Context(broker, market, strategy, state)
    _callback(strategy, ctx, "before_open")
    broker.match("OPEN")
    _callback(strategy, ctx, "on_open")
    broker.match("CLOSE")
    _callback(strategy, ctx, "after_close")
    account.reconcile()
    value, equity, status = account.mark(market)
    db.execute(
        "INSERT INTO daily_account VALUES(?,?,?,?,?,?)",
        (
            day,
            str(account.cash),
            str(value) if value is not None else None,
            str(equity) if equity is not None else None,
            status,
            encode(state),
        ),
    )
    for scenario in market.config.scenarios:
        settle_metrics(
            db, market, day, number(equity) if equity is not None else None, scenario, strategy.metrics
        )


def _fingerprint(path):
    wal = Path(str(path) + "-wal")
    if wal.exists() and wal.stat().st_size:
        raise ValueError("use the snapshot command for a live WAL database")
    return digest(path)


def run(strategy, config, snapshot_path, output_dir, *, resume=None):
    """Generate DB, PDF and HTML. Return (database, PDF) paths for existing callers."""
    fingerprint = _fingerprint(snapshot_path)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "_" + uuid.uuid4().hex[:8]
    path = Path(resume) if resume else output_dir / (run_id + ".db")
    if resume and not path.is_file():
        raise FileNotFoundError(path)
    with closing(readonly(snapshot_path)) as src:
        src.execute("BEGIN")
        market = Market(src, config)
        signature, settings = identity(strategy, config, fingerprint, market.status_data.version)
        if not resume:
            path.touch(exist_ok=False)
        with closing(connect(path)) as db:
            if not resume:
                try:
                    initialize(db, run_id, strategy, config, fingerprint, signature, settings)
                except Exception:
                    db.close()
                    path.unlink(missing_ok=True)
                    raise
            meta = db.execute("SELECT signature,status FROM run_info").fetchone()
            if meta["signature"] != signature:
                raise ValueError("resume requires identical snapshot, code, inputs, and configuration")
            if meta["status"] != "completed":
                try:
                    for index, day in enumerate(market.days):
                        with db:
                            db.execute("BEGIN IMMEDIATE")
                            if db.execute(
                                "SELECT 1 FROM daily_account WHERE trade_date=?", (day,)
                            ).fetchone():
                                continue
                            _day(db, market, strategy, index, day)
                    with db:
                        db.execute("UPDATE run_info SET status='completed', error=NULL")
                except BaseException as err:
                    with db:
                        db.execute("UPDATE run_info SET status='interrupted',error=?", (str(err),))
                    raise
    pdf, _ = export_reports(path)
    return path, pdf


def add_scenario(db_path, snapshot_path, strategy, scenario):
    """Replay daily performance for a new scenario against the frozen account."""
    if not Path(db_path).is_file():
        raise FileNotFoundError(db_path)
    with closing(connect(db_path)) as db, closing(readonly(snapshot_path)) as src:
        meta = db.execute("SELECT * FROM run_info").fetchone()
        config = json.loads(meta["config"])
        config["scenarios"] = tuple(Scenario(**s) for s in config["scenarios"])
        config = Config(**config)
        fingerprint = _fingerprint(snapshot_path)
        market = Market(src, config)
        if (
            meta["status"] != "completed"
            or identity(strategy, config, fingerprint, market.status_data.version)[0] != meta["signature"]
        ):
            raise ValueError("scenario replay requires the original completed run and inputs")
        with db:
            db.execute(
                "INSERT INTO metric_scenarios VALUES(?,?)", (scenario.name, encode(asdict(scenario)))
            )
            for day, equity in db.execute(
                "SELECT trade_date,equity FROM daily_account ORDER BY trade_date"
            ):
                settle_metrics(
                    db,
                    market,
                    day,
                    number(equity) if equity is not None else None,
                    scenario,
                    strategy.metrics,
                )
