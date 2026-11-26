# 数据库结构与历史状态契约

获取、修复及迁移命令见 [维护流程](operations.md)，SQL 查询见 [查询示例](querying.md)。

### market_calendar

每个交易所、每个自然日一行；主键为 `(exchange, cal_date)`。
日期均为 `YYYYMMDD` 文本，未知值使用 SQL NULL。

| 字段 | 含义 |
| --- | --- |
| `exchange` | SSE、SZSE、BSE |
| `cal_date` | 自然日，包含休市日 |
| `is_open` | 1 开市、0 休市、NULL 日历未知 |
| `weekday` | 星期一至星期日，分别为 1–7 |
| `boundary_tag` | 仅开市日填写：0 前后均开市，1 前一天休市，2 后一天休市，3 前后均休市；邻日状态不足以判断则为 NULL |
| `prev_trade_date` | 严格早于当天的最近交易日；不能确认时 NULL |
| `next_trade_date` | 严格晚于当天的最近交易日；不能确认时 NULL |
| `days_since_prev_trade` | 当天距上一交易日的自然日差；例如星期一距上周五为 3 |
| `days_until_next_trade` | 当天距下一交易日的自然日差 |
| `source` | 日历来源；例如 `trade_cal:SSE`、`SSE_SZSE_PROXY`、`UNKNOWN` |
| `build_id` | 构建批次，用于关联生成的 JSON 报告 |

标签所说的“前一天/后一天”均指相邻**自然日**，不指上一/下一交易日。
区间边界缺资料不会自动当作休市；官方 `pretrade_date` 可以辅助判断左边界。
北交所 2021-11-15 之前标记为未开市；之后若没有独立北交所日历，只有沪深
日历均已知且一致时才采用代理日历，并明确记录来源。

### tradable_stock

主键为 `(trade_date, ts_code)`，外键 `(exchange, trade_date)` 关联日历表。
候选记录包括开市/日历未知日期内已经上市过的股票，以及有原始日线的股票。
已退市股票在后续这些日期也保留状态行，`is_tradable=0`、`tags=["退市"]`；
`daily` 不为没有行情的股票制造空价格行。同一行情代码存在不同历史实体时，
按 `security_id` 与上市窗口识别，不为已经退出的旧实体占用新实体的日期记录。
保留无法确认或应排除的记录，以便区分缺数据和已知不可交易的情形。

| 字段 | 含义 |
| --- | --- |
| `trade_date` | 日线日期或候选交易日期 |
| `ts_code` | 用于关联 `daily` 的行情代码 |
| `exchange` | 所属交易所 |
| `security_id` | 对应 `stock_basic.ts_code` 的历史证券身份；无法确认时 NULL |
| `data_available` | 1 表示有 `daily` 原始记录，0 表示没有；不代表数据一定有效 |
| `is_tradable` | 1 有明确交易证据；0 被已知市场、上市区间或全天停牌规则排除；NULL 证据不足或冲突 |
| `reason` | 判断原因，如 `TRADED`、`NO_DAILY_DATA`、`OUTSIDE_LISTING_INTERVAL`、`INVALID_BAR` |
| `tags` | JSON 数组，已确认的当日状态：停牌、*ST、ST、退市 |
| `tags_unknown` | JSON 数组，尚未确认的状态类别；不能当作正常 |

确认池要求身份、上市窗口和开市状态有效，OHLC/成交量额有效且成交量大于零。
**无日线不直接等于停牌**，`NO_DAILY_DATA` 保留为未知。零成交量、日历缺失、
证券身份重叠以及停牌规则与实际日线冲突，也不会被自动放入确认池。

历史身份规则保留旧上港集箱 `T600018.SH` 与行情代码 `600018.SH` 的明确映射，
按上市区间选择对应证券，不会把所有带 T 前缀的证券统一改名。
北交所同时检查其正式开市日与股票上市日，转板前行情仍留在 `daily`，在资格表中
标记排除。上市日期含当日，退市日期不含当日。

代码内包含此前 warning 分析核实的 5 个暂停上市/连续停牌区间及来源链接。
这些例外**不构成完整历史停牌表**。可通过 `--rules PATH.json` 增补有依据的
完整交易日排除区间；不能把盘中临时停牌直接作为全天排除规则。格式示例：

