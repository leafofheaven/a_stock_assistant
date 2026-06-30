# a_stock_assistant

本项目是个人本地 A 股选股辅助工具，用于数据整理、因子观察、候选复核、观察池跟踪和本地复盘，不包含自动交易功能，不构成投资建议。

## 当前功能总览

当前阶段：v0.1 本地日常使用版。系统已经具备日常更新、候选复核、观察池管理、日报、备份和 doctor 体检能力，可以进入个人本地日常使用。

- sample/mock 数据模式，便于无外部数据时跑通流程。
- AKShare + 东方财富 curl fallback 小范围真实数据更新。
- DuckDB 本地存储、真实数据诊断和批量更新诊断。
- 股票池过滤、基础因子计算、综合评分和每日选股。
- 选股逻辑说明、因子权重、候选排名原因和主要贡献因子解释。
- 埃尔德复核：在今日候选之后增加 EMA、MACD、Force Index、Elder Ray 和周线趋势二次技术复核，不覆盖原始排序。
- 埃尔德复核接入人工复核：支持导出带操作建议的 CSV / Markdown，并可显式把趋势确认股票加入观察池。
- 回测诊断、工作流报告和 Streamlit 页面。
- 候选股票复核报告、人工复核模板导出和复核结果导入。
- 观察池管理、每日候选跟踪、观察池变化报告、状态调整与历史记录。
- 本地 DuckDB 备份、恢复 dry-run、报告清理和本地状态诊断。
- Chrome 本地控制台：Streamlit 页面内可修改常用 `.env` 参数、运行白名单命令、实时查看运行进度、查看 doctor 体检并打开 reports 文件夹。

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
python -m core.jobs.doctor_daily_run --pre-run
python -m core.jobs.update_real_data
python -m core.jobs.diagnose_real_data
python -m core.jobs.diagnose_update_batch
python -m core.jobs.diagnose_data_quality
python -m core.jobs.diagnose_factors
python -m core.jobs.explain_selection_logic
python -m core.jobs.run_daily_selection
python -m core.jobs.diagnose_backtest
python -m core.jobs.run_real_workflow --backup-before-run
python -m core.jobs.run_daily_workflow --doctor-before-run --backup-before-run --format all
python -m core.jobs.doctor_daily_run --post-run
streamlit run web/streamlit_app.py
```

## 真实数据工作流

真实数据端到端验证仍可按以下命令拆分执行：

```bash
python -m core.jobs.update_real_data
python -m core.jobs.diagnose_real_data
python -m core.jobs.run_daily_selection
```

最推荐的一条日常命令：

```bash
python -m core.jobs.run_daily_workflow --doctor-before-run --backup-before-run --format all
```

只用本地 DuckDB、不更新数据：

```bash
python -m core.jobs.run_daily_workflow --doctor-before-run --skip-update --format all
```

运行前后体检：

```bash
python -m core.jobs.doctor_daily_run --pre-run
python -m core.jobs.doctor_daily_run --post-run
```

报告输出在 `reports/`，常看 `daily_workflow_*.md`、`selection_review_*.csv`、`watchlist_*.md`。完整复核流程请见 [docs/v0_1_handbook.md](docs/v0_1_handbook.md) 和 [docs/daily_workflow.md](docs/daily_workflow.md)。

买入区间分析：

```bash
python -m core.jobs.calculate_entry_zones
python -m core.jobs.diagnose_entry_zones
python -m core.jobs.export_entry_zone_report --format all
```

该流程基于本地今日候选和观察池股票计算 EMA、支撑阻力、ATR、买入区间、止损位、目标价位和盈亏比，只供个人研究和人工复核，不自动交易。

## 历史功能入口索引

这些入口保留用于任务检查和日常查找，详细说明见 `docs/`：

- 真实数据日常使用流程：`python -m core.jobs.update_real_data`
- 真实因子结果校验：`python -m core.jobs.diagnose_factors`
- 真实回测结果校验：`python -m core.jobs.diagnose_backtest`
- 真实股票样本扩容与批量更新：`REAL_UNIVERSE_PRESET=small`，`python -m core.jobs.diagnose_update_batch`
- 基础信息与 PE/PB 估值字段补全：`ENABLE_REAL_BASIC_ENRICHMENT=true`，`ENABLE_REAL_VALUATION_ENRICHMENT=true`，`python -m core.jobs.diagnose_data_quality`
- 选股逻辑说明：`python -m core.jobs.explain_selection_logic`，`python -m core.jobs.explain_selection_logic --format markdown`，详见 `docs/selection_logic.md`
- 埃尔德复核：`python -m core.jobs.run_elder_review`，`python -m core.jobs.run_elder_review --format markdown`，详见 `docs/elder_review.md`
- 埃尔德复核导出：`python -m core.jobs.export_elder_review`，`python -m core.jobs.export_elder_review --format markdown`，详见 `docs/elder_review_workflow.md`
- 埃尔德复核历史回看：`python -m core.jobs.backtest_elder_review`，`python -m core.jobs.backtest_elder_review --start-date 20240101 --end-date 20260625 --format all`，详见 `docs/elder_review_backtest.md`
- 持仓池基础记录：`python -m core.jobs.import_positions --file <csv>`，`python -m core.jobs.export_positions`，详见 `docs/position_pool.md`
- 持仓每日跟踪：`python -m core.jobs.track_positions`，`python -m core.jobs.track_positions --format markdown`，详见 `docs/position_tracking.md`
- 沪深 A 股全市场股票池：`REAL_UNIVERSE_PRESET=full`，`AKSHARE_SAMPLE_SYMBOLS=`，支持批量更新、断点续跑和失败重试，详见 `docs/real_universe.md`
- 真实运行工作流与报告导出：`python -m core.jobs.run_real_workflow`，`python -m core.jobs.run_real_workflow --no-backtest`，`python -m core.jobs.run_real_workflow --format json`
- 候选股票人工复核清单与结果导出：`python -m core.jobs.export_selection_review`，`python -m core.jobs.export_selection_review --top-n 10`，`python -m core.jobs.export_selection_review --format all`，`--export-selection-review`
- 人工复核结果回填与观察池管理：`review_decisions`，`python -m core.jobs.export_review_template`，`python -m core.jobs.import_review_decisions`，`python -m core.jobs.refresh_watchlist_scores`，`python -m core.jobs.diagnose_watchlist`，`python -m core.jobs.export_watchlist`，`--export-review-template`，`--export-watchlist`
- 观察池每日候选跟踪与变化报告：`watchlist_daily_snapshots`，`watchlist_events`，`python -m core.jobs.refresh_watchlist_from_selection`，`python -m core.jobs.track_watchlist`，`python -m core.jobs.export_watchlist_tracking`，`python -m core.jobs.export_watchlist_tracking_report`，`--track-watchlist`，`--export-watchlist-tracking`
- 一键日常工作流与综合日报：`python -m core.jobs.run_daily_workflow --backup-before-run --format all`，`python -m core.jobs.run_daily_workflow --skip-update --format all`
- 日常运行体检与安全恢复：`python -m core.jobs.doctor_daily_run --pre-run`，`python -m core.jobs.doctor_daily_run --post-run`，`python -m core.jobs.doctor_daily_run --fix-safe`，`python -m core.jobs.run_daily_workflow --doctor-before-run --backup-before-run --format all`
- 观察池状态调整与复核记录管理：`python -m core.jobs.update_review_decision`，`python -m core.jobs.diagnose_review_history`，`--diagnose-review-history`
- 本地数据备份与恢复：`python -m core.jobs.backup_local_data`，`python -m core.jobs.restore_local_data`，`python -m core.jobs.clean_generated_reports`

`run_real_workflow` 偏底层真实数据流程诊断；`run_daily_workflow` 偏日常使用，会一键生成候选复核、观察池、跟踪和 `daily_workflow` 综合日报。

数据质量口径：PE/PB 当前优先补全最新交易日。日报和候选/观察池报告优先看“最新交易日、当前候选、当前观察池”的完整率；全历史 `daily_basic` 完整率偏低通常只表示历史区间估值字段尚未逐日补全。

full 全市场更新口径：页面和 `diagnose_update_batch` 不只看数据库全局最新行情日期，还会逐只股票检查 `daily_price`、`daily_basic`、`adj_factor` 覆盖情况。覆盖率低时会显示“全市场数据未完成”，点击“保存并更新数据”会把缺行情或最新不足的股票加入队列；`FULL_UPDATE_RESUME=true` 时已有最新数据的股票会跳过。

full 基础信息增强口径：`ENABLE_STOCK_BASIC_ENRICHMENT=false`、`FULL_ENABLE_STOCK_BASIC_ENRICHMENT=false` 为默认设置。full 模式不会逐只调用 `stock_individual_info_em`，避免全市场更新在基础增强阶段阻塞。

日常稳定性：运行前可先执行 `python -m core.jobs.doctor_daily_run --pre-run` 检查 `.env`、DuckDB、`reports/.gitkeep`、最近备份和报告、Git 误提交风险。需要安全修复目录或 `reports/.gitkeep` 时运行 `python -m core.jobs.doctor_daily_run --fix-safe`。不要使用 `rm -rf reports`；清理生成报告请用 `python -m core.jobs.clean_generated_reports --force` 或 `find reports -type f ! -name ".gitkeep" -delete`。

## Streamlit 启动

```bash
streamlit run web/streamlit_app.py
```

如果页面黑屏或 DuckDB 被锁，先运行：

```bash
python -m core.jobs.diagnose_streamlit_startup
python scripts/start_streamlit_safe.py --dry-run
python scripts/start_streamlit_safe.py
```

页面用于查看数据状态、今日选股、因子排名、选股逻辑、回测诊断、观察池和本地状态提示。“选股逻辑”Tab 会显示 `total_score` 公式、因子权重、候选排名原因和主要贡献因子。“参数设置 / 本地控制台”提供简化设置向导：切换自定义股票池或预设股票池，修改开始/结束日期，查看“参数日期 vs 数据库日期”，并使用“保存参数”“保存并本地重算”“保存并更新数据”。预设股票池中 `mini / small / medium` 是样本池，`full` 是沪深 A 股全市场，不含北交所；如果 `AKSHARE_SAMPLE_SYMBOLS` 不为空，自定义股票池优先于 full。点击运行后页面会逐行显示当前步骤、当前股票或子任务、成功/失败/跳过数量、实时日志和最终报告路径。修改日期后数据库日期不会立刻变化，需要点击“保存并更新数据”才会联网拉取新行情。若提示 DuckDB 被其他进程锁定，请停止其他 `core.jobs` 或旧 Streamlit；如果 `lsof data/a_stock_assistant.duckdb` 显示 `fileprovi/fileproviderd`，建议把 DuckDB 放到非云同步目录。

full 模式会经过可交易过滤：默认剔除 ST、退市整理、北交所、上市不足 120 天、近 20 日成交不连续和流动性不足股票。近 20 日平均成交额默认门槛为 1 亿元，停牌股票复牌后重新满足成交连续性和流动性规则会自动重新纳入。

Mac 双击启动器：

```bash
chmod +x scripts/mac/A股选股助手.command
open scripts/mac/A股选股助手.command
```

也可以双击 `scripts/mac/A股选股助手.command`，它会启动 Streamlit 并打开 Chrome / 默认浏览器访问 `http://localhost:8501`。这不是完整原生 Swift App，不做菜单栏常驻、不做自动后台更新、不做 dmg、不做云同步。

