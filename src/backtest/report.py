"""Offline interactive HTML and vector PDF from committed daily observations."""

import json
import os
import tempfile
from contextlib import closing
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from reportlab.lib.colors import HexColor
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

from .storage import connect

INK, MUTED, RED, BLUE, PALE = "#182F37", "#536774", "#D12136", "#365BA1", "#DAE3E5"


def font():
    for path in (
        os.environ.get("BACKTEST_PDF_FONT"),
        "/Library/Fonts/Arial Unicode.ttf",
        "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
    ):
        if path and Path(path).is_file():
            pdfmetrics.registerFont(TTFont("BacktestText", path))
            return "BacktestText"
    pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))
    return "STSong-Light"


def draw_report(c, run, config, dates, series, metrics, reference, scenario):
    family = font()
    valuation = {"suspension": "确认停牌沿用前收", "last_close": "缺价沿用前收", "strict": "严格当日收盘"}[config["valuation"]]
    if "delisting" in json.loads(run["settings"]):
        valuation += " / 退市归零"

    def label(x, y, s, size=10, color=INK, align="left", width=None):
        s = str(s)
        if width and pdfmetrics.stringWidth(s, family, size) > width:
            size = max(5, min(size, width * size / pdfmetrics.stringWidth(s, family, size)))
        c.setFont(family, size)
        c.setFillColor(HexColor(color))
        (c.drawRightString if align == "right" else c.drawString)(x, y, s)

    def line(x1, y1, x2, y2, color, width=0.6):
        c.setLineWidth(width)
        c.setStrokeColor(HexColor(color))
        c.line(x1, y1, x2, y2)

    label(44, 786, "策略回测", 25)
    label(44, 757, f"{run['strategy']}   /   {config['start']} – {config['end']}", 12, width=300)
    label(
        550,
        757,
        f"初始资金  {Decimal(str(config['initial_cash'])):,.2f} 元",
        12,
        align="right",
        width=198,
    )
    label(
        44,
        735,
        f"情境  {scenario}     参考  {reference}     价格  {config['price_basis']}     股票池  当日事后确认     估值  {valuation}",
        10,
        MUTED,
        width=510,
    )
    line(44, 714, 550, 714, PALE)
    label(44, 685, "累计收益率", 15)
    for x, color, title in ((330, RED, "策略"), (411, BLUE, reference)):
        line(x, 689, x + 18, 689, color, 2)
        label(x + 23, 685, title, 9, width=110)
    left, bottom, right, top = 86, 454, 545, 654
    vals = [v for vs in series for v in vs if v is not None]
    lo, hi = min(vals), max(vals)
    pad = max((hi - lo) * 0.08, 0.001)
    lo, hi = lo - pad, hi + pad

    def y(v):
        return bottom + (v - lo) / (hi - lo) * (top - bottom)

    for i in range(5):
        v = lo + (hi - lo) * i / 4
        line(left, y(v), right, y(v), PALE)
        label(left - 5, y(v) - 3, f"{100 * v:.1f}%", 8, MUTED, "right")
    line(left, y(0), right, y(0), MUTED)
    for vs, color in zip(series, (RED, BLUE)):
        prior = None
        for i, val in enumerate(vs):
            pt = None if val is None else (left + (right - left) * i / (len(vs) - 1), y(val))
            if prior and pt:
                line(*prior, *pt, color, 1.7)
            prior = pt
    label(left, 436, "期初", 8, MUTED)
    if len(dates) > 2:
        mid = len(dates) // 2
        label(left + (right - left) * (mid + 1) / len(dates) - 20, 436, dates[mid], 8, MUTED)
    label(right, 436, dates[-1], 8, MUTED, "right")

    if series[0][-1] is None:
        latest = next((date for date, value in reversed(list(zip(dates, series[0][1:]))) if value is not None), None)
        if latest:
            label(44, 416, f"策略最后有效估值日  {latest}", 9, RED)

    heading_y = 393
    for index, (name, value, unit) in enumerate(metrics):
        if heading_y < 95:
            c.showPage()
            heading_y = 770
        if index == 0 or heading_y == 770:
            label(44, heading_y, "期末指标", 15)
            label(548, heading_y, dates[-1], 9, MUTED, "right")
            heading_y -= 29
        if value is None:
            display = "不可计算"
        elif unit in ("%", "百分点"):
            display = f"{value * 100:,.2f} {unit}"
        elif unit in {"交易日", "笔", "股", "只"}:
            display = f"{value:,.0f} {unit}"
        else:
            display = f"{value:,.{2 if unit else 4}f} {unit}".strip()
        label(48, heading_y, name, 11, width=300)
        label(548, heading_y, display, 11, INK, "right", width=185)
        line(44, heading_y - 10, 550, heading_y - 10, PALE)
        heading_y -= 34
    label(44, 35, run["run_id"], 8, MUTED, width=500)
    c.showPage()


