# 日常流程

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

```bash
python -m core.jobs.update_real_data
python -m core.jobs.run_daily_selection
python -m core.jobs.export_selection_review --top-n 10 --format all
python -m core.jobs.export_review_template --top-n 10
python -m core.jobs.import_review_decisions --file reports/review_template_xxx.csv
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

## 什么时候不要删除 DuckDB

不要随手删除：

```text
data/a_stock_assistant.duckdb
```

它是本地核心数据库，包含真实数据、复核结果、观察池和历史记录。删除前至少先备份：

```bash
python -m core.jobs.backup_local_data --label before_db_cleanup
```
