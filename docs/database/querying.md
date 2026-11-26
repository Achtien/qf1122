# 日线数据调取

## 第一章：直接读取 SQLite 原始数据

本章记录现有数据库的直接读取方法，示例使用 Python 标准库 `sqlite3` 和 SQL。
后续程序封装的 API 调取方法另起章节；本章不依赖或假设这些 API 已经实现。

### 1.1 数据库位置与读取约定

数据库位于项目根目录下的 `data/daily_data/daily_data.db`。
日期使用 8 位文本 `YYYYMMDD`，例如 `20261120`；在这一格式下，文本排序与日期排序一致。
示例中的 `BETWEEN` 同时包含起止日期；需要确定时间顺序时必须写 `ORDER BY`。

回测以只读方式连接，避免路径写错时创建空数据库，也避免查询代码误改数据。
下面的代码从**项目根目录**启动。后续示例中的 `conn` 指此处连接，查询代码应放进
`try` 块，在全部读取完成后关闭连接。

```python
from pathlib import Path
import sqlite3

db_path = (Path.cwd() / "data/daily_data/daily_data.db").resolve()
conn = sqlite3.connect(db_path.as_uri() + "?mode=ro", uri=True, timeout=30)
conn.row_factory = sqlite3.Row
conn.execute("PRAGMA query_only=ON")

try:
    # 同一轮回测的多次查询使用同一快照，避免期间更新造成前后不一致。
    conn.execute("BEGIN")
    bounds = conn.execute(
        "SELECT min(trade_date) AS first_date, max(trade_date) AS last_date "
        "FROM daily WHERE ts_code <> '000001.SH'"
    ).fetchone()
    print(dict(bounds))

    # 将本章后续查询放在这里。
finally:
    conn.rollback()  # 结束只读事务，不修改数据。
    conn.close()
```

代码中用 `?` 绑定日期和股票代码，不将这些值拼入 SQL 字符串。
NULL 在 Python 中对应 `None`；不要默认替换成 0。
若要求不同时间运行的回测也完全可复现，应另外保存数据库快照与回测参数：
当前主库会增量更新，也可能在修复时改写历史值；一次只读事务不能提供永久版本。
备份运行中的 SQLite 库应使用 SQLite backup API，不能只复制 `.db` 而遗漏 WAL。

### 1.2 表的用途、主键与连接关系

| 表 | 主键 | 用途 |
| --- | --- | --- |
| `daily` | `(trade_date, ts_code)` | 股票原始日线及上证综指 `000001.SH`；包含历史退市股票及部分旧代码、转板前历史 |
| `stock_basic` | `ts_code` | 最近抓取的证券基础资料；含上市、退市日期与当前状态 |
| `trade_cal` | `(exchange, cal_date)` | 原始交易所日历，包含自然日及开闭市状态 |
| `market_calendar` | `(exchange, cal_date)` | 派生日历，增加星期数、边界标签、前后交易日及间隔 |
| `tradable_stock` | `(trade_date, ts_code)` | 交易证据与资格判断，区分确认、排除、未知 |
| `stock_name_history` | `(ts_code, start_date, name)` | 曾用名有效区间、公告日期及变更原因；用于历史 ST 判断 |
| `stock_suspensions` | `(trade_date, ts_code, suspend_type, suspend_timing)` | 停复牌来源，保留日内停牌时间段 |
| `status_fetch_state` | `(api, scope)` | 状态来源的成功请求覆盖、抓取时间与数量 |
| `dataset_meta` | `key` | 随库保存的派生规则、标签版本及待重建标记 |
| `date_status` | `trade_date` | 仅股票下载状态与记录数，不含指数；不等同于逐只股票完整性证明 |
| `runs`、`request_log`、`warnings`、`rejected_rows` | 见各表 | 下载批次、请求及异常定位 |

`tradable_stock` 通过 `(trade_date, ts_code)` 连接 `daily`；通过
`(exchange, trade_date)` 连接 `market_calendar(exchange, cal_date)`。
日历连接必须包含交易所，否则同一天会与多家交易所日历匹配，导致重复行。

上证综指使用 `ts_code='000001.SH'`，在 `daily` 中与股票并行，每日一行。
它不进入股票基础表或 `tradable_stock`；不能通过后两张表的 INNER JOIN 获取指数。
`000001.SZ` 是股票代码，不能与上证综指混用。以下股票池、数量和缺口查询均排除指数；
若要读取包括指数在内的全部原始记录，可不加此过滤条件。

