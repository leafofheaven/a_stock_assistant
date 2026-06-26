# A 股选股投资辅助软件项目说明文档

## 1. 项目名称

`a_stock_assistant`

## 2. 项目定位

本项目是一个面向个人投资者的 **A 股选股投资辅助软件**。

项目目标不是自动交易，也不是预测股票必然涨跌，而是建立一个可验证、可解释、可回测的投资辅助系统，用于：

1. 自动获取 A 股基础行情与财务数据；
2. 清洗和存储本地数据；
3. 根据规则构建可交易股票池；
4. 计算多个选股因子；
5. 形成综合评分与候选股票池；
6. 对选股策略进行历史回测；
7. 通过网页界面展示每日选股结果、个股详情和回测表现。

本项目第一阶段只做 **研究与辅助决策系统**，不接入券商交易接口，不自动下单。

---

## 3. 第一阶段 MVP 目标

第一阶段需要完成一个本地可运行版本。

用户运行以下命令后：

```bash
python -m core.jobs.run_daily_selection
```

系统应自动完成：

1. 更新最近交易日 A 股数据；
2. 构建可交易股票池；
3. 计算基础因子；
4. 计算综合评分；
5. 输出排名靠前的候选股票；
6. 将结果保存到本地数据库；
7. 在 Streamlit 页面中查看结果。

启动前端页面：

```bash
streamlit run web/streamlit_app.py
```

页面应至少包含：

1. 今日选股；
2. 个股详情；
3. 因子排名；
4. 策略回测；
5. 数据更新状态。

---

## 4. 非目标

第一阶段不要实现以下功能：

1. 不做自动下单；
2. 不接入券商交易 API；
3. 不做分钟级高频交易；
4. 不做机器学习预测模型；
5. 不做新闻大模型荐股；
6. 不生成“明日必涨”结论；
7. 不承诺投资收益；
8. 不把回测结果等同于真实收益。

---

## 5. 技术栈

### 5.1 语言与运行环境

* Python 3.12
* 本地运行优先
* 后续可 Docker 化部署

### 5.2 数据处理

* pandas
* numpy
* duckdb
* pyarrow

### 5.3 数据源

第一阶段预留两个数据源适配器：

* Tushare
* AKShare

要求：

1. 所有数据源函数统一返回 `pandas.DataFrame`；
2. 真实 API 调用逻辑与业务计算逻辑分离；
3. 单元测试不得直接调用真实外部 API；
4. 测试中使用 mock 数据。

### 5.4 后端

* FastAPI

### 5.5 前端

* Streamlit

### 5.6 配置管理

* python-dotenv
* pydantic-settings

### 5.7 测试

* pytest

### 5.8 代码质量

* ruff
* mypy，可后续加入
* 日志使用 Python 标准 logging

---

## 6. 项目目录结构

请 Codex 按以下目录结构创建项目：

```text
a_stock_assistant/
  README.md
  PROJECT_SPEC.md
  pyproject.toml
  .env.example
  .gitignore

  app/
    __init__.py
    main.py
    config.py
    api/
      __init__.py
      routes_stocks.py
      routes_factors.py
      routes_backtest.py

  core/
    __init__.py

    data_sources/
      __init__.py
      tushare_client.py
      akshare_client.py
      base.py

    storage/
      __init__.py
      duckdb_store.py
      schema.sql

    universe/
      __init__.py
      stock_pool.py

    factors/
      __init__.py
      trend.py
      momentum.py
      liquidity.py
      volatility.py
      fundamental.py
      scoring.py

    strategy/
      __init__.py
      selector.py
      portfolio.py

    backtest/
      __init__.py
      engine.py
      metrics.py
      rules_cn_a.py

    jobs/
      __init__.py
      update_daily_data.py
      compute_factors.py
      run_daily_selection.py

  web/
    streamlit_app.py

  tests/
    __init__.py
    test_data_sources.py
    test_stock_pool.py
    test_factors.py
    test_scoring.py
    test_selector.py
    test_backtest.py

  notebooks/
    factor_research.ipynb
```

---

## 7. 核心架构

系统分为六层：

```text
数据源层
  ↓
数据清洗与存储层
  ↓
股票池过滤层
  ↓
因子计算层
  ↓
策略与回测层
  ↓
前端展示层
```

### 7.1 数据源层

位置：

```text
core/data_sources/
```

职责：

