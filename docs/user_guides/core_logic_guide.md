# A 股选股辅助系统：核心逻辑说明

## 1. 应用定位与使用边界

本系统是个人本地 A 股选股辅助工具，用于数据整理、因子观察、候选复核、观察池跟踪、模拟持仓匹配和每日研究留档。系统仅供个人研究使用，不自动交易，不接券商，不构成投资建议。

系统不会替用户下单，也不会给出保证收益、必涨或自动买卖指令。页面、报告和 Excel 中的分数、状态、区间和提示，作用是帮助用户更快整理研究对象，并提醒哪些地方需要人工复核。

需要特别注意：

- `total_score` 是主筛选分数，不是买入优先级。
- 埃尔德复核是二次技术状态判断，不改变 `total_score`。
- 买入区间、止损位和目标价位是研究计划辅助，不是自动交易指令。
- 观察池是持续跟踪名单，不是买入清单。
- 页面和 Excel 中的“序号”只代表当前显示顺序，不代表交易顺序。

## 2. 整体工作流

系统的日常链路可以概括为：

股票池 -> 数据更新 -> 因子计算 -> 综合分 `total_score` -> 今日候选 -> 埃尔德复核 -> 买入区间 / 止损 / 目标价 -> 观察池 -> 外部模拟持仓匹配 -> 每日研究工作簿 Excel。

各环节的定位如下：

- 股票池负责确定当前研究范围，例如 mini / small / medium 样本池，或 full 沪深 A 股全市场股票池。
- 数据更新负责补充本地 DuckDB 中的日行情、基础行情和估值字段。
- 因子计算负责从趋势、动量、流动性、基本面、波动风险等角度生成分项分数。
- `total_score` 按当前代码配置的权重汇总分项分数，是今日候选的主筛选依据。
- 今日候选用于进入人工复核，不代表买入清单。
- 埃尔德复核用于判断技术节奏，例如趋势、回调、过热或数据不足。
- 买入区间用于整理当前价、支撑阻力、止损参考、目标价参考和盈亏比。
- 观察池用于跟踪不应因为掉出当日 Top 候选就立即删除的股票。
- 外部模拟持仓用于把用户已有模拟仓位与系统区间、风险和状态进行匹配。
- 每日研究工作簿 Excel 用于留档、筛选、复盘和后续人工分析。

当前日常选股主流程的伪代码如下，具体实现以 `core/jobs/run_daily_selection.py` 和相关函数为准：

```text
load settings and local DuckDB data
resolve stock universe:
    if AKSHARE_SAMPLE_SYMBOLS is not empty:
        use custom symbols
    else:
        use REAL_UNIVERSE_PRESET such as full

for selection_date:
    build tradeable universe using stock_basic, daily_price, daily_basic
    calculate raw metrics:
        return_20d from daily_price.close
        avg_amount_20d from daily_price.amount
        avg_turnover_20d from daily_basic.turnover_rate
        pe_score from daily_basic.pe
        volatility_20d from daily_price.close returns
    normalize each metric within the same trade_date
    compute trend_score, momentum_score, liquidity_score, fundamental_score, volatility_score
    total_score = weighted sum of component scores
    select Top N by total_score descending
    write factor_scores and strategy_result to DuckDB
    run Elder review for candidates / watchlist when requested
    compute entry zones when requested
    update watchlist snapshots when requested
    export reports / workbook when requested
```

注意：`core/factors/` 下提供了更多基础因子函数，例如 60 日收益、均线位置、相对强弱、60 日新高、最大回撤、ROE、PB、营收增长等。当前日常选股主链路实际使用哪些指标，以 `core/jobs/run_daily_selection.py::_calculate_minimal_real_scores()` 为准。

## 3. 数据来源与本地数据库

系统以本地 DuckDB 为核心数据仓库。真实数据链路中可以使用 AKShare、东方财富 K 线接口和本地缓存数据；部分环境也可以配置 Tushare。数据源可能因为网络、代理、接口结构变化、停牌、空数据或本地 DuckDB 文件锁而失败或缺失。

页面中的数据源预检会检查 DuckDB 锁、Python / macOS 代理状态、东方财富 K 线接口连通性。东方财富 K 线接口不可用或 DuckDB 被锁时，页面不会启动批量更新。

主要表的含义：

- `stock_basic`：股票基础信息，例如股票代码、名称、行业、市场、上市日期等。
- `daily_price`：日行情，例如开盘、收盘、最高、最低、成交量、成交额等。
- `daily_basic`：估值和基础行情字段，例如换手率、PE、PB、市值等；部分数据源可能只补齐最新交易日。
- `factor_scores`：因子分数和综合分。
- `strategy_result`：今日选股结果，是 Streamlit 今日选股页面的主要本地数据源。
- 观察池相关表：保存观察池状态、每日跟踪快照和事件记录。
- 买入区间相关表：保存支撑阻力、买入区间、止损位、目标价位和风险提示。
- 外部模拟持仓相关表：保存用户导入的外部模拟仓位和匹配结果。

