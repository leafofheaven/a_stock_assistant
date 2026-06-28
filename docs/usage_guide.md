# 完整使用说明

当前阶段为 v0.1 本地日常使用版。建议先阅读 [v0.1 日常使用手册](v0_1_handbook.md)，再按本文查找细节命令。

本文档说明如何在本地使用 `a_stock_assistant`。所有命令默认从项目目录执行：

```bash
cd /Users/wanghao/Documents/股票
source .venv/bin/activate
```

本项目是个人本地 A 股选股辅助工具，用于数据整理、因子观察、候选复核、观察池跟踪和本地复盘，不包含自动交易功能。

## 项目目录

- `app/`：配置模块。
- `core/`：数据源、存储、因子、选股、回测、任务命令。
- `web/`：Streamlit 页面。
- `tests/`：自动测试。
- `scripts/`：项目检查脚本。
- `docs/`：使用文档。
- `data/`：本地 DuckDB 数据库，默认不提交。
- `reports/`：运行生成报告，默认不提交。
- `backups/`：本地备份，默认不提交。

## Python 虚拟环境

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .
```

如需启动页面：

```bash
pip install -e .[app]
```

## .env 配置

```bash
cp .env.example .env
```

常用配置：

```env
DATA_PROVIDER=sample
TUSHARE_TOKEN=
DUCKDB_PATH=./data/a_stock_assistant.duckdb
REAL_DATA_START_DATE=20240101
REAL_DATA_END_DATE=
REAL_UNIVERSE_PRESET=mini
AKSHARE_SAMPLE_SYMBOLS=000001,600000,000002
AKSHARE_ADJUST=qfq
ENABLE_REAL_BASIC_ENRICHMENT=true
ENABLE_REAL_VALUATION_ENRICHMENT=true
```

`.env` 不应提交到 Git。`TUSHARE_TOKEN` 可以为空。

## sample 数据模式

sample 模式用于无真实数据时验证流程：

```env
DATA_PROVIDER=sample
```

运行：

```bash
python -m core.jobs.run_daily_selection
streamlit run web/streamlit_app.py
```

## AKShare 真实数据模式

```env
DATA_PROVIDER=akshare
REAL_DATA_START_DATE=20240101
REAL_DATA_END_DATE=20240630
AKSHARE_SAMPLE_SYMBOLS=000001,600000,000002
AKSHARE_ADJUST=qfq
```

更新真实数据：

```bash
python -m core.jobs.update_real_data
```

AKShare 获取日线失败时，项目会在小范围样本上尝试系统 curl 请求东方财富 kline fallback。

默认还会尝试补全基础信息和估值字段：

- `ENABLE_REAL_BASIC_ENRICHMENT=true`：尽量补全行业、市场、上市日期等 `stock_basic` 字段。
- `ENABLE_REAL_VALUATION_ENRICHMENT=true`：尽量补全 PE/PB、`total_mv`、`circ_mv` 等 `daily_basic` 字段。当前会优先使用 AKShare 可用的快照类接口；接口不可用时，尝试东方财富 quote curl fallback。

这两个补全失败时不会影响日线行情写入；如需保持旧的简化逻辑，可在 `.env` 中设为 `false`。

估值补全通常写入每只股票最新交易日对应的 `daily_basic`。运行 `python -m core.jobs.diagnose_data_quality` 查看 PE/PB 完整率；再运行 `python -m core.jobs.diagnose_factors` 判断 `fundamental_score` 是否恢复。PE/PB 缺失时，候选复核和观察池报告会保留缺失提示，已有值时不再提示缺失。

## REAL_UNIVERSE_PRESET

当 `AKSHARE_SAMPLE_SYMBOLS` 为空时，可用预设样本：

```env
AKSHARE_SAMPLE_SYMBOLS=
REAL_UNIVERSE_PRESET=mini
```

- `mini`：约 3 只。
- `small`：约 30 只。
- `medium`：约 100 只。

如果 `AKSHARE_SAMPLE_SYMBOLS` 显式设置，则优先使用它。

## 数据更新

```bash
python -m core.jobs.update_real_data
python -m core.jobs.diagnose_real_data
python -m core.jobs.diagnose_update_batch
python -m core.jobs.diagnose_data_quality
```

`diagnose_real_data` 用于判断本地 DuckDB 是否足够运行选股。`diagnose_update_batch` 用于查看样本股票覆盖率。`diagnose_data_quality` 用于查看基础信息和估值字段完整率。

## 诊断、选股、因子和回测

```bash
python -m core.jobs.diagnose_factors
python -m core.jobs.run_daily_selection
python -m core.jobs.diagnose_backtest
```

`run_daily_selection` 会优先使用本地真实数据；真实数据不足时会清楚说明是否回退 sample。

如果 `fundamental_score` 为空或偏低，先运行：

```bash
python -m core.jobs.diagnose_data_quality
python -m core.jobs.diagnose_factors
```

AKShare 小范围验证下，`pe` / `pb` 仍可能为空；报告和页面会显示字段缺失提示。

## 候选复核

导出候选复核报告：

```bash
python -m core.jobs.export_selection_review --top-n 10 --format all
```

导出人工复核模板：

```bash
python -m core.jobs.export_review_template --top-n 10
```

导入复核结果：

```bash
python -m core.jobs.import_review_decisions --file reports/review_template_xxx.csv
```

## 观察池

```bash
python -m core.jobs.refresh_watchlist_scores --dry-run
python -m core.jobs.refresh_watchlist_scores
python -m core.jobs.diagnose_watchlist
python -m core.jobs.export_watchlist --format all
python -m core.jobs.track_watchlist --export-report --format all
python -m core.jobs.export_watchlist_tracking_report --format all
```

`refresh_watchlist_scores` 会从本地 DuckDB 的最新行情、估值和评分结果刷新 active watch 股票；没有评分时会给出 `score_missing_reason`，不会修改人工复核决策。

## 一键日常工作流

也可以在 Streamlit 的“参数设置 / 本地控制台”中操作：

- 保存参数：只保存设置，不运行命令；
- 保存并本地重算：只用本地已有数据，不联网更新行情；
- 保存并更新数据：保存设置后联网更新行情并生成报告。

自定义股票池会写入 `AKSHARE_SAMPLE_SYMBOLS`，它不为空时 `REAL_UNIVERSE_PRESET=small/medium` 不生效。切换到预设股票池会自动清空 `AKSHARE_SAMPLE_SYMBOLS`。修改结束日期后，数据库最新行情日期不会自动变化，需要点击“保存并更新数据”。

运行前体检：

```bash
python -m core.jobs.doctor_daily_run --pre-run
```

推荐日常运行：

```bash
python -m core.jobs.run_daily_workflow --doctor-before-run --backup-before-run --format all
```

只使用本地库、不更新真实数据：

```bash
python -m core.jobs.run_daily_workflow --skip-update --format all
```

输出位于 `reports/daily_workflow_*.md/json/csv`，包含 Top 候选、观察池、观察池变化、PE/PB 完整率和下一步建议。`run_real_workflow` 仍保留用于底层真实数据流程诊断。

PE/PB 当前优先补全最新交易日。日常判断请优先看日报中的最新交易日口径、当前候选口径和观察池口径；全历史完整率低不代表当前候选股票缺少 PE/PB。

运行后复查：

```bash
python -m core.jobs.doctor_daily_run --post-run
```

安全修复本地目录和 `reports/.gitkeep`：

```bash
python -m core.jobs.doctor_daily_run --fix-safe
```

`--fix-safe` 不会删除或覆盖 DuckDB，不会修改 `.env`。

手动调整复核状态：

```bash
python -m core.jobs.update_review_decision --ts-code 002475.SZ --decision watch --reason "继续观察"
python -m core.jobs.update_review_decision --ts-code 002475.SZ --archive --reason "归档观察"
python -m core.jobs.diagnose_review_history --ts-code 002475.SZ
```

## 备份恢复

```bash
python -m core.jobs.diagnose_local_state
python -m core.jobs.backup_local_data --label before_change
python -m core.jobs.list_backups
python -m core.jobs.restore_local_data --backup-dir backups/a_stock_backup_xxx --dry-run
python -m core.jobs.restore_local_data --backup-dir backups/a_stock_backup_xxx --force
python -m core.jobs.clean_generated_reports --dry-run
```

恢复默认 dry-run；只有加 `--force` 才会覆盖当前 DuckDB。

## Streamlit 页面

```bash
streamlit run web/streamlit_app.py
```

页面用途：

- 数据状态；
- 今日选股；
- 因子排名；
- 回测诊断；
- 候选复核；
- 观察池；
- 观察池跟踪；
- 本地状态 / 备份提示。
