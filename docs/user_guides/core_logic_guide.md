# A 股选股辅助系统：核心计算逻辑与公式说明

本说明用于解释系统筛选股票、计算分数、生成候选、做埃尔德复核、计算买入区间和维护观察池的核心计算口径。它只解释当前代码已经实现的逻辑，不新增公式，不修改权重，不改变排序。

本系统仅供个人研究使用，不自动交易，不接券商，不构成投资建议。综合分（total_score）不是收益预测，埃尔德分（elder_score）不是买入信号，买入区间不是交易指令，页面和 Excel 中的“序号”也不是买入顺序。

## 0. 字段命名约定

本系统用户可见字段尽量采用“中文名称（英文名）”格式。中文名称用于理解含义，英文名用于和代码、数据库字段或导出字段对应。

例如：

- 综合分（total_score）
- 趋势分（trend_score）
- 动量分（momentum_score）
- 流动性分（liquidity_score）
- 基本面分（fundamental_score）
- 波动分（volatility_score）
- 埃尔德分（elder_score）
- 操作提示（action_hint）
- 买入区间下限（entry_low）
- 止损价（stop_loss）
- 盈亏比（reward_risk_ratio）

后续 Excel、页面和说明文档应尽量保持同一套命名口径：表头尽量中文；如需保留英文内部字段名，使用括号并列；不要出现一列中文、一列英文、另一列拼音或半翻译的混杂口径；不默认导出排名字段（rank）类字段。

## 1. 先看总流程

系统完整链路是：

股票池 -> 可交易性过滤 -> 行情与估值数据 -> 分项因子计算 -> 横截面标准化 -> 综合分（total_score） -> 今日候选 -> 埃尔德复核 -> 买入区间 / 止损 / 目标价 -> 观察池 -> Excel 留档。

核心思路是：

1. 先用可交易性过滤排除明显不适合进入研究池的股票。
2. 再用综合分（total_score）从可交易股票中缩小研究范围。
3. 再用埃尔德复核判断当前技术节奏。
4. 再用买入区间整理价格计划参考。
5. 最后把需要持续看的股票放入观察池，并导出每日研究工作簿。

伪代码如下：

```text
对每个交易日期（trade_date）:
    读取股票基础信息、日行情、估值数据
    构建可交易股票池
    计算 20日收益率（return_20d）、20日平均成交额（avg_amount_20d）、
        市盈率倒数分（pe_score）、20日波动率（volatility_20d）
    在同一交易日期内做横截面标准化
    生成趋势分（trend_score）、动量分（momentum_score）、
        流动性分（liquidity_score）、基本面分（fundamental_score）、波动分（volatility_score）
    计算综合分（total_score）
    按综合分选出 Top N 今日候选
    保存因子分数和选股结果
    对候选和观察池做埃尔德复核
    计算买入区间、止损价、目标价
    更新观察池快照
    导出报告和 Excel 工作簿
```

## 2. 股票池与可交易性过滤公式

可交易性过滤是进入研究池的门槛，不是买入条件。full 模式代表沪深 A 股全市场，不含北交所。

当前过滤口径包括：

1. 排除北交所：
   - 排除 BSE / BJ；
   - 排除 8 开头、4 开头等北交所代码；
   - `INCLUDE_BSE=false` 时不纳入北交所。

2. 排除 ST / *ST / 退市整理 / 退市名称：
   - 名称中包含 ST、*ST、退市、退市整理等异常标识的股票会被排除。

3. 上市天数：

```text
listing_days >= MIN_LISTING_DAYS
```

当前默认：

```text
MIN_LISTING_DAYS = 120
```

4. 近 20 日有效交易天数：

```text
traded_days_20d >= MIN_TRADED_DAYS_20D
```

当前默认：

```text
MIN_TRADED_DAYS_20D = 18
```

5. 近 20 日平均成交额：

```text
avg_amount_20d >= MIN_AVG_AMOUNT_20D
```

当前默认：

```text
MIN_AVG_AMOUNT_20D = 100000000
```