系统不会在文档、报告或页面中泄露 token。`.env`、DuckDB、本地报告和导出文件都不应提交到仓库。

## 4. 股票池与可交易性过滤

`REAL_UNIVERSE_PRESET=full` 表示沪深 A 股全市场，不含北交所。系统默认排除北交所 / BSE / BJ 以及 8 开头、4 开头等北交所代码。mini / small / medium 是样本池，用于小范围验证和快速运行。

当 `AKSHARE_SAMPLE_SYMBOLS` 非空时，自定义股票池优先于预设股票池；当它为空时，系统使用 `REAL_UNIVERSE_PRESET`。

可交易性过滤用于排除当前不适合进入研究流程的标的。当前代码中的过滤逻辑包括：

- 排除 ST、*ST、退市整理、退市或明显异常名称股票。
- 排除北交所股票。
- 按上市时长过滤，默认 `MIN_LISTING_DAYS=120`。
- 检查近 20 日有效成交天数，默认 `MIN_TRADED_DAYS_20D=18`。
- 检查流动性，默认近 20 日平均成交额不低于 `MIN_AVG_AMOUNT_20D=100000000`，近 20 日成交额中位数不低于 `MIN_MEDIAN_AMOUNT_20D=50000000`，最新成交额不低于 `MIN_LATEST_AMOUNT=30000000`。
- 停牌或近期无有效成交不是永久黑名单。后续复牌并重新满足成交和流动性条件后，可以重新进入可交易股票池。

过滤结果受本地数据完整性影响。某些股票可能因为行情缺失、停牌、接口空数据、上市日期缺失或成交额不足而暂时无法进入候选。

## 5. 因子计算逻辑

本章描述当前日常选股主链路的真实计算口径。源码位置主要在 `core/jobs/run_daily_selection.py::_calculate_minimal_real_scores()`、`core/factors/*` 和 `core/factors/scoring.py`。

### 5.1 当前日常选股实际使用的计算口径总表

| 分数 | 输入数据 | 主要指标 | 分数方向 | 标准化 / 处理方式 | 缺失处理 | 源码位置 |
|---|---|---|---|---|---|---|
| `trend_score` | `daily_price.ts_code`, `trade_date`, `close` | `return_20d = close / close.shift(20) - 1` | 20 日收益越高分越高 | `normalize_factor(..., factor_col="return_20d", higher_is_better=True)`；同一 `trade_date` 横截面 min-max 到 0-100 | 少于 20 个交易日或 `close` 缺失时为 NaN；标准化后仍为 NaN；计算 `total_score` 时该分项按 0 计 | `core/jobs/run_daily_selection.py::_calculate_minimal_real_scores`; `core/factors/trend.py::calculate_return_20d`; `core/factors/scoring.py::normalize_factor` |
| `momentum_score` | `daily_price.ts_code`, `trade_date`, `close` | 当前主链路同样使用 `return_20d` | 20 日收益越高分越高 | `normalize_factor(..., factor_col="return_20d", higher_is_better=True)` | 同 `trend_score` | `core/jobs/run_daily_selection.py::_calculate_minimal_real_scores`; `core/factors/trend.py::calculate_return_20d` |
| `liquidity_score` | `daily_price.amount` | `avg_amount_20d = amount.rolling(20, min_periods=1).mean()` | 近 20 日平均成交额越高分越高 | `normalize_factor(..., factor_col="avg_amount_20d", higher_is_better=True)` | `amount` 缺失时该指标为 NaN；计算 `total_score` 时缺失分项按 0 计 | `core/jobs/run_daily_selection.py::_calculate_minimal_real_scores`; `core/factors/liquidity.py::calculate_avg_amount_20d` |
| `fundamental_score` | `daily_basic.pe` | `pe_score = 1 / pe`，仅正 PE 有效 | `pe_score` 越高分越高，即正 PE 越低分越高 | `normalize_factor(..., factor_col="pe_score", higher_is_better=True)` | `pe` 缺失、非正数或不可转数值时为 NaN；计算 `total_score` 时该分项按 0 计 | `core/jobs/run_daily_selection.py::_calculate_minimal_real_scores`; `core/factors/fundamental.py::calculate_pe_score` |
| `volatility_score` | `daily_price.close` | `volatility_20d = pct_change(close).rolling(20, min_periods=2).std()` | 波动率越低分越高 | `normalize_factor(..., factor_col="volatility_20d", higher_is_better=False)` | 少于 2 个收益样本或 `close` 缺失时为 NaN；计算 `total_score` 时缺失分项按 0 计 | `core/jobs/run_daily_selection.py::_calculate_minimal_real_scores`; `core/factors/volatility.py::calculate_volatility_20d` |
| `total_score` | 五个分项分数 | 加权求和 | 分数越高越靠前 | 默认权重见下方公式；结果 clip 到 0-100 | 缺失分项在 `calculate_total_score()` 中按 0 参与综合分计算；但 `total_score` 缺失的行不会进入候选 | `core/factors/scoring.py::calculate_total_score`; `core/strategy/selector.py::select_top_stocks` |

