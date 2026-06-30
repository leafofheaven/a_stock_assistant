# 买入区间、支撑阻力和止损位

Task 49 增加本地买入区间分析。它只读取本地 `daily_price`、最新 `strategy_result` 和观察池数据，计算支撑阻力、EMA、ATR、参考区间和盈亏比，不修改 `total_score`、因子权重或今日选股排序。

## 命令

```bash
python -m core.jobs.calculate_entry_zones
python -m core.jobs.diagnose_entry_zones
python -m core.jobs.export_entry_zone_report --format all
```

一键串行验收：

```bash
python scripts/verify_task.py task49
```

## 输出字段

核心表为 `entry_zone_snapshots`，字段包括：

- 当前价；
- EMA13 / EMA22 / EMA60；
- 20 日和 60 日支撑位、阻力位；
- nearest_support / nearest_resistance；
- ATR14 和波动率；
- entry_low / entry_high / entry_mid；
- stop_loss；
- target_price；
- risk_pct / reward_pct / reward_risk_ratio；
- chase_risk；
- entry_zone_status；
- 中文解释说明。

## 状态说明

- `in_zone`：位于买入区间；
- `near_zone`：接近买入区间；
- `above_zone`：高于买入区间，等待回调；
- `below_zone`：低于买入区间；
- `weak_no_entry`：趋势偏弱，暂不进入；
- `insufficient_data`：数据不足。

`chase_risk` 分为 `low / medium / high`，用于提示短线追高风险，不代表自动交易动作。

## 页面

Streamlit 新增“买入区间分析”Tab。今日选股和观察池页面也会展示买入区间、止损位、目标价位、盈亏比和状态提示。

## 限制

- 买入区间、止损位、目标价位仅供个人研究和人工复核；
- 不自动交易；
- 不接券商；
- 不构成收益保证；
- 数据不足时会显示 `insufficient_data`，不会回退 sample 数据。