def _export(db_path, scenario_id, output, kind):
    path = Path(db_path).resolve()
    if not path.is_file():
        raise FileNotFoundError(path)
    output = Path(output or path.with_suffix("." + kind)).resolve()
    if output.suffix.lower() != "." + kind or output == path:
        raise ValueError(f"expected a {kind} output")
    with closing(connect(path)) as db:
        run = db.execute("SELECT * FROM run_info").fetchone()
        if run["status"] != "completed":
            raise ValueError("report requires a completed run")
        config = json.loads(run["config"])
        scenario = scenario_id or config["report_scenario"]
        try:
            entry = db.execute(
                "SELECT config FROM metric_scenarios WHERE scenario_id=?", (scenario,)
            ).fetchone()
            if entry is None:
                raise ValueError(f"unknown scenario {scenario}")
            settings = json.loads(entry[0])
            reference = settings["benchmark"] or scenario
            if settings["benchmark_returns"] is not None:
                reference = scenario
            elif reference == "000001.SH":
                reference = "上证综指"
            dates = [
                r[0] for r in db.execute("SELECT trade_date FROM daily_account ORDER BY trade_date")
            ]
            curve = {
                name: dict(
                    db.execute(
                        """SELECT trade_date,value FROM daily_metrics
                WHERE scenario_id=? AND metric_name=? ORDER BY trade_date""",
                        (scenario, name),
                    )
                )
                for name in ("total_return", "benchmark_return")
            }
            series = [[0.0] + [vs[d] for d in dates] for vs in curve.values()]
            if any(v is None for v in series[1]):
                raise ValueError("reference curve incomplete")
            metrics = [
                db.execute(
                    """SELECT label,value,unit FROM daily_metrics m JOIN metric_definitions d
                ON m.metric_name=d.name WHERE scenario_id=? AND trade_date=? AND metric_name=?""",
                    (scenario, dates[-1], name),
                ).fetchone()
                for name in config["report_metrics"]
            ]
            with tempfile.NamedTemporaryFile(dir=output.parent, suffix="." + kind, delete=False) as tmp:
                temp = Path(tmp.name)
            try:
                if kind == "pdf":
                    c = canvas.Canvas(str(temp), pagesize=(595, 842), pageCompression=1)
                    c.setTitle(f"{run['strategy']} / {dates[0]} - {dates[-1]}")
                    draw_report(c, run, config, dates, series, metrics, reference, scenario)
                    c.save()
                else:
                    data = {
                        "strategy": run["strategy"], "runId": run["run_id"],
                        "config": config, "scenario": scenario, "reference": reference,
                        "dates": ["期初", *dates], "series": series,
                        "metrics": [list(row) for row in metrics],
                        "delistingZero": "delisting" in json.loads(run["settings"]),
                        "valuationStatus": ["ok"] + [r[0] for r in db.execute(
                            "SELECT valuation_status FROM daily_account ORDER BY trade_date"
                        )],
                    }
                    payload = json.dumps(data, ensure_ascii=False, allow_nan=False).replace("<", "\\u003c")
                    template = Path(__file__).with_name("report.html").read_text(encoding="utf-8")
                    temp.write_text(template.replace("{{REPORT_DATA}}", payload), encoding="utf-8")
                temp.replace(output)
            finally:
                temp.unlink(missing_ok=True)
            with db:
                db.execute(
                    "UPDATE run_info SET report_status='completed', report_file=?, report_scenario=?, reported_at=?, error=NULL",
                    (str(output.name), scenario, datetime.now(timezone.utc).isoformat()),
                )
        except Exception as err:
            with db:
                db.execute("UPDATE run_info SET report_status='failed',error=?", (str(err),))
            raise
    return output


def export_pdf(db_path, scenario_id=None, output=None):
    return _export(db_path, scenario_id, output, "pdf")


def export_html(db_path, scenario_id=None, output=None):
    return _export(db_path, scenario_id, output, "html")


def export_reports(db_path, scenario_id=None):
    """Generate both formats; run_info points to the interactive HTML on success."""
    pdf = export_pdf(db_path, scenario_id)
    return pdf, export_html(db_path, scenario_id)
