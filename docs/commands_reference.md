# 命令参考

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

作用：查看股票池数量、可计算因子股票数量、各因子非空率、NaN 数量和 Top 10 综合评分股票。`fundamental_score` 为空时，先结合 `diagnose_data_quality` 查看 `pe` / `pb` 是否缺失。

## 选股

命令：

```bash
python -m core.jobs.run_daily_selection
```

作用：基于本地数据生成候选股票摘要。重点看数据来源、是否回退 sample、候选股票数量。

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
python -m core.jobs.diagnose_watchlist
python -m core.jobs.export_watchlist --format all
```

作用：查看 active watch 股票和导出观察池报告。重点看 `history_count`、`reason`、`notes`。

## 观察池跟踪

命令：

```bash
python -m core.jobs.track_watchlist
python -m core.jobs.track_watchlist --export-report --format all
python -m core.jobs.export_watchlist_tracking_report --format all
```

作用：生成观察池 snapshot，并导出价格和评分变化报告。重点看 `缺少行情股票数量`、`缺少评分股票数量`。

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

## Streamlit

命令：

```bash
streamlit run web/streamlit_app.py
```

作用：启动本地页面。页面显示数据状态、今日选股、因子排名、回测诊断、观察池和本地备份提示。

## 测试与检查

命令：

```bash
python -m pytest
python scripts/check_project.py
python scripts/check_task.py task27
```

输出 `passed` 表示通过。
