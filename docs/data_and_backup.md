# 数据与备份

所有命令默认先执行：

```bash
cd /Users/wanghao/Documents/股票
source .venv/bin/activate
```

## 本地数据文件

- `data/a_stock_assistant.duckdb`：核心本地数据库，包含行情、因子、选股结果、复核结果、观察池和历史记录。
- `reports/`：运行生成报告，可重新生成。
- `backups/`：本地备份目录。
- `.env`：本地配置文件，可能包含 token，不应提交。

`data/`、`reports/`、`backups/`、`.env` 都不应提交到 Git。

## 诊断本地状态

```bash
python -m core.jobs.diagnose_local_state
python -m core.jobs.doctor_daily_run --pre-run
python -m core.jobs.diagnose_data_quality
```

重点看：

- DuckDB 是否存在；
- DuckDB 文件大小；
- 核心表行数；
- reports 文件数量；
- backups 数量；
- 是否发现本地数据路径被 Git 跟踪。
- `stock_basic` 的行业、市场、上市日期完整率；
- `daily_basic` 的 `pe`、`pb`、市值字段完整率。

`doctor_daily_run` 还会检查当前分支、工作区、`.env`、DATA_PROVIDER、DuckDB 路径、核心表、`reports/.gitkeep`、最近备份、最近日报和 Git 误提交风险。

## 安全修复

```bash
python -m core.jobs.doctor_daily_run --fix-safe
```

允许修复：创建缺失的 `reports/`、`backups/`、`data/` 和 `reports/.gitkeep`。

不会做：删除或覆盖 `data/a_stock_assistant.duckdb`、修改 `.env`、自动提交、自动推送。

## 创建备份

```bash
python -m core.jobs.backup_local_data --label before_change
```

包含 reports：

```bash
python -m core.jobs.backup_local_data --include-reports --label before_cleanup
```

备份不会保存 `.env` 原文或 token。

## 查看备份

```bash
python -m core.jobs.list_backups
```

## 恢复 dry-run

```bash
python -m core.jobs.restore_local_data --backup-dir backups/a_stock_backup_xxx --dry-run
```

dry-run 会展示当前库和备份库表行数对比，不覆盖当前数据库。

## 强制恢复

```bash
python -m core.jobs.restore_local_data --backup-dir backups/a_stock_backup_xxx --force
```

强制恢复前会自动创建 safety backup。

## 清理报告

先 dry-run：

```bash
python -m core.jobs.clean_generated_reports --dry-run
```

确认后删除系统生成报告：

```bash
python -m core.jobs.clean_generated_reports --force
```

清理命令只匹配系统生成报告，不删除用户自定义文件。

不要使用：

```bash
rm -rf reports
```

如需手动清理，保留 `reports/.gitkeep`：

```bash
find reports -type f ! -name ".gitkeep" -delete
```

## 确认没有误提交

```bash
git status
git status --ignored --short reports data backups .env
```

如果看到 `!! data/`、`!! reports/`、`!! backups/`、`!! .env`，表示这些路径被忽略，没有进入提交。