即近 20 日平均成交额不低于 1 亿元。

6. 近 20 日成交额中位数：

```text
median_amount_20d >= MIN_MEDIAN_AMOUNT_20D
```

当前默认：

```text
MIN_MEDIAN_AMOUNT_20D = 50000000
```

7. 最新成交额：

```text
latest_amount >= MIN_LATEST_AMOUNT
```

当前默认：

```text
MIN_LATEST_AMOUNT = 30000000
```

如果某股票因为停牌、接口空数据或成交不连续被排除，它不是永久黑名单。后续复牌并重新满足数据和成交条件后，可以重新进入研究池。

## 3. 横截面标准化公式

所有分项分数都依赖横截面标准化。横截面标准化的含义是：只在同一个交易日期（trade_date）内，把当天同一批股票的某个指标转成 0 到 100 分。

如果该指标越高越好：

```text
score = (value - min_value) / (max_value - min_value) * 100
```

如果该指标越低越好：

```text
score = 100 - [(value - min_value) / (max_value - min_value) * 100]
```

特殊情况：

1. 如果同一交易日所有有效值都相同：

```text
score = 50
```

2. NaN / inf / 不可转数值：
   - 不参与 `min_value` 和 `max_value` 计算；
   - 标准化结果保持缺失。

3. 标准化范围：
   - 只在同一个交易日期（trade_date）内比较；
   - 不跨日期比较；
   - 不使用未来数据。

用户理解：分数不是绝对分，而是“当天同一批股票里的相对位置分”。例如趋势分（trend_score）=90，表示它当天在该股票池中的 20 日涨幅相对靠前，不表示未来一定上涨。

## 4. 分项因子公式

### 4.1 趋势分（trend_score）

计算目的：衡量股票过去约 20 个交易日的价格趋势强弱。

输入数据：

- 股票代码（ts_code）
- 交易日期（trade_date）
- 收盘价（close）

计算公式：

```text
20日收益率（return_20d）= 当前收盘价 / 20 个交易日前收盘价 - 1
```

分数生成：

```text
趋势分（trend_score）= 对同一交易日期（trade_date）内的 20日收益率（return_20d）做横截面标准化
```

分数方向：20日收益率（return_20d）越高，趋势分（trend_score）越高。

缺失处理：

- 少于 20 个交易日时，20日收益率（return_20d） 为空；
- 趋势分（trend_score） 为空；
- 计算综合分（total_score）时该分项按 0 处理。

用户如何理解：趋势分高，说明这只股票近期涨幅在同日股票池中靠前，但不代表可以买入，还要看是否过热、是否有买入区间、流动性是否足够。

### 4.2 动量分（momentum_score）

计算目的：衡量近期强势程度。

重要说明：当前主链路中，动量分（momentum_score）目前也使用 20日收益率（return_20d），因此它与趋势分（trend_score）存在重叠，不是两个完全独立的指标。

输入数据：

- 股票代码（ts_code）
- 交易日期（trade_date）
- 收盘价（close）

计算公式：

```text
20日收益率（return_20d）= 当前收盘价 / 20 个交易日前收盘价 - 1
```

分数生成：

```text
动量分（momentum_score）= 对同一交易日期（trade_date）内的 20日收益率（return_20d）做横截面标准化
```

分数方向：20日收益率（return_20d）越高，动量分（momentum_score）越高。

缺失处理：

- 少于 20 个交易日时，20日收益率（return_20d） 为空；
- 动量分（momentum_score） 为空；
- 计算综合分（total_score）时该分项按 0 处理。

用户如何理解：在当前版本中，趋势分和动量分都偏向“近期强势程度”，因此综合分（total_score）对近期涨幅较强的股票会有较明显偏好。后续如果接入相对强弱、60 日新高等指标，动量分（momentum_score）可以进一步独立化。

### 4.3 流动性分（liquidity_score）

计算目的：衡量股票交易是否活跃。

输入数据：