1. 从 Tushare 或 AKShare 获取数据；
2. 将不同来源的数据统一成标准字段；
3. 对外返回 DataFrame；
4. 不在数据源层做选股逻辑。

需要实现：

```python
get_stock_basic()
get_trade_calendar()
get_daily_price(start_date, end_date)
get_daily_basic(start_date, end_date)
get_adj_factor(start_date, end_date)
```

所有函数返回 `pandas.DataFrame`。

---

## 8. 数据表设计

第一阶段使用 DuckDB + Parquet。

### 8.1 stock_basic

股票基础信息表。

字段建议：

```text
ts_code         股票代码
symbol          股票简称代码
name            股票名称
area            地域
industry        行业
market          市场
list_date       上市日期
delist_date     退市日期
is_hs           是否沪深港通
```

### 8.2 trade_calendar

交易日历表。

```text
exchange        交易所
cal_date        日期
is_open         是否开市
pretrade_date   上一个交易日
```

### 8.3 daily_price

日线行情表。

```text
ts_code         股票代码
trade_date      交易日期
open            开盘价
high            最高价
low             最低价
close           收盘价
pre_close       昨收价
change          涨跌额
pct_chg         涨跌幅
vol             成交量
amount          成交额
```

### 8.4 daily_basic

每日基础指标表。

```text
ts_code         股票代码
trade_date      交易日期
turnover_rate   换手率
volume_ratio    量比
pe              市盈率
pb              市净率
ps              市销率
total_mv        总市值
circ_mv         流通市值
```

### 8.5 adj_factor

复权因子表。

```text
ts_code         股票代码
trade_date      交易日期
adj_factor      复权因子
```

### 8.6 factor_values

因子值表。

```text
ts_code              股票代码
trade_date           交易日期
factor_name          因子名称
factor_value         因子原始值
```

### 8.7 factor_scores

因子评分表。

```text
ts_code              股票代码
trade_date           交易日期
trend_score          趋势分
momentum_score       动量分
liquidity_score      流动性分
volatility_score     波动风险分
fundamental_score    基本面分
total_score          综合分
```

### 8.8 strategy_result

每日选股结果表。

```text
trade_date           交易日期
rank                 排名
ts_code              股票代码
name                 股票名称
industry             行业
total_score          综合分
select_reason        入选理由
risk_note            风险提示
```

### 8.9 backtest_result

回测结果表。

```text
strategy_name        策略名称
start_date           回测开始日期
end_date             回测结束日期
annual_return        年化收益率
max_drawdown         最大回撤
sharpe_ratio         夏普比率
win_rate             胜率
turnover             换手率
created_at           生成时间
```

---

## 9. 股票池过滤规则

位置：

```text
core/universe/stock_pool.py
```

函数建议：

```python
def build_tradeable_universe(
    stock_basic: pd.DataFrame,
    daily_price: pd.DataFrame,
    daily_basic: pd.DataFrame,
    trade_date: str,
) -> pd.DataFrame:
    ...
```

第一阶段过滤规则：

1. 排除 ST、*ST 股票；
2. 排除停牌股票；
3. 排除上市不足 120 个交易日的股票；
4. 排除近 20 个交易日日均成交额低于 1 亿元的股票；
5. 排除近 20 个交易日停牌天数超过 3 天的股票；
6. 排除财务数据严重缺失的股票；
7. 保留主板、创业板、科创板股票；
8. 后续可配置是否排除北交所股票。

输出字段：

```text
ts_code
name
industry
list_date
trade_date
avg_amount_20d
avg_turnover_20d
is_tradeable
exclude_reason
```

---

## 10. 因子计算模块

位置：

```text
core/factors/
```

第一阶段实现以下因子。

---

### 10.1 趋势因子

文件：

```text
core/factors/trend.py
```

实现：

```python
calculate_return_20d()
calculate_return_60d()
calculate_ma_position()
calculate_ma_alignment()
```

含义：

1. 20 日收益率；
2. 60 日收益率；
3. 收盘价相对 20 日均线的位置；
4. 均线多头排列，例如 5 日均线 > 20 日均线 > 60 日均线。

---

### 10.2 动量因子

文件：

```text
core/factors/momentum.py
```

实现：

```python
calculate_relative_strength()
calculate_new_high_60d()
```

含义：

1. 个股近 20 日收益是否强于沪深 300；
2. 是否接近或突破 60 日新高。

---

### 10.3 流动性因子

文件：

```text
core/factors/liquidity.py
```

