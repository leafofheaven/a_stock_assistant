# 日常流程

v0.1 推荐流程已经整理到 [v0.1 日常使用手册](v0_1_handbook.md)。本页保留日常流程拆解。

所有命令默认先执行：

```bash
cd /Users/wanghao/Documents/股票
source .venv/bin/activate
```

## A. 最简单日常流程

```bash
python -m core.jobs.run_real_workflow --backup-before-run
```

适合日常完整运行。它会先备份本地 DuckDB，再执行已有工作流。

## B. 跳过更新，只看本地数据

```bash
python -m core.jobs.run_real_workflow --skip-update
```

适合已经更新过数据，只想重新诊断、选股和生成工作流报告。

## C. 完整复核流程

每天运行前可先体检：

```bash
python -m core.jobs.doctor_daily_run --pre-run
```

推荐日常一键命令：

```bash
python -m core.jobs.run_daily_workflow --doctor-before-run --backup-before-run --format all
```

不更新数据、只使用本地 DuckDB：

```bash
python -m core.jobs.run_daily_workflow --skip-update --format all
```

该命令会生成 `reports/daily_workflow_*.md`、`reports/daily_workflow_*.json`，`--format all` 还会生成 CSV 摘要。清理运行生成文件时优先使用 `python -m core.jobs.clean_generated_reports --force`，不要删除 `reports/.gitkeep`。

运行后复查：

```bash
python -m core.jobs.doctor_daily_run --post-run
```

如果 `reports/.gitkeep`、`reports/`、`backups/` 或 `data/` 缺失，可以运行安全修复：

```bash
python -m core.jobs.doctor_daily_run --fix-safe
```

`--fix-safe` 不会删除或覆盖 DuckDB，不会修改 `.env`，也不会自动提交代码。

阅读日报时优先看最新交易日 PE/PB 完整率、候选股票 PE/PB 缺失数量、观察池 PE/PB 缺失数量。全历史 PE/PB 完整率低，通常表示历史区间估值字段可能为空，不等于当前候选缺估值。

手动拆分流程如下：

```bash
python -m core.jobs.update_real_data
python -m core.jobs.run_daily_selection
python -m core.jobs.export_selection_review --top-n 10 --format all
python -m core.jobs.export_review_template --top-n 10
python -m core.jobs.import_review_decisions --file reports/review_template_xxx.csv
python -m core.jobs.refresh_watchlist_scores
python -m core.jobs.diagnose_watchlist
python -m core.jobs.track_watchlist --export-report --format all
```

## 每天/每周怎么用

每天可以运行：

```bash
python -m core.jobs.run_real_workflow --skip-update
streamlit run web/streamlit_app.py
```

每周或准备更新数据时运行：

```bash
python -m core.jobs.backup_local_data --label before_weekly_update
python -m core.jobs.update_real_data
python -m core.jobs.run_real_workflow --skip-update
```

## 什么时候备份

- 更新真实数据前；
- 批量导入人工复核结果前；
- 使用 `restore_local_data --force` 前；
- 合并较大代码改动前；
- 准备清理 reports 前。

备份命令：

```bash
python -m core.jobs.backup_local_data --label before_change
```

## 什么时候清理 reports

reports 是运行生成文件，积累较多时可以先 dry-run：

```bash
python -m core.jobs.clean_generated_reports --dry-run
```

确认后再删除：

```bash
python -m core.jobs.clean_generated_reports --force
```

不要使用：

```bash
rm -rf reports
```

如需手动清理，保留 `reports/.gitkeep`：

```bash
find reports -type f ! -name ".gitkeep" -delete
```

## 什么时候不要删除 DuckDB

不要随手删除：

```text
data/a_stock_assistant.duckdb
```

它是本地核心数据库，包含真实数据、复核结果、观察池和历史记录。删除前至少先备份：

```bash
python -m core.jobs.backup_local_data --label before_db_cleanup
```
