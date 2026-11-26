# 日频回测策略开发指南

一个策略占用根目录 `strategy/` 下的一个子目录。运行入口读取该目录的 `strategy.py`，每次新回测在同目录的 `results/` 中生成同名 SQLite 数据库、交互 HTML 与 PDF。HTML 内嵌全部数据和脚本，可直接用浏览器离线打开，悬停在图表上查看日期及两条收益曲线的数值。引擎、SQL 表结构、命令行、报告生成器和引擎测试位于 `src/backtest/`。完整示例见[非 ST 涨停股最小市值策略](../../strategy/limit_up_lowest/README.md)。

## 跑通示例

以下命令从项目根目录运行，使用 Python 3.13 及项目锁定的依赖。

```sh
uv sync --locked
uv run --locked python -m backtest run strategy/limit_up_lowest/strategy.py
```

首次使用默认入口时，引擎通过 SQLite backup 将本地行情库冻结到 `data/backtest_snapshots/`，包含已提交的 WAL 数据。快照文件以内容的 SHA-256 命名，可以供多策略共用。默认入口会制作并识别快照，磁盘上需为约 4 GB 的临时副本留出空间。已有快照时，显式传入 `--snapshot` 可直接复用。示例策略缺少专用输入库时会自动准备历史涨跌停价及总市值，需要联网并配置 `TUSHARE_TOKEN` 或项目根目录的 `.tushare_token`。输入齐备后，回测与报告均可离线运行。

标签已迁移的库须完成派生重建，`dataset_meta.tags_dirty` 为 `1` 时，制作快照与运行都会报错。标签版本及必需结构使用 `src/get_data/stock_tags.py` 的同一套就绪检查。制作快照前后各检查一次，防止把来源更新中间态冻结为可用输入。已完成但存在 `tags_unknown` 的库可以运行，未知状态按原值传递。旧的 v2 标签快照须先修复来源库并重新制作快照；旧的无标签快照仍可读取，其状态类别默认未知。

```sh
# 单独冻结一次，命令输出快照路径
MARKET=$(uv run --locked python -m backtest snapshot data/daily_data/daily_data.db data/backtest_snapshots)
uv run --locked python -m backtest run strategy/limit_up_lowest/strategy.py --snapshot "$MARKET"

# RESULT 指向打印的单次回测 .db，续跑时使用原策略、配置、输入和快照
uv run --locked python -m backtest run strategy/limit_up_lowest/strategy.py --snapshot "$MARKET" --resume "$RESULT"
uv run --locked python -m backtest report "$RESULT" --scenario default
# 只重新导出交互报告
uv run --locked python -m backtest report "$RESULT" --scenario default --format html
```

## 新策略范式

在 `strategy/<策略名>/strategy.py` 实现 `Strategy`，并定义无参数工厂 `build()`，返回一个新策略实例与 `Config`。策略输入文件通过 `Path(__file__)` 定位。将跨日可变状态保存在可 JSON 序列化的 `ctx.state` 中，每日事务会保存该状态。声明策略版本、参数及影响决策的输入文件，便于续跑核对。

策略模块可选定义 `prepare(snapshot_path)`。新回测的命令行顺序为：加载模块、取得行情快照、调用 `prepare`、调用 `build()`、正式回测。输入文件应在 `build()` 创建实例时读取，避免模块导入时因文件缺失而失败。`prepare` 应复用已有完整输入，只有准备成功后才发布新输入；异常会阻止 `build()` 和正式回测。`--resume` 跳过此钩子，续跑必须保留原输入文件。直接调用 Python `run(...)` 时不会自动调用该模块钩子，调用者需先准备输入。

```python
from backtest import Config, Field, Metric, Strategy

class Observe(Strategy):
    version = "1"
    fields = {"strategy.universe_size": Field(kind="integer", unit="只")}
    metrics = {"strategy.fills": Metric("累计成交笔数", "笔", lambda v: len(v.trades()))}

    def before_open(self, ctx):
        ctx.record("strategy.universe_size", len(ctx.universe))

    def on_open(self, ctx):
        code = "600000.SH"
        if code in ctx.universe and not ctx.positions:
            price = ctx.open_price(code)
            if price and price * ctx.lot_size <= ctx.cash:
                ctx.order(code, "BUY", 1)

    def after_close(self, ctx):
        ctx.state["last_date"] = ctx.day

def build():
    return Observe(), Config("20240102", "20240131", initial_cash="100000",
                             report_metrics=Config.report_metrics + ("strategy.fills",))
```

