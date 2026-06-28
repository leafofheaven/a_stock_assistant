# 埃尔德复核

埃尔德复核是今日候选股票之后的二次技术复核层。它只读取本地 `daily_price` 和当前候选结果，不修改 `total_score` 公式、不修改因子权重，也不改变今日选股原始排序。

## 指标范围

当前复核会计算：

- EMA13；
- EMA22；
- MACD；
- MACD signal；
- MACD histogram；
- MACD histogram slope；
- Elder Force Index 2 日平滑；
- Elder Force Index 13 日平滑；
- Bull Power = high - EMA13；
- Bear Power = low - EMA13；
- close_to_ema13_pct；
- close_to_ema22_pct。

## 复核框架

第一层看周线趋势：

- 基于日线聚合周线；
- 判断周线 EMA 结构；
- 判断周线 MACD histogram 是否改善。

第二层看日线回调：

- 判断收盘价是否接近 EMA13 / EMA22；
- 避免明显追高；
- 判断是否仍处于趋势结构内。

第三层看短线触发：

- Force Index 是否由负转正；
- MACD histogram 是否由弱转强；
- Elder Ray 是否显示空头压力减弱或多头力量增强。

## 输出字段

复核结果会保留原始候选字段，并新增：

- `elder_score`：二次复核分，仅用于人工复核；
- `action_hint`：复核状态；
- `elder_reason`：中文解释；
- EMA / MACD / Force Index / Elder Ray 等指标字段。

`action_hint` 可能包括：

- 趋势确认，进入人工复核；
- 趋势尚可，等待回调；
- 短线过热，不追；
- 趋势偏弱，暂缓；
- 数据不足。

## 命令

```bash
python -m core.jobs.run_elder_review
python -m core.jobs.run_elder_review --format markdown
```

## 页面

启动页面：

```bash
streamlit run web/streamlit_app.py
```

进入“埃尔德复核”标签页查看当前候选的二次复核结果。页面会保留原始 `total_score`，并展示 `elder_score`、`action_hint` 和指标明细。

## 限制

- 仅供个人研究使用，不自动交易。
- 不输出买卖指令，不接券商。
- 数据不足时会显示“数据不足”，不会抛出难懂异常。
- `elder_score` 不是新的选股排序依据，只用于今日候选之后的人工技术复核。