```json
{
  "aliases": {},
  "alias_sources": {},
  "blocked_intervals": [
    {
      "security_id": "证券身份代码",
      "start_date": "20240102",
      "end_date": "20240103",
      "reason": "FULL_DAY_SUSPENDED",
      "source": "核实该区间的公告链接或文档路径"
    }
  ]
}
```

自定义区间起止日期均包含当日；默认追加至内置规则。设置
`"disable_builtin": true` 可改为完全使用自定义规则。

按日期取得有明确交易证据的股票及日历标签：

```sql
SELECT s.ts_code, s.security_id, c.weekday, c.boundary_tag
FROM tradable_stock AS s
JOIN market_calendar AS c
  ON c.exchange = s.exchange AND c.cal_date = s.trade_date
WHERE s.trade_date = '20261120' AND s.is_tradable = 1
ORDER BY s.ts_code;

-- 定位资格未知的记录
SELECT trade_date, ts_code, data_available, reason
FROM tradable_stock
WHERE is_tradable IS NULL
ORDER BY trade_date, ts_code;
```

这是一份根据当天完整日线得到的**事后交易证据清单**。回测若在开盘前做决策，
不能用当日最终成交量、日线是否存在来预先筛选股票；仍需当时可得的上市、停牌
信息。清单也不保证具体时点能够成交，涨跌停、盘中停牌等需由撮合逻辑另行处理。

重复运行会在一个事务内替换派生记录，并同步 `daily` 的标签；原始价格字段
不变；错误或提交前中断则回滚。全量构建期间会占用数据库写锁，新增记录和索引
也需要磁盘空间。数据修复或规则修改后，应重建受影响日期；日历修复可能影响相邻
交易日的间隔字段，最稳妥的做法是全量重建。

每次完成后生成 `data/daily_data/reports/trading_tables_<build_id>.json`，记录规则
及来源、规则摘要、各原因计数、未知记录样例、日历缺失数量。全部异常记录可通过
两张表中的 NULL 状态及非空 `tags_unknown` 定位。退出码 0 表示本次没有未决提醒；2 表示**已提交**但仍有
未知状态或边界信息不完整；1 为失败；130 为用户中断。

首次下载自动构建派生表；旧库可运行迁移入口，更新程序也会同步维护这两张表。

## 两个标签字段

`daily` 和 `tradable_stock` 都新增以下字段；原 13 个行情字段、单位、主键保持原义。

| 字段 | SQLite 类型 | 含义 |
| --- | --- | --- |
| `tags` | `TEXT NOT NULL`，JSON 数组 | 已确认的当日状态，如 `["停牌","*ST"]` |
| `tags_unknown` | `TEXT NOT NULL`，JSON 数组 | 尚不能确认的状态类别，如 `["*ST","ST"]` |

支持的值固定为 `停牌`、`*ST`、`ST`、`退市`，按此顺序保存。
`*ST` 与 `ST` 不会同时出现在 `tags`；ST 状态未知时，两者都列在 `tags_unknown`。
`tags=[]` 仅表示没有已确认标签；只有同时 `tags_unknown=[]` 才表示这四类状态
在当前来源口径内均已判定。迁移初始列默认未知，避免未处理行看似正常。
指数 `000001.SH` 不适用股票状态，两个列表均为 `[]`。

| 标签 | 判定依据和日期语义 |
| --- | --- |
| 停牌 | `suspend_d` 当日有 `S`，或已有经核实的整日停牌/暂停上市规则命中；不能由缺日线推断 |
| *ST | 当日唯一有效曾用名以 `*ST`、`S*ST` 或 `G*ST` 开头 |
| ST | 当日唯一有效曾用名以 `ST`、`SST` 或 `GST` 开头；不包含 *ST |
| 退市 | 对应历史证券身份的 `delist_date` 起（含当日）进入退市状态；此前不会因当前 D 状态而标退市 |