`daily` 已有 `(ts_code, trade_date)` 辅索引，适合单股区间查询；主键适合单日横截面。
`tradable_stock` 同样有代码日期索引，另有 `is_tradable=1` 的部分索引。

### 1.3 daily 的全部字段及价格口径

| 字段 | 含义及单位 |
| --- | --- |
| `ts_code` | Tushare 行情代码，如 `600000.SH`、`000001.SZ`、`920001.BJ` |
| `trade_date` | 日线日期，`YYYYMMDD` |
| `open` | 开盘价，元 |
| `high` | 最高价，元 |
| `low` | 最低价，元 |
| `close` | 收盘价，元 |
| `pre_close` | 除权口径的昨收价，元；不保证等于前一条记录的 `close` |
| `change` | 涨跌额，元 |
| `pct_chg` | 涨跌幅，百分数；`2.5` 表示 `2.5%`，转小数收益率需除以 100 |
| `vol` | 成交量，手；转股数时乘以 100 |
| `amount` | 成交额，千元；转元时乘以 1000 |
| `ah_vol` | 盘后成交量，手 |
| `ah_amount` | 盘后成交额，千元 |
| `tags` | JSON 数组；已确认的当日股票状态，参见 1.13 |
| `tags_unknown` | JSON 数组；尚未确认的状态类别，不能当作正常 |

上述元/股数口径适用于股票。上证综指的 OHLC、`pre_close`、`change` 是**指数点位**；
`pct_chg` 仍为百分数、`vol` 为手、`amount` 为千元；盘后两列均为 NULL，属于接口不提供。
不能对指数点位按股票股数做持仓估值。

当前 `daily` 中股票的 OHLC 是**未复权价格**，数据库尚未存入 `adj_factor` 复权因子。
`pre_close`、`pct_chg` 并不能替代完整复权因子序列，也不能直接重建所需的所有
前复权/后复权价格。跨分红、送转、换股等事件做收益和持仓计算，应补充复权因子、
公司行为或现金/股份变动处理，不能直接用相邻未复权 `close` 相除作为统一收益口径。

部分行情保留源数据 NULL 或异常值。盘后字段较早年份没有数据；即使在有该字段的
时期，也不应把所有 NULL 当作零成交量。查询 `daily` 不会自动清洗、填充或复权。
停牌日通常没有日线，不应补成具有正常成交能力的交易记录。

### 1.4 查询单只股票的区间行情

```python
rows = conn.execute(
    '''SELECT ts_code, trade_date, open, high, low, close, pre_close,
              "change", pct_chg, vol, amount, ah_vol, ah_amount
       FROM daily
       WHERE ts_code = ? AND trade_date BETWEEN ? AND ?
       ORDER BY trade_date''',
    ("600000.SH", "20250101", "20251231"),
).fetchall()

records = [dict(row) for row in rows]
```

这里读取的是指定行情代码的原始记录，不自动过滤其上市区间、市场资格或异常值。
代码发生变更时，应先按第 1.10 节核实代码沿革，不能仅凭字符串不同就认定是两只股票。

### 1.5 查询单日横截面与多只股票

下面读取单日全部股票原始行情（排除上证综指），仍不等于已去重、已确认市场资格的股票池：

```python
rows = conn.execute(
    '''SELECT ts_code, trade_date, open, high, low, close, pre_close,
              "change", pct_chg, vol, amount, ah_vol, ah_amount
       FROM daily
       WHERE trade_date = ? AND ts_code <> '000001.SH'
       ORDER BY ts_code''',
    ("20261120",),
).fetchall()
```

少量多股查询可动态生成**占位符数量**，股票代码本身仍通过参数绑定。
下面将代码每批限制为 200 个，既处理空列表，也避免一次绑定过多参数；
每批结果按代码、日期排序，若要将所有批次合并成全局时间顺序，需要再排序。

```python
codes = list(dict.fromkeys(["600000.SH", "000001.SZ", "600018.SH"]))
for offset in range(0, len(codes), 200):
    part = codes[offset:offset + 200]
    placeholders = ",".join("?" for _ in part)
    sql = f'''
        SELECT ts_code, trade_date, close, vol, amount
        FROM daily
        WHERE ts_code IN ({placeholders}) AND trade_date BETWEEN ? AND ?
        ORDER BY ts_code, trade_date
    '''
    rows = conn.execute(sql, (*part, "20250101", "20251231")).fetchall()
    # 在这里处理本批 rows。
```

