# 埃尔德复核与观察池流程

本流程把 Task 40 的埃尔德技术复核结果接入人工复核和观察池管理。它不修改 `total_score` 公式，不修改因子权重，也不改变今日选股原始排序。

## 页面流程

启动页面：

```bash
streamlit run web/streamlit_app.py
```

进入“埃尔德复核”标签页后，可以看到：

- 原始 `rank`；
- 原始 `total_score`；
- `elder_score`；
- 操作建议；
- 技术状态；
- 周线趋势；
- 日线回调；
- Force Index 信号；
- Elder Ray 信号；
- 中文复核原因。

操作建议包括：

- 加入观察池；
- 等待回调；
- 暂缓；
- 忽略。

这些建议只用于人工复核流程，不会直接改变今日选股排序。

## 命令流程

查看复核摘要：

```bash
python -m core.jobs.run_elder_review
python -m core.jobs.run_elder_review --format markdown
```

导出人工复核 CSV / Markdown：

```bash
python -m core.jobs.export_elder_review
python -m core.jobs.export_elder_review --format markdown
```

导出文件会写入 `reports/`，该目录是本地生成文件，不应提交到 Git。

## 加入观察池

默认导出不会写入观察池。若希望把“趋势确认，进入人工复核”的股票加入观察池，可显式运行：

```bash
python -m core.jobs.export_elder_review --add-confirmed-to-watchlist
```

建议先 dry-run：

```bash
python -m core.jobs.export_elder_review --add-confirmed-to-watchlist --dry-run
```

如果股票已经在 active watch 观察池中，命令会跳过，不重复添加，也不会覆盖原有观察池状态和历史记录。

## selection_review 字段

候选复核导出会带出以下埃尔德字段：

- `elder_score`；
- `action_hint`；
- `elder_reason`；
- `weekly_trend`；
- `daily_pullback`；
- `force_signal`；
- `elder_ray_signal`。

## 限制

- 仅供个人研究使用，不自动交易。
- 不接券商，不输出买卖指令。
- 埃尔德复核是二次技术复核层，不是新的选股排序依据。
- 数据不足时会显示“数据不足”，不会抛出难懂异常。
