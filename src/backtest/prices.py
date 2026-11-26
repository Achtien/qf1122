"""Select a single price basis for signals, executions and marks in a snapshot."""

PRICE_COLUMNS = ("open", "high", "low", "close", "pre_close", "change")
OTHER_COLUMNS = ("pct_chg", "vol", "amount", "ah_vol", "ah_amount")


def relation(db, basis):
    required = {"trade_date", "ts_code", *PRICE_COLUMNS, *OTHER_COLUMNS}

    def columns(table):
        return {row[1] for row in db.execute(f"PRAGMA table_info({table})")}

    if not required <= columns("daily"):
        raise ValueError("incomplete daily schema")
    if basis == "raw":
        return "daily"
    if required <= columns("adjusted_daily"):
        return "adjusted_daily"
    if not {"ts_code", "trade_date", "adj_factor"} <= columns("adj_factor"):
        raise ValueError("adjusted prices require adjusted_daily or daily adj_factor")
    # Fixed factor anchor of 1. Positive factors only; a missing factor leaves a missing price.
    prices = ", ".join(f'd."{key}" * f.adj_factor AS "{key}"' for key in PRICE_COLUMNS)
    other = ", ".join(f'd."{key}"' for key in OTHER_COLUMNS)
    return f"""(SELECT d.trade_date,d.ts_code,{prices},{other} FROM daily d
                LEFT JOIN adj_factor f ON f.ts_code=d.ts_code AND f.trade_date=d.trade_date AND f.adj_factor>0)"""