### 1.6 读取交易日、星期数和前后边界标签

`market_calendar` 每家交易所、每个自然日一行，包括休市日。
`weekday` 为星期一至星期日对应的 `1–7`；`is_open` 为 `1` 开市、`0` 休市、
NULL 日历状态未知。`boundary_tag` 仅在开市日且相邻状态可判断时填写：

| 标签 | 前一个自然日 | 后一个自然日 |
| --- | --- | --- |
| `0` | 开市 | 开市 |
| `1` | 休市 | 开市 |
| `2` | 开市 | 休市 |
| `3` | 休市 | 休市 |

标签比较的是相邻**自然日**，不是上一/下一交易日。休市日和无法确认边界的开市日，
标签都可能为 NULL，需同时看 `is_open`，不能将 NULL 当作标签 `0`。

```python
days = conn.execute(
    '''SELECT cal_date, weekday, boundary_tag,
              prev_trade_date, next_trade_date,
              days_since_prev_trade, days_until_next_trade, source, build_id
       FROM market_calendar
       WHERE exchange = ? AND is_open = 1 AND cal_date BETWEEN ? AND ?
       ORDER BY cal_date''',
    ("SSE", "20250101", "20251231"),
).fetchall()
```

`prev_trade_date`、`next_trade_date` 严格早于/晚于当天；两个间隔字段是自然日差。
例如星期一距上周五的 `days_since_prev_trade=3`，不是 2 个休市日。
首个市场交易日可能根本没有上一交易日，末端日历缺少后续资料也可能无法确定下一
交易日，两者都使用 NULL；不能直接填 0。2026-11-23 核查时，北交所首日
`20211115` 的上一交易日为空属于正常边界。

`source='SSE_SZSE_PROXY'` 表示北交所采用沪深一致日历的代理结果，并非独立抓取
的北交所日历；`build_id` 对应生成报告中的构建批次。

### 1.7 连接行情、确认名单与日历

`tradable_stock` 的关键字段如下：

| 字段 | 含义 |
| --- | --- |
| `security_id` | 当前规则识别出的历史证券身份，通常关联 `stock_basic.ts_code`；未知时 NULL |
| `data_available` | `1` 有原始日线记录，`0` 没有；存在记录不代表数值一定有效 |
| `is_tradable` | `1` 有明确交易证据，`0` 有明确排除依据，NULL 证据不足或相互冲突 |
| `reason` | 判断原因，如 `TRADED`、`NO_DAILY_DATA`、`UNKNOWN_IDENTITY`、`OUTSIDE_LISTING_INTERVAL` |
| `tags`、`tags_unknown` | 与 `daily` 相同的历史状态列表；无日线日期也可读取 |

下面的查询用于**事后核对与筛选有实际交易证据的记录**。`is_tradable=1` 使用了当天
完整 OHLC、成交量等信息，不能用来确定当天开盘前的选股范围；否则会引入未来信息。
它也不是具体时点可以买入或卖出的保证，涨跌停、盘中停牌、撮合和滑点仍需另行处理。

```python
rows = conn.execute(
    '''SELECT d.ts_code, s.security_id, d.trade_date,
              d.open, d.high, d.low, d.close, d.pre_close,
              d."change", d.pct_chg, d.vol, d.amount, d.ah_vol, d.ah_amount,
              c.weekday, c.boundary_tag, c.prev_trade_date, c.next_trade_date
       FROM tradable_stock AS s
       JOIN daily AS d
         ON d.trade_date = s.trade_date AND d.ts_code = s.ts_code
       JOIN market_calendar AS c
         ON c.exchange = s.exchange AND c.cal_date = s.trade_date
       WHERE s.trade_date = ? AND s.is_tradable = 1
       ORDER BY d.ts_code''',
    ("20261120",),
).fetchall()
```

要检查未知记录，应从 `tradable_stock` 出发并 `LEFT JOIN daily`。
使用 `INNER JOIN daily` 会直接丢掉没有行情的候选行，掩盖需要核查的缺口。

### 1.8 定位未知状态、整日缺口与下载 warning

```python
unknown = conn.execute(
    '''SELECT s.trade_date, s.ts_code, s.security_id,
              s.data_available, s.reason, d.close, d.vol
       FROM tradable_stock AS s
       LEFT JOIN daily AS d
         ON d.trade_date = s.trade_date AND d.ts_code = s.ts_code
       WHERE s.trade_date BETWEEN ? AND ? AND s.is_tradable IS NULL
       ORDER BY s.trade_date, s.ts_code''',
    ("20150708", "20150710"),
).fetchall()
```

