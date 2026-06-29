# 观察池每日候选跟踪

Task 48 将“每日选股结果”和“观察池”打通。今日 Top 候选用于发现机会，观察池用于持续跟踪；股票掉出当日 Top-N 后不会自动移出观察池。

仅供个人研究使用，不自动交易。

## 状态体系

观察池每日跟踪使用以下状态：

- `new_candidate`：新入选
- `active_watch`：正常观察
- `strong_watch`：重点观察
- `wait_pullback`：等待回调
- `near_buy_zone`：接近买入区间
- `overheated`：短线过热
- `weakening`：走势转弱
- `invalidated`：逻辑失效
- `bought`：已买入
- `removed`：已移出

这些状态只用于人工复核和观察分层，不改变 `total_score`、因子权重或今日选股原始排序。

## 常用命令

```bash
python -m core.jobs.refresh_watchlist_from_selection
python -m core.jobs.track_watchlist
python -m core.jobs.diagnose_watchlist
python -m core.jobs.export_watchlist_tracking
python -m core.jobs.run_daily_workflow --doctor-before-run --skip-update --format all
```

`refresh_watchlist_from_selection` 会读取本地 `strategy_result` 或 `factor_scores`，把今日 Top-N 中尚未在 active watch 的股票加入观察池，并写入 `watchlist_daily_snapshots` 与 `watchlist_events`。

`track_watchlist` 会先刷新每日候选跟踪，再保留旧版 `watchlist_snapshots`，用于兼容历史观察池报告。

## 重点字段

- `today_rank` / `previous_rank` / `rank_change`
- `total_score` / `total_score_change`
- `selected_count_5d` / `selected_count_10d`
- `consecutive_selected_days`
- `watch_status` / `watch_status_label`
- `daily_note`
- `action_hint` / `elder_score`

今日选股页面会附加“是否在观察池”“观察池状态”“近 5/10 日入选次数”“连续入选天数”和“建议加入观察池”等字段，但不会改变候选排序。

## 事件记录

`watchlist_events` 记录以下变化：

- 加入观察池
- 今日新入选
- 状态变化
- 排名明显上升或下降
- `total_score` 明显上升或下降

后续如转入持仓池或手动移出，可继续使用事件表记录人工操作历史。
