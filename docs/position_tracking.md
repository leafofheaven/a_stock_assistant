# 持仓每日跟踪

Task 45 在持仓池基础上增加每日跟踪。它只读取本地 `positions` 和 `daily_price`，不接券商、不自动交易，也不生成正式卖出规则。

## 运行命令

```bash
python -m core.jobs.track_positions
python -m core.jobs.track_positions --format markdown
python -m core.jobs.track_positions --format all
```

`export_positions` 也会带出最新跟踪字段：

```bash
python -m core.jobs.export_positions --format markdown
```

## 跟踪字段

对 `status=active` 的持仓，命令会计算：

- `latest_close`
- `latest_trade_date`
- `entry_price`
- `pnl_pct`
- `holding_days`
- `max_gain_pct`
- `max_drawdown_pct`
- `close_to_entry_pct`
- `latest_elder_score`
- `weekly_trend`
- `daily_pullback`
- `force_signal`
- `elder_ray_signal`
- `technical_state`
- `position_hint`
- `position_reason`

`reduced` 和 `exited` 记录默认不进入 active 每日跟踪；`export_positions` 仍可展示所有持仓记录。

## position_hint 口径

第一版只做温和提示，不是交易指令：

- 持仓正常
- 持有观察
- 波动加大，需人工复核
- 数据不足

如果买入日期之后行情不足，或最新收盘价取不到，会显示“数据不足”，不会报错。

## 页面

启动页面：

```bash
streamlit run web/streamlit_app.py
```

进入“持仓池”标签页查看最新持仓跟踪字段。

## 限制

- 当前只做持仓每日跟踪和基础复核提示。
- 不做完整卖出复核规则。
- 不输出自动交易指令。
- 不接券商。
- 仅供个人研究使用，不自动交易。