实现：

```python
calculate_avg_amount_20d()
calculate_avg_turnover_20d()
```

含义：

1. 近 20 日平均成交额；
2. 近 20 日平均换手率。

---

### 10.4 波动风险因子

文件：

```text
core/factors/volatility.py
```

实现：

```python
calculate_volatility_20d()
calculate_max_drawdown_60d()
```

含义：

1. 近 20 日收益率波动率；
2. 近 60 日最大回撤。

---

### 10.5 基本面因子

文件：

```text
core/factors/fundamental.py
```

实现：

```python
calculate_roe()
calculate_pe_score()
calculate_pb_score()
calculate_revenue_growth()
```

含义：

1. ROE；
2. PE 相对估值；
3. PB 相对估值；
4. 营收增速。

第一阶段如果财务数据暂时不完整，可以先预留接口，并用 mock 数据测试。

---

## 11. 综合评分模块

位置：

```text
core/factors/scoring.py
```

第一阶段采用简单加权模型：

```text
综合分 =
  30% 趋势分
+ 20% 动量分
+ 20% 流动性分
+ 15% 基本面分
+ 15% 风险控制分
```

要求：

1. 每个子因子先标准化为 0 到 100 分；
2. 越高越好；
3. 风险类因子需要反向处理，例如波动率越高，风险分越低；
4. 缺失值不得直接导致程序崩溃；
5. 缺失值处理方式需要明确记录；
6. 输出总分和各分项得分。

函数建议：

```python
def normalize_factor(
    df: pd.DataFrame,
    factor_col: str,
    higher_is_better: bool = True,
) -> pd.Series:
    ...
```

```python
def calculate_total_score(
    factor_df: pd.DataFrame,
    weights: dict[str, float] | None = None,
) -> pd.DataFrame:
    ...
```

---

## 12. 策略模块

位置：

```text
core/strategy/
```

### 12.1 selector.py

职责：

1. 接收股票池和因子评分；
2. 按综合分排序；
3. 输出候选股票列表；
4. 给出简单入选理由和风险提示。

函数建议：

```python
def select_top_stocks(
    scored_df: pd.DataFrame,
    top_n: int = 30,
) -> pd.DataFrame:
    ...
```

输出字段：

```text
trade_date
rank
ts_code
name
industry
trend_score
momentum_score
liquidity_score
fundamental_score
volatility_score
total_score
select_reason
risk_note
```

---

### 12.2 portfolio.py

职责：

1. 根据候选股票构建模拟持仓；
2. 第一阶段只做等权组合；
3. 后续再支持行业约束、单票权重上限、风险预算等。

函数建议：

```python
def build_equal_weight_portfolio(
    selected_df: pd.DataFrame,
    max_positions: int = 20,
) -> pd.DataFrame:
    ...
```

---

## 13. 回测模块

位置：

```text
core/backtest/
```

### 13.1 engine.py

实现一个轻量级日频回测引擎。

第一阶段规则：

1. 每周调仓一次；
2. 每次持有综合分最高的前 N 只股票；
3. 等权买入；
4. 默认持仓数量为 20 只；
5. 考虑手续费；
6. 考虑印花税；
7. 考虑滑点；
8. 考虑停牌不能交易；
9. 考虑涨停买不进；
10. 考虑跌停卖不出；
11. 不允许未来函数。

函数建议：

```python
def run_backtest(
    price_df: pd.DataFrame,
    score_df: pd.DataFrame,
    start_date: str,
    end_date: str,
    rebalance_frequency: str = "W",
    top_n: int = 20,
    initial_cash: float = 1_000_000,
    commission_rate: float = 0.0003,
    stamp_tax_rate: float = 0.0005,
    slippage_rate: float = 0.0005,
) -> dict:
    ...
```

---

### 13.2 metrics.py

计算回测指标：

```python
calculate_annual_return()
calculate_max_drawdown()
calculate_sharpe_ratio()
calculate_win_rate()
calculate_turnover()
calculate_yearly_returns()
```

输出指标：

```text
annual_return
max_drawdown
sharpe_ratio
win_rate
turnover
yearly_returns
equity_curve
trade_records
position_records
```

---

### 13.3 rules_cn_a.py

封装 A 股交易规则。

第一阶段需要考虑：

1. T+1；
2. 涨跌停；
3. 停牌；
4. 新股上市初期异常交易；
5. ST 股票涨跌幅规则后续再扩展；
6. 科创板、创业板涨跌幅差异后续再扩展。