### 回调时序

| 回调 | 数据 | 下单与成交 |
| --- | --- | --- |
| `before_open(ctx)` | 当日确认股票池、过去的完整行情、上个日结后的账户 | 当日开盘单和收盘单进入队列 |
| `on_open(ctx)` | 盘前开盘单已成交，当日开盘价已公开 | 开盘单立即按当日开盘价成交。收盘单排队 |
| `after_close(ctx)` | 当日收盘单已处理，可读当天完整行情和成交 | 新单最早指向下一回测交易日。末日下单会留下一条区间外拒单记录 |
| 日结 | 引擎估值，计算各情境截至当日的指标 | 账户、交易、策略数据、指标及检查点在同一事务中提交 |

当日股票池来自所选交易所的 `tradable_stock.is_tradable=1`。该名单带有当日收盘后才能确认的资格信息。回测按草案在盘前公开名单，开盘回调也可观察开盘价并按同一价格交易。全额成交仅受股票资格、有效价格、现金及可卖股数等约束，交易费用与滑点均为零。账户使用 T+1，买入当天的股数从下一可交易日开始可卖。

### Context API

| 成员 | 输入、返回与边界 |
| --- | --- |
| `day`、`previous_day`、`phase` | 当前日期、上个市场交易日、回调名。日期均为 `YYYYMMDD` |
| `universe` | 当日确认的股票代码集合。并列排序应自行声明，例如按代码升序 |
| `cash`、`lot_size`、`positions` | 剩余现金为 Decimal，每手股数为整数。只读持仓映射的值以**股**计 |
| `sellable(code)` | 该证券当前可卖股数，结合当日资格与 T+1 |
| `open_price(code)` | 开盘及收盘后可读，返回 Decimal 或缺值 None |
| `bars(date)` | 返回按代码索引的完整日线字典。横截面为当日股票池与所查日确认池中身份相符的交集。开盘前及开盘中只能查以前的完整日线 |
| `status(code, date=None)` | 查询当前可交易或已持有证券的状态，默认当天。包含 `tags`、`tags_unknown`、`security_id`、`is_tradable`、`data_available`、`reason`、`market_open` 等字段。无行情日也能查询，日期最大为当前回测日 |
| `statuses(date=None)` | 批量返回当前股票池与持仓的状态映射，键为代码，日期规则同上 |
| `history(code, start, end)` | 返回该代码及证券身份在闭区间内的行情行，升序排列。沿用同样的阶段限制，可回看回测区间之前的交易日 |
| `order(code, side, lots, session="OPEN", *, touch_low=None)` | `side` 为 BUY/SELL，`session` 为 OPEN/CLOSE，数量为正整数**手**。返回订单 ID。可在 SELL/CLOSE 单提交时预设触发价，目标日最低价触及或低于该价即以收盘价卖出，否则到期。开盘时只看到订单已提交 |
| `cancel(id)` | 撤销仍在等待的订单，返回是否成功 |
| `orders()`、`trades()`、`accounts()` | 可见订单、已发生成交、已提交的日终账户，均返回字典列表。日结前的现金及持仓取当前上下文 |
| `state`、`record(key, value, code=None)`、`observations(key)` | 跨日状态、记录注册字段、查询其历史值。同日同键同代码重复记录时保留最后值 |

历史日线含原库 OHLC、前收、涨跌、成交量额等字段，成交与记账统一使用 Decimal。`bars()` 与 `history()` 增加 `tags`、`tags_unknown` 元组，原始价和复权价均从同日、同一证券身份的 `tradable_stock` 读取标签。`status()`、`statuses()` 返回独立字典，标签值也是元组。状态查询优先采用持仓证券身份，其次采用当日池身份，代码复用时身份不符的历史行返回未知。

