# Tushare 股票数据：完整目录与接口摘要


- 核对日期：2026-11-22（Asia/Shanghai）。
- 目录来源：[股票数据总览](https://tushare.pro/document/2?doc_id=14)。
- 覆盖范围：左侧“股票数据”节点及其全部后代，共111页：1个总览、8个分类页、102个接口页。
- 读取情况：111页均成功读取；其中3个分类页正文为空，102个接口页均有正文。
- 参数部分列出网页参数表中的名称和必选标记；条件必选、类型、默认值、单位及完整含义仍需点击原文核对。
- 输出部分记录字段表条目数，并仅列举前12个字段；它不是完整字段表。积分、限量和更新时间是读取当时的页面说明。
- ETF、指数、港股、美股等同级栏目不在本次目录范围内；正文中的跨栏目链接仅在相关说明中保留。

本文保留原接口目录和全部接口摘要，属于采集时的供应商参考快照；本项目实际调用范围与操作入口见 [维护流程](operations.md)。

## 总览与代码规则

本项目历史状态标签采用 `namechange`（历史名称有效区间）、`suspend_d`
（逐日停复牌）及 `stock_basic`（上市/退市日期）。2000 积分流程不调用需要
3000 积分的 `stock_st`。`namechange` 的输入起止日期筛选公告日期，项目按证券
获取完整名称历史后再按输出有效区间判断 ST；不把当前简称用于历史日期。
停复牌接口中 `S` 为停牌、`R` 为复牌，`suspend_timing` 仅日内停牌有值。
实现口径及缺失处理见 [数据存储与维护](schema.md)。依据：
[曾用名](https://tushare.pro/document/2?doc_id=100)、
[停复牌](https://tushare.pro/document/2?doc_id=214)、
[ST 名单权限](https://tushare.pro/document/2?doc_id=397)。

Tushare 的股票接口覆盖证券基础资料、行情、财务、公司行为与资金交易等主题。证券标识通常通过 `ts_code` 传入，使用带市场后缀的代码。

| 市场 | 交易所标识 | 代码后缀 |
| --- | --- | --- |
| 上海 | `SSE` | `.SH` |
| 深圳 | `SZSE` | `.SZ` |
| 北京 | `BSE` | `.BJ` |
| 香港 | `HKEX` | `.HK` |

来源：[上市公司数据总览](https://tushare.pro/document/2?doc_id=14)。

## 分类目录

| 分类 | 接口页数 | 原站分类页 |
| --- | ---: | --- |
| [基础数据](#category-24) | 13 | [doc_id=24](https://tushare.pro/document/2?doc_id=24) |
| [行情数据](#category-15) | 17 | [doc_id=15](https://tushare.pro/document/2?doc_id=15) |
| [财务数据](#category-16) | 10 | [doc_id=16](https://tushare.pro/document/2?doc_id=16) |
| [参考数据](#category-17) | 15 | [doc_id=17](https://tushare.pro/document/2?doc_id=17) |
| [特色数据](#category-291) | 11 | [doc_id=291](https://tushare.pro/document/2?doc_id=291) |
| [两融及转融通](#category-330) | 7 | [doc_id=330](https://tushare.pro/document/2?doc_id=330) |
| [资金流向数据](#category-342) | 7 | [doc_id=342](https://tushare.pro/document/2?doc_id=342) |
| [打板专题数据](#category-346) | 22 | [doc_id=346](https://tushare.pro/document/2?doc_id=346) |

<a id="category-24"></a>

## 基础数据

基础资料用于确定证券范围、交易日期及公司身份；具体接口还涉及管理层、上市状态和代码变更。 [分类来源](https://tushare.pro/document/2?doc_id=24)

| 文档 | 接口 | 原文 |
| --- | --- | --- |
| [股票列表](#doc-25) | `stock_basic` | [doc_id=25](https://tushare.pro/document/2?doc_id=25) |
| [每日股本（盘前）](#doc-329) | `stk_premarket` | [doc_id=329](https://tushare.pro/document/2?doc_id=329) |
| [交易日历](#doc-26) | `trade_cal` | [doc_id=26](https://tushare.pro/document/2?doc_id=26) |
| [ST股票列表](#doc-397) | `stock_st` | [doc_id=397](https://tushare.pro/document/2?doc_id=397) |
| [ST风险警示板股票](#doc-423) | `st` | [doc_id=423](https://tushare.pro/document/2?doc_id=423) |
| [沪深港通股票列表](#doc-398) | `stock_hsgt` | [doc_id=398](https://tushare.pro/document/2?doc_id=398) |
| [股票曾用名](#doc-100) | `namechange` | [doc_id=100](https://tushare.pro/document/2?doc_id=100) |
| [上市公司基本信息](#doc-112) | `stock_company` | [doc_id=112](https://tushare.pro/document/2?doc_id=112) |
| [上市公司管理层](#doc-193) | `stk_managers` | [doc_id=193](https://tushare.pro/document/2?doc_id=193) |
| [管理层薪酬和持股](#doc-194) | `stk_rewards` | [doc_id=194](https://tushare.pro/document/2?doc_id=194) |
| [北交所新旧代码对照](#doc-375) | `bse_mapping` | [doc_id=375](https://tushare.pro/document/2?doc_id=375) |
| [IPO新股上市](#doc-123) | `new_share` | [doc_id=123](https://tushare.pro/document/2?doc_id=123) |
| [股票历史列表](#doc-262) | `bak_basic` | [doc_id=262](https://tushare.pro/document/2?doc_id=262) |

<a id="doc-25"></a>

### 股票列表

原文：[股票基础信息](https://tushare.pro/document/2?doc_id=25) · doc_id=25 · 接口：`stock_basic`

stock_basic 用于建立股票主表，含代码、名称、地域、行业、上市状态和实控人等资料。门槛为2000积分，每分钟50次、每次最多6000行；宜拉取后本地复用。PE、PB及股本指标需查 daily_basic。

- 输入参数名：`ts_code`、`name`、`market`、`list_status`、`exchange`、`is_hs`。
- 参数表标为必选：无（仍可能有组合条件）。
- 输出字段表：17项；前12项：`ts_code`、`symbol`、`name`、`area`、`industry`、`fullname`、`enname`、`cnspell`、`market`、`exchange`、`curr_type`、`list_status`。

<a id="doc-329"></a>

### 每日股本（盘前）

原文：[股本情况（盘前）](https://tushare.pro/document/2?doc_id=329) · doc_id=329 · 接口：`stk_premarket`

stk_premarket 提供盘前股本、前收盘价及涨跌停价。历史从2024-05-01开始，9:00与18:10各更新一次；每次最多8000条，可分批查询。需另外申请“盘前股本”权限。

- 输入参数名：`ts_code`、`trade_date`、`start_date`、`end_date`。
- 参数表标为必选：无（仍可能有组合条件）。
- 输出字段表：7项；字段名：`trade_date`、`ts_code`、`total_share`、`float_share`、`pre_close`、`up_limit`、`down_limit`。

<a id="doc-26"></a>

### 交易日历

原文：[交易日历](https://tushare.pro/document/2?doc_id=26) · doc_id=26 · 接口：`trade_cal`

trade_cal 查询交易所开闭市日期和前一交易日，默认选择上交所。需2000积分；页面说明北交所可参照沪深交易日历。

- 输入参数名：`exchange`、`start_date`、`end_date`、`is_open`。
- 参数表标为必选：无（仍可能有组合条件）。
- 输出字段表：4项；字段名：`exchange`、`cal_date`、`is_open`、`pretrade_date`。

<a id="doc-397"></a>

### ST股票列表

原文：[ST股票列表](https://tushare.pro/document/2?doc_id=397) · doc_id=397 · 接口：`stock_st`

stock_st 按交易日还原ST名单，也能筛选个股或日期范围。需3000积分；9:20更新，每次最多1000行。历史起点为2000-01-01，更早记录无法补全。

- 输入参数名：`ts_code`、`trade_date`、`start_date`、`end_date`。
- 参数表标为必选：无（仍可能有组合条件）。
- 输出字段表：5项；字段名：`ts_code`、`name`、`trade_date`、`type`、`type_name`。

<a id="doc-423"></a>

### ST风险警示板股票

原文：[ST风险警示板股票](https://tushare.pro/document/2?doc_id=423) · doc_id=423 · 接口：`st`

st 记录风险警示的公告日、实施日、类别及原因，适合检查个股ST事件。需6000积分，每次上限1000条；历史查询可按股票拆分。

- 输入参数名：`ts_code`、`pub_date`、`imp_date`。
- 参数表标为必选：无（仍可能有组合条件）。
- 输出字段表：7项；字段名：`ts_code`、`name`、`pub_date`、`imp_date`、`st_type`、`st_reason`、`st_explain`。

<a id="doc-398"></a>

### 沪深港通股票列表

原文：[沪深港通股票列表](https://tushare.pro/document/2?doc_id=398) · doc_id=398 · 接口：`stock_hsgt`

stock_hsgt 按互联互通方向查询每日标的名单。历史从2025-08-12起，9:20更新；需3000积分，每次最多2000行，可按类型分批请求。

- 输入参数名：`ts_code`、`trade_date`、`type`、`start_date`、`end_date`。
- 参数表标为必选：`type`。
- 输出字段表：5项；字段名：`ts_code`、`trade_date`、`type`、`name`、`type_name`。

<a id="doc-100"></a>

### 股票曾用名

原文：[股票曾用名](https://tushare.pro/document/2?doc_id=100) · doc_id=100 · 接口：`namechange`

namechange 提供股票名称变更历史，包括名称适用区间、公告日及更名原因；可按证券代码和日期范围过滤。页面未给出积分、频率或单次条数门槛。

- 输入参数名：`ts_code`、`start_date`、`end_date`。
- 参数表标为必选：无（仍可能有组合条件）。
- 输出字段表：6项；字段名：`ts_code`、`name`、`start_date`、`end_date`、`ann_date`、`change_reason`。

<a id="doc-112"></a>

### 上市公司基本信息

原文：[上市公司基本信息](https://tushare.pro/document/2?doc_id=112) · doc_id=112 · 接口：`stock_company`

stock_company 查询公司全称、注册及成立资料、主要负责人、联系方式、员工规模和业务范围。至少120积分可用；每次最多4500条，可分交易所拉取。

- 输入参数名：`ts_code`、`exchange`。
- 参数表标为必选：无（仍可能有组合条件）。
- 输出字段表：18项；前12项：`ts_code`、`com_name`、`com_id`、`exchange`、`chairman`、`manager`、`secretary`、`reg_capital`、`setup_date`、`province`、`city`、`introduction`。

<a id="doc-193"></a>

### 上市公司管理层

原文：[上市公司管理层](https://tushare.pro/document/2?doc_id=193) · doc_id=193 · 接口：`stk_managers`

stk_managers 提供董监高姓名、职务、任期、教育背景与履历等资料，并支持公告日期筛选。需2000积分；5000积分以上可获得较高调用频率。

- 输入参数名：`ts_code`、`ann_date`、`start_date`、`end_date`。
- 参数表标为必选：无（仍可能有组合条件）。
- 输出字段表：12项；字段名：`ts_code`、`ann_date`、`name`、`gender`、`lev`、`title`、`edu`、`national`、`birthday`、`begin_date`、`end_date`、`resume`。

<a id="doc-194"></a>

### 管理层薪酬和持股

原文：[管理层薪酬和持股](https://tushare.pro/document/2?doc_id=194) · doc_id=194 · 接口：`stk_rewards`

stk_rewards 按公司及报告期查询管理人员的薪酬和持股数量，同时返回公告日与职务。需2000积分；5000积分以上调用频率较高。

- 输入参数名：`ts_code`、`end_date`。
- 参数表标为必选：`ts_code`。
- 输出字段表：7项；字段名：`ts_code`、`ann_date`、`end_date`、`name`、`title`、`reward`、`hold_vol`。

<a id="doc-375"></a>

### 北交所新旧代码对照

原文：[北交所新旧代码对照表](https://tushare.pro/document/2?doc_id=375) · doc_id=375 · 接口：`bse_mapping`

bse_mapping 对照北交所股票变更前后的代码，并提供名称和上市日期。需2000积分，每次最多1000条；页面称现有记录不足300条。

- 输入参数名：`o_code`、`n_code`。
- 参数表标为必选：无（仍可能有组合条件）。
- 输出字段表：4项；字段名：`name`、`o_code`、`n_code`、`list_date`。

<a id="doc-123"></a>

### IPO新股上市

原文：[IPO新股列表](https://tushare.pro/document/2?doc_id=123) · doc_id=123 · 接口：`new_share`

new_share 查询IPO申购与上市信息，涵盖发行量、价格、市盈率、申购上限、募集金额和中签率。需120积分，每次最多2000条，无累计总量限制。

- 输入参数名：`start_date`、`end_date`。
- 参数表标为必选：无（仍可能有组合条件）。
- 输出字段表：12项；字段名：`ts_code`、`sub_code`、`name`、`ipo_date`、`issue_date`、`amount`、`market_amount`、`price`、`pe`、`limit_amount`、`funds`、`ballot`。

<a id="doc-262"></a>

### 股票历史列表

原文：[股票历史列表（历史每天股票列表）](https://tushare.pro/document/2?doc_id=262) · doc_id=262 · 接口：`bak_basic`

bak_basic 保存每日股票基础资料快照，包含行业、估值、股本和部分财务指标。历史始于2016年；正式使用需5000积分，每次最多7000条，可逐日取得历史。

- 输入参数名：`trade_date`、`ts_code`。
- 参数表标为必选：无（仍可能有组合条件）。
- 输出字段表：24项；前12项：`trade_date`、`ts_code`、`name`、`industry`、`area`、`pe`、`float_share`、`total_share`、`total_assets`、`liquid_assets`、`fixed_assets`、`reserved`。

<a id="category-15"></a>

## 行情数据

行情类别包含不同频率的价格、成交、复权及交易状态数据。各接口的时间覆盖、权限和输出口径分别规定。 [分类来源](https://tushare.pro/document/2?doc_id=15)

| 文档 | 接口 | 原文 |
| --- | --- | --- |
| [历史日线](#doc-27) | `daily` | [doc_id=27](https://tushare.pro/document/2?doc_id=27) |
| [实时日线](#doc-372) | `rt_k` | [doc_id=372](https://tushare.pro/document/2?doc_id=372) |
| [历史分钟](#doc-370) | `stk_mins` | [doc_id=370](https://tushare.pro/document/2?doc_id=370) |
| [实时分钟](#doc-374) | `rt_min` | [doc_id=374](https://tushare.pro/document/2?doc_id=374) |
| [A股实时分钟-日累计](#doc-457) | `rt_min_daily` | [doc_id=457](https://tushare.pro/document/2?doc_id=457) |
| [周线行情](#doc-144) | `weekly` | [doc_id=144](https://tushare.pro/document/2?doc_id=144) |
| [月线行情](#doc-145) | `monthly` | [doc_id=145](https://tushare.pro/document/2?doc_id=145) |
| [复权行情](#doc-146) | `pro_bar` | [doc_id=146](https://tushare.pro/document/2?doc_id=146) |
| [周/月线行情(每日更新)](#doc-336) | `stk_weekly_monthly` | [doc_id=336](https://tushare.pro/document/2?doc_id=336) |
| [周/月线复权行情(每日更新)](#doc-365) | `stk_week_month_adj` | [doc_id=365](https://tushare.pro/document/2?doc_id=365) |
| [复权因子](#doc-28) | `adj_factor` | [doc_id=28](https://tushare.pro/document/2?doc_id=28) |
| [每日指标](#doc-32) | `daily_basic` | [doc_id=32](https://tushare.pro/document/2?doc_id=32) |
| [通用行情接口](#doc-109) | `pro_bar` | [doc_id=109](https://tushare.pro/document/2?doc_id=109) |
| [每日涨跌停价格](#doc-183) | `stk_limit` | [doc_id=183](https://tushare.pro/document/2?doc_id=183) |
| [每日停复牌信息](#doc-214) | `suspend_d` | [doc_id=214](https://tushare.pro/document/2?doc_id=214) |
| [沪深股通十大成交股](#doc-48) | `hsgt_top10` | [doc_id=48](https://tushare.pro/document/2?doc_id=48) |
| [备用行情](#doc-255) | `bak_daily` | [doc_id=255](https://tushare.pro/document/2?doc_id=255) |

<a id="doc-27"></a>

### 历史日线

原文：[A股日线行情](https://tushare.pro/document/2?doc_id=27) · doc_id=27 · 接口：`daily`

daily 返回未复权日K线，停牌日不产生记录，交易日15:00—16:00入库。120积分可试用、每分钟50次；5000积分每分钟500次，单次6000行。全市场历史宜按日期分批，日期格式为YYYYMMDD。

- 输入参数名：`ts_code`、`trade_date`、`start_date`、`end_date`。
- 参数表标为必选：无（仍可能有组合条件）。
- 输出字段表：13项；前12项：`ts_code`、`trade_date`、`open`、`high`、`low`、`close`、`pre_close`、`change`、`pct_chg`、`vol`、`amount`、`ah_vol`。

<a id="doc-372"></a>

### 实时日线

原文：[A股实时日线](https://tushare.pro/document/2?doc_id=372) · doc_id=372 · 接口：`rt_k`

rt_k 提供盘中实时日K线，可指定代码或使用代码通配符，单次最多6000条。代码必须带.SH、.SZ或.BJ后缀；需另外申请“A股日线RT”权限。

- 输入参数名：`ts_code`。
- 参数表标为必选：`ts_code`。
- 输出字段表：15项；前12项：`ts_code`、`name`、`pre_close`、`high`、`open`、`low`、`close`、`vol`、`amount`、`num`、`ask_price1`、`ask_volume1`。

<a id="doc-370"></a>

### 历史分钟

原文：[股票历史分钟行情](https://tushare.pro/document/2?doc_id=370) · doc_id=370 · 接口：`stk_mins`

stk_mins 查询2010-01-01以来的1、5、15、30、60分钟历史K线，支持SDK及HTTP。需独立“A股历史分钟”权限；每次8000行、每分钟500次，滚动24小时最多30万次，可按代码和时间分段。

- 输入参数名：`ts_code`、`freq`、`start_date`、`end_date`。
- 参数表标为必选：`ts_code`、`freq`。
- 输出字段表：8项；字段名：`ts_code`、`trade_time`、`open`、`close`、`high`、`low`、`vol`、`amount`。

<a id="doc-374"></a>

### 实时分钟

原文：[A股实时分钟](https://tushare.pro/document/2?doc_id=374) · doc_id=374 · 接口：`rt_min`

rt_min 返回已结束周期的实时分钟K线，支持1至60分钟及多个逗号分隔代码；每次上限1000行，需“A股分钟RT”权限。当前也含沪深转债，沪市转债须传topic=HQ_BND_MIN。

- 输入参数名：`freq`、`ts_code`。
- 参数表标为必选：`freq`、`ts_code`。
- 输出字段表：8项；字段名：`ts_code`、`time`、`open`、`close`、`high`、`low`、`vol`、`amount`。

<a id="doc-457"></a>

### A股实时分钟-日累计

原文：[A股实时分钟-日累计](https://tushare.pro/document/2?doc_id=457) · doc_id=457 · 接口：`rt_min_daily`

rt_min_daily 可一次取回单只A股从当日开盘到查询时刻的分钟历史。使用前需另行开通“A股分钟RT”权限。

- 输入参数名：`freq`、`ts_code`。
- 参数表标为必选：`freq`、`ts_code`。
- 输出字段表：9项；字段名：`ts_code`、`freq`、`time`、`open`、`close`、`high`、`low`、`vol`、`amount`。

<a id="doc-144"></a>

### 周线行情

原文：[周线行情](https://tushare.pro/document/2?doc_id=144) · doc_id=144 · 接口：`weekly`

weekly 提供A股周K线，每周最后一个交易日更新。需2000积分，每次最多6000行，无累计总量限制，可按交易日分批查询；需要每天更新的周进度应查看每日更新的周线接口。

- 输入参数名：`ts_code`、`trade_date`、`start_date`、`end_date`。
- 参数表标为必选：无（仍可能有组合条件）。
- 输出字段表：11项；字段名：`ts_code`、`trade_date`、`close`、`open`、`high`、`low`、`pre_close`、`change`、`pct_chg`、`vol`、`amount`。

<a id="doc-145"></a>

### 月线行情

原文：[月线行情](https://tushare.pro/document/2?doc_id=145) · doc_id=145 · 接口：`monthly`

monthly 提供A股月K线及月度成交量、成交额等行情字段。需2000积分，每次最多4500行，无累计总量限制；支持按股票、交易日或日期区间筛选。

- 输入参数名：`ts_code`、`trade_date`、`start_date`、`end_date`。
- 参数表标为必选：无（仍可能有组合条件）。
- 输出字段表：11项；字段名：`ts_code`、`trade_date`、`close`、`open`、`high`、`low`、`pre_close`、`change`、`pct_chg`、`vol`、`amount`。

<a id="doc-146"></a>

### 复权行情

原文：[A股复权行情](https://tushare.pro/document/2?doc_id=146) · doc_id=146 · 接口：`pro_bar`

pro_bar 在SDK内利用复权因子计算行情，要求SDK≥1.2.26，不能直接以HTTP调用。前复权锚定请求的end_date，并采用分红再投口径，因此可能不同于行情软件。页面“仅支持日线”说明与周/月示例并存，使用时需核验。

- 输入参数名：`ts_code`、`start_date`、`end_date`、`asset`、`adj`、`freq`、`ma`。
- 参数表标为必选：`ts_code`、`asset`、`freq`。
- 本页未单独列出输出字段表；输出应结合关联行情接口说明核对。

<a id="doc-336"></a>

### 周/月线行情(每日更新)

原文：[股票周/月线行情(每日更新)](https://tushare.pro/document/2?doc_id=336) · doc_id=336 · 接口：`stk_weekly_monthly`

stk_weekly_monthly 每日更新股票周、月K线，适合跟踪尚未结束的周期。需2000积分，每次上限6000行，无累计总量限制；可按交易日分批拉取。

- 输入参数名：`ts_code`、`trade_date`、`start_date`、`end_date`、`freq`。
- 参数表标为必选：`freq`。
- 输出字段表：13项；前12项：`ts_code`、`trade_date`、`end_date`、`freq`、`open`、`high`、`low`、`close`、`pre_close`、`vol`、`amount`、`change`。

<a id="doc-365"></a>

### 周/月线复权行情(每日更新)

原文：[股票周/月线行情(复权--每日更新)](https://tushare.pro/document/2?doc_id=365) · doc_id=365 · 接口：`stk_week_month_adj`

stk_week_month_adj 返回按日更新的周、月复权行情，每天17:00和22:00更新。需2000积分，每次最多6000行，无累计总量限制，可按交易日循环查询。

- 输入参数名：`ts_code`、`trade_date`、`start_date`、`end_date`、`freq`。
- 参数表标为必选：`freq`。
- 输出字段表：21项；前12项：`ts_code`、`trade_date`、`end_date`、`freq`、`open`、`high`、`low`、`close`、`pre_close`、`open_qfq`、`high_qfq`、`low_qfq`。

<a id="doc-28"></a>

### 复权因子

原文：[复权因子](https://tushare.pro/document/2?doc_id=28) · doc_id=28 · 接口：`adj_factor`

adj_factor 查询平台计算的复权因子，既支持个股全历史，也支持单日全市场。当天因子约9:15—9:20入库；需2000积分，5000积分以上支持较高调用频率。

- 输入参数名：`ts_code`、`trade_date`、`start_date`、`end_date`。
- 参数表标为必选：无（仍可能有组合条件）。
- 输出字段表：3项；字段名：`ts_code`、`trade_date`、`adj_factor`。

<a id="doc-32"></a>

### 每日指标

原文：[每日指标](https://tushare.pro/document/2?doc_id=32) · doc_id=32 · 接口：`daily_basic`

daily_basic 提供换手率、估值、股息率、股本及市值等每日指标，交易日15:00—17:00更新。至少2000积分，每次6000条，可按日期分批取数；5000积分无累计总量限制。

- 输入参数名：`ts_code`、`trade_date`、`start_date`、`end_date`。
- 参数表标为必选：`ts_code`。
- 输出字段表：19项；前12项：`ts_code`、`trade_date`、`close`、`turnover_rate`、`turnover_rate_f`、`volume_ratio`、`pe`、`pe_ttm`、`pb`、`ps`、`ps_ttm`、`dv_ratio`。

<a id="doc-109"></a>

### 通用行情接口

原文：[通用行情接口](https://tushare.pro/document/2?doc_id=109) · doc_id=109 · 接口：`pro_bar`

pro_bar 在SDK端统一股票、指数、ETF、期货及期权行情，也支持复权和动态均线；不能直接HTTP调用，各品种权限分别适用。动态指标起始行可能为NaN，计算均线须向前多取足够交易日后裁剪目标区间。

- 输入参数名：`ts_code`、`start_date`、`end_date`、`asset`、`adj`、`freq`、`ma`、`factors`、`adjfactor`。
- 参数表标为必选：`ts_code`。
- 本页未单独列出输出字段表；输出应结合关联行情接口说明核对。

<a id="doc-183"></a>

### 每日涨跌停价格

原文：[每日涨跌停价格](https://tushare.pro/document/2?doc_id=183) · doc_id=183 · 接口：`stk_limit`

stk_limit 提供A/B股与基金的每日涨跌停价，覆盖自2007-01-04起的数据，当日约9:00更新。需2000积分，每次最多5800条，无累计总量限制；分钟调用频率随积分档位变化。

- 输入参数名：`ts_code`、`trade_date`、`start_date`、`end_date`。
- 参数表标为必选：无（仍可能有组合条件）。
- 输出字段表：7项；字段名：`trade_date`、`ts_code`、`pre_close`、`up_limit`、`down_limit`、`asset_type`、`exchange`。

<a id="doc-214"></a>

### 每日停复牌信息

原文：[每日停复牌信息](https://tushare.pro/document/2?doc_id=214) · doc_id=214 · 接口：`suspend_d`

suspend_d 按日期查询股票停复牌状态与停牌时段。历史从2000-01-03开始，不定期更新；需2000积分，每次最多5000行，5000积分可提高请求频率。

- 输入参数名：`ts_code`、`trade_date`、`start_date`、`end_date`、`suspend_type`。
- 参数表标为必选：无（仍可能有组合条件）。
- 输出字段表：4项；字段名：`ts_code`、`trade_date`、`suspend_timing`、`suspend_type`。

<a id="doc-48"></a>

### 沪深股通十大成交股

原文：[沪深股通十大成交股](https://tushare.pro/document/2?doc_id=48) · doc_id=48 · 接口：`hsgt_top10`

hsgt_top10 查询沪股通、深股通每日成交额前十的个股明细，含排名、买卖金额及净买入。当天记录通常18:00—20:00更新；页面未注明积分或条数上限。

- 输入参数名：`ts_code`、`trade_date`、`start_date`、`end_date`、`market_type`。
- 参数表标为必选：无（仍可能有组合条件）。
- 输出字段表：11项；字段名：`trade_date`、`ts_code`、`name`、`close`、`change`、`rank`、`market_type`、`amount`、`net_amount`、`buy`、`sell`。

<a id="doc-255"></a>

### 备用行情

原文：[备用行情](https://tushare.pro/document/2?doc_id=255) · doc_id=255 · 接口：`bak_daily`

bak_daily 提供日行情及额外交易指标，历史约从2017年中开始，早期个别日期缺失。正式权限需5000积分；每次最多7000行，可按日期分批查询。

- 输入参数名：`ts_code`、`trade_date`、`start_date`、`end_date`、`offset`、`limit`。
- 参数表标为必选：无（仍可能有组合条件）。
- 输出字段表：31项；前12项：`ts_code`、`trade_date`、`name`、`pct_change`、`close`、`change`、`open`、`high`、`low`、`pre_close`、`vol_ratio`、`turn_over`。

<a id="category-16"></a>

## 财务数据

围绕公司定期报告及业绩信息提供数据。公告日、报告期和报告类型含义不同，使用时应分别筛选。 [分类来源](https://tushare.pro/document/2?doc_id=16)

| 文档 | 接口 | 原文 |
| --- | --- | --- |
| [利润表](#doc-33) | `income` | [doc_id=33](https://tushare.pro/document/2?doc_id=33) |
| [资产负债表](#doc-36) | `balancesheet` | [doc_id=36](https://tushare.pro/document/2?doc_id=36) |
| [现金流量表](#doc-44) | `cashflow` | [doc_id=44](https://tushare.pro/document/2?doc_id=44) |
| [业绩预告](#doc-45) | `forecast` | [doc_id=45](https://tushare.pro/document/2?doc_id=45) |
| [业绩快报](#doc-46) | `express` | [doc_id=46](https://tushare.pro/document/2?doc_id=46) |
| [分红送股数据](#doc-103) | `dividend` | [doc_id=103](https://tushare.pro/document/2?doc_id=103) |
| [财务指标数据](#doc-79) | `fina_indicator` | [doc_id=79](https://tushare.pro/document/2?doc_id=79) |
| [财务审计意见](#doc-80) | `fina_audit` | [doc_id=80](https://tushare.pro/document/2?doc_id=80) |
| [主营业务构成](#doc-81) | `fina_mainbz` | [doc_id=81](https://tushare.pro/document/2?doc_id=81) |
| [财报披露日期表](#doc-162) | `disclosure_date` | [doc_id=162](https://tushare.pro/document/2?doc_id=162) |

<a id="doc-33"></a>

### 利润表

原文：[利润表](https://tushare.pro/document/2?doc_id=33) · doc_id=33 · 接口：`income`

income 查询单只股票的利润表，含各类收入、费用、利润和每股收益。需2000积分；全市场单季数据使用income_vip并指定period，需5000积分。须结合公告日、报告期和报表类型区分版本。

- 输入参数名：`ts_code`、`ann_date`、`f_ann_date`、`start_date`、`end_date`、`period`、`report_type`、`comp_type`。
- 参数表标为必选：`ts_code`。
- 输出字段表：94项；前12项：`ts_code`、`ann_date`、`f_ann_date`、`end_date`、`report_type`、`comp_type`、`end_type`、`basic_eps`、`diluted_eps`、`total_revenue`、`revenue`、`int_income`。

<a id="doc-36"></a>

### 资产负债表

原文：[资产负债表](https://tushare.pro/document/2?doc_id=36) · doc_id=36 · 接口：`balancesheet`

balancesheet 查询单股资产、负债及权益项目，需2000积分。全市场某报告期可改用balancesheet_vip并传period，门槛5000积分；应区分合并、母公司及调整前后的报表口径。

- 输入参数名：`ts_code`、`ann_date`、`start_date`、`end_date`、`period`、`report_type`、`comp_type`。
- 参数表标为必选：`ts_code`。
- 输出字段表：158项；前12项：`ts_code`、`ann_date`、`f_ann_date`、`end_date`、`report_type`、`comp_type`、`end_type`、`total_share`、`cap_rese`、`undistr_porfit`、`surplus_rese`、`special_rese`。

<a id="doc-44"></a>

### 现金流量表

原文：[现金流量表](https://tushare.pro/document/2?doc_id=44) · doc_id=44 · 接口：`cashflow`

cashflow 查询单股经营、投资、筹资现金流及相关调节项目，需2000积分。全市场某报告期使用cashflow_vip并传period，需5000积分；注意报告期、公告日期和报表版本的区别。

- 输入参数名：`ts_code`、`ann_date`、`f_ann_date`、`start_date`、`end_date`、`period`、`report_type`、`comp_type`、`is_calc`。
- 参数表标为必选：`ts_code`。
- 输出字段表：97项；前12项：`ts_code`、`ann_date`、`f_ann_date`、`end_date`、`comp_type`、`report_type`、`end_type`、`net_profit`、`finan_exp`、`c_fr_sale_sg`、`recp_tax_rends`、`n_depos_incr_fi`。

<a id="doc-45"></a>

### 业绩预告

原文：[业绩预告](https://tushare.pro/document/2?doc_id=45) · doc_id=45 · 接口：`forecast`

forecast 提供业绩预告类别、利润及增幅区间、首发公告日和变动原因。需2000积分，每次3500行，每日20:00—21:00更新。普通接口面向单股历史；单季全市场查询用forecast_vip，需5000积分。

- 输入参数名：`ts_code`、`ann_date`、`start_date`、`end_date`、`period`、`type`。
- 参数表标为必选：无（仍可能有组合条件）。
- 输出字段表：12项；字段名：`ts_code`、`ann_date`、`end_date`、`type`、`p_change_min`、`p_change_max`、`net_profit_min`、`net_profit_max`、`last_parent_net`、`first_ann_date`、`summary`、`change_reason`。

<a id="doc-46"></a>

### 业绩快报

原文：[业绩快报](https://tushare.pro/document/2?doc_id=46) · doc_id=46 · 接口：`express`

express 提供财务正式报告前的业绩快报，包括收入利润、资产权益、同比变化及审计标记。需2000积分；单季全市场数据改用express_vip，需5000积分，普通接口按单股查询。

- 输入参数名：`ts_code`、`ann_date`、`start_date`、`end_date`、`period`。
- 参数表标为必选：`ts_code`。
- 输出字段表：32项；前12项：`ts_code`、`ann_date`、`end_date`、`revenue`、`operate_profit`、`total_profit`、`n_income`、`total_assets`、`total_hldr_eqy_exc_min_int`、`diluted_eps`、`diluted_roe`、`yoy_net_profit`。

<a id="doc-103"></a>

### 分红送股数据

原文：[分红送股](https://tushare.pro/document/2?doc_id=103) · doc_id=103 · 接口：`dividend`

dividend 记录分红送转方案、进度、派息额以及登记、除权、派息等日期。历史始于2000-01-01，每日20:00—21:00更新；需2000积分，每次最多2000行，查询条件至少填写一项。

- 输入参数名：`ts_code`、`ann_date`、`record_date`、`ex_date`、`imp_ann_date`。
- 参数表标为必选：无（仍可能有组合条件）。
- 输出字段表：16项；前12项：`ts_code`、`end_date`、`ann_date`、`div_proc`、`stk_div`、`stk_bo_rate`、`stk_co_rate`、`cash_div`、`cash_div_tax`、`record_date`、`ex_date`、`pay_date`。

<a id="doc-79"></a>

### 财务指标数据

原文：[财务指标数据](https://tushare.pro/document/2?doc_id=79) · doc_id=79 · 接口：`fina_indicator`

fina_indicator 提供盈利、偿债、周转、成长和现金流等财务指标，需2000积分。单股请求每次最多100条，可按日期分段；全市场某季度使用fina_indicator_vip，需5000积分。

- 输入参数名：`ts_code`、`ann_date`、`start_date`、`end_date`、`period`。
- 参数表标为必选：`ts_code`。
- 输出字段表：167项；前12项：`ts_code`、`ann_date`、`end_date`、`eps`、`dt_eps`、`total_revenue_ps`、`revenue_ps`、`capital_rese_ps`、`surplus_rese_ps`、`undist_profit_ps`、`extra_item`、`profit_dedt`。

<a id="doc-80"></a>

### 财务审计意见

原文：[财务审计意见](https://tushare.pro/document/2?doc_id=80) · doc_id=80 · 接口：`fina_audit`

fina_audit 查询定期财报对应的审计意见、费用、会计师事务所及签字会计师。需2000积分；可结合股票、公告日期或报告期筛选。

- 输入参数名：`ts_code`、`ann_date`、`start_date`、`end_date`、`period`。
- 参数表标为必选：`ts_code`。
- 输出字段表：7项；字段名：`ts_code`、`ann_date`、`end_date`、`audit_result`、`audit_fees`、`audit_agency`、`audit_sign`。

<a id="doc-81"></a>

### 主营业务构成

原文：[主营业务构成](https://tushare.pro/document/2?doc_id=81) · doc_id=81 · 接口：`fina_mainbz`

fina_mainbz 按产品、地区或行业拆分主营收入、成本和利润，并给出币种。需2000积分，每次最多100行；单季全市场使用fina_mainbz_vip，需5000积分，普通接口面向单股历史。

- 输入参数名：`ts_code`、`period`、`type`、`start_date`、`end_date`。
- 参数表标为必选：`ts_code`。
- 输出字段表：9项；字段名：`ts_code`、`end_date`、`bz_item`、`bz_code`、`bz_sales`、`bz_profit`、`bz_cost`、`curr_type`、`update_flag`。

<a id="doc-162"></a>

### 财报披露日期表

原文：[财报披露计划](https://tushare.pro/document/2?doc_id=162) · doc_id=162 · 接口：`disclosure_date`

disclosure_date 查询财报预约披露、实际披露及变更日期。需2000积分，每次最多6000条，无累计总量限制；可按股票、报告期或相关日期筛选。

- 输入参数名：`ts_code`、`end_date`、`pre_date`、`ann_date`、`actual_date`。
- 参数表标为必选：无（仍可能有组合条件）。
- 输出字段表：6项；字段名：`ts_code`、`ann_date`、`end_date`、`pre_date`、`actual_date`、`modify_date`。

<a id="category-17"></a>

## 参考数据

侧重公司行为、股东及市场交易事件。分类介绍里的部分旧入口已经失效，见文末记录。 [分类来源](https://tushare.pro/document/2?doc_id=17)

| 文档 | 接口 | 原文 |
| --- | --- | --- |
| [个股异常波动](#doc-451) | `stk_shock` | [doc_id=451](https://tushare.pro/document/2?doc_id=451) |
| [个股严重异常波动](#doc-452) | `stk_high_shock` | [doc_id=452](https://tushare.pro/document/2?doc_id=452) |
| [交易所重点提示证券](#doc-453) | `stk_alert` | [doc_id=453](https://tushare.pro/document/2?doc_id=453) |
| [前十大股东](#doc-61) | `top10_holders` | [doc_id=61](https://tushare.pro/document/2?doc_id=61) |
| [前十大流通股东](#doc-62) | `top10_floatholders` | [doc_id=62](https://tushare.pro/document/2?doc_id=62) |
| [股权质押统计数据](#doc-110) | `pledge_stat` | [doc_id=110](https://tushare.pro/document/2?doc_id=110) |
| [股权质押明细数据](#doc-111) | `pledge_detail` | [doc_id=111](https://tushare.pro/document/2?doc_id=111) |
| [股票回购](#doc-124) | `repurchase` | [doc_id=124](https://tushare.pro/document/2?doc_id=124) |
| [限售股解禁](#doc-160) | `share_float` | [doc_id=160](https://tushare.pro/document/2?doc_id=160) |
| [大宗交易](#doc-161) | `block_trade` | [doc_id=161](https://tushare.pro/document/2?doc_id=161) |
| [股票开户数据（停）](#doc-164) | `stk_account` | [doc_id=164](https://tushare.pro/document/2?doc_id=164) |
| [股票开户数据（旧）](#doc-165) | `stk_account_old` | [doc_id=165](https://tushare.pro/document/2?doc_id=165) |
| [股东人数](#doc-166) | `stk_holdernumber` | [doc_id=166](https://tushare.pro/document/2?doc_id=166) |
| [股东增减持](#doc-175) | `stk_holdertrade` | [doc_id=175](https://tushare.pro/document/2?doc_id=175) |
| [股票增发](#doc-494) | `stk_seasoned` | [doc_id=494](https://tushare.pro/document/2?doc_id=494) |

<a id="doc-451"></a>

### 个股异常波动

原文：[个股异常波动](https://tushare.pro/document/2?doc_id=451) · doc_id=451 · 接口：`stk_shock`

stk_shock 汇集交易所公布的个股异常波动事件，可查看触发原因与统计期间。调用门槛为6000积分；每次至多1000行，较大范围按证券或日期拆分。

- 输入参数名：`ts_code`、`trade_date`、`start_date`、`end_date`。
- 参数表标为必选：无（仍可能有组合条件）。
- 输出字段表：6项；字段名：`ts_code`、`trade_date`、`name`、`trade_market`、`reason`、`period`。

<a id="doc-452"></a>

### 个股严重异常波动

原文：[个股严重异常波动](https://tushare.pro/document/2?doc_id=452) · doc_id=452 · 接口：`stk_high_shock`

stk_high_shock 面向交易所认定的严重异常波动，返回证券、市场、原因及对应期间。需6000积分；每次上限1000行，可分证券、分日期读取。

- 输入参数名：`ts_code`、`trade_date`、`start_date`、`end_date`。
- 参数表标为必选：无（仍可能有组合条件）。
- 输出字段表：6项；字段名：`ts_code`、`trade_date`、`name`、`trade_market`、`reason`、`period`。

<a id="doc-453"></a>

### 交易所重点提示证券

原文：[交易所重点提示证券](https://tushare.pro/document/2?doc_id=453) · doc_id=453 · 接口：`stk_alert`

stk_alert 查询交易所重点提示的证券，以及提示类别和有效日期范围。需6000积分；每批不超过1000行，可利用证券代码或日期继续查询。

- 输入参数名：`ts_code`、`trade_date`、`start_date`、`end_date`。
- 参数表标为必选：无（仍可能有组合条件）。
- 输出字段表：5项；字段名：`ts_code`、`name`、`start_date`、`end_date`、`type`。

<a id="doc-61"></a>

### 前十大股东

原文：[前十大股东](https://tushare.pro/document/2?doc_id=61) · doc_id=61 · 接口：`top10_holders`

top10_holders 查询公司十大股东及持股数量、比例、变动和股东类别，支持按报告期或公告日期筛选。门槛2000积分，达到5000积分以上可获得更高调用频次。

- 输入参数名：`ts_code`、`period`、`ann_date`、`start_date`、`end_date`。
- 参数表标为必选：`ts_code`。
- 输出字段表：9项；字段名：`ts_code`、`ann_date`、`end_date`、`holder_name`、`hold_amount`、`hold_ratio`、`hold_float_ratio`、`hold_change`、`holder_type`。

<a id="doc-62"></a>

### 前十大流通股东

原文：[前十大流通股东](https://tushare.pro/document/2?doc_id=62) · doc_id=62 · 接口：`top10_floatholders`

top10_floatholders 用于观察公司流通股前十大持有人，返回持仓数量、比例及变化。可按报告期、公告日期检索；2000积分起用，5000积分以上提高频次。

- 输入参数名：`ts_code`、`period`、`ann_date`、`start_date`、`end_date`。
- 参数表标为必选：`ts_code`。
- 输出字段表：9项；字段名：`ts_code`、`ann_date`、`end_date`、`holder_name`、`hold_amount`、`hold_ratio`、`hold_float_ratio`、`hold_change`、`holder_type`。

<a id="doc-110"></a>

### 股权质押统计数据

原文：[股权质押统计数据](https://tushare.pro/document/2?doc_id=110) · doc_id=110 · 接口：`pledge_stat`

pledge_stat 按证券和统计日提供质押次数、限售及非限售质押数量、股本和质押比例，适合汇总层面的质押风险研究。需2000积分，每批最多1000行。

- 输入参数名：`ts_code`、`end_date`。
- 参数表标为必选：无（仍可能有组合条件）。
- 输出字段表：7项；字段名：`ts_code`、`end_date`、`pledge_count`、`unrest_pledge`、`rest_pledge`、`total_share`、`pledge_ratio`。

<a id="doc-111"></a>

### 股权质押明细数据

原文：[股权质押明细](https://tushare.pro/document/2?doc_id=111) · doc_id=111 · 接口：`pledge_detail`

pledge_detail 查询单笔质押中的股东、质押对象、数量、起止日及解除情况，并包含持股和质押占比。门槛2000积分，每次最多1000行，可按公告日期筛选。

- 输入参数名：`ts_code`、`ann_date`、`start_date`、`end_date`。
- 参数表标为必选：无（仍可能有组合条件）。
- 输出字段表：14项；前12项：`ts_code`、`ann_date`、`holder_name`、`pledge_amount`、`start_date`、`end_date`、`is_release`、`release_date`、`pledgor`、`holding_amount`、`pledged_amount`、`p_total_ratio`。

<a id="doc-124"></a>

### 股票回购

原文：[股票回购](https://tushare.pro/document/2?doc_id=124) · doc_id=124 · 接口：`repurchase`

repurchase 提供公司回购的公告、实施进度、数量、金额及价格上下限。需2000积分；输入日期采用YYYYMMDD，可用公告日或日期区间检索。

- 输入参数名：`ann_date`、`start_date`、`end_date`。
- 参数表标为必选：无（仍可能有组合条件）。
- 输出字段表：9项；字段名：`ts_code`、`ann_date`、`end_date`、`proc`、`exp_date`、`vol`、`amount`、`high_limit`、`low_limit`。

<a id="doc-160"></a>

### 限售股解禁

原文：[限售股解禁](https://tushare.pro/document/2?doc_id=160) · doc_id=160 · 接口：`share_float`

share_float 记录解禁日期、数量、比例、持有人及股份类别。120积分可用；单批上限6000行，总数据量未设上限。调用有分钟频次限制，5000积分以上频次更高。

- 输入参数名：`ts_code`、`ann_date`、`float_date`、`start_date`、`end_date`。
- 参数表标为必选：`ts_code`。
- 输出字段表：7项；字段名：`ts_code`、`ann_date`、`float_date`、`float_share`、`float_ratio`、`holder_name`、`share_type`。

<a id="doc-161"></a>

### 大宗交易

原文：[大宗交易](https://tushare.pro/document/2?doc_id=161) · doc_id=161 · 接口：`block_trade`

block_trade 查询股票大宗成交的价格、数量、金额与买卖双方。2000积分起用；每批最多1000行，总量不限，分钟频次受控，5000积分以上可提高频次。

- 输入参数名：`ts_code`、`trade_date`、`start_date`、`end_date`。
- 参数表标为必选：无（仍可能有组合条件）。
- 输出字段表：7项；字段名：`ts_code`、`trade_date`、`price`、`vol`、`amount`、`buyer`、`seller`。

<a id="doc-164"></a>

### 股票开户数据（停）

原文：[股票账户开户数据](https://tushare.pro/document/2?doc_id=164) · doc_id=164 · 接口：`stk_account`

stk_account 为已停止更新的周度开户统计，需600积分。2017-02-10起不再公布当周持仓和交易账户数；页面提示2015-05-08以前的结构应参阅旧版接口，使用历史序列时需检查口径。

- 输入参数名：`date`、`start_date`、`end_date`。
- 参数表标为必选：无（仍可能有组合条件）。
- 输出字段表：5项；字段名：`date`、`weekly_new`、`total`、`weekly_hold`、`weekly_trade`。

<a id="doc-165"></a>

### 股票开户数据（旧）

原文：[股票账户开户数据（旧）](https://tushare.pro/document/2?doc_id=165) · doc_id=165 · 接口：`stk_account_old`

stk_account_old 保存旧口径的沪深开户、活跃、累计及交易账户统计，页面标示覆盖2008年1月至2015-05-29。需600积分，可按时间区间查询；后续口径见stk_account。

- 输入参数名：`start_date`、`end_date`。
- 参数表标为必选：无（仍可能有组合条件）。
- 输出字段表：9项；字段名：`date`、`new_sh`、`new_sz`、`active_sh`、`active_sz`、`total_sh`、`total_sz`、`trade_sh`、`trade_sz`。

<a id="doc-166"></a>

### 股东人数

原文：[股东人数](https://tushare.pro/document/2?doc_id=166) · doc_id=166 · 接口：`stk_holdernumber`

stk_holdernumber 查询公司披露的股东户数，披露时间不固定。2000积分可用，基础频率为每分钟200次；单批最多3000行，总量不限，5000积分以上可提高频次。报告截止日参数拼写为enddate。

- 输入参数名：`ts_code`、`ann_date`、`enddate`、`start_date`、`end_date`。
- 参数表标为必选：无（仍可能有组合条件）。
- 输出字段表：4项；字段名：`ts_code`、`ann_date`、`end_date`、`holder_num`。

<a id="doc-175"></a>

### 股东增减持

原文：[股东增减持](https://tushare.pro/document/2?doc_id=175) · doc_id=175 · 接口：`stk_holdertrade`

stk_holdertrade 跟踪重要股东增减持数量、比例、成交均价及后续持仓，也提供预案进度。需2000积分；每批最多3000行，总量不限；5000积分以上限制较宽。筛选交易方向用trade_type，返回方向字段为in_de。

- 输入参数名：`ts_code`、`ann_date`、`start_date`、`end_date`、`trade_type`、`holder_type`。
- 参数表标为必选：无（仍可能有组合条件）。
- 输出字段表：14项；前12项：`ts_code`、`ann_date`、`holder_name`、`holder_type`、`in_de`、`change_vol`、`change_ratio`、`after_share`、`after_ratio`、`avg_price`、`total_share`、`begin_date`。

<a id="doc-494"></a>

### 股票增发

原文：[股票增发](https://tushare.pro/document/2?doc_id=494) · doc_id=494 · 接口：`stk_seasoned`

stk_seasoned 追踪A股增发从预案、审批到实施的各环节，并记录定价、募集资金、费用及配售结果。历史始于1991年，每日09:00和21:00更新；需2000积分，每次最多3000行，可按代码或日期分批查询。

- 输入参数名：`ts_code`、`ann_date`、`start_date`、`end_date`。
- 参数表标为必选：无（仍可能有组合条件）。
- 输出字段表：69项；前12项：`ts_code`、`ann_date`、`first_ann_date`、`proj_info_source`、`board_approval_dt`、`sh_approval_dt`、`sasac_approval_dt`、`csrc_approval_dt`、`fo_type`、`fo_stock_type`、`cur_stage`、`valid_st_dt`。

<a id="category-291"></a>

## 特色数据

特色数据涉及研究报告、持仓成本估计及技术指标等。筹码结果属于模型估计，算法差异会影响与其他平台的对比。分类页的金股权限说明为2000积分，而金股接口页为6000积分；此处按具体接口页记录。 [分类来源](https://tushare.pro/document/2?doc_id=291)

| 文档 | 接口 | 原文 |
| --- | --- | --- |
| [券商盈利预测数据](#doc-292) | `report_rc` | [doc_id=292](https://tushare.pro/document/2?doc_id=292) |
| [每日筹码及胜率](#doc-293) | `cyq_perf` | [doc_id=293](https://tushare.pro/document/2?doc_id=293) |
| [每日筹码分布](#doc-294) | `cyq_chips` | [doc_id=294](https://tushare.pro/document/2?doc_id=294) |
| [股票技术面因子](#doc-296) | `stk_factor` | [doc_id=296](https://tushare.pro/document/2?doc_id=296) |
| [股票技术面因子(专业版）](#doc-328) | `stk_factor_pro` | [doc_id=328](https://tushare.pro/document/2?doc_id=328) |
| [股票开盘集合竞价数据](#doc-353) | `stk_auction_o` | [doc_id=353](https://tushare.pro/document/2?doc_id=353) |
| [股票收盘集合竞价数据](#doc-354) | `stk_auction_c` | [doc_id=354](https://tushare.pro/document/2?doc_id=354) |
| [神奇九转指标](#doc-364) | `stk_nineturn` | [doc_id=364](https://tushare.pro/document/2?doc_id=364) |
| [AH股比价](#doc-399) | `stk_ah_comparison` | [doc_id=399](https://tushare.pro/document/2?doc_id=399) |
| [机构调研数据](#doc-275) | `stk_surv` | [doc_id=275](https://tushare.pro/document/2?doc_id=275) |
| [券商月度金股](#doc-267) | `broker_recommend` | [doc_id=267](https://tushare.pro/document/2?doc_id=267) |

<a id="doc-292"></a>

### 券商盈利预测数据

原文：[卖方盈利预测数据](https://tushare.pro/document/2?doc_id=292) · doc_id=292 · 接口：`report_rc`

report_rc 提取券商研报中的盈利预测，覆盖2010年起历史。交易日数据分别在21:15及次日09:15更新，每批最多3000行。2000积分试用每天10次；8000积分每天10万次；10000积分以上不设每日总次数上限。

- 输入参数名：`ts_code`、`report_date`、`start_date`、`end_date`。
- 参数表标为必选：无（仍可能有组合条件）。
- 输出字段表：23项；前12项：`ts_code`、`name`、`report_date`、`report_title`、`report_type`、`classify`、`org_name`、`author_name`、`quarter`、`op_rt`、`op_pr`、`tp`。

<a id="doc-293"></a>

### 每日筹码及胜率

原文：[每日筹码及胜率](https://tushare.pro/document/2?doc_id=293) · doc_id=293 · 接口：`cyq_perf`

cyq_perf 提供A股筹码成本分位数、加权成本和胜率估计，历史始于2018-02-01，约18—19时更新。采用三角分布及历史换手衰减思路，属于模型估计。每批最多6000行；5000/10000/15000积分对应每天2万/20万/不限次数。

- 输入参数名：`ts_code`、`trade_date`、`start_date`、`end_date`。
- 参数表标为必选：`ts_code`。
- 输出字段表：11项；字段名：`ts_code`、`trade_date`、`his_low`、`his_high`、`cost_5pct`、`cost_15pct`、`cost_50pct`、`cost_85pct`、`cost_95pct`、`weight_avg`、`winner_rate`。

<a id="doc-294"></a>

### 每日筹码分布

原文：[每日筹码分布](https://tushare.pro/document/2?doc_id=294) · doc_id=294 · 接口：`cyq_chips`

cyq_chips 返回各成本价位的筹码占比，为三角分布及历史筹码衰减模型结果。覆盖2018年起数据，18—19时更新，每批最多6000行。5000积分每天2万次且每分钟200次；10000积分每天20万次；15000积分每日总次数不限。

- 输入参数名：`ts_code`、`trade_date`、`start_date`、`end_date`。
- 参数表标为必选：`ts_code`。
- 输出字段表：4项；字段名：`ts_code`、`trade_date`、`price`、`percent`。

<a id="doc-296"></a>

### 股票技术面因子

原文：[股票技术因子（量化因子）](https://tushare.pro/document/2?doc_id=296) · doc_id=296 · 接口：`stk_factor`

stk_factor 输出行情、复权价格及MACD、KDJ、RSI等指标，技术指标按前复权价格计算。社区计算数据覆盖历史，每批最多10000行。5000积分每分钟100次，8000积分以上每分钟500次；可分批或分页读取。

- 输入参数名：`ts_code`、`trade_date`、`start_date`、`end_date`。
- 参数表标为必选：无（仍可能有组合条件）。
- 输出字段表：35项；前12项：`ts_code`、`trade_date`、`close`、`open`、`high`、`low`、`pre_close`、`change`、`pct_change`、`vol`、`amount`、`adj_factor`。

<a id="doc-328"></a>

### 股票技术面因子(专业版）

原文：[股票技术面因子(专业版)](https://tushare.pro/document/2?doc_id=328) · doc_id=328 · 接口：`stk_factor_pro`

stk_factor_pro 提供更多日频技术指标及估值等字段；bfq/qfq/hfq分别表示不复权、前复权、后复权。每批最多10000行；5000积分每分钟30次，8000积分以上500次。各因子有默认参数；pre_close与前一日close_qfq口径可能不同。

- 输入参数名：`ts_code`、`trade_date`、`start_date`、`end_date`。
- 参数表标为必选：无（仍可能有组合条件）。
- 输出字段表：261项；前12项：`ts_code`、`trade_date`、`open`、`open_hfq`、`open_qfq`、`high`、`high_hfq`、`high_qfq`、`low`、`low_hfq`、`low_qfq`、`close`。

<a id="doc-353"></a>

### 股票开盘集合竞价数据

原文：[股票开盘集合竞价数据](https://tushare.pro/document/2?doc_id=353) · doc_id=353 · 接口：`stk_auction_o`

stk_auction_o 保存历史开盘集合竞价行情；页面标注时点为09:30。覆盖2010-01-01起数据，在交易日20:00更新，每批最多10000行。需要在权限中心单独申请集合竞价成交权限，可按日期分批读取。

- 输入参数名：`ts_code`、`trade_date`、`start_date`、`end_date`。
- 参数表标为必选：无（仍可能有组合条件）。
- 输出字段表：9项；字段名：`ts_code`、`trade_date`、`close`、`open`、`high`、`low`、`vol`、`amount`、`vwap`。

<a id="doc-354"></a>

### 股票收盘集合竞价数据

原文：[股票收盘集合竞价数据](https://tushare.pro/document/2?doc_id=354) · doc_id=354 · 接口：`stk_auction_c`

stk_auction_c 提供15:00收盘集合竞价行情，历史从2010-01-01起，交易日20:00更新。每次最多10000行，可分日期查询；须另行开通集合竞价成交权限。

- 输入参数名：`ts_code`、`trade_date`、`start_date`、`end_date`。
- 参数表标为必选：无（仍可能有组合条件）。
- 输出字段表：9项；字段名：`ts_code`、`trade_date`、`close`、`open`、`high`、`low`、`vol`、`amount`、`vwap`。

<a id="doc-364"></a>

### 神奇九转指标

原文：[神奇九转指标](https://tushare.pro/document/2?doc_id=364) · doc_id=364 · 接口：`stk_nineturn`

stk_nineturn 返回九转序列的连续上涨、下跌计数及转折标记，包含日线和分钟频率相关结果。数据始于2023-01-01，每天21:00更新；6000积分可用，每批最多10000行，可按证券和日期拆分。

- 输入参数名：`ts_code`、`trade_date`、`freq`、`start_date`、`end_date`。
- 参数表标为必选：无（仍可能有组合条件）。
- 输出字段表：13项；前12项：`ts_code`、`trade_date`、`freq`、`open`、`high`、`low`、`close`、`vol`、`amount`、`up_count`、`down_count`、`nine_up_turn`。

<a id="doc-399"></a>

### AH股比价

原文：[AH股比价](https://tushare.pro/document/2?doc_id=399) · doc_id=399 · 接口：`stk_ah_comparison`

stk_ah_comparison 比较A股与对应H股的价格、涨跌幅和溢价。数据自2025-08-12积累，每天17:00更新；5000积分起用，每批最多1000行。官方注明2026-11-18缺数且暂时无法补齐，不能假定时间序列连续。

- 输入参数名：`hk_code`、`ts_code`、`trade_date`、`start_date`、`end_date`。
- 参数表标为必选：无（仍可能有组合条件）。
- 输出字段表：11项；字段名：`hk_code`、`ts_code`、`trade_date`、`hk_name`、`hk_pct_chg`、`hk_close`、`name`、`close`、`pct_chg`、`ah_comparison`、`ah_premium`。

<a id="doc-275"></a>

### 机构调研数据

原文：[机构调研表](https://tushare.pro/document/2?doc_id=275) · doc_id=275 · 接口：`stk_surv`

stk_surv 记录机构调研上市公司的日期、参与方、地点、接待方式和内容。需5000积分，每次最多400行；可分时间段循环查询或分页读取。

- 输入参数名：`ts_code`、`trade_date`、`start_date`、`end_date`。
- 参数表标为必选：无（仍可能有组合条件）。
- 输出字段表：10项；字段名：`ts_code`、`name`、`surv_date`、`fund_visitors`、`rece_place`、`rece_mode`、`rece_org`、`org_type`、`comp_rece`、`content`。

<a id="doc-267"></a>

### 券商月度金股

原文：[券商每月荐股](https://tushare.pro/document/2?doc_id=267) · doc_id=267 · 接口：`broker_recommend`

broker_recommend 按月份查询券商推荐的股票名单及券商名称，当月结果通常于1—3日更新。该接口页要求6000积分，每批最多1000行；分类介绍页另写2000积分，两处门槛不一致，应核实账户实际权限。

- 输入参数名：`month`。
- 参数表标为必选：`month`。
- 输出字段表：4项；字段名：`month`、`broker`、`ts_code`、`name`。

<a id="category-330"></a>

## 两融及转融通

该分类页没有正文；其7个接口页面均已读取。 [分类来源](https://tushare.pro/document/2?doc_id=330)

| 文档 | 接口 | 原文 |
| --- | --- | --- |
| [融资融券交易汇总](#doc-58) | `margin` | [doc_id=58](https://tushare.pro/document/2?doc_id=58) |
| [融资融券交易明细](#doc-59) | `margin_detail` | [doc_id=59](https://tushare.pro/document/2?doc_id=59) |
| [融资融券标的（盘前）](#doc-326) | `margin_secs` | [doc_id=326](https://tushare.pro/document/2?doc_id=326) |
| [转融券交易汇总(停）](#doc-332) | `slb_sec` | [doc_id=332](https://tushare.pro/document/2?doc_id=332) |
| [转融资交易汇总](#doc-331) | `slb_len` | [doc_id=331](https://tushare.pro/document/2?doc_id=331) |
| [转融券交易明细(停）](#doc-333) | `slb_sec_detail` | [doc_id=333](https://tushare.pro/document/2?doc_id=333) |
| [做市借券交易汇总(停）](#doc-334) | `slb_len_mm` | [doc_id=334](https://tushare.pro/document/2?doc_id=334) |

<a id="doc-58"></a>

### 融资融券交易汇总

原文：[融资融券交易汇总](https://tushare.pro/document/2?doc_id=58) · doc_id=58 · 接口：`margin`

margin 汇总各交易所每日两融余额和发生额。2000积分可用，每批最多4000行；前一日数据最晚约次日09:05更新，深交所和北交所的周五数据延至周一上午。2014-09-22起，总量口径包含已调出标的的余额。

- 输入参数名：`trade_date`、`start_date`、`end_date`、`exchange_id`。
- 参数表标为必选：无（仍可能有组合条件）。
- 输出字段表：9项；字段名：`trade_date`、`exchange_id`、`rzye`、`rzmre`、`rzche`、`rqye`、`rqmcl`、`rzrqye`、`rqyl`。

<a id="doc-59"></a>

### 融资融券交易明细

原文：[融资融券交易明细](https://tushare.pro/document/2?doc_id=59) · doc_id=59 · 接口：`margin_detail`

margin_detail 提供证券层面的两融余额和发生额，需2000积分，每批最多6000行。前一日数据约次日08:30发布；深交所和北交所周五数据周一上午更新。数量单位随证券类型为股、份或手，名称字段自2019-09-10后才有值。

- 输入参数名：`trade_date`、`ts_code`、`start_date`、`end_date`。
- 参数表标为必选：无（仍可能有组合条件）。
- 输出字段表：11项；字段名：`trade_date`、`ts_code`、`name`、`rzye`、`rqye`、`rzmre`、`rqyl`、`rzche`、`rqchl`、`rqmcl`、`rzrqye`。

<a id="doc-326"></a>

### 融资融券标的（盘前）

原文：[融资融券标的（盘前更新）](https://tushare.pro/document/2?doc_id=326) · doc_id=326 · 接口：`margin_secs`

margin_secs 用于盘前确认沪、深、京两融标的，范围包括ETF，并记录所属交易所。需2000积分；每批最多6000行，可按代码、日期或交易所拆分；5000积分不设总量限制。

- 输入参数名：`ts_code`、`trade_date`、`exchange`、`start_date`、`end_date`。
- 参数表标为必选：无（仍可能有组合条件）。
- 输出字段表：4项；字段名：`trade_date`、`ts_code`、`name`、`exchange`。

<a id="doc-332"></a>

### 转融券交易汇总(停）

原文：[转融券交易汇总](https://tushare.pro/document/2?doc_id=332) · doc_id=332 · 接口：`slb_sec`

slb_sec 提供转融券期初、出借、期末数量及余额汇总；目录已标记“停”。每批最多5000行，可分批查历史。2000积分对应每分钟200次，5000积分对应每分钟500次。

- 输入参数名：`trade_date`、`ts_code`、`start_date`、`end_date`。
- 参数表标为必选：无（仍可能有组合条件）。
- 输出字段表：7项；字段名：`trade_date`、`ts_code`、`name`、`ope_inv`、`lent_qnt`、`cls_inv`、`end_bal`。

<a id="doc-331"></a>

### 转融资交易汇总

原文：[转融资交易汇总](https://tushare.pro/document/2?doc_id=331) · doc_id=331 · 接口：`slb_len`

slb_len 汇总转融资的期初及期末余额、竞价和展期金额、偿还金额。每批最多5000行，可按日期拆分查询历史；2000积分每分钟200次，5000积分每分钟500次。

- 输入参数名：`trade_date`、`start_date`、`end_date`。
- 参数表标为必选：无（仍可能有组合条件）。
- 输出字段表：6项；字段名：`trade_date`、`ob`、`auc_amount`、`repo_amount`、`repay_amount`、`cb`。

<a id="doc-333"></a>

### 转融券交易明细(停）

原文：[转融券交易明细](https://tushare.pro/document/2?doc_id=333) · doc_id=333 · 接口：`slb_sec_detail`

slb_sec_detail 查询转融券明细中的证券、期限、费率和出借数量，目录标记为“停”。每批最多5000行；2000积分每分钟200次，5000积分每分钟500次，历史可分批读取。

- 输入参数名：`trade_date`、`ts_code`、`start_date`、`end_date`。
- 参数表标为必选：无（仍可能有组合条件）。
- 输出字段表：6项；字段名：`trade_date`、`ts_code`、`name`、`tenor`、`fee_rate`、`lent_qnt`。

<a id="doc-334"></a>

### 做市借券交易汇总(停）

原文：[做市借券交易汇总](https://tushare.pro/document/2?doc_id=334) · doc_id=334 · 接口：`slb_len_mm`

slb_len_mm 返回做市借券的期初、出借、期末数量与余额；目录标记“停”。单批最多5000行，可分日期或证券读取历史。2000积分每分钟200次，5000积分每分钟500次。

- 输入参数名：`trade_date`、`ts_code`、`start_date`、`end_date`。
- 参数表标为必选：无（仍可能有组合条件）。
- 输出字段表：7项；字段名：`trade_date`、`ts_code`、`name`、`ope_inv`、`lent_qnt`、`cls_inv`、`end_bal`。

<a id="category-342"></a>

## 资金流向数据

该分类页没有正文；其7个接口页面均已读取。 [分类来源](https://tushare.pro/document/2?doc_id=342)

| 文档 | 接口 | 原文 |
| --- | --- | --- |
| [个股资金流向](#doc-170) | `moneyflow` | [doc_id=170](https://tushare.pro/document/2?doc_id=170) |
| [个股资金流向（THS）](#doc-348) | `moneyflow_ths` | [doc_id=348](https://tushare.pro/document/2?doc_id=348) |
| [个股资金流向（DC）](#doc-349) | `moneyflow_dc` | [doc_id=349](https://tushare.pro/document/2?doc_id=349) |
| [板块资金流向（THS)](#doc-371) | `moneyflow_cnt_ths` | [doc_id=371](https://tushare.pro/document/2?doc_id=371) |
| [行业资金流向（THS）](#doc-343) | `moneyflow_ind_ths` | [doc_id=343](https://tushare.pro/document/2?doc_id=343) |
| [板块资金流向（DC）](#doc-344) | `moneyflow_ind_dc` | [doc_id=344](https://tushare.pro/document/2?doc_id=344) |
| [大盘资金流向（DC）](#doc-345) | `moneyflow_mkt_dc` | [doc_id=345](https://tushare.pro/document/2?doc_id=345) |

<a id="doc-170"></a>

### 个股资金流向

原文：[个股资金流向](https://tushare.pro/document/2?doc_id=170) · doc_id=170 · 接口：`moneyflow`

按主动买卖方向及订单金额层级统计沪深A股资金，历史从2010年起。需2000积分，单次最多6000行。小单低于5万元，中单5万至20万元，大单20万至100万元，特大单不少于100万元。净流入采用L2订单口径，不能直接以各档金额相减替代。

- 输入参数名：`ts_code`、`trade_date`、`start_date`、`end_date`。
- 参数表标为必选：无（仍可能有组合条件）。
- 输出字段表：20项；前12项：`ts_code`、`trade_date`、`buy_sm_vol`、`buy_sm_amount`、`sell_sm_vol`、`sell_sm_amount`、`buy_md_vol`、`buy_md_amount`、`sell_md_vol`、`sell_md_amount`、`buy_lg_vol`、`buy_lg_amount`。

<a id="doc-348"></a>

### 个股资金流向（THS）

原文：[个股资金流向（THS）](https://tushare.pro/document/2?doc_id=348) · doc_id=348 · 接口：`moneyflow_ths`

同花顺口径的个股资金变化，覆盖2019-07-26起的历史，收盘后刷新。需要6000积分；一次最多6000行，可分股票或日期获取。

- 输入参数名：`ts_code`、`trade_date`、`start_date`、`end_date`。
- 参数表标为必选：无（仍可能有组合条件）。
- 输出字段表：13项；前12项：`trade_date`、`ts_code`、`name`、`pct_change`、`latest`、`net_amount`、`net_d5_amount`、`buy_lg_amount`、`buy_lg_amount_rate`、`buy_md_amount`、`buy_md_amount_rate`、`buy_sm_amount`。

<a id="doc-349"></a>

### 个股资金流向（DC）

原文：[个股资金流向（DC）](https://tushare.pro/document/2?doc_id=349) · doc_id=349 · 接口：`moneyflow_dc`

东方财富口径的个股资金变化，历史起点为2023-09-11，盘后刷新。门槛为5000积分；每次上限6000行，可按股票和日期分批读取。

- 输入参数名：`ts_code`、`trade_date`、`start_date`、`end_date`。
- 参数表标为必选：无（仍可能有组合条件）。
- 输出字段表：15项；前12项：`trade_date`、`ts_code`、`name`、`pct_change`、`close`、`net_amount`、`net_amount_rate`、`buy_elg_amount`、`buy_elg_amount_rate`、`buy_lg_amount`、`buy_lg_amount_rate`、`buy_md_amount`。

<a id="doc-371"></a>

### 板块资金流向（THS)

原文：[同花顺概念板块资金流向（THS）](https://tushare.pro/document/2?doc_id=371) · doc_id=371 · 接口：`moneyflow_cnt_ths`

查询同花顺概念板块的日度资金变化。需要6000积分，每次最多5000行，可按板块代码及日期拆分请求。

- 输入参数名：`ts_code`、`trade_date`、`start_date`、`end_date`。
- 参数表标为必选：无（仍可能有组合条件）。
- 输出字段表：12项；字段名：`trade_date`、`ts_code`、`name`、`lead_stock`、`close_price`、`pct_change`、`industry_index`、`company_num`、`pct_change_stock`、`net_buy_amount`、`net_sell_amount`、`net_amount`。

<a id="doc-343"></a>

### 行业资金流向（THS）

原文：[同花顺行业资金流向（THS）](https://tushare.pro/document/2?doc_id=343) · doc_id=343 · 接口：`moneyflow_ind_ths`

查询同花顺行业板块的资金变化，覆盖2024-09-10以来数据，盘后刷新。需要6000积分，一次不超过5000行，可分行业和日期读取。

- 输入参数名：`ts_code`、`trade_date`、`start_date`、`end_date`。
- 参数表标为必选：无（仍可能有组合条件）。
- 输出字段表：12项；字段名：`trade_date`、`ts_code`、`industry`、`lead_stock`、`close`、`pct_change`、`company_num`、`pct_change_stock`、`close_price`、`net_buy_amount`、`net_sell_amount`、`net_amount`。

<a id="doc-344"></a>

### 板块资金流向（DC）

原文：[东财概念及行业板块资金流向（DC）](https://tushare.pro/document/2?doc_id=344) · doc_id=344 · 接口：`moneyflow_ind_dc`

查询东方财富各板块的资金变化，盘后刷新。需要6000积分；每次最多5000行，可分板块和日期获取。

- 输入参数名：`ts_code`、`trade_date`、`start_date`、`end_date`、`content_type`。
- 参数表标为必选：无（仍可能有组合条件）。
- 输出字段表：18项；前12项：`trade_date`、`content_type`、`ts_code`、`name`、`pct_change`、`close`、`net_amount`、`net_amount_rate`、`buy_elg_amount`、`buy_elg_amount_rate`、`buy_lg_amount`、`buy_lg_amount_rate`。

<a id="doc-345"></a>

### 大盘资金流向（DC）

原文：[大盘资金流向（DC）](https://tushare.pro/document/2?doc_id=345) · doc_id=345 · 接口：`moneyflow_mkt_dc`

查询东方财富大盘资金统计，盘后刷新。120积分用于试用，正式调用门槛为6000积分。一次最多3000行，可分日期区间获取。

- 输入参数名：`trade_date`、`start_date`、`end_date`。
- 参数表标为必选：无（仍可能有组合条件）。
- 输出字段表：15项；前12项：`trade_date`、`close_sh`、`pct_change_sh`、`close_sz`、`pct_change_sz`、`net_amount`、`net_amount_rate`、`buy_elg_amount`、`buy_elg_amount_rate`、`buy_lg_amount`、`buy_lg_amount_rate`、`buy_md_amount`。

<a id="category-346"></a>

## 打板专题数据

该分类页没有正文；其22个接口页面均已读取。 [分类来源](https://tushare.pro/document/2?doc_id=346)

| 文档 | 接口 | 原文 |
| --- | --- | --- |
| [龙虎榜每日统计单](#doc-106) | `top_list` | [doc_id=106](https://tushare.pro/document/2?doc_id=106) |
| [龙虎榜机构交易单](#doc-107) | `top_inst` | [doc_id=107](https://tushare.pro/document/2?doc_id=107) |
| [THS涨跌停榜单](#doc-355) | `limit_list_ths` | [doc_id=355](https://tushare.pro/document/2?doc_id=355) |
| [涨跌停和炸板数据](#doc-298) | `limit_list_d` | [doc_id=298](https://tushare.pro/document/2?doc_id=298) |
| [涨停股票连板天梯](#doc-356) | `limit_step` | [doc_id=356](https://tushare.pro/document/2?doc_id=356) |
| [涨停最强板块统计](#doc-357) | `limit_cpt_list` | [doc_id=357](https://tushare.pro/document/2?doc_id=357) |
| [THS概念板块分类](#doc-259) | `ths_index` | [doc_id=259](https://tushare.pro/document/2?doc_id=259) |
| [THS概念板块行情](#doc-260) | `ths_daily` | [doc_id=260](https://tushare.pro/document/2?doc_id=260) |
| [THS概念板块成分](#doc-261) | `ths_member` | [doc_id=261](https://tushare.pro/document/2?doc_id=261) |
| [DC概念板块分类](#doc-362) | `dc_index` | [doc_id=362](https://tushare.pro/document/2?doc_id=362) |
| [DC概念板块成分](#doc-363) | `dc_member` | [doc_id=363](https://tushare.pro/document/2?doc_id=363) |
| [DC概念板块行情](#doc-382) | `dc_daily` | [doc_id=382](https://tushare.pro/document/2?doc_id=382) |
| [开盘竞价成交（当日）](#doc-369) | `stk_auction` | [doc_id=369](https://tushare.pro/document/2?doc_id=369) |
| [市场游资最全名录](#doc-311) | `hm_list` | [doc_id=311](https://tushare.pro/document/2?doc_id=311) |
| [游资交易每日明细](#doc-312) | `hm_detail` | [doc_id=312](https://tushare.pro/document/2?doc_id=312) |
| [THS热榜](#doc-320) | `ths_hot` | [doc_id=320](https://tushare.pro/document/2?doc_id=320) |
| [DC热榜](#doc-321) | `dc_hot` | [doc_id=321](https://tushare.pro/document/2?doc_id=321) |
| [TDX概念板块分类](#doc-376) | `tdx_index` | [doc_id=376](https://tushare.pro/document/2?doc_id=376) |
| [TDX概念板块成分](#doc-377) | `tdx_member` | [doc_id=377](https://tushare.pro/document/2?doc_id=377) |
| [TDX概念板块行情](#doc-378) | `tdx_daily` | [doc_id=378](https://tushare.pro/document/2?doc_id=378) |
| [榜单数据（KP）](#doc-347) | `kpl_list` | [doc_id=347](https://tushare.pro/document/2?doc_id=347) |
| [题材成分（KP）](#doc-351) | `kpl_concept_cons` | [doc_id=351](https://tushare.pro/document/2?doc_id=351) |

<a id="doc-106"></a>

### 龙虎榜每日统计单

原文：[龙虎榜每日明细](https://tushare.pro/document/2?doc_id=106) · doc_id=106 · 接口：`top_list`

按交易日查询龙虎榜记录，历史可追溯至2005年。需要2000积分，每次最多10000行；较长历史须拆分请求。

- 输入参数名：`trade_date`、`ts_code`。
- 参数表标为必选：`trade_date`。
- 输出字段表：15项；前12项：`trade_date`、`ts_code`、`name`、`close`、`pct_change`、`turnover_rate`、`amount`、`l_sell`、`l_buy`、`l_amount`、`net_amount`、`net_rate`。

<a id="doc-107"></a>

### 龙虎榜机构交易单

原文：[龙虎榜机构明细](https://tushare.pro/document/2?doc_id=107) · doc_id=107 · 接口：`top_inst`

查询龙虎榜机构席位的买卖明细。需要5000积分，一次最多10000行，可调整筛选条件分批取得历史记录。

- 输入参数名：`trade_date`、`ts_code`。
- 参数表标为必选：`trade_date`。
- 输出字段表：10项；字段名：`trade_date`、`ts_code`、`exalter`、`side`、`buy`、`buy_rate`、`sell`、`sell_rate`、`net_buy`、`reason`。

<a id="doc-355"></a>

### THS涨跌停榜单

原文：[涨跌停榜单（同花顺）](https://tushare.pro/document/2?doc_id=355) · doc_id=355 · 接口：`limit_list_ths`

同花顺涨跌停相关股票池，覆盖2023-11-01起的数据，约16时更新。每次最多4000行；8000积分以上每分钟500次、日调用量不限。不同股票池的非空字段不同，最大封单只在涨停及连板池提供。仅限个人学习研究，商用采购须另行联系同花顺。

- 输入参数名：`trade_date`、`ts_code`、`limit_type`、`market`、`start_date`、`end_date`。
- 参数表标为必选：无（仍可能有组合条件）。
- 输出字段表：24项；前12项：`trade_date`、`ts_code`、`name`、`price`、`pct_chg`、`open_num`、`lu_desc`、`limit_type`、`tag`、`status`、`first_lu_time`、`last_lu_time`。

<a id="doc-298"></a>

### 涨跌停和炸板数据

原文：[涨跌停列表（新）](https://tushare.pro/document/2?doc_id=298) · doc_id=298 · 接口：`limit_list_d`

统计A股涨停、跌停与炸板，历史从2020年起，不含ST股票。每次最多2500行。5000积分档每分钟200次、每天10000次；8000积分以上每分钟500次、日调用量不限。

- 输入参数名：`trade_date`、`ts_code`、`limit_type`、`exchange`、`start_date`、`end_date`。
- 参数表标为必选：无（仍可能有组合条件）。
- 输出字段表：18项；前12项：`trade_date`、`ts_code`、`industry`、`name`、`close`、`pct_chg`、`amount`、`limit_amount`、`float_mv`、`total_mv`、`turnover_ratio`、`fd_amount`。

<a id="doc-356"></a>

### 涨停股票连板天梯

原文：[连板天梯](https://tushare.pro/document/2?doc_id=356) · doc_id=356 · 接口：`limit_step`

记录连续涨停股票的晋级情况，覆盖2023-11-13以来数据。每次最多2000行；8000积分以上每分钟500次，日调用量不限，可分股票及日期查询。

- 输入参数名：`trade_date`、`ts_code`、`start_date`、`end_date`、`nums`。
- 参数表标为必选：无（仍可能有组合条件）。
- 输出字段表：4项；字段名：`ts_code`、`name`、`trade_date`、`nums`。

<a id="doc-357"></a>

### 涨停最强板块统计

原文：[最强板块统计](https://tushare.pro/document/2?doc_id=357) · doc_id=357 · 接口：`limit_cpt_list`

按概念板块统计涨停强度，便于观察强势板块变化。每次最多2000行；8000积分以上每分钟500次，日调用量不限，可分代码与日期获取。

- 输入参数名：`trade_date`、`ts_code`、`start_date`、`end_date`。
- 参数表标为必选：无（仍可能有组合条件）。
- 输出字段表：9项；字段名：`ts_code`、`name`、`trade_date`、`days`、`up_stat`、`cons_nums`、`up_nums`、`pct_chg`、`rank`。

<a id="doc-259"></a>

### THS概念板块分类

原文：[概念和行业指数](https://tushare.pro/document/2?doc_id=259) · doc_id=259 · 接口：`ths_index`

同花顺概念、行业及特色板块的指数基础资料。需要6000积分，单次最多5000行；文档说明一次能够取全，勿重复循环拉取。

- 输入参数名：`ts_code`、`exchange`、`type`。
- 参数表标为必选：无（仍可能有组合条件）。
- 输出字段表：6项；字段名：`ts_code`、`name`、`count`、`exchange`、`list_date`、`type`。

<a id="doc-260"></a>

### THS概念板块行情

原文：[板块指数行情](https://tushare.pro/document/2?doc_id=260) · doc_id=260 · 接口：`ths_daily`

同花顺板块指数的历史行情，每日19时、21时刷新。需要6000积分，每次最多3000行，可按指数和日期区间分批读取。

- 输入参数名：`ts_code`、`trade_date`、`start_date`、`end_date`。
- 参数表标为必选：无（仍可能有组合条件）。
- 输出字段表：14项；前12项：`ts_code`、`trade_date`、`close`、`open`、`high`、`low`、`pre_close`、`avg_price`、`change`、`pct_change`、`vol`、`turnover_rate`。

<a id="doc-261"></a>

### THS概念板块成分

原文：[概念板块成分](https://tushare.pro/document/2?doc_id=261) · doc_id=261 · 接口：`ths_member`

查询同花顺概念板块的当前成分，页面明确提供最新名单，不应视为历史时点成分。需要6000积分，每分钟最多200次。

- 输入参数名：`ts_code`、`con_code`。
- 参数表标为必选：无（仍可能有组合条件）。
- 输出字段表：7项；字段名：`ts_code`、`con_code`、`con_name`、`weight`、`in_date`、`out_date`、`is_new`。

<a id="doc-362"></a>

### DC概念板块分类

原文：[概念板块](https://tushare.pro/document/2?doc_id=362) · doc_id=362 · 接口：`dc_index`

按交易日取得东方财富概念板块记录。需要6000积分，单次最多5000行，可分日期读取历史。

- 输入参数名：`ts_code`、`name`、`trade_date`、`start_date`、`end_date`、`idx_type`。
- 参数表标为必选：`idx_type`。
- 输出字段表：13项；前12项：`ts_code`、`trade_date`、`name`、`leading`、`leading_code`、`pct_change`、`leading_pct`、`total_mv`、`turnover_rate`、`up_num`、`down_num`、`idx_type`。

<a id="doc-363"></a>

### DC概念板块成分

原文：[板块成分](https://tushare.pro/document/2?doc_id=363) · doc_id=363 · 接口：`dc_member`

东方财富板块的每日成分，支持还原历史名单，起点为2024-12-20。需要6000积分，每次最多8000行，可分板块与日期获取。

- 输入参数名：`ts_code`、`con_code`、`trade_date`、`start_date`、`end_date`。
- 参数表标为必选：无（仍可能有组合条件）。
- 输出字段表：4项；字段名：`trade_date`、`ts_code`、`con_code`、`name`。

<a id="doc-382"></a>

### DC概念板块行情

原文：[概念板块行情](https://tushare.pro/document/2?doc_id=382) · doc_id=382 · 接口：`dc_daily`

东方财富概念、行业及地域板块的行情，历史从2020年起。需要6000积分，一次最多2000行，可按日期分批查询。

- 输入参数名：`ts_code`、`trade_date`、`start_date`、`end_date`、`idx_type`。
- 参数表标为必选：无（仍可能有组合条件）。
- 输出字段表：13项；前12项：`ts_code`、`trade_date`、`close`、`open`、`high`、`low`、`change`、`pct_change`、`vol`、`amount`、`swing`、`turnover_rate`。

<a id="doc-369"></a>

### 开盘竞价成交（当日）

原文：[当日集合竞价](https://tushare.pro/document/2?doc_id=369) · doc_id=369 · 接口：`stk_auction`

开盘集合竞价成交数据，当日约09:26—09:29可取，历史从2025-01-16起。每次最多8000行，权限须单独申请。页面早期描述含ETF，但后续备注已将ETF迁至 etf_auction，应按拆分后的接口取数。

- 输入参数名：`ts_code`、`trade_date`、`start_date`、`end_date`。
- 参数表标为必选：无（仍可能有组合条件）。
- 输出字段表：9项；字段名：`ts_code`、`trade_date`、`vol`、`price`、`amount`、`pre_close`、`turnover_rate`、`volume_ratio`、`float_share`。
- 拆分入口：[ETF集合竞价](https://tushare.pro/document/2?doc_id=493)、[ETF涨跌停价格](https://tushare.pro/document/2?doc_id=491)。

<a id="doc-311"></a>

### 市场游资最全名录

原文：[游资名录](https://tushare.pro/document/2?doc_id=311) · doc_id=311 · 接口：`hm_list`

查询游资名称、分类说明及关联机构。需要5000积分，单次上限1000条；页面称整体名单不足500条，另附示例名录表。

- 输入参数名：`name`。
- 参数表标为必选：无（仍可能有组合条件）。
- 输出字段表：3项；字段名：`name`、`desc`、`orgs`。
- 原站附有游资名单示例；实际名单以接口返回为准。

<a id="doc-312"></a>

### 游资交易每日明细

原文：[游资每日明细](https://tushare.pro/document/2?doc_id=312) · doc_id=312 · 接口：`hm_detail`

每日游资交易记录，历史从2022年8月起；分类可关联游资名录。需要10000积分，每次最多2000行，可分批查询且无总量上限。页面展示的示例只覆盖当日部分记录。

- 输入参数名：`trade_date`、`ts_code`、`hm_name`、`start_date`、`end_date`。
- 参数表标为必选：无（仍可能有组合条件）。
- 输出字段表：9项；字段名：`trade_date`、`ts_code`、`ts_name`、`buy_amount`、`sell_amount`、`net_amount`、`hm_name`、`hm_orgs`、`tag`。

<a id="doc-320"></a>

### THS热榜

原文：[THS热榜](https://tushare.pro/document/2?doc_id=320) · doc_id=320 · 接口：`ths_hot`

同花顺热度排行覆盖股票、板块、ETF、可转债及港美股等对象。盘中与盘后各采集4次，最后一批约22时。需要6000积分，一次最多2000行，可分日期获取。

- 输入参数名：`trade_date`、`ts_code`、`market`、`is_new`。
- 参数表标为必选：无（仍可能有组合条件）。
- 输出字段表：11项；字段名：`trade_date`、`data_type`、`ts_code`、`ts_name`、`rank`、`pct_change`、`current_price`、`concept`、`rank_reason`、`hot`、`rank_time`。

<a id="doc-321"></a>

### DC热榜

原文：[DC热榜](https://tushare.pro/document/2?doc_id=321) · doc_id=321 · 接口：`dc_hot`

东方财富热度排行覆盖A股、ETF及港美股等市场。盘中、盘后各采集4次，末批约22时。需要8000积分，每次最多2000行，可分日期获取。

- 输入参数名：`trade_date`、`ts_code`、`market`、`hot_type`、`is_new`。
- 参数表标为必选：无（仍可能有组合条件）。
- 输出字段表：8项；字段名：`trade_date`、`data_type`、`ts_code`、`ts_name`、`rank`、`pct_change`、`current_price`、`rank_time`。

<a id="doc-376"></a>

### TDX概念板块分类

原文：[TDX板块信息](https://tushare.pro/document/2?doc_id=376) · doc_id=376 · 接口：`tdx_index`

通达信概念、行业、风格及地域等板块的基础资料。需要6000积分，每次最多1000行，可按日期拆分查询。

- 输入参数名：`ts_code`、`trade_date`、`idx_type`。
- 参数表标为必选：无（仍可能有组合条件）。
- 输出字段表：9项；字段名：`ts_code`、`trade_date`、`name`、`idx_type`、`idx_count`、`total_share`、`float_share`、`total_mv`、`float_mv`。

<a id="doc-377"></a>

### TDX概念板块成分

原文：[TDX板块成分](https://tushare.pro/document/2?doc_id=377) · doc_id=377 · 接口：`tdx_member`

通达信板块成分股，历史从2025-03-28起。需要6000积分，每次最多3000行，可按板块代码和日期分批读取。

- 输入参数名：`ts_code`、`con_code`、`trade_date`、`start_date`、`end_date`。
- 参数表标为必选：无（仍可能有组合条件）。
- 输出字段表：4项；字段名：`ts_code`、`trade_date`、`con_code`、`con_name`。

<a id="doc-378"></a>

### TDX概念板块行情

原文：[TDX板块行情](https://tushare.pro/document/2?doc_id=378) · doc_id=378 · 接口：`tdx_daily`

通达信板块行情，包含成交及估值指标。需要6000积分，单次最多3000行，可按板块代码及日期分批获取。

- 输入参数名：`ts_code`、`trade_date`、`start_date`、`end_date`。
- 参数表标为必选：无（仍可能有组合条件）。
- 输出字段表：38项；前12项：`ts_code`、`trade_date`、`close`、`open`、`high`、`low`、`pre_close`、`change`、`pct_change`、`vol`、`amount`、`rise`。

<a id="doc-347"></a>

### 榜单数据（KP）

原文：[开盘啦榜单数据](https://tushare.pro/document/2?doc_id=347) · doc_id=347 · 接口：`kpl_list`

提供涨停、跌停和炸板等榜单。交易日早上6时补前一交易日，周五记录在周六更新。每次最多8000行。5000积分档每分钟200次、每天10000次；8000积分以上每分钟500次、日调用量不限。

- 输入参数名：`ts_code`、`trade_date`、`tag`、`start_date`、`end_date`。
- 参数表标为必选：无（仍可能有组合条件）。
- 输出字段表：24项；前12项：`ts_code`、`name`、`trade_date`、`lu_time`、`ld_time`、`open_time`、`last_time`、`lu_desc`、`tag`、`theme`、`net_change`、`bid_amount`。

<a id="doc-351"></a>

### 题材成分（KP）

原文：[开盘啦题材成分](https://tushare.pro/document/2?doc_id=351) · doc_id=351 · 接口：`kpl_concept_cons`

查询开盘啦概念题材对应的成分股。需要5000积分，每次最多3000行，可按题材代码和日期拆分获取。

- 输入参数名：`trade_date`、`ts_code`、`con_code`。
- 参数表标为必选：无（仍可能有组合条件）。
- 输出字段表：7项；字段名：`ts_code`、`name`、`con_name`、`con_code`、`trade_date`、`desc`、`hot_num`。

## 旧链接及原站差异

以下4个链接仍出现在总览或分类正文中，但本次打开均显示“文档不存在”。它们不在当前股票数据目录的102个接口条目中，未为其补写接口内容。

| 旧入口 | 来源页面 | 读取结果 |
| --- | --- | --- |
| [沪深股通成份股](https://tushare.pro/document/2?doc_id=104) | 总览14、基础24 | 页面显示404 |
| [停复牌信息](https://tushare.pro/document/2?doc_id=31) | 总览14、行情15 | 页面显示404 |
| [沪深港通资金流向](https://tushare.pro/document/2?doc_id=47) | 参考17 | 页面显示404 |
| [港股通十大成交股](https://tushare.pro/document/2?doc_id=49) | 参考17 | 页面显示404 |

原站字段表还存在表头不一致：复权因子和沪深股通十大成交股的输出表也使用“必选”列名。本文件按表格所在的输入/输出位置识别，不将输出表误认作第二组输入参数。

利润表、资产负债表、现金流量表等接口的报告类型说明，以及技术因子的大量输出字段，并未在摘要中完整展开；开发调用时须回到对应原文。此文件也未把示例中的输出记录或省略号当作真实接口返回全集。
