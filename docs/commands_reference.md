# 命令参考

v0.1 常用命令优先看 [v0.1 日常使用手册](v0_1_handbook.md)。本页保留完整命令索引。

所有命令默认先执行：

```bash
cd /Users/wanghao/Documents/股票
source .venv/bin/activate
```

## 环境检查

命令：

```bash
python -m pytest
python scripts/check_project.py
python scripts/check_task.py task27
```

作用：运行测试、项目检查和当前 Task 检查。输出 `passed` 或 `checks passed` 表示通过。

## 真实数据

命令：

```bash
python -m core.jobs.update_real_data
python -m core.jobs.diagnose_real_data
python -m core.jobs.diagnose_data_quality
```

作用：更新少量真实数据并诊断 DuckDB 是否可用于选股。重点看 `daily_price 行数`、`最新行情日期`、`是否足够运行 run_daily_selection`。

常用参数：真实数据范围由 `.env` 中 `REAL_DATA_START_DATE`、`REAL_DATA_END_DATE`、`AKSHARE_SAMPLE_SYMBOLS` 或 `REAL_UNIVERSE_PRESET` 控制。

`update_real_data` 会输出 `[progress]` 进度行，显示当前阶段、当前股票、成功/失败/跳过数量。AKShare 基础信息增强字段缺失时，会使用基础字段或本地 preset 兜底，不影响主行情写入。

## 基础信息与估值字段

命令：

```bash
python -m core.jobs.diagnose_data_quality
```

作用：查看 `stock_basic` 中 `name`、`industry`、`market`、`list_date` 完整率，以及 `daily_basic` 中 `turnover_rate`、`pe`、`pb`、`total_mv`、`circ_mv` 完整率。

相关配置：

```env
ENABLE_REAL_BASIC_ENRICHMENT=true
ENABLE_REAL_VALUATION_ENRICHMENT=true
```

关闭补全后会保持简化逻辑；补全失败不影响主行情更新。

PE/PB 估值补全开启后，更新任务会优先尝试 AKShare 快照接口；不可用时尝试东方财富 quote curl fallback。诊断输出中的 `pe_non_null_rate`、`pb_non_null_rate`、`valuation_updated_count` 可用于判断补全是否生效。

## 批量更新

命令：

```bash
python -m core.jobs.diagnose_update_batch
```

作用：查看配置股票数量、已有行情股票数量、覆盖率和缺数据股票。

## 因子

命令：

```bash
python -m core.jobs.diagnose_factors
```

作用：查看股票池数量、可计算因子股票数量、各因子非空率、NaN 数量和 Top 10 综合评分股票。`fundamental_score` 为空时，先结合 `diagnose_data_quality` 查看 PE/PB 是否缺失；PE/PB 补全后，`pe_score` 和 `fundamental_score` 应出现非空率。

## 选股

命令：

```bash
python -m core.jobs.run_daily_selection
python -m core.jobs.explain_selection_logic
python -m core.jobs.explain_selection_logic --format markdown
python -m core.jobs.explain_selection_logic --ts-code 002475.SZ
python -m core.jobs.run_elder_review
python -m core.jobs.run_elder_review --format markdown
python -m core.jobs.export_elder_review
python -m core.jobs.export_elder_review --format markdown
python -m core.jobs.backtest_elder_review
python -m core.jobs.backtest_elder_review --format markdown
python -m core.jobs.backtest_elder_review --start-date 20240101 --end-date 20260625 --format all
python -m core.jobs.import_positions --file docs/templates/positions_import_template.csv --dry-run
python -m core.jobs.export_positions
python -m core.jobs.export_positions --format markdown
```

作用：`run_daily_selection` 基于本地数据生成候选股票摘要；`explain_selection_logic` 查看当前 `total_score` 公式、因子权重、候选排名原因和主要贡献因子；`run_elder_review` 在今日候选之后追加埃尔德技术复核；`export_elder_review` 导出带操作建议的人工复核 CSV / Markdown；`backtest_elder_review` 对埃尔德复核结果做历史回看，输出 `forward_return_5d`、`max_drawdown_20d`、`elder_score` 分组和 `action_hint` 分组表现；`import_positions` / `export_positions` 用于本地持仓池手工记录和导出。解释、复核和持仓池命令只读取或写入本地数据，不改变选股结果。