- 成交额（amount）
- 股票代码（ts_code）
- 交易日期（trade_date）

计算公式：

```text
20日平均成交额（avg_amount_20d）= 最近 20 个交易日成交额均值
```

分数生成：

```text
流动性分（liquidity_score）= 对同一交易日期（trade_date）内的 20日平均成交额（avg_amount_20d）做横截面标准化
```

分数方向：20日平均成交额（avg_amount_20d）越高，流动性分（liquidity_score）越高。

缺失处理：

- 成交额（amount）缺失时，20日平均成交额（avg_amount_20d）可能为空；
- 流动性分（liquidity_score） 为空；
- 计算综合分（total_score）时该分项按 0 处理。

用户如何理解：流动性分高，说明成交额较活跃，理论上更适合交易型研究；流动性分低的股票即使其他分数高，也要谨慎。

### 4.4 基本面分（fundamental_score）

计算目的：当前主链路主要用估值口径衡量基本面 / 估值吸引力。

输入数据：

- 市盈率（pe）
- 股票代码（ts_code）
- 交易日期（trade_date）

计算公式：

```text
如果 pe > 0:
    市盈率倒数分（pe_score）= 1 / 市盈率（pe）
否则:
    市盈率倒数分（pe_score）= 空
```

分数生成：

```text
基本面分（fundamental_score）= 对同一交易日期（trade_date）内的市盈率倒数分（pe_score）做横截面标准化
```

因为：

```text
市盈率倒数分（pe_score）= 1 / 市盈率（pe）
```

所以正 PE 越低，市盈率倒数分（pe_score）越高，基本面分（fundamental_score）越高。

缺失处理：

- 市盈率（pe）缺失时，市盈率倒数分（pe_score）为空；
- 市盈率（pe）<= 0 时，市盈率倒数分（pe_score）为空；
- 市盈率（pe）不可转数值时，市盈率倒数分（pe_score）为空；
- 基本面分（fundamental_score）为空；
- 计算综合分（total_score）时该分项按 0 处理。

当前主筛选口径没有稳定把 ROE、PB、营收增长合成到基本面分（fundamental_score）。代码里可以存在 ROE、PB、营收增长相关函数，但它们暂未进入当前主筛选口径。

用户如何理解：基本面分高主要表示当前正 PE 相对较低，不等同于公司基本面一定优秀。PE 缺失或非正时，该分项会缺失并在综合分（total_score）中按 0 处理。

### 4.5 波动分（volatility_score）

计算目的：衡量股票近期波动风险。

输入数据：

- 收盘价（close）
- 股票代码（ts_code）
- 交易日期（trade_date）

计算公式：

```text
日收益率（daily_return）= 收盘价（close）.pct_change()
20日波动率（volatility_20d）= 最近 20 个交易日日收益率（daily_return）的标准差
```

分数生成：

```text
波动分（volatility_score）= 对同一交易日期（trade_date）内的20日波动率（volatility_20d）做反向横截面标准化
```

也就是：

```text
20日波动率（volatility_20d）越低，波动分（volatility_score）越高
20日波动率（volatility_20d）越高，波动分（volatility_score）越低
```

缺失处理：

- 少于足够收益样本时，20日波动率（volatility_20d）为空；
- 波动分（volatility_score）为空；
- 计算综合分（total_score）时该分项按 0 处理。

用户如何理解：波动分高，说明近期波动相对较小；波动分低，说明价格波动较大，即使涨幅强，也可能风险更高。

## 5. 综合分（total_score）公式

当前默认权重如下：

```text
total_score =
  0.30 * 趋势分（trend_score）
+ 0.20 * 动量分（momentum_score）
+ 0.20 * 流动性分（liquidity_score）
+ 0.15 * 基本面分（fundamental_score）
+ 0.15 * 波动分（volatility_score）
```

含义：

1. 趋势分（trend_score）权重 30%。
2. 动量分（momentum_score）权重 20%。
3. 流动性分（liquidity_score）权重 20%。
4. 基本面分（fundamental_score）权重 15%。
5. 波动分（volatility_score）权重 15%。