### 5.2 `total_score` 公式

当前默认权重定义在 `core/factors/scoring.py::DEFAULT_WEIGHTS`：

```text
total_score =
  0.30 * trend_score
+ 0.20 * momentum_score
+ 0.20 * liquidity_score
+ 0.15 * fundamental_score
+ 0.15 * volatility_score
```

`calculate_total_score()` 的处理规则：

1. 权重必须覆盖 `trend_score`、`momentum_score`、`liquidity_score`、`fundamental_score`、`volatility_score`。
2. 不允许额外权重字段。
3. 权重不能为负数。
4. 权重总和必须等于 1.0。
5. 分项分数会被转换为数值并裁剪到 0-100。
6. 缺失分项列会补成 NaN。
7. 计算 `total_score` 时，各分项 NaN 会按 0 参与加权求和。
8. `total_score` 最终也会裁剪到 0-100。

今日候选阶段由 `core/strategy/selector.py::select_top_stocks()` 处理。该函数会剔除 `total_score` 缺失的行，按 `trade_date` 分组，并在每个交易日内按 `total_score` 降序、`ts_code` 升序排序，再取 Top N。`top_n` 由调用方传入；策略函数默认值是 30，日常流程中会使用配置或调用参数传入的 Top N。

### 5.3 横截面标准化口径

`core/factors/scoring.py::normalize_factor()` 使用同一 `trade_date` 内的横截面 min-max 标准化：

```text
score = (value - min(value_on_same_trade_date)) / (max - min) * 100
```

如果 `higher_is_better=False`，则反向处理：

```text
score = 100 - score
```

处理细节：

1. 按 `trade_date` 分组，不跨日期比较。
2. 输出是 0-100 分。
3. NaN、不可转数值、正负无穷值不参与 min-max 计算，并在返回结果中保持 NaN。
4. 如果同一交易日所有有效值都相同，则这些有效值给中性分 50。
5. 返回 Series 名称为 `{factor_col}_score`，但日常选股会把它赋值到 `trend_score`、`momentum_score` 等业务字段。
6. 标准化只使用当前行所属交易日的横截面数据，不使用未来日期。

### 5.4 各分项“怎么算”

#### `trend_score` 趋势分

- 输入字段：`daily_price.ts_code`、`daily_price.trade_date`、`daily_price.close`。
- 中间指标：`return_20d = close / close.shift(20) - 1`，按 `ts_code` 分组、按 `trade_date` 排序。
- 分数方向：`return_20d` 越大，`trend_score` 越高。
- 标准化：同一 `trade_date` 横截面 min-max 到 0-100，`higher_is_better=True`。
- 缺失处理：不足 20 个交易日时没有 `return_20d`；该行 `trend_score` 为 NaN；计算 `total_score` 时该分项按 0 处理。
- 源码：`core/factors/trend.py::calculate_return_20d`，`core/jobs/run_daily_selection.py::_calculate_minimal_real_scores`。

#### `momentum_score` 动量分

- 输入字段：当前主链路使用 `daily_price.ts_code`、`trade_date`、`close`。
- 中间指标：当前主链路同样使用 `return_20d`。
- 分数方向：`return_20d` 越大，`momentum_score` 越高。
- 标准化：同一 `trade_date` 横截面 min-max 到 0-100，`higher_is_better=True`。
- 缺失处理：同 `trend_score`。
- 源码：`core/jobs/run_daily_selection.py::_calculate_minimal_real_scores`。
- 说明：`core/factors/momentum.py` 另有 `calculate_relative_strength()` 和 `calculate_new_high_60d()`，但当前日常选股主链路未在 `_calculate_minimal_real_scores()` 中调用它们；如果后续接入，应以对应源码为准。

#### `liquidity_score` 流动性分

- 输入字段：当前主链路使用 `daily_price.amount`。
- 中间指标：`avg_amount_20d = amount` 按 `ts_code` 分组后的 20 日滚动均值，`min_periods=1`。
- 分数方向：`avg_amount_20d` 越大，`liquidity_score` 越高。
- 标准化：同一 `trade_date` 横截面 min-max 到 0-100，`higher_is_better=True`。
- 缺失处理：`amount` 缺失会导致指标缺失；计算 `total_score` 时缺失分项按 0 处理。
- 源码：`core/factors/liquidity.py::calculate_avg_amount_20d`，`core/jobs/run_daily_selection.py::_calculate_minimal_real_scores`。
- 说明：`calculate_avg_turnover_20d()` 会计算 `daily_basic.turnover_rate` 的 20 日均值，当前主链路会合并 `avg_turnover_20d` 供展示和后续数据使用，但 `liquidity_score` 实际使用的是 `avg_amount_20d`。

#### `fundamental_score` 基本面 / 估值分

