# A 股历史数据库与日频回测

从 Tushare 获取全市场股票日线和上证综指，维护历史名称、停复牌、交易日历与股票资格，并使用不可变行情快照运行日频策略回测。默认主库为 `data/daily_data/daily_data.db`。

## 安装与首次获取

在项目根目录运行：

```sh
uv sync --locked
uv run --locked python src/get_data/get_daily.py
```

Python 固定为 3.13.2，依赖版本由 `uv.lock` 管理。运行前配置 `TUSHARE_TOKEN` 环境变量或根目录 `.tushare_token`；也可用 `--token-file PATH` 指定凭据文件。程序不自动加载 `.env`。

首次下载默认从 **2004-11-22** 到上海时间最近已结束的数据日，自动获取股票、指数、基础资料、日历和历史状态来源，生成完整表结构与标签，无需依次执行其他建表脚本。失败请求保留审计记录，可重跑续传；未知历史状态保留在 `tags_unknown`，不会当作正常。

如需重建现有库截至 2026-11-25 的日期范围：

```sh
uv run --locked python src/get_data/get_daily.py --start-date 20041122 --end-date 20261125
```

同一范围的重新获取受上游历史修订影响。需要保留原始数据版本、审计日志或自定义规则时，迁移 SQLite 一致性备份；不能只复制正在写入的 `.db` 而遗漏 WAL。完整流程见 [数据库获取与迁移](docs/database/operations.md)。

## 修复标签与日常更新

```sh
# 仅用库内来源重建标签和派生表；无需联网、无需 Token，不改价格
uv run --locked python src/get_data/add_tag.py

# 来源缺失或需要获取上游修订时，联网刷新历史状态再重建
uv run --locked python src/get_data/add_tag.py --refresh-status

# 获取新行情、补失败日期，并同步历史状态与派生表
uv run --locked python src/get_data/update.py
```

标签版本 3 修复 `GST → ST`、`G*ST → *ST`，同时识别 `SST`、`S*ST`、空白、大小写和全角字符。判定使用当日有效曾用名及历史证券身份，不以当前简称回填过去。默认 `add_tag.py` 处理已有股票行情的完整区间；全量重建可能较久，日志会报告进度。

退出码 `0` 为成功，`2` 为处理完成但存在告警或未知数据，`1` 为失败，`130` 为中断。详情位于 `data/daily_data/reports/`。修复后请重新制作行情快照，既有快照不会随主库变化。

## 运行回测

```sh
uv run --locked python -m backtest run strategy/limit_up_lowest/strategy.py
```

默认先通过 SQLite backup 制作内容寻址快照；已有快照可通过 `--snapshot PATH` 复用。策略需要的涨跌停数据须单独准备，见 [示例策略](strategy/limit_up_lowest/README.md)。每次运行在策略目录的 `results/` 中生成 SQLite 结果库、交互 HTML 和 PDF。

回测采用盘前、开盘、收盘后三个回调，支持 T+1、状态查询、停牌估值、退市归零、逐日指标及中断续跑。它使用当日事后确认资格池和理想化开收盘成交，无手续费、滑点或流动性约束；详细行为和限制见 [策略开发指南](docs/backtest/guide.md)。

## 目录与文档

```text
src/
  get_data/          获取、增量更新、标签及派生表的正式实现
  backtest/          回测引擎、结果存储、HTML/PDF 报告
  temporary/         历史临时代码，不参与正式运行或安装
strategy/            策略、输入与结果
data/               本地行情库、快照与审计输出
tests/              数据库流程的离线测试
docs/database/      获取维护、结构契约、SQL 查询、接口参考
docs/backtest/      策略开发、引擎行为与结果存储
```

| 文档 | 内容 |
| --- | --- |
| [数据库获取与迁移](docs/database/operations.md) | 首次建库、GST/G*ST 修复、增量更新、断点续传、迁移文件与退出码 |
| [数据库结构与状态契约](docs/database/schema.md) | 日历、资格表、历史身份、标签、来源覆盖、事务及规则 |
| [SQLite 查询示例](docs/database/querying.md) | 字段单位、股票池、历史状态、缺口检查、指数对齐与分批读取 |
| [Tushare 接口参考](docs/database/api_reference.md) | 原接口目录、全部接口摘要及供应商链接 |
| [策略开发指南](docs/backtest/guide.md) | 策略范式、Context API、配置、运行及报告 |
| [回测稳健性检验](docs/analyse/design.md#运行与查看报告) | 固定持仓置换、十段独立回测与交互报告 |
| [回测架构与存储契约](docs/backtest/design.md) | 阶段时序、价格假设、账本、指标公式、事务及恢复 |

`data/daily_data/update.py` 保留为增量更新兼容入口。正式程序不依赖 `temporary/`，可在迁移时省略该目录。

Git 忽略虚拟环境、数据库、策略 SQLite 输入、回测产物和凭据。换机时提交/复制 `.python-version`、`pyproject.toml`、`uv.lock` 和正式源码，在目标机器执行 `uv sync --locked`；数据与凭据另行迁移或重新获取。

## 验证

```sh
uv lock --check
uv run --locked python -m unittest discover -s tests -v
uv run --locked python -m unittest discover -s src/backtest/tests -v
```

测试使用临时数据库与模拟接口，不访问真实行情库或 Token。