如需把“趋势确认，进入人工复核”的股票加入观察池，可显式运行：

```bash
python -m core.jobs.export_elder_review --add-confirmed-to-watchlist --dry-run
python -m core.jobs.export_elder_review --add-confirmed-to-watchlist
```

已有 active watch 记录会跳过，不重复添加。

## 回测

命令：

```bash
python -m core.jobs.diagnose_backtest
```

作用：基于本地数据做最小回测诊断。重点看 equity_curve 行数、trade_records 行数和指标是否存在。

## 工作流

命令：

```bash
python -m core.jobs.run_real_workflow
python -m core.jobs.run_real_workflow --skip-update
python -m core.jobs.run_real_workflow --backup-before-run
```

作用：串联更新、诊断、选股、回测和报告。`--skip-update` 不更新真实数据；`--backup-before-run` 先备份 DuckDB。

## 候选复核

命令：

```bash
python -m core.jobs.export_selection_review --top-n 10 --format all
python -m core.jobs.export_review_template --top-n 10
python -m core.jobs.import_review_decisions --file reports/review_template_xxx.csv
```

作用：导出候选复核报告、导出可编辑 CSV 模板、导入人工复核结果。导入前可先用 `--dry-run`。

## 观察池

命令：

```bash
python -m core.jobs.refresh_watchlist_scores --dry-run
python -m core.jobs.refresh_watchlist_scores
python -m core.jobs.refresh_watchlist_scores --export-report
python -m core.jobs.diagnose_watchlist
python -m core.jobs.export_watchlist --format all
```

作用：刷新 active watch 股票的最新本地评分、PE/PB、基础信息，查看并导出观察池报告。重点看 `total_score`、`score_missing_reason`、`history_count`、`reason`、`notes`。`--dry-run` 只预览，不写入 snapshot。

## 观察池跟踪

命令：

```bash
python -m core.jobs.track_watchlist
python -m core.jobs.track_watchlist --export-report --format all
python -m core.jobs.export_watchlist_tracking_report --format all
```

作用：生成观察池 snapshot，并导出价格、评分、PE/PB 变化报告。重点看 `缺少行情股票数量`、`缺少评分股票数量`、`score_change`、`pe_change`、`pb_change`。

## 一键日常工作流

命令：

```bash
python -m core.jobs.doctor_daily_run --pre-run
python -m core.jobs.run_daily_workflow --backup-before-run --format all
python -m core.jobs.run_daily_workflow --doctor-before-run --backup-before-run --format all
python -m core.jobs.run_daily_workflow --skip-update --format all
python -m core.jobs.run_daily_workflow --top-n 10 --format all
python -m core.jobs.run_daily_workflow --no-watchlist-tracking
python -m core.jobs.doctor_daily_run --post-run
```

作用：按日常顺序执行更新、数据质量诊断、因子诊断、选股、候选复核报告、观察池评分刷新、观察池报告、观察池跟踪，并导出 `reports/daily_workflow_*.md/json/csv`。`run_real_workflow` 偏底层诊断，`run_daily_workflow` 偏日常使用。

`--doctor-before-run` 会把运行前体检摘要写入日报；如需运行后复查，可加 `--doctor-after-run`。只有加 `--stop-on-doctor-failure` 时，运行前体检失败才会阻断工作流。

日报中的 PE/PB 质量优先看最新交易日、当前候选和当前观察池口径。全历史完整率低不一定表示当前候选缺估值。

命令行会逐步输出 `[progress]` 行。Streamlit 本地控制台会把这些行解析成当前步骤、当前子任务、成功/失败/跳过数量、实时日志和最终报告路径。

## 日常体检与安全修复

命令：

```bash
python -m core.jobs.doctor_daily_run
python -m core.jobs.doctor_daily_run --pre-run
python -m core.jobs.doctor_daily_run --post-run
python -m core.jobs.doctor_daily_run --fix-safe
python -m core.jobs.doctor_daily_run --json
```

