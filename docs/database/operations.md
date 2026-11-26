# 数据库获取、更新与迁移

正式实现位于 `src/get_data/`，所有命令从项目根目录运行。`get_daily.py` 负责首次获取与断点续传，`update.py` 负责增量更新，`add_tag.py` 负责已有库的标签修复。它们共用 `stock_tags.py` 和 `daily_tables.py`，不导入 `src/temporary/`。

## 新电脑恢复环境与首次建库

```sh
uv sync --locked
uv run --locked python src/get_data/get_daily.py
```

Python 版本由 `.python-version` 固定为 3.13.2，依赖由 `uv.lock` 固定。uv 以可编辑方式安装两个正式包 `get_data`、`backtest`，无需设置 `PYTHONPATH`。采集逻辑使用标准库；PDF 输出使用 ReportLab，`tzdata` 提供没有系统时区数据库时的上海时区。

凭据读取顺序为 `TUSHARE_TOKEN` 环境变量、项目根目录 `.tushare_token`；可以用 `--token-file PATH` 指定文件。程序不自动加载 `.env`。凭据单独配置，不能提交到 Git。

首次下载默认从 **2004-11-22** 开始，到上海时间最近已结束的数据日（18 点前取前一天，之后取当天）。该固定起点保留现有数据库的早期历史，不随迁移日期滚动。仅运行 `get_daily.py` 即可建立股票日线、上证综指、L/D/P 基础资料、原始日历、曾用名、停复牌缓存、交易资格、历史标签及审计表。

如需与本次检查的现有库对齐截止范围：

```sh
uv run --locked python src/get_data/get_daily.py --start-date 20041122 --end-date 20261125
```

这会重新获取相同日期范围及表结构；供应商事后修订、抓取时间、运行 ID 和已有审计日志不会被复刻。需要逐字节相同或保留自定义规则、研究输入与结果时，应另行迁移 SQLite 一致性备份及对应文件。新建库默认内置的身份映射和五个暂停上市区间见 [结构与状态规则](schema.md)；额外规则须通过 `--rules` 提供。

## 修复现有库的 GST / G*ST 标签

```sh
uv run --locked python src/get_data/add_tag.py
```

默认只使用库内曾用名、停复牌、基础资料和日历，**不联网、不要求 Token、不重新下载价格**。按已有股票行情的完整日期范围，在一个事务内重建派生表并同步 `daily` 标签；原始 13 个行情字段保持不变。重复运行得到相同的标签与资格数据，审计运行号和构建号会更新。全量派生重建仍需扫描历史数据并占用写锁。

标签版本由 2 升至 3。新增 `GST → ST`、`G*ST → *ST`，保留 `SST`、`S*ST`，统一大小写、空白和全角字符。只有前缀匹配且该日曾用名唯一、来源覆盖有效时才确认风险；名称冲突、缺口、覆盖不足保留未知，不使用当前简称倒填历史。

来源尚未下载或需要刷新上游修订时：

```sh
uv run --locked python src/get_data/add_tag.py --refresh-status
```

此命令需要 Token，会刷新基础资料、完整曾用名和停复牌，再重建标签，仍不下载价格。`get_daily.py --migrate-only` 会联网续补缺失状态；加 `--offline` 与默认 `add_tag.py` 等价。旧库需要恢复规则时，先用库内 `dataset_meta.eligibility_rules`；缺失时查原构建报告，仍缺失则明确提供 `--rules`。

旧版本行情快照不会自动改变。标签修复后需重新制作快照；v2 标签快照不能通过 v3 就绪检查。无标签旧快照仍按回测的 legacy 规则处理，旧结果库可继续导出报告。

## 下载、续传与精确修复

```sh
uv run --locked python src/get_data/get_daily.py --init-only
uv run --locked python src/get_data/get_daily.py --start-date 20261119 --end-date 20261120
uv run --locked python src/get_data/get_daily.py --retry-warnings
uv run --locked python src/get_data/get_daily.py --start-date 20100104 --end-date 20100104 --force
```

默认跳过 success / warning 股票日期，重试 failed 和未处理日期；指数日期覆盖独立检查。`--retry-warnings` 重抓股票警告日期，`--force` 重抓指定范围的股票和指数。`--max-days N` 分别限制本次待下载的股票日期和指数日期，适合小规模连通性验证，不代表全历史已完成。

所有请求按声明限额的 75% 平滑执行。`--daily-limit-rpm` 默认 200，即 150 次/分钟，起点间隔至少 0.4 秒；股票基础资料另外受 50 × 75% 的限额约束。失败请求也占用限速槽位。同一账号的其他进程须自行协调额度。

## 数据与检查

`daily` 保存全部 13 个行情字段及 `tags`、`tags_unknown` 两个状态字段，主键 `(trade_date, ts_code)`，辅索引
`(ts_code, trade_date)`。包含 `ah_vol`、`ah_amount`，无单位转换：成交量为手，
成交额为千元。股票价格是未复权行情；本次脚本不另外下载复权因子。