- 输入字段：当前主链路使用 `daily_basic.pe`。
- 中间指标：`pe_score = 1 / pe`，只对正 PE 计算；PE 缺失、非正数或不可转数值时为 NaN。
- 分数方向：`pe_score` 越大分越高，也就是正 PE 越低，`fundamental_score` 越高。
- 标准化：同一 `trade_date` 横截面 min-max 到 0-100，`higher_is_better=True`。
- 缺失处理：PE 缺失时 `pe_score` 和 `fundamental_score` 可能为空；计算 `total_score` 时该分项按 0 处理。
- 源码：`core/factors/fundamental.py::calculate_pe_score`，`core/jobs/run_daily_selection.py::_calculate_minimal_real_scores`。
- 说明：`core/factors/fundamental.py` 还提供 `calculate_roe()`、`calculate_pb_score()`、`calculate_revenue_growth()`。其中 `calculate_pb_score()` 口径为 `1 / pb`，正 PB 越低分越高；ROE 和营收增长函数会优先使用已有字段或可推导字段。但当前日常选股主链路没有把 ROE、PB、营收增长合成到 `fundamental_score`，不能把它们描述成已稳定参与主筛选。

#### `volatility_score` 波动分

- 输入字段：`daily_price.ts_code`、`trade_date`、`close`。
- 中间指标：先按股票计算日收益 `pct_change(close)`，再计算 20 日滚动标准差 `volatility_20d`，`min_periods=2`。
- 分数方向：波动率越低，`volatility_score` 越高。
- 标准化：同一 `trade_date` 横截面 min-max 后反向处理，`higher_is_better=False`。
- 缺失处理：少于 2 个收益样本或 `close` 缺失时为 NaN；计算 `total_score` 时缺失分项按 0 处理。
- 源码：`core/factors/volatility.py::calculate_volatility_20d`，`core/jobs/run_daily_selection.py::_calculate_minimal_real_scores`。
- 说明：`core/factors/volatility.py::calculate_max_drawdown_60d()` 提供 60 日最大回撤指标，当前主链路未把它直接用于 `volatility_score`。

## 6. 今日候选生成逻辑

今日候选从 `factor_scores` 计算结果进入 `strategy_result`。日常工作流中，`run_daily_selection` 会基于最新可用行情日期生成因子分数，写入 `factor_scores`，再用 `select_top_stocks()` 生成候选并写入 `strategy_result`。`run_daily_workflow --skip-update` 会在不更新行情的情况下重新计算并持久化本地可展示结果。

候选生成口径：

1. 选择日期：真实数据模式优先使用 `daily_price` 中最新可用 `trade_date`，避免错误使用系统当前日期。
2. 因子分数：由 `core/jobs/run_daily_selection.py::_calculate_minimal_real_scores()` 生成，并写入 `factor_scores`。
3. 候选排序：`core/strategy/selector.py::select_top_stocks()` 按 `trade_date` 分组，在每个日期内按 `total_score` 降序、`ts_code` 升序排序。
4. 缺失过滤：`total_score` 缺失的股票不会进入候选。
5. Top N：由调用方传入；策略函数默认 `top_n=30`，日常流程会按配置或命令参数决定实际数量。
6. 入库：候选结果写入 `strategy_result`，Streamlit 今日选股页面优先读取 DuckDB 最新 `strategy_result`，不会自动回退 sample 数据。

内部可能保留 `rank` 作为原始选股排名，但普通用户页面和每日 Excel 应优先使用“序号”或 `display_order` 展示当前表格顺序。

今日候选的用途是进入人工研究和观察池管理，不是买入清单。用户可以按综合分、趋势分、动量分、流动性分、基本面分、波动分、行业、埃尔德状态、买入区间状态等字段自行筛选和排序。

需要注意：

- 不使用 `rank` 作为买入优先级。
- 不把页面序号解释为交易顺序。
- Excel 默认应避免导出 rank 字段；如果内部需要保留原始排名，应使用更明确的字段名并放入调试或高级字段。
- 序号只代表当前 Sheet 显示顺序，不代表买入优先级。

## 7. 埃尔德复核逻辑

埃尔德复核是二次技术状态判断层。它不覆盖 `total_score`，不修改因子权重，不改变今日选股结果，也不代表买入优先级。它主要帮助用户判断候选股当前技术节奏，例如趋势是否改善、是否过热、是否等待回调、是否数据不足。

适用对象包括今日候选、观察池，以及当前代码支持的持仓池展示。它不是对全市场股票逐只强制复核，而是对已经进入候选或跟踪流程的股票做技术状态补充。

埃尔德复核使用 `daily_price`。当前代码会计算：

- EMA13、EMA22；
- MACD、MACD signal、MACD histogram、MACD histogram slope；
- Elder Force Index 2 日平滑和 13 日平滑；
- Bull Power、Bear Power；
- `close_to_ema13_pct`、`close_to_ema22_pct`；
- 周线趋势判断，基于日线聚合后的周线结构和 MACD histogram 改善情况。

输出字段包括：