缺失处理：

```text
如果某个分项为空，则在综合分（total_score）中按 0 参与计算。
```

举例：

```text
趋势分（trend_score）= 80
动量分（momentum_score）= 80
流动性分（liquidity_score）= 70
基本面分（fundamental_score）= 空
波动分（volatility_score）= 60
```

则：

```text
综合分（total_score）=
0.30 * 80
+ 0.20 * 80
+ 0.20 * 70
+ 0.15 * 0
+ 0.15 * 60
= 24 + 16 + 14 + 0 + 9
= 63
```

缺失分项按 0 会拉低综合分。综合分（total_score）越高，说明这只股票在当前可交易股票池里，按当前权重综合看更靠前，但它仍不是收益预测，也不是买入优先级。

## 6. 今日候选如何生成

今日候选生成步骤：

1. 计算所有可交易股票的分项分数和综合分（total_score）。
2. 剔除综合分（total_score）缺失的股票。
3. 在同一个交易日期（trade_date）内按综合分（total_score）从高到低排序。
4. 如果综合分（total_score）相同，按股票代码排序作为稳定排序。
5. 取 Top N。
6. 写入选股结果表（strategy_result）。
7. Streamlit 今日选股页面读取最新选股结果表（strategy_result）。

今日候选不是买入清单，只是进入人工研究的候选名单。

页面和 Excel 的“序号”只是当前显示顺序，不是买入顺序。内部排名字段（rank）不作为普通用户默认判断依据，也不应被理解为交易优先级。

## 7. 计算示例

### 示例一：为什么一只股票得分高

假设某股票：

- 20 日涨幅靠前，趋势分（trend_score） / 动量分（momentum_score）高；
- 近 20 日成交额高，流动性分（liquidity_score）高；
- PE 为正且相对较低，基本面分（fundamental_score）较高；
- 20 日波动率较低，波动分（volatility_score）较高。

则综合分（total_score）会较高，更容易进入今日候选。

### 示例二：为什么看起来不错但没进候选

假设某股票：

- 近期涨幅不错；
- 但成交额不足；
- PE 缺失或为负；
- 波动率较高。

则趋势分可能不错，但流动性分、基本面分、波动分会拖累综合分（total_score），因此可能无法进入 Top N。

## 8. 埃尔德复核计算公式

埃尔德复核是二次技术状态判断层。它不覆盖 综合分（total_score），不修改因子权重，不改变今日候选排序，也不代表买入优先级。

主要输出字段采用中文名称（英文名）口径：

- 埃尔德分（elder_score）：技术状态 / 节奏复核分。
- 操作提示（action_hint）：例如“趋势确认，进入人工复核”“短线过热，不追”等。
- 复核原因（elder_reason）：解释为什么得到当前操作提示。
- 周线趋势（weekly_trend）：描述周线是否改善。
- 日线回调（daily_pullback）：描述价格是否接近 EMA 节奏。
- 强力指数信号（force_signal）：描述强力指数是否转强。
- 埃尔德射线信号（elder_ray_signal）：描述多头力量或空头压力变化。

### 8.1 日线指标

指数移动平均线（EMA）：

```text
13日指数移动平均线（EMA13）= 收盘价（close）的 13 日指数移动平均
22日指数移动平均线（EMA22）= 收盘价（close）的 22 日指数移动平均
```

MACD：

```text
MACD线（MACD line）= 12日EMA - 26日EMA
MACD信号线（MACD signal）= MACD线的 9 日 EMA
MACD柱状图（MACD histogram）= MACD线 - MACD信号线
MACD柱状图斜率（MACD histogram slope）= MACD柱状图当日值 - 前一日值
```

强力指数（Force Index）：

```text
强力指数（force_index）= (收盘价（close） - 前一日收盘价（previous_close）) * 成交量（vol）
2日平滑强力指数（force_index_2d）= 强力指数的 2 日平滑
13日平滑强力指数（force_index_13d）= 强力指数的 13 日平滑
```