函数建议：

```python
def is_suspended(row: pd.Series) -> bool:
    ...
```

```python
def is_limit_up(row: pd.Series) -> bool:
    ...
```

```python
def is_limit_down(row: pd.Series) -> bool:
    ...
```

```python
def can_buy(row: pd.Series) -> bool:
    ...
```

```python
def can_sell(row: pd.Series) -> bool:
    ...
```

---

## 14. Streamlit 前端页面

位置：

```text
web/streamlit_app.py
```

第一阶段页面包含 5 个 Tab。

---

### 14.1 今日选股

展示字段：

```text
排名
股票代码
股票名称
行业
综合分
趋势分
动量分
流动性分
基本面分
风险分
近20日涨跌幅
近20日日均成交额
当前PE
当前PB
入选理由
风险提示
```

支持：

1. 按综合分排序；
2. 按行业筛选；
3. 按成交额筛选；
4. 导出 CSV。

---

### 14.2 个股详情

输入股票代码后展示：

1. 股票基本信息；
2. 最近日线行情；
3. 近 20 日涨跌幅；
4. 近 60 日涨跌幅；
5. 成交额变化；
6. 换手率变化；
7. 因子历史排名；
8. 最近入选记录；
9. 风险提示。

第一阶段不强制画复杂 K 线图，可以先用折线图展示收盘价和成交额。

---

### 14.3 因子排名

展示：

1. 趋势因子排名；
2. 动量因子排名；
3. 流动性因子排名；
4. 基本面因子排名；
5. 风险因子排名；
6. 综合分排名。

---

### 14.4 策略回测

展示：

1. 回测参数；
2. 净值曲线；
3. 年化收益率；
4. 最大回撤；
5. 夏普比率；
6. 胜率；
7. 年度收益；
8. 历史持仓；
9. 历史交易记录。

---

### 14.5 数据更新状态

展示：

1. 最新行情日期；
2. 最新因子日期；
3. 最新选股结果日期；
4. 各数据表行数；
5. 最近一次任务运行状态；
6. 错误日志。

---

## 15. 定时任务模块

位置：

```text
core/jobs/
```

### 15.1 update_daily_data.py

职责：

1. 更新股票基础信息；
2. 更新交易日历；
3. 更新日线行情；
4. 更新每日基础指标；
5. 更新复权因子；
6. 增量写入 DuckDB。

---

### 15.2 compute_factors.py

职责：

1. 读取本地行情和基础数据；
2. 计算股票池；
3. 计算所有因子；
4. 计算综合评分；
5. 保存到本地数据库。

---

### 15.3 run_daily_selection.py

职责：

1. 调用数据更新；
2. 调用因子计算；
3. 调用选股策略；
4. 保存每日候选股票；
5. 输出结果摘要。

命令行运行：

```bash
python -m core.jobs.run_daily_selection
```

---

## 16. 配置文件

### 16.1 .env.example

```env
TUSHARE_TOKEN=your_tushare_token_here
DATA_DIR=./data
DUCKDB_PATH=./data/a_stock_assistant.duckdb
LOG_LEVEL=INFO
DEFAULT_TOP_N=30
DEFAULT_BACKTEST_TOP_N=20
```

---

## 17. README 需要包含的内容

`README.md` 至少包括：

1. 项目简介；
2. 安装方式；
3. 环境变量配置；
4. 如何更新数据；
5. 如何运行选股；
6. 如何启动页面；
7. 如何运行测试；
8. 当前限制；
9. 风险声明。

示例命令：

```bash
pip install -e .
```

```bash
python -m core.jobs.run_daily_selection
```

```bash
streamlit run web/streamlit_app.py
```

```bash
pytest
```

---

## 18. Codex 开发要求

Codex 在实现本项目时，需要遵守以下规则：

1. 先搭建项目骨架，再逐步实现模块；
2. 每次只实现一个清晰模块；
3. 所有核心函数必须有类型提示；
4. 所有核心函数必须有 docstring；
5. 所有核心逻辑必须有单元测试；
6. 测试不能依赖真实外部 API；
7. 不得把 token 写死在代码里；
8. 不得在因子和回测中使用未来数据；
9. 数据源异常时要有日志和错误处理；
10. 页面展示逻辑不得与核心计算逻辑混在一起。

---

## 19. 推荐 Codex 执行顺序