- `elder_score`：埃尔德复核分，只代表技术状态 / 节奏复核。
- `action_hint`：操作提示，例如“趋势确认，进入人工复核”“趋势尚可，等待回调”“短线过热，不追”“趋势偏弱，暂缓”“忽略”“数据不足”等。
- `elder_reason`：中文复核原因。
- `weekly_trend`：周线趋势状态。
- `daily_pullback`：日线回调状态。
- `force_signal`：强力指数信号。
- `elder_ray_signal`：Elder-ray 信号。
- `latest_trade_date` / `review_date`：复核使用的最新行情日期。

当前逻辑会使用某只股票自身可用的最新行情日期进行复核。如果股票行情日期落后于全局最新交易日，不应直接误判为日线数据不足；只有日线样本确实不足时，才显示“日线数据不足”。如果日线足够但周线样本不足，应提示“周线样本不足”或“长周期样本不足”。

### 7.1 埃尔德复核规则表

| 模块 | 使用指标 | 判断规则 | 输出字段 | 含义 | 源码位置 |
|---|---|---|---|---|---|
| 日线指标 | `close`, `high`, `low`, `vol` 或 `amount` | EMA13、EMA22、MACD、MACD signal、MACD histogram、MACD histogram slope、Force Index 2 / 13、Bull Power、Bear Power、close 到 EMA 的距离 | `ema13`, `ema22`, `macd`, `force_index_2d`, `bull_power` 等 | 提供日线技术状态基础数据 | `core/technical/elder.py::calculate_elder_indicators` |
| 周线趋势 | 日线聚合周线后的 `close`, EMA13, EMA22, MACD histogram slope | 周线 close >= EMA13，且 EMA13 >= EMA22 或 MACD histogram slope > 0 | `weekly_trend`, `weekly_trend_improving` | 判断中期趋势是否改善 | `core/technical/elder.py::calculate_weekly_elder_trend` |
| 日线回调 | `close_to_ema13_pct`, `close_to_ema22_pct` | `abs(close_to_ema13_pct) <= 5` 或 `abs(close_to_ema22_pct) <= 8` | `daily_pullback`, `daily_pullback_ok` | 判断价格是否仍在 EMA 节奏附近 | `core/technical/elder.py::_classify_elder_state` |
| 过热判断 | `close_to_ema13_pct`, `close_to_ema22_pct` | `close_to_ema13_pct > 10` 且 `close_to_ema22_pct > 12` | `action_hint`, `daily_pullback` | 判断是否短线偏高、不适合追 | `core/technical/elder.py::_classify_elder_state` |
| 强力指数 | `force_index_2d` 和前一日 `force_index_2d` | 前一日 <= 0 且当日 > 0 为由负转正；当日 > 0 为偏强 | `force_signal` | 判断短线买盘 / 卖压变化 | `core/technical/elder.py::_classify_elder_state` |
| Elder-ray | `bull_power`, `bear_power`, 前一日 `bear_power` | `bull_power > 0` 或 `bear_power > previous_bear_power` | `elder_ray_signal` | 判断多头增强或空头压力减弱 | `core/technical/elder.py::_classify_elder_state` |
| 短线触发 | Force 由负转正，或 MACD histogram slope > 0 且 Elder-ray 改善 | 任一条件满足则 `short_trigger=True` | `short_trigger` | 判断是否有短线触发信号 | `core/technical/elder.py::_classify_elder_state` |

### 7.2 `elder_score` 与 `action_hint` 生成口径

`elder_score` 初始为 0，并按以下条件加分：

- 周线趋势改善：+35。
- 日线接近 EMA：+20。
- 未短线过热：+10。
- Force Index 2 日由负转正：+15。
- MACD histogram slope > 0：+10。
- Elder-ray 多头增强或空头压力减弱：+10。

随后根据状态限制和生成 `action_hint`：

- 如果周线趋势未改善：返回 `min(score, 45)`，`action_hint = "趋势偏弱，暂缓"`。
- 如果短线过热：返回 `min(score, 70)`，`action_hint = "短线过热，不追"`。
- 如果周线改善、日线接近 EMA、短线触发成立：返回 `min(score, 100)`，`action_hint = "趋势确认，进入人工复核"`。
- 如果周线改善、日线接近 EMA、但短线触发不明确：返回 `min(score, 85)`，`action_hint = "趋势尚可，等待回调"`。
- 如果周线改善但价格离 EMA 较远：返回 `min(score, 75)`，`action_hint = "趋势尚可，等待回调"`。
- 如果候选股票少于 `min_daily_rows=35` 行日线：`elder_score=0`，`action_hint="数据不足"`，原因提示日线数据不足。
- 如果日线足够但周线聚合后少于 12 周：`elder_score=0`，`action_hint="数据不足"`，原因提示周线样本不足或长周期样本不足。

如果候选行的 `trade_date` 晚于某只股票自身最新行情日期，当前逻辑会使用该股票自身最新可用行情日期复核，并在 `elder_reason` 中说明使用该股票最新可用日期，避免把“缺全局最新交易日行情”误判为“日线数据不足”。

常见提示的理解：

- “短线过热，不追”：表示价格节奏可能偏高，短期回撤风险较高，但不等于中期趋势一定变差。
- “等待回调”：表示趋势或结构尚可，但当前价格位置可能不适合追高。
- “趋势偏弱，暂缓”：表示技术结构仍需观察。
- “数据不足”：表示缺少足够行情样本，暂不做技术复核。