如果数据没有成交量（vol），系统会用成交额（amount）作为回退字段参与强力指数（Force Index）计算。

埃尔德射线（Elder-ray）：

```text
多头力量（Bull Power / bull_power）= 最高价（high） - 13日指数移动平均线（EMA13）
空头力量（Bear Power / bear_power）= 最低价（low） - 13日指数移动平均线（EMA13）
```

价格相对 EMA 的距离：

```text
相对EMA13距离（close_to_ema13_pct）= (收盘价（close） - EMA13) / EMA13 * 100%
相对EMA22距离（close_to_ema22_pct）= (收盘价（close） - EMA22) / EMA22 * 100%
```

### 8.2 周线趋势判断

周线由日线聚合得到。周线趋势改善条件为：

```text
周收盘价（weekly_close）>= 周线EMA13（weekly_EMA13）
并且
(
    周线EMA13（weekly_EMA13）>= 周线EMA22（weekly_EMA22）
    或 MACD柱状图斜率（MACD histogram slope）> 0
)
```

如果周线样本少于 12 周，则周线样本不足。

### 8.3 日线回调判断

如果：

```text
abs(相对EMA13距离（close_to_ema13_pct）) <= 5
或
abs(相对EMA22距离（close_to_ema22_pct）) <= 8
```

则认为价格仍在均线节奏附近：

```text
日线回调有效（daily_pullback_ok）= true
```

### 8.4 短线过热判断

如果：

```text
相对EMA13距离（close_to_ema13_pct）> 10
且
相对EMA22距离（close_to_ema22_pct）> 12
```

则认为短线过热，操作提示（action_hint） 可能为“短线过热，不追”。

### 8.5 埃尔德分（elder_score） 加分规则

埃尔德分（elder_score） 初始为 0：

- 周线趋势改善：+35
- 日线接近 EMA：+20
- 未短线过热：+10
- Force Index 2 日由负转正：+15
- MACD histogram slope > 0：+10
- Elder-ray 多头增强或空头压力减弱：+10

Elder-ray 多头增强或空头压力减弱的判断是：

```text
多头力量（bull_power）> 0
或
空头力量（bear_power）> 前一日空头力量（previous_bear_power）
```

短线触发成立的判断是：

```text
2日平滑强力指数（force_index_2d）由负转正
或
(
    MACD柱状图斜率（MACD histogram slope）> 0
    且埃尔德射线（Elder-ray）多头增强或空头压力减弱
)
```

### 8.6 操作提示（action_hint） 生成规则

1. 如果周线趋势未改善：

```text
埃尔德分（elder_score）最高限制为 45
操作提示（action_hint）= “趋势偏弱，暂缓”
```

2. 如果短线过热：

```text
埃尔德分（elder_score）最高限制为 70
操作提示（action_hint）= “短线过热，不追”
```

3. 如果周线改善 + 日线接近 EMA + 短线触发成立：

```text
埃尔德分（elder_score）最高 100
操作提示（action_hint）= “趋势确认，进入人工复核”
```

4. 如果周线改善 + 日线接近 EMA + 短线触发不明确：

```text
埃尔德分（elder_score）最高 85
操作提示（action_hint）= “趋势尚可，等待回调”
```

5. 如果周线改善但价格离 EMA 较远：

```text
埃尔德分（elder_score）最高 75
操作提示（action_hint）= “趋势尚可，等待回调”
```

6. 如果日线样本不足：

```text
埃尔德分（elder_score）= 0
操作提示（action_hint）= “数据不足”
```

7. 如果周线样本不足：

```text
埃尔德分（elder_score）= 0
操作提示（action_hint）= “数据不足”
```

如果某只股票行情日期落后于全局最新交易日，系统使用该股票自身最新可用行情日期做复核，避免把“缺最新交易日行情”误判成“日线数据不足”。

## 9. 买入区间计算公式

买入区间、止损位、目标价位和盈亏比是启发式研究计划参考，不是买入卖出指令。