`NO_DAILY_DATA` 只表示缺少日线证据，不能单独判定为漏下载或停牌。
也不要用 `COALESCE(is_tradable, 0)` 永久抹去未知状态。

下面按原始沪深日历检查“某个开市日整个市场都没有日线”的情况。
结束日期应限定为希望覆盖且上游已发布日线的日期，不应把未来开市日当成下载缺口。

```python
missing_days = conn.execute(
    '''WITH expected AS (
           SELECT DISTINCT cal_date
           FROM trade_cal
           WHERE exchange IN ('SSE', 'SZSE') AND is_open = 1
             AND cal_date BETWEEN ? AND ?
       )
       SELECT e.cal_date, s.status, s.returned_rows, s.saved_rows
       FROM expected AS e
       LEFT JOIN date_status AS s ON s.trade_date = e.cal_date
       WHERE NOT EXISTS (
           SELECT 1 FROM daily AS d WHERE d.trade_date = e.cal_date AND d.ts_code <> '000001.SH'
       )
       ORDER BY e.cal_date''',
    ("20250101", "20261120"),
).fetchall()
```

该查询依赖 `trade_cal` 自身已有覆盖，不能发现日历自身缺日，也不能发现某个日期
只少了部分股票。截止日查询也应排除指数；不能用指数已入库来证明同日股票已下载。
即便股票最大日期足够新，也不能证明中间没有缺口。

```python
warnings = conn.execute(
    '''SELECT id, run_id, api, trade_date, ts_code, field, kind, message
       FROM warnings
       WHERE trade_date BETWEEN ? AND ?
       ORDER BY trade_date, id''',
    ("20250101", "20261120"),
).fetchall()
```

有些区间级、运行级 warning 的 `trade_date` 为空，应另外按 `run_id` 查询：
`SELECT * FROM warnings WHERE run_id = ? ORDER BY id`。
下载报告与派生表构建报告保存在 `data/daily_data/reports/`；原始下载 warning
不会因为生成交易资格表而自动删除或改成“已修复”。

### 1.9 大区间分批读取

全市场 22 年数据不宜一次 `fetchall()` 到内存。可限定所需列和日期后，用
`fetchmany()` 分批处理；以下顺序按交易日期、代码排列，适合按时间推进的回测。

```python
cursor = conn.execute(
    '''SELECT trade_date, ts_code, open, high, low, close, vol, amount
       FROM daily
       WHERE trade_date BETWEEN ? AND ? AND ts_code <> '000001.SH'
       ORDER BY trade_date, ts_code''',
    ("20200101", "20251231"),
)

while True:
    batch = cursor.fetchmany(20_000)
    if not batch:
        break
    # 在这里消费本批结果；不要再将所有 batch 追加到一个无限增长的列表。
    for row in batch:
        pass  # 替换为回测处理逻辑。
```

批次可能从某个交易日中间切开。策略若需要完整单日横截面，应先按第 1.6 节取得
交易日期，再逐日查询；或者在内存中保留最后一个未结束日期，等下一批拼完整再处理。

### 1.10 上市退市、历史身份和代码沿革

读取历史行情时，不要添加 `stock_basic.list_status='L'` 来筛选历史股票池。
这会用“今天还在上市”过滤过去数据，重新引入幸存者偏差。
`stock_basic` 是最近抓取的基础资料，并非逐日历史快照；当前名称、市场分类、上市状态
不能直接当成某个历史日当时已知的信息。上市/退市日期只提供资格区间约束，不能替代
完整历史停牌、恢复上市、转板及代码变更记录。

北交所数据还可能包含开市或上市前的历史：原始 `daily` 保留这些记录，资格判断同时
考虑 `20211115` 北交所正式开市日期与个股上市区间。不能因为存在 `.BJ` 日线就认定
该股在当日已经可在北交所交易。

截至 2026-11-23 的检查，以下三组旧代码行情在新代码下也有回填序列：

| 旧代码 | 新代码 | 新代码启用日期 | 已核对的重叠行数 |
| --- | --- | --- | ---: |
| `000022.SZ` | `001872.SZ` | 2018-12-26 | 3,072 |
| `000043.SZ` | `001914.SZ` | 2019-12-16 | 3,458 |
| `300114.SZ` | `302132.SZ` | 2025-02-17 | 3,421 |