高 `total_score` 但埃尔德提示“短线过热”，通常表示候选质量可能不错，但技术节奏需要等待。埃尔德分高不代表一定买入，埃尔德分低也不代表股票基本面或主因子一定差。

## 8. 买入区间、止损与目标价

买入区间、止损位、目标价位和盈亏比仅用于研究计划，不代表自动买入，也不代表系统建议买入。用户可以结合当前价格、支撑位、阻力位、追高风险、盈亏比和自身研究判断使用。

当前买入区间模块使用本地 `daily_price`，计算：

- 当前价；
- EMA13、EMA22、EMA60；
- 近 20 日和近 60 日支撑位；
- 近 20 日和近 60 日阻力位；
- `nearest_support`、`nearest_resistance`；
- ATR14 或近似波动区间；
- `entry_low`、`entry_high`、`entry_mid`；
- `stop_loss`、`target_price`；
- `risk_pct`、`reward_pct`、`reward_risk_ratio`；
- `chase_risk`；
- `entry_zone_status` 及中文说明。

当前状态包括：

- `in_zone`：位于买入区间。
- `near_zone`：接近买入区间。
- `above_zone`：高于买入区间，等待回调。
- `below_zone`：低于买入区间。
- `weak_no_entry`：趋势偏弱，暂不进入。
- `insufficient_data`：数据不足。

少于 20 个交易日时，系统会返回数据不足而不是报错。少于 60 个交易日时，部分长期支撑阻力可能为空，但短周期信息仍可用于有限复核。

### 8.1 买入区间计算口径

买入区间是启发式研究规则，不是交易信号。源码位置为 `core/entry_zones/calculator.py`。

基础指标：

- EMA13、EMA22、EMA60：基于 `close.ewm(span=13/22/60, adjust=False).mean()`。
- 20 日支撑位：`low.rolling(20, min_periods=20).min()`。
- 60 日支撑位：`low.rolling(60, min_periods=60).min()`。
- 20 日阻力位：`high.rolling(20, min_periods=20).max()`。
- 60 日阻力位：`high.rolling(60, min_periods=60).max()`。
- ATR14：当日 true range 的 14 日均值，true range 取 `high-low`、`abs(high-pre_close)`、`abs(low-pre_close)` 的最大值。
- `nearest_support`：在支撑位、EMA22、EMA60 中，取不高于当前 close 的最大值。
- `nearest_resistance`：在 20 日和 60 日阻力位中，取不低于当前 close 的最小值。

趋势偏弱判断：

- `close < EMA60`，或
- `EMA13 < EMA22 < EMA60`。

过热判断：

- `close_to_ema13 > 10%`，或
- `close_to_ema22 > 14%`，或
- 当前价距离 `nearest_resistance` 小于 3%。

区间计算：

- 如果趋势偏弱：
  - `entry_low = nearest_support or support_20d`
  - `entry_high = EMA22 or close`
  - `entry_zone_status = weak_no_entry`
  - `chase_risk = medium`
- 如果趋势不弱：
  - `entry_low = nearest_support or EMA22 or support_20d`
  - `entry_high = entry_low + 0.5 * ATR14`
  - `entry_mid = (entry_low + entry_high) / 2`
  - `entry_zone_status` 由当前价相对区间和过热状态判断
  - `chase_risk` 根据当前价偏离 EMA 和区间状态判断

状态触发：

- `insufficient_data`：少于 20 个交易日，或关键价格 / 区间字段缺失。
- `above_zone`：过热且 close > entry_high，或 close 高于区间上沿。
- `in_zone`：`entry_low <= close <= entry_high`。
- `near_zone`：当前价距离区间上下沿不超过 `max(0.5 * ATR14, close * 2%)`。
- `below_zone`：当前价低于区间且不满足接近区间。
- `weak_no_entry`：趋势偏弱。

风险和目标：

- `stop_loss`：
  - `buffer = max(ATR14 or entry_mid * 3%, entry_mid * 3%)`
  - `base = nearest_support or entry_mid`
  - `stop_loss = min(base - buffer, entry_mid * 0.92)`
- `risk = entry_mid - stop_loss`
- `target_price`：
  - 如果 `risk <= 0`，返回 `nearest_resistance`
  - 否则 `rr_target = entry_mid + 2 * risk`
  - 如果没有有效阻力位，使用 `rr_target`
  - 如果有阻力位，取 `max(nearest_resistance, rr_target)`
- `reward = target_price - entry_mid`
- `reward_risk_ratio = reward / risk`，当 `risk <= 0` 或字段不足时为空。
- `risk_pct = risk / entry_mid`
- `reward_pct = reward / entry_mid`

追高风险：

- `high`：`entry_zone_status=above_zone`，或 `close_to_ema13 > 10%`，或 `close_to_ema22 > 14%`。
- `medium`：`entry_zone_status` 为 `near_zone` 或 `below_zone`。
- `low`：其他情况。

