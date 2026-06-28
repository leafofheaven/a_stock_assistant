# 选股逻辑说明

本项目当前选股逻辑是固定规则的本地评分流程，不包含自动交易。页面和报告中的候选结果用于个人研究、复盘、观察池管理和人工复核。

## 综合评分公式

当前 `total_score` 使用 `core/factors/scoring.py` 中的默认权重：

```text
total_score = trend_score * 0.30 + momentum_score * 0.20 + liquidity_score * 0.20 + fundamental_score * 0.15 + volatility_score * 0.15
```

缺失的分项在总分计算中按 0 处理，避免本地数据不完整时流程崩溃。

## 因子说明

| 因子 | 权重 | 说明 |
| --- | ---: | --- |
| 趋势 `trend_score` | 0.30 | 观察近 20 日 / 60 日涨跌幅、均线位置和均线排列。 |
| 动量 `momentum_score` | 0.20 | 观察相对强弱和 60 日新高情况。 |
| 流动性 `liquidity_score` | 0.20 | 观察近 20 日成交额和换手率。 |
| 基本面 `fundamental_score` | 0.15 | 观察 PE、PB、ROE、营收增长等基础估值 / 财务字段。 |
| 波动风险 `volatility_score` | 0.15 | 观察近 20 日波动率和 60 日最大回撤，分数越高代表当前规则下风险分项越好。 |

## 选股流程

1. 读取本地 DuckDB 或 sample 数据。
2. 构建可交易股票池，排除 ST、停牌、上市交易日不足、流动性不足等样本。
3. 按 `ts_code` 和 `trade_date` 计算基础因子。
4. 在同一 `trade_date` 内做横截面标准化。
5. 使用固定权重计算 `total_score`。
6. 每个交易日按 `total_score` 从高到低排序，输出 Top N 候选。
7. 候选结果进入人工复核、观察池和报告。

## 候选解释

Task 36 新增的解释层会展示：

- 每只候选股票的因子加权贡献；
- 排名靠前的主要贡献因子；
- 低分或缺失字段形成的弱项；
- 当前 `logic_version` 和公式摘要；
- 相关源码路径。

解释层只读取已有评分结果，不改变公式、权重、排序或候选股票。

## 查看方式

```bash
python -m core.jobs.explain_selection_logic
python -m core.jobs.explain_selection_logic --format markdown
python -m core.jobs.explain_selection_logic --ts-code 002475.SZ
streamlit run web/streamlit_app.py
```

Streamlit 页面中可以在“选股逻辑”Tab 查看公式、因子说明、流程说明和当前候选股票的排名原因。

个人研究工具，结果需自行复核。
