from math import isclose

from backtest.metrics import Moments
from .baseline import METRICS

TOLERANCE = 1e-12


def tied(a, b):
    return isclose(a, b, rel_tol=TOLERANCE, abs_tol=TOLERANCE)


def summarize(rows, actual, permutation):
    summary = []
    for metric in METRICS:
        values = [r[metric] for r in rows if r["status"] == "ok" and r.get(metric) is not None]
        moments = Moments()
        for value in values:
            moments.add(value)
        n, mean, sd = moments.n, moments.mean, moments.sd()
        x = actual[metric]
        row = dict(metric=metric, actual=x, actual_reason=actual.get(metric + "_reason"),
                   requested=len(rows), valid=n, mean=mean if n else None, sd=sd)
        if permutation:
            reason = None
            if any(r["status"] != "ok" for r in rows):
                reason = "部分路径不可执行"
            elif x is None or sd is None:
                reason = "真实值缺失或有效样本不足"
            elif tied(sd, 0) or tied(min(values), max(values)):
                reason = "置换结果无可辨差异"
            row.update(reason=reason, at_or_above=sum(v > x or tied(v, x) for v in values) if x is not None else None)
            for k in (2, 3):
                limit = mean + k * sd if sd is not None else None
                row[f"upper{k}"] = limit
                row[f"above{k}"] = None if reason else x > limit and not tied(x, limit)
        summary.append(row)
    return summary