请 Codex 按以下顺序开发。

---

### Task 1：创建项目骨架

目标：

1. 创建目录结构；
2. 创建 `pyproject.toml`；
3. 创建 `.env.example`；
4. 创建 `README.md`；
5. 创建空模块文件；
6. 配置 pytest；
7. 确保项目可以安装和运行测试。

验收标准：

```bash
pip install -e .
pytest
```

应正常运行。

---

### Task 2：实现配置模块

文件：

```text
app/config.py
```

要求：

1. 从 `.env` 读取配置；
2. 使用 pydantic-settings；
3. 支持 Tushare token、数据目录、DuckDB 路径、日志等级；
4. 添加单元测试。

---

### Task 3：实现数据源接口

文件：

```text
core/data_sources/base.py
core/data_sources/tushare_client.py
core/data_sources/akshare_client.py
```

要求：

1. 定义统一数据源接口；
2. 实现 Tushare 客户端；
3. 实现 AKShare 客户端；
4. 加入日志；
5. 加入异常处理；
6. 测试使用 mock，不调用真实 API。

---

### Task 4：实现 DuckDB 存储层

文件：

```text
core/storage/duckdb_store.py
core/storage/schema.sql
```

要求：

1. 创建核心数据表；
2. 支持 DataFrame 写入；
3. 支持按日期增量更新；
4. 支持读取指定日期范围数据；
5. 添加单元测试。

---

### Task 5：实现股票池过滤

文件：

```text
core/universe/stock_pool.py
```

要求：

1. 排除 ST；
2. 排除上市不足 120 个交易日；
3. 排除近 20 日成交额过低；
4. 排除近 20 日停牌过多；
5. 输出股票池和排除原因；
6. 添加单元测试。

---

### Task 6：实现基础因子

文件：

```text
core/factors/trend.py
core/factors/momentum.py
core/factors/liquidity.py
core/factors/volatility.py
core/factors/fundamental.py
```

要求：

1. 实现所有基础因子；
2. 不允许未来函数；
3. 输入输出均为 DataFrame；
4. 添加单元测试。

---

### Task 7：实现综合评分

文件：

```text
core/factors/scoring.py
```

要求：

1. 实现因子标准化；
2. 实现 0 到 100 分评分；
3. 实现加权综合分；
4. 处理缺失值；
5. 添加单元测试。

---

### Task 8：实现选股策略

文件：

```text
core/strategy/selector.py
core/strategy/portfolio.py
```

要求：

1. 按综合分选出前 N 只股票；
2. 生成入选理由；
3. 生成风险提示；
4. 构建等权组合；
5. 添加单元测试。

---

### Task 9：实现回测引擎

文件：

```text
core/backtest/engine.py
core/backtest/metrics.py
core/backtest/rules_cn_a.py
```

要求：

1. 每周调仓；
2. 等权持仓；
3. 考虑手续费、印花税、滑点；
4. 考虑停牌、涨停买不进、跌停卖不出；
5. 输出净值曲线、交易记录、持仓记录、核心指标；
6. 添加单元测试。

---

### Task 10：实现 Streamlit 页面

文件：

```text
web/streamlit_app.py
```

要求：

1. 实现今日选股页面；
2. 实现个股详情页面；
3. 实现因子排名页面；
4. 实现策略回测页面；
5. 实现数据更新状态页面；
6. 页面只调用已有核心模块，不直接写复杂业务逻辑。

---

### Task 11：实现一键运行任务

文件：

```text
core/jobs/run_daily_selection.py
```

要求：

1. 一键更新数据；
2. 一键计算因子；
3. 一键生成选股结果；
4. 输出命令行摘要；
5. 保存结果到本地数据库。

---

## 20. 第一阶段完成标准

第一阶段完成后，应满足：

1. 本地项目可以安装；
2. 测试可以运行；
3. 可以更新或模拟更新数据；
4. 可以计算股票池；
5. 可以计算基础因子；
6. 可以生成综合评分；
7. 可以输出每日候选股票；
8. 可以做简单回测；
9. 可以通过 Streamlit 页面查看结果；
10. 所有核心模块都有测试。

---

## 21. 风险声明

本项目仅用于投资研究、数据分析和辅助决策，不构成任何投资建议。

任何选股结果、评分结果和回测结果均不代表未来收益。用户需要自行判断市场风险、流动性风险、模型失效风险和交易执行风险。

第一阶段不得自动下单。
