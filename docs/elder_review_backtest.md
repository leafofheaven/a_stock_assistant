# 埃尔德复核历史回看

Task 42 增加 `backtest_elder_review`，用于回看埃尔德复核层在历史样本中的表现。它只读取本地 `daily_price` 或 sample 数据，不修改 `total_score`、因子权重、今日选股原始排序，也不会自动交易。

Task 43 后，回看报告把 `elder_score` 明确定位为“技术状态 / 节奏复核分”，不是买入优先级或收益预测。

## 运行命令

默认生成 Markdown、CSV、JSON：

```bash
python -m core.jobs.backtest_elder_review
```

只输出 Markdown：

```bash
python -m core.jobs.backtest_elder_review --format markdown
```

指定区间并导出全部格式：

```bash
python -m core.jobs.backtest_elder_review --start-date 20240101 --end-date 20260625 --format all
```

报告默认写入 `reports/elder_backtest_*.md`、`reports/elder_backtest_*.csv`、`reports/elder_backtest_*.json`。这些是本地生成文件，不应提交到 Git。

## 回看口径

每个信号日只使用该股票截至当日的行情计算埃尔德复核结果，后续收益指标只在信号生成后计算，避免未来函数。

当前输出指标包括：

- `forward_return_5d`
- `forward_return_10d`
- `forward_return_20d`
- `max_drawdown_20d`
- `max_gain_20d`
- `hit_rate_5d`
- `hit_rate_10d`
- `hit_rate_20d`

分组统计包括：

- `elder_score` 分组：top / middle / bottom
- `action_hint` 分组：趋势确认，进入人工复核；趋势尚可，等待回调；短线过热，不追；趋势偏弱，暂缓；数据不足
- 当前候选 / `selection_review` 样本分组：当明细中存在 `rank` 或 `total_score` 时单独统计；
- `total_score 分层`：high / middle / low / unknown，用于观察同一选股强弱层里的 Elder 表现；
- 市场阶段分层：strong / range / weak / unknown，基于样本平均 20 日历史涨跌粗分，不使用未来数据；
- 市场阶段 x `action_hint` 组合分层。

## 如何解读

重点看 top / middle / bottom 的 5 日、10 日、20 日未来收益和命中率是否有梯度，也可以看不同 `action_hint` 的后续表现是否符合直觉。若 top 组或“趋势确认”组没有跑赢其他组，应把它理解为节奏提示，而不是收益预测。

`短线过热，不追` 的含义是短期回撤风险偏高；如果 20 日 `max_gain` 较高，可能说明它处在强趋势中的高位波动阶段，不应简单解读为中期趋势差。

如果报告显示有效信号数量很少，通常是因为样本股票少、历史天数不足，或接近样本结束日期的记录缺少未来 20 日行情。

## 限制

- 当前只用于个人本地研究和复盘。
- 少量股票样本的结果不代表全市场结论。
- 回看结果不构成交易建议。
- 不自动交易。