停牌记录的 `suspend_timing` 为空代表非日内停牌；有值则保留日内停牌语义。
日内停牌可以与 `is_tradable=1` 的当日成交证据并存。整日停牌无日线时为
`is_tradable=0`；整日停牌与日线同时存在时为未知，原因 `SUSPENSION_BAR_CONFLICT`。
当日只有 `R`（复牌）不会添加停牌标签。

退市是此处的终止状态：已退市行只保留 `["退市"]`，不把最后的 ST 名称无限延伸。
`tradable_stock` 在已经上市的股票退市后，仍在后续开市/日历未知日期保留状态行，
`is_tradable=0`、`reason='DELISTED'`。同一行情代码复用于新实体时优先选择该日
有效实体，保留 `security_id` 身份区分。`daily` 仍只保存真实返回的行情，
没有日线的停牌或退市日期请从 `tradable_stock` 查询，不能仅查 `daily`。

曾用名有效区间包含起止日；区间冲突、缺口、空响应、未核验到该日期时，ST 保留未知。
不会用 `stock_basic.name` 当前简称回填历史。身份不明时退市和 ST 判断也保持未知。
已成功查询且没有 S 记录仅表示接口在该日未报告停牌，不构成上游绝无漏数的证明。

这些标签描述按现有历史来源重建的状态，不是“开盘前已知”的快照。
`ann_date` 作为来源字段保留，但此实现不按公告时间过滤历史有效状态；源数据可能
事后修订，公告日期也可能缺失。需要时点可得性时应另核对公告与数据获取时间，
不能因存在标签就认为当时已能获得该信息。

## 来源表与更新范围

| 表 | 主要字段 | 用途 |
| --- | --- | --- |
| `stock_name_history` | `ts_code,name,start_date,end_date,ann_date,change_reason` | 一只证券的全部名称区间，主键 `(ts_code,start_date,name)` |
| `stock_suspensions` | `ts_code,trade_date,suspend_timing,suspend_type` | 当日停复牌记录，空时间段保存为空字符串 |
| `status_fetch_state` | `api,scope,as_of_date,fetched_at,row_count` | 成功查询覆盖；scope 为证券身份或交易日期，包含合法空响应 |
| `dataset_meta` | `key,value` | `eligibility_rules`、`tag_version`、`tags_dirty` |

曾用名按股票查询完整历史，不带 `start_date/end_date`：官方这两个输入参数表示
**公告日期筛选**，不是“有效名称与目标区间相交”。逐股请求避免全市场截断，
也能取得目标范围之前开始但在范围内仍有效的名称。
当股票行情截止日推进时，会重新核验相关股票的曾用名；已经退市且核验到退市日期的
身份不必每日重复请求。这比只比较当前简称请求更多，但可以覆盖更新期间曾加 ST
又摘 ST、最终简称未变的情况。一次全市场更新可能包含数千次名称请求。

