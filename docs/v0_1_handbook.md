# v0.1 日常使用手册

本手册面向个人本地日常使用。工具用于数据整理、候选复核和观察池跟踪；仅供个人研究使用，不自动交易。

## 1. 第一次使用

进入项目目录并激活环境：

```bash
cd /Users/wanghao/Documents/股票
source .venv/bin/activate
```

检查配置文件：

```bash
ls .env
python -m core.jobs.doctor_daily_run
```

如果 `.env` 不存在：

```bash
cp .env.example .env
```

常用 `.env` 项：

- `DATA_PROVIDER=akshare`
- `AKSHARE_SAMPLE_SYMBOLS=000001,600000,000002`
- `REAL_UNIVERSE_PRESET=small`
- `ENABLE_REAL_BASIC_ENRICHMENT=true`
- `ENABLE_REAL_VALUATION_ENRICHMENT=true`

## 2. 每天推荐流程

运行前体检：

```bash
python -m core.jobs.doctor_daily_run --pre-run
```

一键日常运行：

```bash
python -m core.jobs.run_daily_workflow --doctor-before-run --backup-before-run --format all
```

运行后检查：

```bash
python -m core.jobs.doctor_daily_run --post-run
```

重点查看：

- `reports/daily_workflow_*.md`
- Top 候选数量；
- 是否回退 sample；
- 最新行情日期；
- 最新交易日 PE/PB 完整率；
- 观察池变化；
- doctor 检查摘要。

## 3. 只用本地数据、不更新

已经更新过数据，只想重跑报告：

```bash
python -m core.jobs.run_daily_workflow --doctor-before-run --skip-update --format all
```

## 4. 查看候选

常用文件：

- `reports/daily_workflow_*.md`
- `reports/selection_review_*.csv`
- `reports/selection_review_*.json`
- `reports/selection_review_*.md`

如需单独导出候选复核报告：

```bash
python -m core.jobs.export_selection_review --top-n 10 --format all
```

## 5. 人工复核

导出可编辑模板：

```bash
python -m core.jobs.export_review_template --top-n 10
```

编辑 CSV 后先 dry-run：

```bash
python -m core.jobs.import_review_decisions --file reports/review_template_xxx.csv --dry-run
```

确认后导入：

```bash
python -m core.jobs.import_review_decisions --file reports/review_template_xxx.csv
```

## 6. 观察池刷新

预览刷新：

```bash
python -m core.jobs.refresh_watchlist_scores --dry-run
```

正式刷新并查看：

```bash
python -m core.jobs.refresh_watchlist_scores
python -m core.jobs.diagnose_watchlist
python -m core.jobs.export_watchlist --format all
```

观察池跟踪：

```bash
python -m core.jobs.track_watchlist --export-report --format all
python -m core.jobs.export_watchlist_tracking_report --format all
```

## 7. 备份

建议在更新真实数据、导入人工复核结果、强制恢复前备份：

```bash
python -m core.jobs.backup_local_data --label before_change
python -m core.jobs.list_backups
```

## 8. 恢复

先 dry-run：

```bash
python -m core.jobs.restore_local_data --backup-dir backups/a_stock_backup_xxx --dry-run
```

确认后 force：

```bash
python -m core.jobs.restore_local_data --backup-dir backups/a_stock_backup_xxx --force
```

## 9. 清理报告

推荐：

```bash
python -m core.jobs.clean_generated_reports --force
```

或保留 `reports/.gitkeep`：

```bash
find reports -type f ! -name ".gitkeep" -delete
```

不要使用：

```bash
rm -rf reports
```

## 10. Git 注意事项

不要提交：

- 不提交 data/
- 不提交 backups/
- 不提交 reports/ 生成文件；
- 不提交 .env
- 本地 DuckDB。

需要保留：

- `reports/.gitkeep`

检查命令：

```bash
git status --short
git status --ignored --short reports data backups .env
```

## 11. 常见异常处理

### doctor warning

先看 warning 的建议。常见 warning 是没有备份、工作区有未提交改动、缺少最近报告。

### 没有备份

```bash
python -m core.jobs.backup_local_data --label before_change
```

### reports/.gitkeep 被删

```bash
python -m core.jobs.doctor_daily_run --fix-safe
```

### AKShare 接口失败

先重跑本地流程：

```bash
python -m core.jobs.run_daily_workflow --doctor-before-run --skip-update --format all
```

再按需重试真实数据更新：

```bash
python -m core.jobs.update_real_data
```

### run_daily_workflow partial_success

打开最新日报，看步骤状态和 doctor 建议：

```bash
ls -t reports/daily_workflow_*.md | head
python -m core.jobs.doctor_daily_run --post-run
```

### 粘贴命令带上终端提示符

只复制命令本身，不复制 `$`、`%` 或路径提示符。文件名中的 `xxx` 是占位符，要替换成真实文件名。