## 9. 观察池与观察池每日跟踪

### 当前观察池

当前观察池对应页面中的观察池列表，也对应每日研究 Excel 中的 `04_观察池`。它用于回答：

- 当前要观察哪些股票；
- 为什么进入观察池；
- 当前观察状态；
- 已观察多久；
- 最近综合分和复核状态；
- 入池原因和观察原因。

观察池不是买入清单。它的作用是保存持续跟踪对象，避免股票掉出当日 Top 候选后就从研究流程中消失。

观察池状态包括新入选、正常观察、重点观察、等待回调、接近买入区间、短线过热、走势转弱、逻辑失效、已买入、已移出等。状态只作为人工复核提示，不输出自动交易动作。

### 观察池每日跟踪

观察池每日跟踪对应 Excel 中的 `05_观察池跟踪`。它用于回答：

- 观察池股票每天状态如何变化；
- 综合分是否变化；
- 是否重新进入 Top N；
- 是否为新候选；
- 近 5 日 / 近 10 日入选次数；
- 连续入选天数；
- 埃尔德复核提示如何变化；
- 每日备注是什么。

用户可按交易日期、综合分、综合分变化、是否 Top N、是否新候选、埃尔德分、操作提示、观察池状态等字段自行排序和筛选。不要使用 `rank` 字段作为买入优先级。

## 10. 外部模拟持仓导入与匹配

系统支持导入外部模拟持仓模板，用于把用户在其他工具里维护的模拟仓位与系统中的买入区间、止损位、目标价位、盈亏比、追高风险、观察状态等字段进行匹配。

当前流程面向本地文件和用户手工导入，不读取同花顺 / 雪球登录态，不接券商，不自动交易。外部模拟持仓不代表真实交易，也不会触发下单。

外部模拟持仓的作用是帮助用户整理已有模拟仓位的研究状态，例如：

- 当前价相对持仓价的变化；
- 是否接近系统计算的区间或风险位置；
- 是否存在数据不足；
- 是否需要人工复核持仓计划。

## 11. 每日研究工作簿 Excel

每日研究工作簿 Excel 用于每日复盘、留档、手工筛选和后续上传给 ChatGPT 继续分析。它不是交易指令文件。

当前工作簿的主要 Sheet 包括：

- `00_摘要`；
- `01_今日候选`；
- `02_埃尔德复核`；
- `03_买入区间`；
- `04_观察池`；
- `05_观察池跟踪`；
- `06_外部模拟持仓`；
- `07_风险提示`；
- `08_数据质量`；
- `09_参数配置`；
- `10_说明`。

Excel 默认应避免导出 rank 字段。用户可用综合分、各因子分、埃尔德分、买入区间状态、追高风险、观察池状态、数据质量提示等字段自行筛选排序。序号只代表当前 Sheet 显示顺序，不代表买入优先级。

## 12. 数据质量与常见异常

常见数据质量和运行异常包括：

- 数据源不可用：例如东方财富 K 线接口暂时不可访问。
- DuckDB 被锁：例如另一个 core.jobs 命令、Streamlit 进程或 macOS FileProvider 正在占用数据库文件。
- Python / macOS 系统代理异常：可能导致 AKShare、东方财富接口无法访问。
- PE / PB 缺失：部分历史区间或个别股票可能缺少估值字段，会影响估值分和基本面分。
- 基本面分缺失记录：通常与 `daily_basic`、PE、PB、ROE、营收增长等可计算数据缺失有关。
- 最新行情不足：部分股票可能停牌、接口空数据或只更新到较早交易日。
- 空数据股票：接口返回空行情时会记录为空数据或暂不可用，不应中断全市场更新。

数据质量 warning 不一定代表系统不可用，但会影响部分因子、埃尔德复核、买入区间或个股判断。遇到异常时应先查看数据更新状态、预检结果、诊断命令和数据质量说明。

## 13. 推荐日常使用流程

建议日常使用步骤：

1. 打开本地 Streamlit 页面。
2. 查看数据更新状态，确认 DuckDB、代理和东方财富接口状态。
3. 在可用网络下运行数据源预检。
4. 根据需要执行全市场批量补数据或增量更新。
5. 执行本地重算或日常工作流。
6. 查看今日候选，确认数据日期和候选数量。
7. 查看埃尔德复核，判断候选股票的技术节奏。
8. 查看买入区间，整理支撑阻力、止损参考、目标价参考和盈亏比。
9. 查看观察池和观察池每日跟踪，关注连续入选、状态变化和复核提示。
10. 如有外部模拟持仓，导入模板并查看匹配结果。
11. 导出每日研究工作簿 Excel。
12. 根据自己的研究口径筛选、排序、记录和复盘。

## 14. 不应如何使用本系统

不应这样使用本系统：