作用：检查当前分支、工作区、`.env`、DATA_PROVIDER、样本配置、DuckDB、核心表、最新行情日期、最新交易日 PE/PB 完整率、`reports/.gitkeep`、最近备份、最近日报和 Git 误提交风险。`--fix-safe` 只创建缺失的 `reports/`、`backups/`、`data/` 和 `reports/.gitkeep`，不会删除或覆盖 DuckDB，也不会修改 `.env`。

## Chrome 本地控制台 / 参数设置页

命令：

```bash
streamlit run web/streamlit_app.py
```

打开 `http://localhost:8501` 后进入“参数设置 / 本地控制台”。页面提供简化设置向导：

- 保存参数：只保存 `.env`，不运行命令；
- 保存并本地重算：运行 `run_daily_workflow --doctor-before-run --skip-update --format all`，只用本地已有数据；
- 保存并更新数据：运行 `run_daily_workflow --doctor-before-run --backup-before-run --format all`，会联网更新真实行情。

运行命令时页面会实时追加日志，并展示当前运行步骤、当前处理股票或子任务、成功/失败/跳过数量和最终报告路径。

自定义股票池会写入 `AKSHARE_SAMPLE_SYMBOLS`，它不为空时 `REAL_UNIVERSE_PRESET` 不生效。使用预设股票池会清空 `AKSHARE_SAMPLE_SYMBOLS` 并保存 `REAL_UNIVERSE_PRESET=small` 或 `medium`。结束日期留空表示尽量拉取到最新可得日期；修改结束日期后，只有“保存并更新数据”会让数据库最新行情日期变化。

Mac 双击启动器：

```bash
chmod +x scripts/mac/A股选股助手.command
open scripts/mac/A股选股助手.command
```

这不是完整原生 Swift App，不做菜单栏常驻、不做自动后台更新、不做 dmg、不做云同步。

Task 35-38 的交接说明见 [task_35_38_handoff.md](task_35_38_handoff.md)。

## 复核状态调整

命令：

```bash
python -m core.jobs.update_review_decision --ts-code 002475.SZ --decision watch --reason "继续观察"
python -m core.jobs.update_review_decision --ts-code 002475.SZ --decision pass --reason "暂不关注"
python -m core.jobs.update_review_decision --ts-code 002475.SZ --decision exclude --reason "人工排除"
python -m core.jobs.update_review_decision --ts-code 002475.SZ --decision needs_data --reason "需要补充财务数据"
python -m core.jobs.update_review_decision --ts-code 002475.SZ --archive --reason "归档观察"
python -m core.jobs.update_review_decision --ts-code 002475.SZ --reactivate --reason "重新观察"
python -m core.jobs.diagnose_review_history --ts-code 002475.SZ
```

作用：手动调整观察池状态并记录历史。输出中 `是否写入 history: 是` 表示已保存历史记录。

## 备份恢复

命令：

```bash
python -m core.jobs.diagnose_local_state
python -m core.jobs.backup_local_data
python -m core.jobs.backup_local_data --include-reports
python -m core.jobs.list_backups
python -m core.jobs.restore_local_data --backup-dir backups/a_stock_backup_xxx --dry-run
python -m core.jobs.restore_local_data --backup-dir backups/a_stock_backup_xxx --force
python -m core.jobs.clean_generated_reports --dry-run
python -m core.jobs.clean_generated_reports --force
```

作用：诊断本地状态、备份 DuckDB、列出备份、恢复和清理生成报告。恢复默认不覆盖；`--force` 才会恢复。

不要使用 `rm -rf reports`。推荐清理命令是 `python -m core.jobs.clean_generated_reports --force`，或 `find reports -type f ! -name ".gitkeep" -delete`，保留 `reports/.gitkeep`。

## Streamlit

命令：

```bash
streamlit run web/streamlit_app.py
```

作用：启动本地页面。页面显示数据状态、今日选股、因子排名、选股逻辑、回测诊断、观察池和本地备份提示。

## 测试与检查

命令：

```bash
python -m pytest
python scripts/check_project.py
python scripts/check_task.py task27
python scripts/check_task.py task39
```

输出 `passed` 表示通过。

`task39` 用于检查 Task 35-39 状态交接文档、Chrome 本地控制台流程、选股逻辑说明、实时进度说明和 AKShare 基础增强 warning 解释是否仍然存在。