## 文档目录

- [完整使用说明](docs/usage_guide.md)
- [v0.1 日常使用手册](docs/v0_1_handbook.md)
- [v0.1 发布说明](docs/v0_1_release_notes.md)
- [命令参考](docs/commands_reference.md)
- [日常流程](docs/daily_workflow.md)
- [选股逻辑说明](docs/selection_logic.md)
- [埃尔德复核](docs/elder_review.md)
- [埃尔德复核与观察池流程](docs/elder_review_workflow.md)
- [观察池每日候选跟踪](docs/watchlist_candidate_tracking.md)
- [埃尔德复核历史回看](docs/elder_review_backtest.md)
- [买入区间、支撑阻力和止损位](docs/entry_zones.md)
- [持仓池](docs/position_pool.md)
- [持仓每日跟踪](docs/position_tracking.md)
- [沪深 A 股全市场股票池](docs/real_universe.md)
- [Task 35-38 交接说明](docs/task_35_38_handoff.md)
- [常见问题排查](docs/troubleshooting.md)
- [数据与备份](docs/data_and_backup.md)

## 当前限制

- 默认只做小范围真实数据试运行，不做全市场长周期下载。
- AKShare fallback 的字段完整性可能弱于 Tushare。默认会尝试补全 `stock_basic` 的行业、上市日期，以及 `daily_basic` 的 PE/PB、市值字段；估值补全会优先使用 AKShare 快照接口，不可用时尝试东方财富 quote curl fallback，获取不到时允许为空。
- 可在 `.env` 中用 `ENABLE_REAL_BASIC_ENRICHMENT=false` 或 `ENABLE_REAL_VALUATION_ENRICHMENT=false` 关闭补全；关闭后会保持简化逻辑。
- 用 `python -m core.jobs.diagnose_data_quality` 查看 PE/PB 完整率；用 `python -m core.jobs.diagnose_factors` 判断 `fundamental_score` 是否恢复。PE/PB 仍可能为空，`adj_factor` 可能简化为 `1.0`。
- 本项目不接券商，不自动交易。
- `.env`、`data/`、`reports/`、`backups/` 为本地个人数据，不应提交到 Git。
- AKShare 基础信息增强如果出现字段缺失，系统会使用基础股票信息或本地 preset 兜底；这类 warning 不影响主行情更新。