- 不应把页面序号或 Excel 序号当作买入顺序。
- 不应把 `total_score` 当作收益预测。
- 不应把埃尔德分当作买入信号。
- 不应把买入区间、止损位或目标价位当作自动交易指令。
- 不应忽略数据质量提示。
- 不应在 PE、PB、行情或周线样本缺失时强行解读。
- 不应把观察池当作买入清单。
- 不应把外部模拟持仓导入当作真实交易记录。
- 不应将本系统输出作为投资建议。

本系统的价值在于帮助用户整理数据、缩小研究范围、保留每日研究档案，并把需要人工判断的地方明确显示出来。最终判断仍由用户自行负责。

## 15. 源码位置索引

| 模块 | 主要文件 / 函数 | 说明 |
|---|---|---|
| 股票池与可交易性过滤 | `core/universe/stock_pool.py::build_tradeable_universe`; `core/data_sources/real_universe.py`; `core/data_sources/universe_presets.py` | 解析股票池、过滤 ST / 北交所 / 退市 / 上市时长 / 流动性 / 近期成交连续性。 |
| 数据更新 | `core/jobs/update_real_data.py`; `core/jobs/run_full_batch_update.py`; `core/data_sources/akshare_client.py`; `core/runtime/data_source_preflight.py` | 更新本地 DuckDB 数据、全市场批量补数据、东方财富 K 线 fallback、数据源预检。 |
| 因子函数库 | `core/factors/trend.py`; `core/factors/momentum.py`; `core/factors/liquidity.py`; `core/factors/fundamental.py`; `core/factors/volatility.py` | 提供基础指标函数，例如 20 日收益、均线位置、相对强弱、成交额、PE/PB、波动率、最大回撤等。 |
| 当前日常选股因子流水线 | `core/jobs/run_daily_selection.py::_calculate_minimal_real_scores` | 当前主链路实际使用 `return_20d`、`avg_amount_20d`、`avg_turnover_20d`、`pe_score`、`volatility_20d` 生成分项分数。 |
| 横截面标准化与 `total_score` | `core/factors/scoring.py::normalize_factor`; `core/factors/scoring.py::calculate_total_score`; `core/factors/scoring.py::DEFAULT_WEIGHTS` | 同一交易日 min-max 标准化，默认权重汇总综合分。 |
| 今日候选 | `core/strategy/selector.py::select_top_stocks`; `core/jobs/run_daily_selection.py` | 按 `trade_date` 分组，剔除 `total_score` 缺失，按 `total_score` 降序取 Top N，并写入 `strategy_result`。 |
| 埃尔德复核 | `core/technical/elder.py::calculate_elder_indicators`; `core/technical/elder.py::calculate_weekly_elder_trend`; `core/technical/elder.py::build_elder_review`; `core/technical/elder.py::_classify_elder_state` | 计算 EMA、MACD、Force Index、Bull/Bear Power、周线趋势和 `elder_score` / `action_hint`。 |
| 埃尔德复核命令与导出 | `core/jobs/run_elder_review.py`; `core/jobs/export_elder_review.py`; `core/jobs/backtest_elder_review.py` | 运行复核、导出复核报告、做历史回看。 |
| 买入区间 | `core/entry_zones/calculator.py::add_technical_indicators`; `core/entry_zones/calculator.py::calculate_entry_zones_for_targets`; `core/entry_zones/calculator.py::_entry_zone_record` | 计算 EMA、支撑阻力、ATR14、买入区间、止损位、目标价位和盈亏比。 |
| 买入区间命令与导出 | `core/jobs/calculate_entry_zones.py`; `core/jobs/diagnose_entry_zones.py`; `core/jobs/export_entry_zone_report.py` | 计算、诊断、导出买入区间研究报告。 |
| 观察池 | `core/review/decisions.py`; `core/review/watchlist_scores.py`; `core/review/tracking.py`; `core/jobs/refresh_watchlist_from_selection.py`; `core/jobs/track_watchlist.py` | 观察池决策、评分刷新、每日快照、状态变化和事件记录。 |
| 观察池报告 | `core/reporting/watchlist_report.py`; `core/reporting/watchlist_tracking_report.py`; `core/jobs/export_watchlist.py`; `core/jobs/export_watchlist_tracking.py` | 导出当前观察池和观察池每日跟踪报告。 |
| 外部模拟持仓 | `core/external_positions/importer.py`; `core/jobs/import_external_positions.py`; `core/jobs/export_external_position_report.py` | 导入外部模拟持仓并匹配买入区间、止损位、目标价和风险状态。 |
| 每日研究 Excel | `core/jobs/export_daily_research_workbook.py` | 导出包含摘要、今日候选、埃尔德复核、买入区间、观察池、外部模拟持仓、数据质量等 Sheet 的工作簿。 |
| 日常工作流报告 | `core/jobs/run_daily_workflow.py`; `core/reporting/daily_workflow_report.py`; `core/reporting/workflow_report.py` | 串行执行诊断、选股、复核、报告生成等本地流程。 |
| Streamlit 页面展示 | `web/streamlit_app.py` | 页面展示、下载核心逻辑说明、数据更新状态、今日选股、选股逻辑、埃尔德复核、买入区间、观察池、外部模拟持仓和 Excel 导出入口。 |