合计 9,951 条旧代码记录被当前规则标记为 `UNKNOWN_IDENTITY`，对应新代码的同日
记录已进入确认名单。上述数量是该次检查的快照，不应写入回测程序作为永久常量。
不能直接将旧代码未知行也改为 `is_tradable=1`，否则可能把同一证券重复计数。
除部分 `pct_chg` 精度差异外，已核对的同日行情数值一致，原始差异应保留。

当前查询用的 `ts_code` 是**行情存储键**，不保证是该历史日实际挂牌使用的代码。
当前 `security_id` 也只是已实施规则下的身份标识，还没有完整覆盖所有代码沿革。
需要按当时实际代码连接其他历史数据时，必须建立带生效日期的代码历史，并在证券
身份与日期层面去重；这一完整映射尚未作为通用 API 提供。

三组变更依据分别为公司实施公告：
[招商港口](https://static.cninfo.com.cn/finalpage/2018-12-26/1205690369.PDF)、
[招商积余](https://disc.static.szse.cn/download/disc/disk02/finalpage/2019-12-16/a5a3d55e-cc2e-42e6-91c1-ea98235594fb.PDF)、
[中航成飞](https://static.cninfo.com.cn/finalpage/2025-02-15/1222544408.PDF)。

另一种情况是 `600018.SH`：该行情代码下包含旧上港集箱的历史，资格表用
`security_id='T600018.SH'` 标记旧主体，用 `security_id='600018.SH'` 标记后续主体。
要区分这两段，应查询资格表中的身份，不能只按当前基础资料上市日删掉早期行情，
也不能把所有 T 前缀统一去掉。跨主体换股事件的收益计算需独立处理公司行为。

### 1.11 更新入口与文档边界

增量更新入口为项目根目录下的 `src/get_data/update.py`。
该程序分别比较股票和上证综指的本地覆盖与上游实际可获取日期，补足差异；
补入股票时同步派生表。价格、结构和状态来源均就绪且没有显式规则/刷新任务时不写入数据库。更新完成后，应重新
打开只读连接，开始下一轮回测。

在项目根目录运行：

```sh
uv run --locked python src/get_data/update.py
```

股票默认只补缺失的整日与 `date_status='failed'` 日期；指数单独按上交所开市日
检查缺口，旧库首次运行会补齐已有股票区间内的历史指数。不会重抓所有历史 warning，
也不会检查上游对已有日期每个数值的事后修订。官方日线通常在交易日 15–16 点发布，
因此默认 16 点前即使探测到当日非空响应，也暂缓将当日当成完整日线入库；报告分别
记录“已观察到的最新日期”和“可入库的最新日期”。可用 `--settle-hour 18` 延后这一时间。
[Tushare 日线接口说明](https://tushare.pro/document/2?doc_id=27)

指数正常在 18 点左右更新，独立采用 `--index-settle-hour`（默认 18），并单独探测
是否实际发布。股票先更新、指数稍后补齐是允许的；指数请求失败不会被记成股票下载失败。
[指数日线接口说明](https://tushare.pro/document/2?doc_id=95)

更新器沿用现有资格规则，不会自动修复第 1.10 节的代码沿革限制。更多参数、失败续补
和退出码见[维护流程](operations.md)的增量更新部分。

本章所有示例均是直接 SQLite 调取，不是封装 API 的调用约定。
后续新增 API 章节时，应继续明确价格是否复权、日期区间是否包含端点、历史代码如何
映射、股票池使用何时可得的信息，以及 NULL 的处理方式。

### 1.12 同表读取上证综指与对齐基准

以下读取原始指数行情，不会混入 `000001.SZ`：

```python
benchmark = conn.execute(
    '''SELECT ts_code, trade_date, open, high, low, close, pre_close,
              "change", pct_chg, vol, amount, ah_vol, ah_amount
       FROM daily
       WHERE ts_code = ? AND trade_date BETWEEN ? AND ?
       ORDER BY trade_date''',
    ("000001.SH", "20250101", "20251231"),
).fetchall()
```

若要把每只股票与当天基准并排展示，可对同一张表按日期连接：

```python
paired = conn.execute(
    '''SELECT s.trade_date, s.ts_code, s.close AS stock_close,
              b.close AS benchmark_close, b.pct_chg AS benchmark_pct_chg
       FROM daily AS s
       LEFT JOIN daily AS b
         ON b.trade_date = s.trade_date AND b.ts_code = '000001.SH'
       WHERE s.ts_code = ? AND s.trade_date BETWEEN ? AND ?
       ORDER BY s.trade_date''',
    ("600000.SH", "20250101", "20251231"),
).fetchall()
```

使用 LEFT JOIN 保留指数缺失的日期，不把缺少基准的股票日静默删除。若改成全市场，
应将 `s.ts_code = ?` 改成 `s.ts_code <> '000001.SH'` 并相应移除第一个绑定参数。
只要读取 `daily` 的单日全量记录、不排除指数，就会得到股票各一行加指数一行。

指数缺口应按上交所日历单独查；不能用股票 `date_status='success'` 判断指数完整：

```sql
SELECT c.cal_date
FROM trade_cal AS c
LEFT JOIN daily AS b ON b.trade_date = c.cal_date AND b.ts_code = '000001.SH'
WHERE c.exchange = 'SSE' AND c.is_open = 1
  AND c.cal_date BETWEEN :start_date AND :end_date
  AND b.ts_code IS NULL
ORDER BY c.cal_date;
```

结束日期应取已发布指数的最新日期。回测采用 `pct_chg / 100.0` 作为基准日收益时，
要在情境配置中固定这一计算口径；若从收盘点位计算，需额外读取区间首日前一个
交易日的点位，并确认中间没有缺日。缺失基准不能填零。上证综指在这里作为比较
基准，不自动成为可交易股票，也不是无风险收益率。

### 1.13 读取停牌、ST、*ST 与退市标签

执行新版本下载、更新或迁移后，`daily` 与 `tradable_stock` 均有 `tags` 和
`tags_unknown` 两个 JSON 数组字段。支持的状态为 `停牌`、`*ST`、`ST`、`退市`。
前者存已确认状态，后者存未确认类别；`tags=[]` 且 `tags_unknown` 非空不能解释为正常。
未进行旧库迁移时，这些字段不存在，请先运行 `uv run --locked python src/get_data/add_tag.py`（来源缺失时加 `--refresh-status`）。

查询没有行情的停牌/退市日期应从 `tradable_stock` 出发。`daily` 不会补造空 OHLC。
用 JSON 元素比较精确匹配标签，避免把 `*ST` 当成 `ST`：

```sql
SELECT t.trade_date,t.ts_code,t.security_id,t.tags,t.tags_unknown,t.is_tradable,d.close
FROM tradable_stock AS t
LEFT JOIN daily AS d USING(trade_date,ts_code)
WHERE t.trade_date=:day
  AND EXISTS (SELECT 1 FROM json_each(t.tags) AS j WHERE j.value='*ST')
ORDER BY t.ts_code;
```

需要四类状态都已确认且没有任何标签的记录时：

```sql
SELECT trade_date,ts_code
FROM tradable_stock
WHERE trade_date=:day AND tags='[]' AND tags_unknown='[]';
```

这只筛状态，不保证行情存在或一定可以成交；是否要求 `is_tradable=1` 需要另行决定。
`停牌` 可以表示日内停牌，有有效成交的日内停牌不自动变成全日不可交易。
当前已退市的股票，其退市日前的行不会被回填 `退市`；有效退市日起的状态行才标记。
当前简称也不会回填历史 ST。指数的两个列表均为空，因股票状态不适用于指数。

Python 可按标准 JSON 解码：

```python
import json

row = conn.execute(
    "SELECT tags,tags_unknown FROM tradable_stock WHERE ts_code=? AND trade_date=?",
    ("600000.SH", "20261120"),
).fetchone()
if row is not None:
    confirmed = json.loads(row["tags"])
    unverified = json.loads(row["tags_unknown"])
```

完整未知位置可查询 `WHERE tags_unknown<>'[]'`，再关联来源表检查名称区间和
`status_fetch_state` 覆盖；`trading_tables_<build_id>.json` 中也有分类数量和样例。
`dataset_meta.tags_dirty='1'` 表示数据来源已更新而标签重建尚未完成。

标签是现有来源重建的历史有效状态，尚不代表指定时点已知的信息。名称区间来自
`namechange`，公告日期保存在 `ann_date`，但本实现不按公告时间生成盘前可见快照。
历史资料缺失、冲突与源数据修订仍需审查。具体来源、权限、刷新与迁移流程见
[数据存储与维护](schema.md)。
