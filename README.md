# a_stock_assistant

本项目是个人本地 A 股选股辅助工具，用于数据整理、因子观察、候选复核、观察池跟踪和本地复盘，不包含自动交易功能，不构成投资建议。

## 当前功能总览

- sample/mock 数据模式，便于无外部数据时跑通流程。
- AKShare + 东方财富 curl fallback 小范围真实数据更新。
- DuckDB 本地存储、真实数据诊断和批量更新诊断。
- 股票池过滤、基础因子计算、综合评分和每日选股。
- 回测诊断、工作流报告和 Streamlit 页面。
- 候选股票复核报告、人工复核模板导出和复核结果导入。
- 观察池管理、观察池跟踪、观察池变化报告、状态调整与历史记录。
- 本地 DuckDB 备份、恢复 dry-run、报告清理和本地状态诊断。

## 快速开始

```bash
cd /Users/wanghao/Documents/股票
source .venv/bin/activate
pip install -e .
cp .env.example .env
```

以上命令默认在项目根目录执行。

常用本地检查：

```bash
python -m pytest
python scripts/check_project.py
python scripts/check_task.py task11
python scripts/check_task.py task26
python scripts/check_task.py task27
```

## 常用命令

```bash
python -m core.jobs.diagnose_local_state
python -m core.jobs.update_real_data
python -m core.jobs.diagnose_real_data
python -m core.jobs.diagnose_update_batch
python -m core.jobs.diagnose_data_quality
python -m core.jobs.diagnose_factors
python -m core.jobs.run_daily_selection
python -m core.jobs.diagnose_backtest
python -m core.jobs.run_real_workflow --backup-before-run
streamlit run web/streamlit_app.py
```

## 真实数据工作流

真实数据端到端验证的常用入口：

最简单的日常入口：

```bash
python -m core.jobs.run_real_workflow --backup-before-run
```

只看本地 DuckDB，不更新数据：

```bash
python -m core.jobs.run_real_workflow --skip-update
```

完整复核流程请见 [docs/daily_workflow.md](docs/daily_workflow.md)。

## 历史功能入口索引

这些入口保留用于任务检查和日常查找，详细说明见 `docs/`：

- 真实数据日常使用流程：`python -m core.jobs.update_real_data`
- 真实因子结果校验：`python -m core.jobs.diagnose_factors`
- 真实回测结果校验：`python -m core.jobs.diagnose_backtest`
- 真实股票样本扩容与批量更新：`REAL_UNIVERSE_PRESET=small`，`python -m core.jobs.diagnose_update_batch`
- 基础信息与 PE/PB 估值字段补全：`ENABLE_REAL_BASIC_ENRICHMENT=true`，`ENABLE_REAL_VALUATION_ENRICHMENT=true`，`python -m core.jobs.diagnose_data_quality`
- 真实运行工作流与报告导出：`python -m core.jobs.run_real_workflow`，`python -m core.jobs.run_real_workflow --no-backtest`，`python -m core.jobs.run_real_workflow --format json`
- 候选股票人工复核清单与结果导出：`python -m core.jobs.export_selection_review`，`python -m core.jobs.export_selection_review --top-n 10`，`python -m core.jobs.export_selection_review --format all`，`--export-selection-review`
- 人工复核结果回填与观察池管理：`review_decisions`，`python -m core.jobs.export_review_template`，`python -m core.jobs.import_review_decisions`，`python -m core.jobs.diagnose_watchlist`，`python -m core.jobs.export_watchlist`，`--export-review-template`，`--export-watchlist`
- 观察池跟踪与变化报告：`watchlist_snapshots`，`python -m core.jobs.track_watchlist`，`python -m core.jobs.export_watchlist_tracking_report`，`--track-watchlist`，`--export-watchlist-tracking`
- 观察池状态调整与复核记录管理：`python -m core.jobs.update_review_decision`，`python -m core.jobs.diagnose_review_history`，`--diagnose-review-history`
- 本地数据备份与恢复：`python -m core.jobs.backup_local_data`，`python -m core.jobs.restore_local_data`，`python -m core.jobs.clean_generated_reports`

## Streamlit 启动

```bash
streamlit run web/streamlit_app.py
```

页面用于查看数据状态、今日选股、因子排名、回测诊断、观察池和本地状态提示。个人研究工具，结果需自行复核。

## 文档目录

- [完整使用说明](docs/usage_guide.md)
- [命令参考](docs/commands_reference.md)
- [日常流程](docs/daily_workflow.md)
- [常见问题排查](docs/troubleshooting.md)
- [数据与备份](docs/data_and_backup.md)

## 当前限制

- 默认只做小范围真实数据试运行，不做全市场长周期下载。
- AKShare fallback 的字段完整性可能弱于 Tushare。默认会尝试补全 `stock_basic` 的行业、上市日期，以及 `daily_basic` 的 PE/PB、市值字段；估值补全会优先使用 AKShare 快照接口，不可用时尝试东方财富 quote curl fallback，获取不到时允许为空。
- 可在 `.env` 中用 `ENABLE_REAL_BASIC_ENRICHMENT=false` 或 `ENABLE_REAL_VALUATION_ENRICHMENT=false` 关闭补全；关闭后会保持简化逻辑。
- 用 `python -m core.jobs.diagnose_data_quality` 查看 PE/PB 完整率；用 `python -m core.jobs.diagnose_factors` 判断 `fundamental_score` 是否恢复。PE/PB 仍可能为空，`adj_factor` 可能简化为 `1.0`。
- 本项目不接券商，不自动交易。
- `.env`、`data/`、`reports/`、`backups/` 为本地个人数据，不应提交到 Git。