**上证综指作为同表的一行存储**：`ts_code='000001.SH'`，每个上交所交易日一条；
不新增逐日指数列，也不建立另一张指数行情表。`000001.SZ` 仍是平安银行，两者不同。
指数来自 `index_daily`，OHLC/昨收/涨跌额为指数点位；`pct_chg` 为百分数，
`vol` 为手，`amount` 为千元；接口不提供的 `ah_vol`、`ah_amount` 均为 NULL。
指数不进入 `stock_basic` 或 `tradable_stock`，也不计入股票数量、股票缺口及
`date_status` 的股票返回/入库数量。纯股票查询需要 `WHERE ts_code <> '000001.SH'`。

首次下载会按年分片拉取请求范围内的指数；重新运行时，即使股票已为 success，
仍会单独补缺失指数。`--force` 会同时重抓两类行情，`--max-days` 分别限制两类
待处理日期数。指数的缺列、错代码/日期、重复日期、缺值、非有限值及价格异常
会留下 warning，不写入异常指数行；下次通过日期缺口自动续补。股票与指数共用
同一个限速器。接口与字段依据：[指数日线](https://tushare.pro/document/2?doc_id=95)。

盘后两字段从 **2026-07-06** 起才有数据。之前的空值正常；之后接口未提供或
不适用的值也保留为 NULL，不人为补零。检查盘后字段是否缺列及两字段是否只有
一项为空。必需日线字段为空则记录到具体股票、日期、字段。

程序按交易日请求全市场，**不按当前上市名单过滤行情**。同时获取三家交易所
的 L（上市）、D（退市）、P（暂停上市）资料，以及按年切片的沪深交易日历。
验证日历包含请求区间内每个自然日；只剩一个有效交易所日历时采用它并记录
warning，两个都失败则跳过该年并在报告中定位。北交所参照沪深交易日历。

逐批检查空响应、缺列、重复主键、日期错位、非有限数字、空必填值、OHLC
关系、负成交值、数量明显偏少/突降及 6000 行截断风险。停牌没有日线，故
在市数量与返回数量不要求完全相等；数量检查仅为启发式。

数值为空或价格关系异常但主键有效的行保留原值并记 warning；主键错误、
非有限数字或重复行放入 `rejected_rows`，不静默丢弃。达到 6000 条会记录
潜在截断，需要后续按股票等更小请求补拉。脚本不声称已证明所有历史数据完整。
结束时额外检查与区间相交的已退市证券是否完全没有日线。
另外按股票汇总位于上市/退市区间外的行情：例如现行北交所代码可能返回转板前
历史。保留原数据并报告区间、行数，供回测时核验实际市场资格，不自动视为当时
可交易的 A 股，也不自动删除这些记录。
北交所的市场资格检查还考虑其 2021-11-15 开市日期；部分 `stock_basic`
上市日期实际沿用更早的精选层日期，因此仅比较 `list_date` 不充分。

## 日志与恢复

数据库除行情外还保存 `stock_basic`、`trade_cal`、`runs`、`request_log`、
`date_status`、`warnings`、`rejected_rows`。每次请求失败会立即记录 warning
及参数，随后处理下一次请求；质量异常同样记录后继续。有效行以事务 UPSERT
保存，重复运行不会生成重复主键。每日失败不会回滚其他日期的数据。

运行完成或 Ctrl+C 中断时，控制台汇总本次 warnings，并生成：

```text
data/daily_data/reports/warnings_<run_id>.md
```

报告包含接口、请求参数、日期、股票代码、字段、原因、数据库 warning ID，
以及区间内尚未通过检查的日期。进程被强制杀死/断电时，最后尚未提交的事务
会回滚；既有数据库日志仍在，但来不及生成 Markdown，可续跑后生成新报告。
退出码：0 正常；2 下载结束但有 warning 或既有异常未修复；1 致命错误；
130 用户中断。数据库开启 WAL，不要在运行中只复制 `.db` 文件备份，
请使用 SQLite backup API。

## 增量更新到最新行情

```sh
uv run --locked python src/get_data/update.py
```

更新器仅使用标准库，复用现有下载器的 HTTPS 客户端、质量检查和平滑限速。
凭据仍读取 `TUSHARE_TOKEN` 或 `.tushare_token`。
全局原始限额默认 200 次/分钟，实际使用 75%；股票资料接口另受 50 次/分钟的
75% 限额约束。使用 `--limit-rpm` 可降低全局限额。

处理顺序：

1. 只读分别检查本地股票和指数的日期覆盖，检查股票失败日期，并补查沪深日历。
2. 分别查询全市场 `daily` 和上证综指 `index_daily`，以有效非空响应确定各自最新日期。
   每类默认最多探测 20 个交易日，可用 `--probe-days` 调整；无法确认时报告 warning，
   不会把网络异常当成“没有更新”。
3. 股票默认北京时间 16 点后入库当日数据（`--settle-hour`）；指数默认 18 点后
   （`--index-settle-hour`），且仍要求接口实际返回数据。报告分别记录两类的已观察到
   日期和可入库日期。指数未发布不会阻止已就绪的股票入库，之后可只补指数。
4. 检查最早已有行情至可用最新日期之间的整日缺口，以及 `date_status='failed'`
   的日期。即使最大日期相同，中间有缺口也会补齐。已存在的历史 warning 不自动重抓；
   上游对已有日期的价格修订也不在默认增量检查范围内。
5. 存在待补股票日期、旧库结构待迁移或显式 `--refresh-status` 时刷新三交易所 L/D/P 基础资料。
   只补指数且状态缓存齐全时不刷新股票资料。
   旧库没有指数时，自动从库中最早股票日期起按年补齐指数，不重下载已完成的股票。
   某个日期或指数年度批次失败会跳过，
   继续下载其他日期；整日缺列、错主键、非有限数值、6000 行截断等不入库。
   数量明显偏少/骤降默认暂缓该日，核实停牌后可用 `--allow-low-count` 放行数量启发式；
   此参数不能绕过结构、截断和丢失既有代码检查。6000 行上限仍需人工拆分请求修复。
6. 按股票获取曾用名全历史，按缺少的交易日期获取停复牌记录。新截止日到来时，
   为覆盖期间可能出现的加 ST、摘 ST 再加 ST 等变化，重新核验相关股票的曾用名，
   不只比较当前简称。状态来源有失败仍可保存价格，并将无法确认的标签留在 `tags_unknown`。
7. 所有本次成功日期、基础资料、状态来源、日历、审计日志与派生表在同一个事务内提交。
   失败日期留待下次补充；提交前若发现其他进程改过数据库，则取消本次提交并提示重跑。
   派生表构建失败会连同本次原始数据写入一起回滚。

正常股票增量会重建受影响日期及其前方交易日，以更新旧截止日的下一交易日信息；
历史上市/退市窗口或历史日历发生变化时，会全量重建派生表，耗时相应增加。
只补指数且资格规则/历史日历不变时，无需重建股票资格表。
更新后缺席于最新基础列表的旧证券不会被删除。

派生规则保存于 `dataset_meta.eligibility_rules`，迁移数据库时会随库携带。
旧版数据库第一次迁移时仍需从 `trading_tables_<build_id>.json` 恢复规则：先查
`--report-dir`，再查数据库同级 `reports/`。缺失或各区间规则不同则需要
`--rules PATH.json` 明确指定，不会静默换回默认规则。迁移完成后报告用于审计，
程序不再依赖它们重建。显式指定规则即使没有待补价格，也会触发全量重建。

**价格、数据库结构与状态来源覆盖均已就绪，而且未要求刷新状态或指定规则时，不写数据库。**
旧库升级或状态缺口修复即使没有新价格也会写入；若无可保存数据且无结构/规则升级，
则不写数据库。无论有无更新，都会在 reports 目录生成
`update_<时间和随机标识>.md` 及同名 JSON，记录日期比较、失败位置和请求参数。
`database_changed` 表明数据库是否已提交；提交后报告落盘异常会明确显示已提交状态。
退出码：0 成功/无需更新，2 有待补或质量提醒，1 致命错误，130 中断。

报告中的 `local_latest_before/after`、`updated_dates`、`failed_dates` 仅指股票；
指数分别看 `index_local_latest_before`、`index_latest_after`、`index_updated_dates`、
`index_failed_dates` 和 `index_deferred_dates`。仅补指数时，股票 `updated_dates=[]`
但 `database_changed=true` 是正常情况。

上游没有提供全市场“发布完成”标志，时间窗口与数量校验不能证明每只股票数据完备。
当日首次同步建议在发布窗口结束后进行；盘中回测股票池仍需遵守原始调取文档中的
时点要求。接口依据：[日线及发布时段](https://tushare.pro/document/2?doc_id=27)、
[交易日历](https://tushare.pro/document/2?doc_id=26)、
[账号频次](https://tushare.pro/document/1?doc_id=290)。

原始 SQL 调取方法见 [查询示例](querying.md)。

`data/daily_data/update.py` 保留为兼容入口，仅转发到 `get_data.update`。`src/temporary/` 不参与运行、安装或验收。

## 验证与迁移文件

```sh
uv lock --check
uv run --locked python -m unittest discover -s tests -v
uv run --locked python -m unittest discover -s src/backtest/tests -v
```

迁移项目需包含 `src/`（可去除 temporary）、`strategy/`、测试、文档以及 `.python-version`、`pyproject.toml`、`uv.lock`。虚拟环境在目标电脑重新生成。`.gitignore` 排除了行情库、策略 SQLite 输入、回测结果、缓存和凭据，使用 Git 迁移时这些内容需单独备份或重新获取。涨跌停输入属于策略数据，由策略目录的准备脚本生成，不是主行情库的组成部分。

运行中的 SQLite 数据库用 backup API 备份，不能只复制主文件而遗漏 WAL。`--db` 可指向独立数据库，`--report-dir` 可指定审计输出。