`tags` 为确认标签，支持 `停牌`、`*ST`、`ST`、`退市`。`tags_unknown` 为尚未确认的类别。ST 与 *ST 精确匹配，资格池仍由 `is_tradable=1` 决定。策略自行决定风险标签的筛选规则，例如下面同时排除已确认和未知的 ST 风险类别。

```python
states = ctx.statuses()
risk = {"ST", "*ST"}
candidates = [
    code for code in sorted(ctx.universe)
    if not risk.intersection(set(states[code]["tags"]) | set(states[code]["tags_unknown"]))
]
```

状态接口在盘前即可查当天历史有效标签，延续当日确认池的事后信息假设。标签来源按有效日期重建，尚未按公告时刻过滤。历史完整行情仍受原有阶段限制。停牌期间持仓通过 `status()` 查询，`history()` 返回实际存在的行情行。

默认 `valuation="suspension"`，确认的全天停牌沿用同一证券、同一价格口径的最近有效收盘价。判断条件为 `停牌` 在确认标签中且 `is_tradable=0`。该证券所属市场确认休市时也沿用前收。日内停牌且 `is_tradable=1` 时，使用当天价格并按既定开收盘模型交易。`NO_DAILY_DATA`、未知停牌、全天停牌与行情冲突时，缺乏有效报价的持仓估值为 NULL，账户状态为 `missing`。沿用报价的真实日期保存在 `daily_positions.price_date`，账户状态为 `stale`。新标签库的估值报价要求同一身份且有确认交易资格，排除冲突行情。

| valuation | 历史价使用规则 |
| --- | --- |
| `suspension`（默认） | 确认全天停牌或所属交易所休市时沿用前收 |
| `strict` | 使用当日有效收盘价，缺少报价时估值为 NULL |
| `last_close` | 显式选择所有缺价日沿用最近有效收盘价，兼容旧回测口径 |

退市持仓的估值价、市值和可卖股数从生效日起均为零，股数保留供核对，对应股票仍出现在 `ctx.positions`。退市依据同一 `security_id` 的已确认标签，或 `stock_basic` 中该身份的有效退市日期。代码复用时，原持仓和新实体分别判断。`events` 记录一次 `delisting_writeoff`，零估值的 `price_date` 为日结日期。退市规则对三种估值模式均生效，现金继续计入总资本。账户总资本降至零时，当日收益为 -100%，此后连续零资产日收益约定为 0。策略模块作为受信任的本地 Python 运行。

旧无标签快照中，普通历史状态返回四类未知，已知证券身份的退市日期仍可生效。默认模式遇到无法确认的无行情日会保存缺值，显式选 `last_close` 可沿用此前的缺价估值行为。

### 配置、价格和扩展

- `Config(start, end, initial_cash="1000000", lot_size=100, exchanges=("SSE","SZSE","BSE"), price_basis="raw", valuation="suspension", scenarios=..., report_scenario="default", report_metrics=...)`。区间两端包含，按交易所开市日并集推进。默认账户启动时全为现金。
- `raw` 使用原始股价。`adjusted` 优先读取具备相同日线字段和唯一日期/代码键的 `adjusted_daily`。快照若提供以日期与代码为唯一键的 `adj_factor(trade_date, ts_code, adj_factor)`，也可用原始报价乘当日正因子，固定以因子 1 为锚。缺少这两种输入时会报错。公司行为只在价格序列体现。示例涨跌停价采用原始口径，因此示例固定为 raw。
- `Strategy.fields` 注册 `Field(scope, kind, unit, version)`，默认 scope 为 daily，另支持 position 和 run。position 记录需传代码，run 的查询视图取该键最后值。kind 为 integer、number、boolean、text 或 json，默认 number。名称以 `strategy.` 开头。
- `Strategy.metrics` 注册 `Metric(label, unit, compute, version)`。每天每个情境调用一次 `compute(view)`，返回数值或 None。可读 `view.day`、`view.scenario_id`、`view.parameters`、`view.values`（当日内置指标）、`view.trades()`、`view.accounts()`、`view.observations(key)`。历史查询均截止当天，包括事后重算情境时。单位填 `%` 或 `百分点` 时，返回小数并由 PDF 换算。自定义指标错误记录在 `daily_metrics.reason`。
- `Strategy.parameters` 是策略参数字典，`Strategy.input_files` 列出策略读取的文件路径。恢复时核对策略文件、辅助文件、引擎、配置与行情快照的摘要。影响交易的辅助模块也应列入 input_files。
- `Scenario(name, benchmark, annual_rf, periods, benchmark_returns, daily_rf, parameters)`。默认上证综指 000001.SH、零年无风险利率、252 个交易日。无风险年率按复利换算，亦可传逐日小数收益字典。自定义基准可传快照中的行情代码，或用 `benchmark_returns={日期: 简单日收益率}` 覆盖。参考收益从首日开始计，指数使用相邻交易日的收盘点位比值。用于 PDF 的情境需要完整的参考曲线。