停复牌来源保留原始代码，并识别明确核实的历史别名：`T00018.SH` 对应旧证券身份
`T600018.SH`（上港集箱，2000-07-19 上市、2006-10-20 退市）。该历史返回值曾在
[Tushare 仓库的问题记录](https://github.com/waditu/tushare/issues/1683)中直接列出，
上市/退市日期与本地当前基础资料相符；当年的行情代码为 `600018`，见
[2005 年年度报告](https://static.cninfo.com.cn/finalpage/2006-02-16/16450034.PDF)。
程序按当日有效证券身份连接来源，不将旧实体停牌状态套用到 2006-10-26 上市的新实体。
只接受这一明确别名，不普遍补齐短代码或去除 T 前缀。

当前标签版本为 3，保留 v2 的历史身份别名修复，并增加 GST / G*ST 识别。默认 `add_tag.py` 使用已有缓存；原先失败的来源需使用 `add_tag.py --refresh-status` 补齐。正在运行的 Python 进程不会自动加载修改后的模块。

停复牌按交易日期全市场查询，成功覆盖的历史日期默认复用。历史状态修订可用
`--refresh-status` 强制请求所有相关名称和日期；代码不能自动发现上游对已缓存
停牌历史的静默修订。名字有效区间发生历史状态变化时，会重建受影响日期及相邻边界；
只有普通简称变化、风险状态未变时，不必重建更早的资格记录。

官方接口核对（2026-11-26）：[namechange](https://tushare.pro/document/2?doc_id=100)
提供上述名称区间；[suspend_d](https://tushare.pro/document/2?doc_id=214) 从
2000-01-03 起提供数据，至少 2000 积分，单次 5000 行。
[stock_st](https://tushare.pro/document/2?doc_id=397) 的每日 ST 名单要求至少
3000 积分，因此当前 2000 积分流程不调用它。曾用名接口页未单列频次，程序沿用
账号全局额度；若实际账户返回更低限额，按 warning 调低命令行限速。

所有请求，包括失败请求，共用平滑限速：默认原始 200 次/分钟的 75%，起点间隔
至少 0.4 秒；股票基础资料另限制为 50 × 75%。原始限额设成 60 时为
45 次/分钟、至少 1.333 秒一次。下载/迁移参数为 `--daily-limit-rpm`，更新参数为
`--limit-rpm`，均填写原始限额。单股曾用名达到 1000 行触发保守异常检查，
这不是官方公布的 namechange 返回上限；停复牌达到 5000 行则视为潜在截断。

## 事务、失败续补与验收

下载/迁移先添加缺少的结构，逐批提交成功的来源缓存，然后在一个事务中重建派生表
并更新日线标签。中断后可以续用已提交来源；`dataset_meta.tags_dirty='1'`
表示来源/行情已变化而派生尚未完成，此时不要把旧标签当成此次处理的最终结果。
更新器将本次成功数据、来源、标签、规则和日志一起提交，若有其他程序同时改库，
会在提交前取消陈旧计划；失败的单批来源不会覆盖之前缓存。

没有新增价格不代表没有工作：旧结构迁移、失败来源续补和显式规则/状态刷新仍会
更新数据库。只有价格、结构、来源覆盖均就绪且没有显式刷新请求，更新器才完全
不写库；无论是否写库都会生成本次 Markdown/JSON 报告。

空名称历史记录 `EMPTY_NAME_HISTORY`；缺列、错日期、重复主键、非法日期和潜在
截断记录 `INVALID_STATUS_SOURCE`；请求失败记录 `REQUEST_FAILED`。
错误含 API、代码/日期及请求参数，异常批次跳过后继续。空响应若会清空之前已有的
名称历史，则另记 `STATUS_SOURCE_SHRANK` 并保留旧缓存，待下次重试。
首次查询的合法空名称历史会缓存，
但其 ST 仍未知；后续可用 `--refresh-status` 重查。上下游身份不明等遗留状态
不会被这次标签功能强行消除。

`T600018.SH` 的 `EMPTY_NAME_HISTORY` 表示使用该查询键未取得名称区间，不能
据此断言它历史上从未 ST；也不采用新实体的名称回填旧实体。该空响应与网络失败、
历史代码校验失败是不同问题，保留 ST 未知，需另外核查上游历史覆盖或旧代码查询能力。

结束报告位于 `data/daily_data/reports/`。`trading_tables_<build_id>.json` 中的
`tag_unknown_counts`、`tag_unknown_samples` 给出分类数量与样例；完整未知记录
可以查询 `tags_unknown<>'[]'`。构建结果含未知时记录 `DERIVED_UNKNOWN`，
不因数据已提交而声称全历史状态完整。退出码 2 表示有提醒，1 表示失败，
130 表示中断；更新报告的 `database_changed` 区分是否已提交。

```sql
-- 某日所有有状态或有未知状态的股票，包括没有行情的行
SELECT trade_date,ts_code,security_id,data_available,is_tradable,reason,tags,tags_unknown
FROM tradable_stock
WHERE trade_date=:day AND (tags<>'[]' OR tags_unknown<>'[]')
ORDER BY ts_code;

-- 一只股票的历史状态与可选行情
SELECT t.trade_date,t.ts_code,t.tags,t.tags_unknown,d.close
FROM tradable_stock AS t
LEFT JOIN daily AS d USING(trade_date,ts_code)
WHERE t.ts_code=:code AND t.trade_date BETWEEN :start_date AND :end_date
ORDER BY t.trade_date;
```

实现使用临时数据库和模拟接口验证；维护命令是否已在真实库执行，应以该库 `dataset_meta` 与最新运行报告为准。