指数移动平均线（EMA）：

```text
13日指数移动平均线（EMA13）= 收盘价（close）的 13 日 EMA
22日指数移动平均线（EMA22）= 收盘价（close）的 22 日 EMA
60日指数移动平均线（EMA60）= 收盘价（close）的 60 日 EMA
```

支撑和阻力：

```text
20日支撑位（support_20d）= 最近 20 日最低价（low）的最小值
60日支撑位（support_60d）= 最近 60 日最低价（low）的最小值
20日阻力位（resistance_20d）= 最近 20 日最高价（high）的最大值
60日阻力位（resistance_60d）= 最近 60 日最高价（high）的最大值
```

14日平均真实波幅（ATR14）：

```text
真实波幅（true_range）= max(
    最高价（high） - 最低价（low）,
    abs(最高价（high） - 前一日收盘价（previous_close）),
    abs(最低价（low） - 前一日收盘价（previous_close）)
)

14日平均真实波幅（ATR14）= 真实波幅（true_range）的 14 日均值
```

最近支撑和最近阻力：

```text
最近支撑位（nearest_support）=
在 20日支撑位（support_20d）、60日支撑位（support_60d）、
22日指数移动平均线（EMA22）、60日指数移动平均线（EMA60）中，
取不高于当前收盘价（close）的最大值

最近阻力位（nearest_resistance）=
在 20日阻力位（resistance_20d）、60日阻力位（resistance_60d）中，
取不低于当前收盘价（close）的最小值
```

趋势偏弱：

```text
收盘价（close）< 60日指数移动平均线（EMA60）
或
13日指数移动平均线（EMA13）< 22日指数移动平均线（EMA22）< 60日指数移动平均线（EMA60）
```

过热：

```text
相对EMA13距离（close_to_ema13_pct）> 10%
或
相对EMA22距离（close_to_ema22_pct）> 14%
或
当前价距离最近阻力位（nearest_resistance）小于 3%
```

如果趋势不弱：

```text
买入区间下限（entry_low）= 最近支撑位（nearest_support）或 22日指数移动平均线（EMA22）或 20日支撑位（support_20d）
买入区间上限（entry_high）= 买入区间下限（entry_low） + 0.5 * 14日平均真实波幅（ATR14）
买入区间中值（entry_mid）= (买入区间下限（entry_low） + 买入区间上限（entry_high）) / 2
```

如果趋势偏弱：

```text
买入区间下限（entry_low）= 最近支撑位（nearest_support）或 20日支撑位（support_20d）
买入区间上限（entry_high）= 22日指数移动平均线（EMA22）或 收盘价（close）
买入区间状态（entry_zone_status）= weak_no_entry
```

止损参考：

```text
缓冲距离（buffer）= max(14日平均真实波幅（ATR14）, 买入区间中值（entry_mid） * 3%)
基准价（base）= 最近支撑位（nearest_support）或 买入区间中值（entry_mid）
止损价（stop_loss）= min(基准价（base） - 缓冲距离（buffer）, 买入区间中值（entry_mid） * 0.92)
```

风险：

```text
风险距离（risk）= 买入区间中值（entry_mid） - 止损价（stop_loss）
```

目标价参考：

```text
盈亏比目标价（rr_target）= 买入区间中值（entry_mid） + 2 * 风险距离（risk）

如果没有有效阻力位:
    目标价（target_price）= 盈亏比目标价（rr_target）

如果有有效阻力位:
    目标价（target_price）= max(最近阻力位（nearest_resistance）, 盈亏比目标价（rr_target）)
```

收益和盈亏比：

```text
收益距离（reward）= 目标价（target_price） - 买入区间中值（entry_mid）
盈亏比（reward_risk_ratio）= 收益距离（reward） / 风险距离（risk）
风险比例（risk_pct）= 风险距离（risk） / 买入区间中值（entry_mid）
收益比例（reward_pct）= 收益距离（reward） / 买入区间中值（entry_mid）
```

