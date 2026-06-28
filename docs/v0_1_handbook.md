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

如果希望用 Chrome 本地控制台操作，可以双击 Mac 启动器：

```bash
chmod +x scripts/mac/A股选股助手.command
open scripts/mac/A股选股助手.command
```

浏览器打开 `http://localhost:8501` 后，进入“参数设置 / 本地控制台”。这里可以用简化设置向导修改股票池、日期和运行方式，并打开 reports 文件夹。

页面里三个按钮含义：

- 保存参数：只保存 `.env`，不运行工作流。数据库日期不会变化。
- 保存并本地重算：保存 `.env`，然后只用本地已有数据重新生成报告，不联网更新行情。
- 保存并更新数据：保存 `.env`，然后运行完整日常工作流，会联网更新真实行情，适合修改股票池或结束日期后使用。

运行时页面会实时显示当前步骤、当前处理股票或子任务、成功/失败/跳过数量、日志和最终报告路径。看到 `[progress]` 开头的日志表示命令正在输出进度，不是卡住。

股票池模式：

- 自定义股票池：输入 `000001,600000,002475`，也支持中文逗号、换行、`000001.SZ`。系统会保存为 `AKSHARE_SAMPLE_SYMBOLS=000001,600000,002475`。
- 使用预设股票池：选择 `small` 或 `medium`，保存时会清空 `AKSHARE_SAMPLE_SYMBOLS`，让 `REAL_UNIVERSE_PRESET` 生效。

如果 `AKSHARE_SAMPLE_SYMBOLS` 不为空，预设股票池 small / medium 暂时不会生效。结束日期留空表示尽量拉取到最新可得日期。修改 `REAL_DATA_END_DATE` 后，如果数据库最新行情日期仍较早，需要点击“保存并更新数据”。

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

想看选股逻辑、`total_score` 公式和每只候选的主要贡献因子：

```bash
python -m core.jobs.explain_selection_logic --format markdown
```

也可以在 Streamlit 的“选股逻辑”Tab 查看。

Task 35-38 的参数设置、选股逻辑说明、实时进度和 AKShare 基础信息兼容修复交接说明见 [task_35_38_handoff.md](task_35_38_handoff.md)。

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

如果看到“AKShare 基础增强字段缺失，已使用基础股票信息兜底”，表示基础信息增强字段不可用或结构变化，主行情更新仍可继续。可用 `python -m core.jobs.diagnose_data_quality` 查看行业、市场、上市日期和 PE/PB 完整率。

### run_daily_workflow partial_success

打开最新日报，看步骤状态和 doctor 建议：

```bash
ls -t reports/daily_workflow_*.md | head
python -m core.jobs.doctor_daily_run --post-run
```

### 粘贴命令带上终端提示符

只复制命令本身，不复制 `$`、`%` 或路径提示符。文件名中的 `xxx` 是占位符，要替换成真实文件名。

### Mac 启动器无法打开

先确认执行权限：

```bash
chmod +x scripts/mac/A股选股助手.command
```

如果 macOS 阻止打开，右键 `.command` 文件选择“打开”，或到“系统设置 > 隐私与安全性”允许本次运行。这个启动器不是完整原生 Swift App，不做菜单栏常驻，不做自动后台更新，不做 dmg，不做云同步。