### 逐日指标与结果库

`daily_account` 每日一行，持仓表 `daily_positions` 的数量以股计。持仓额外保存 JSON 数组 `tags`、`tags_unknown` 和 `status_reason`，用于追溯无行情日、资格冲突及退市估值。`run_info.settings.market_status` 记录标签版本与旧库标志，共享状态模块的摘要纳入续跑校验。总资本等于日终现金加各持仓股数乘估值收盘价之和。`orders` 区分 pending、filled、rejected、expired、cancelled，`fills.order_id` 可回查原委托。`cash_ledger` 的初始资金及每次买卖变动可以与日终现金对账。

`daily_metrics` 的唯一键为情境、交易日和指标名。内置指标包含 `equity`、`daily_return`、`total_return`、`benchmark_return`（参考累计收益）、`excess_return`（累计收益之差）、`sharpe`、`information_ratio`、`drawdown_amount`、`max_drawdown_amount`、`longest_drawdown_days`。逐日参考**单日**收益另存在 `scenario_daily_inputs.benchmark_return`。回撤以初始资本为首个峰值，持续时间按连续低于峰值的交易日计。夏普分母取策略日收益样本标准差，信息比率分母取主动日收益样本标准差。样本不足、分母为零或所需数据缺失时查 `reason`。公式详见[存储设计](design.md)。

绘图时可直接查询已经提交的数据。

```sql
SELECT trade_date, metric_name, value
FROM daily_metrics
WHERE scenario_id = 'default'
  AND metric_name IN ('total_return', 'benchmark_return')
ORDER BY trade_date, metric_name;
```

Python 程序可调用 `run(strategy, config, snapshot_path, output_dir, resume=None)`，生成数据库、PDF 和 HTML，返回 `(database_path, pdf_path)`。交互报告路径为 `database_path.with_suffix(".html")`，命令行会打印三个文件路径。`add_scenario(db_path, snapshot_path, strategy, scenario)` 依序补算一个新情境，每日复用当时已存的账户与策略数据。

`export_html(db_path, scenario_id=None, output=None)` 和 `export_pdf(db_path, scenario_id=None, output=None)` 都读取完成的结果库。页首显示初始资金（元），策略累计收益为红线，参考累计收益为蓝线，并列出末日所选指标。HTML 悬停或触摸可显示实际日期、策略与参考累计收益率，沿用历史价的日期另有估值标记。图表支持左右方向键及 Home/End。`export_reports(db_path, scenario_id=None)` 生成两种格式并返回 `(pdf_path, html_path)`。报告只含图表、指标、元数据和操作提示。

默认输出与数据库同名，单格式导出可用 output 指定位置。报告采用临时文件成功后替换，失败时可单独重试。`run_info.report_file` 指向最近成功生成的报告，同时导出两种格式后指向 HTML。`report_status`、`report_scenario`、`reported_at` 记录导出结果。旧结果库可直接导出交互报告，修改估值规则需新建回测。续跑要求原引擎、配置及输入摘要一致。在缺少本地中文字体的环境中，可通过 `BACKTEST_PDF_FONT` 指定中文 TrueType 字体。

## 验证引擎

```sh
uv run --locked python -m unittest discover -s src/backtest/tests -v
```

测试使用独立的临时行情与结果库，覆盖历史 ST 与未知标签、全天/日内停牌、资格冲突、代码复用、迁移就绪检查，以及同价开盘成交、T+1、条件收盘单、跨日委托、现金与持仓、复权、缺价、停牌沿用价、退市归零、零资产收益、指标情境、HTML/PDF 报告和中断恢复。