状态判断：

- 数据不足（insufficient_data）：少于 20 个交易日，或关键价格 / 区间字段缺失。
- 趋势偏弱（weak_no_entry）：趋势偏弱。
- 高于区间（above_zone）：短线过热且价格高于区间，或价格高于区间上沿。
- 位于区间（in_zone）：买入区间下限（entry_low）<= 收盘价（close）<= 买入区间上限（entry_high）。
- 接近区间（near_zone）：当前价距离区间上下沿不超过 `max(0.5 * ATR14, close * 2%)`。
- 低于区间（below_zone）：当前价低于区间且不满足接近区间。

追高风险：

- 高（high）：高于区间，或相对EMA13距离（close_to_ema13_pct）> 10%，或相对EMA22距离（close_to_ema22_pct）> 14%。
- 中（medium）：接近区间或低于区间。
- 低（low）：其他情况。

## 10. 普通用户如何使用这些公式

建议使用顺序：

1. 先用 综合分（total_score） 缩小候选范围。
2. 看 趋势分（trend_score） / 动量分（momentum_score），确认近期强弱。
3. 看 流动性分（liquidity_score），排除流动性太差的股票。
4. 看 基本面分（fundamental_score），注意 PE 缺失或非正导致分项为空。
5. 看 波动分（volatility_score），识别高波动风险。
6. 看埃尔德复核：
   - “短线过热，不追”：说明节奏偏高，先避免追高。
   - “趋势尚可，等待回调”：说明趋势结构尚可，但触发或价格位置还需观察。
   - “趋势偏弱，暂缓”：说明技术结构不够强。
   - “趋势确认，进入人工复核”：说明技术节奏满足复核条件，但仍不是买入指令。
7. 看买入区间：
   - 当前价是否在区间内；
   - 是否明显高于区间；
   - 是否接近止损；
   - 盈亏比（reward_risk_ratio） 是否合理；
   - 追高风险是否过高。
8. 最后进入观察池跟踪。
9. 不使用 排名字段（rank） 或序号作为买入优先级。

## 11. 观察池、模拟持仓与 Excel

观察池用于持续跟踪，不是买入清单。股票掉出当日 Top N 后，不会因此自动从观察池删除。观察池每日跟踪会记录综合分变化、是否重新进入 Top N、是否新候选、埃尔德复核变化和每日备注。

外部模拟持仓用于把用户手工导入的模拟仓位与买入区间、止损位、目标价、盈亏比、风险状态进行匹配。系统不读取同花顺 / 雪球登录态，不接券商，不自动交易。外部模拟持仓不代表真实交易。

每日研究工作簿 Excel 用于复盘和留档，包含今日候选、埃尔德复核、买入区间、观察池、观察池跟踪、外部模拟持仓、数据质量和参数配置等 Sheet。Excel 默认应避免导出 rank 字段；序号只代表当前 Sheet 显示顺序，不代表买入优先级。

## 12. 数据质量与常见异常

常见异常包括：

- 数据源不可用，例如东方财富 K 线接口暂时不可访问。
- DuckDB 被锁，例如另一个任务、Streamlit 或 macOS FileProvider 占用数据库。
- Python / macOS 系统代理异常。
- PE / PB 缺失，导致估值或基本面相关分项缺失。
- 最新行情不足，导致部分股票暂时无法计算因子、埃尔德复核或买入区间。
- 接口空数据股票，会被记录为空数据或暂不可用，不应中断整个流程。

数据质量 warning 不一定代表系统不可用，但会影响部分股票或部分分项的判断。

## 13. 使用边界

必须保留以下边界：

- 仅供个人研究使用。
- 不自动交易。
- 不接券商。
- 不构成投资建议。
- 综合分（total_score） 不是收益预测。
- 埃尔德分不是买入信号。
- 买入区间不是交易指令。
- 止损位和目标价位是研究计划参考。
- 页面序号和 Excel 序号不是买入顺序。
- 数据缺失时不要强行解读。
