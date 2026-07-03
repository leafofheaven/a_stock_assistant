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

常用参数：真实数据范围由 `.env` 中 `REAL_DATA_START_DATE`、`REAL_DATA_END_DATE`、`AKSHARE_SAMPLE_SYMBOLS` 或 `REAL_UNIVERSE_PRESET` 控制。`mini / small / medium` 是样本池；`REAL_UNIVERSE_PRESET=full` 是沪深 A 股全市场，不含北交所。`AKSHARE_SAMPLE_SYMBOLS` 不为空时，自定义股票池优先于 full。

full 模式可交易过滤默认使用：上市不少于 120 天、近 20 日平均成交额不低于 1 亿元、成交额中位数不低于 5000 万元、最新成交额不低于 3000 万元、近 20 日有效成交天数不少于 18 天。停牌股票复牌后重新满足条件会重新纳入。

`update_real_data` 会输出 `[progress]` 进度行，显示当前阶段、当前股票、成功/失败/跳过数量。AKShare 基础信息增强字段缺失时，会使用基础字段或本地 preset 兜底，不影响主行情写入。

full 模式全市场更新可能耗时较长。Task 47 后可通过以下配置控制批量更新、失败重试和断点续跑：

```env
FULL_UPDATE_BATCH_SIZE=50
FULL_UPDATE_LOOKBACK_DAYS=250
FULL_UPDATE_MAX_RETRIES=2
FULL_UPDATE_SLEEP_SECONDS=0.2
FULL_UPDATE_RESUME=true
FULL_UPDATE_MAX_SYMBOLS=0
FULL_UPDATE_MAX_BATCHES=0
ENABLE_STOCK_BASIC_ENRICHMENT=false
FULL_ENABLE_STOCK_BASIC_ENRICHMENT=false
ENABLE_VALUATION_ENRICHMENT=false
FULL_ENABLE_VALUATION_ENRICHMENT=false
```

`FULL_UPDATE_RESUME=true` 时，已有目标结束日期行情的股票会跳过；缺数据或最新行情不足的股票会继续更新。少量股票失败不会中断整个流程，失败列表会在摘要中显示。

真实小批量验收时可临时设置 `FULL_UPDATE_MAX_SYMBOLS=20` 或 `FULL_UPDATE_MAX_BATCHES=1`，只处理少量股票后正常结束。`FULL_UPDATE_BATCH_SIZE` 只控制每批多少只，不代表本次最多处理多少只。

full 更新摘要会区分 `full 基础股票池数量`、`待处理队列` 和 `本次计划处理`。`FULL_UPDATE_MAX_SYMBOLS=20` 只限制本次处理量，不会把 full universe 缩小为 20 或其他续跑窗口大小。

full 模式默认不逐只调用 AKShare `stock_individual_info_em` 做基础信息增强，避免全市场更新卡在增强阶段。需要小样本补充行业、地区等增强字段时，可以手动开启 `ENABLE_STOCK_BASIC_ENRICHMENT=true`；full 模式还需要额外开启 `FULL_ENABLE_STOCK_BASIC_ENRICHMENT=true`。

full 基础股票池解析优先使用专用沪深 A 股列表请求，本地 DuckDB `stock_basic` 只补充字段，不决定 full universe 边界；专用列表失败时才回退本地缓存并给出 warning。该路径不调用 AKShare `stock_info_a_code_name`，避免其内部请求北交所 `stock_info_bj_name_code`。`INCLUDE_BSE=false` 时不会纳入北交所。

full 模式默认也不调用 `stock_a_lg_indicator`、`stock_zh_a_spot_em` 等额外估值网络增强接口。`daily_basic` 可先写入 `turnover_rate` 等基础字段，PE/PB 允许为空，不会阻塞主行情更新。需要小范围验证 PE/PB 补全时，再手动开启 `ENABLE_VALUATION_ENRICHMENT=true` 和 `FULL_ENABLE_VALUATION_ENRICHMENT=true`。

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

作用：查看配置股票数量、已有行情股票数量、覆盖率、缺数据股票、最新行情不足股票和可运行选股数量。

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
python -m core.jobs.track_positions
python -m core.jobs.track_positions --format markdown
python -m core.jobs.track_positions --format all
python -m core.jobs.calculate_entry_zones
python -m core.jobs.diagnose_entry_zones
python -m core.jobs.export_entry_zone_report --format all
```

作用：`run_daily_selection` 基于本地数据生成候选股票摘要；`explain_selection_logic` 查看当前 `total_score` 公式、因子权重、候选排名原因和主要贡献因子；`run_elder_review` 在今日候选之后追加埃尔德技术复核；`export_elder_review` 导出带操作建议的人工复核 CSV / Markdown；`backtest_elder_review` 对埃尔德复核结果做历史回看，输出 `forward_return_5d`、`max_drawdown_20d`、`elder_score` 分组和 `action_hint` 分组表现；`import_positions` / `export_positions` 用于本地持仓池手工记录和导出；`track_positions` 对 active 持仓做每日跟踪，输出 `pnl_pct`、`max_gain_pct`、`max_drawdown_pct`、`latest_elder_score` 和 `position_hint`；`calculate_entry_zones` / `diagnose_entry_zones` / `export_entry_zone_report` 计算并导出买入区间、支撑阻力、止损位和盈亏比。解释、复核、持仓池和买入区间命令只读取或写入本地数据，不改变选股结果。

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

## 全市场批量补数据

命令：

```bash
python -m core.jobs.diagnose_data_source_network --format text
python -m core.jobs.diagnose_data_source_network --format json
python -m core.jobs.preflight_data_source
python -m core.jobs.run_full_batch_update --max-symbols 500 --batch-size 50 --lookback-days 250 --max-retries 1
```

`diagnose_data_source_network` 用于数据源网络诊断，只读检查 DuckDB、代理、DNS、东方财富 K 线接口、Python 请求、curl 默认请求、curl IPv4、curl IPv6 和直连路径，不写 DuckDB，不启动批量更新。Wi-Fi 下东方财富接口失败时，先运行该命令；如果诊断建议切换手机热点，可以切换网络后再重试。

作用：为 `REAL_UNIVERSE_PRESET=full` 做页面化同款补数据。`preflight_data_source` 会检查 DuckDB 锁、Python 代理和东方财富 K 线接口；接口不可用时不要启动批量更新。`run_full_batch_update` 会把参数映射到 `FULL_UPDATE_MAX_SYMBOLS`、`FULL_UPDATE_BATCH_SIZE`、`FULL_UPDATE_LOOKBACK_DAYS` 和 `FULL_UPDATE_MAX_RETRIES`，然后调用现有 `update_real_data`。命令和页面都使用“本次未处理数量”描述未纳入本轮计划的股票，不表示永久跳过。

## 每日研究工作簿 Excel

命令：

```bash
python -m core.jobs.export_daily_research_workbook
python -m core.jobs.export_daily_research_workbook --trade-date 20260630 --output reports/daily_research_20260630.xlsx
```

作用：只读本地 DuckDB 已有结果，导出一份每日研究工作簿 Excel。工作簿包含 `00_摘要`、`01_今日候选`、`02_埃尔德复核`、`03_买入区间`、`04_观察池`、`05_观察池跟踪`、`06_外部模拟持仓`、`07_风险提示`、`08_数据质量`、`09_参数配置`、`10_说明`。默认不导出 rank / 排名字段；序号只代表当前 Sheet 当前显示顺序，不代表买入优先级。用户可按综合分、各因子分、埃尔德分、买入区间、风险状态等字段自行筛选和排序。用户可见字段尽量采用“中文名称（英文名）”格式。该命令不联网更新、不重算因子、不改变 `total_score`、不改变候选排序。

Streamlit 本地控制台中的“导出今日研究工作簿 Excel”按钮调用同一命令。默认输出到 `reports/daily_research_*.xlsx`；自动验收使用 `/tmp/a_stock_assistant_task53/daily_research.xlsx`，不会在工作区留下生成文件。

## 18:00 自动更新

命令：

```bash
python -m core.jobs.run_scheduled_daily_update --dry-run --format text
python -m core.jobs.run_scheduled_daily_update --dry-run --format json
python -m core.jobs.run_scheduled_daily_update --force --format text
python -m core.jobs.run_scheduled_daily_update --force --update-limit 50 --stage-timeout-seconds 180 --format text
python -m core.jobs.run_scheduled_daily_update --force --update-mode daily_incremental --recent-days 5 --format text
python -m core.jobs.run_scheduled_daily_update --force --update-mode full_backfill --stage-timeout-seconds 7200 --format text
python -m core.jobs.run_scheduled_daily_update --force --allow-intraday --update-limit 50 --format text
python -m core.jobs.install_scheduled_daily_update --time 18:00 --dry-run
python -m core.jobs.uninstall_scheduled_daily_update --dry-run
```

作用：在每天 18:00 之后按本地状态决定是否执行收盘后自动更新。流程会先判断交易日、是否已成功更新、DuckDB 锁和数据源预检；预检失败不会启动重型更新。预检通过后串行执行备份、数据更新、日常重算、埃尔德复核、买入区间、观察池跟踪和每日研究工作簿 Excel 导出。

`run_scheduled_daily_update` 在 text 模式下会立即输出阶段进度，并在每个阶段开始前写入状态文件。正式 18:00 自动更新默认使用 `--update-mode daily_incremental`，只处理最近已完成交易日附近的日常增量缺口，不把全市场历史补数据作为默认任务。`daily_incremental` 中“已有最新行情但历史不完整”的股票只作为数据质量 warning，不会导致自动更新失败；历史缺口应通过页面“全市场批量补数据”或手动 `--update-mode full_backfill` 修复。

人工小批量验收建议先运行：

```bash
python -m core.jobs.run_scheduled_daily_update --force --update-limit 50 --stage-timeout-seconds 180 --format text
```

手工历史补库可显式使用：

```bash
python -m core.jobs.run_scheduled_daily_update --force --update-mode full_backfill --stage-timeout-seconds 7200 --format text
```

状态文件会记录 `last_heartbeat_at`、`processed_symbol_count`、`total_symbol_count`、空数据股票数量、网络超时数量和失败股票样例。单只股票空数据或超时会汇总记录，不会默认逐只刷屏；部分股票失败但后续阶段完成时，自动更新可返回 warning。`DATA_SOURCE_REQUEST_TIMEOUT_SECONDS` 控制单请求超时，`SYMBOL_UPDATE_TIMEOUT_SECONDS` 控制单标的处理超时，`FULL_BATCH_UPDATE_TIMEOUT_SECONDS` 控制全市场更新阶段超时。

日期口径：`run_date` 是实际运行自然日，`research_trade_date` 和 `latest_completed_trade_date` 是本次研究对应的最近已完成交易日。若在 18:00 前盘中手动 `--force`，默认仍使用上一个已完成交易日，避免把未完成交易日当作正式收盘后结果。只有显式传入 `--allow-intraday` 时才允许使用当天，并会在 text / JSON 状态中提示“盘中强制运行，结果可能基于未完成交易日数据，不代表正式收盘后结果”。

状态文件默认写入 `data/runtime/scheduled_daily_update_status.json`，运行锁默认使用 `data/runtime/scheduled_daily_update.lock`。这些都是本地运行产物，不应提交。Streamlit “数据更新状态”页面会显示自动更新状态，并在 Excel 文件存在时提供“下载最新自动更新 Excel”按钮。

`install_scheduled_daily_update` 生成用户级 LaunchAgent，默认 label 为 `com.a_stock_assistant.scheduled_daily_update`，使用 `StartCalendarInterval` 在 18:00 触发 `python -m core.jobs.run_scheduled_daily_update --catch-up --scheduled-time 18:00 --update-mode daily_incremental`。如果 18:00 Mac 睡眠，唤醒后可能补跑；如果当天已经 success，不会重复运行。

通知框架默认支持 macOS 本地通知。邮件通知默认关闭；如需启用，可配置 `NOTIFY_EMAIL_ENABLED=true`、`NOTIFY_EMAIL_TO`、`SMTP_HOST`、`SMTP_PORT`、`SMTP_USER`、`SMTP_PASSWORD`、`SMTP_FROM` 和 `SMTP_USE_SSL`。未配置邮件时不会报错，只显示 email disabled。

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
python -m core.jobs.refresh_watchlist_from_selection
python -m core.jobs.track_watchlist
python -m core.jobs.track_watchlist --export-report --format all
python -m core.jobs.export_watchlist_tracking --format all
python -m core.jobs.export_watchlist_tracking_report --format all
```

作用：把今日候选刷新到观察池，生成 `watchlist_daily_snapshots` 与 `watchlist_events`，并导出价格、评分、PE/PB、排名和入选次数变化报告。重点看 `watch_status`、`selected_count_5d`、`selected_count_10d`、`consecutive_selected_days`、`rank_change`、`score_change`。

状态包括 `new_candidate`、`active_watch`、`strong_watch`、`wait_pullback`、`near_buy_zone`、`overheated`、`weakening`、`invalidated`、`bought`、`removed`。这些状态只用于人工复核，不改变 `total_score`、因子权重或今日选股排序。

## 外部模拟持仓

命令：

```bash
python -m core.jobs.generate_external_position_template
python -m core.jobs.import_external_trades --file path/to/external_trades.csv
python -m core.jobs.import_external_positions --file path/to/external_position_snapshots.csv
python -m core.jobs.match_external_positions
python -m core.jobs.diagnose_external_positions
python -m core.jobs.export_external_position_report --format all
```

作用：读取用户手工导出的本地 CSV 文件，把外部模拟交易记录写入 `external_trades`，把外部模拟持仓快照写入 `external_position_snapshots`，并匹配本地买入区间、止损位、目标价位和观察池状态。该流程不登录外部平台，不读取 cookie，不接券商，不自动交易。

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

## 自动回看分析

命令：

```bash
python -m core.jobs.run_lookback_analysis --dry-run --format text
python -m core.jobs.run_lookback_analysis --dry-run --format json
python -m core.jobs.run_lookback_analysis --as-of latest --horizons 1,3,5,10,20 --limit 300 --format text
```

作用：只读本地 DuckDB，基于 `strategy_result`、`daily_price`、埃尔德复核字段、买入区间快照和观察池快照，验证当前系统已有信号在后续 1 / 3 / 5 / 10 / 20 个交易日的历史表现。回看使用每只股票后续有效交易日，不使用自然日；未来收益只在回看阶段计算，不参与当日选股。

独立完整报告默认写入：

```text
reports/lookback/lookback_analysis_YYYYMMDD.xlsx
```

状态文件默认写入：

```text
data/runtime/lookback_analysis_status.json
```

每日研究工作簿会读取最近一次 `lookback_analysis_status.json`，新增 `11_自动回看摘要`，并在 `00_摘要` 中显示最近一次自动回看状态、截止交易日、有效样本数量和完整报告路径。每日研究工作簿只展示摘要，不嵌入 `07_未来收益明细` 等完整明细。

默认不在 18:00 自动更新后运行回看。可选配置：

```bash
RUN_LOOKBACK_AFTER_DAILY_UPDATE=false
```

设为 `true` 后，`run_scheduled_daily_update` 可在导出每日研究工作簿前先运行自动回看分析；默认保持 `false`，避免日常自动更新额外增加重任务。

回看结论只能理解为“历史样本期内表现”，不自动调整综合分（total_score）、因子权重、今日候选排序、埃尔德复核或买入区间逻辑；不构成投资建议，不自动交易。

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

自定义股票池会写入 `AKSHARE_SAMPLE_SYMBOLS`，它不为空时 `REAL_UNIVERSE_PRESET` 不生效。使用预设股票池会清空 `AKSHARE_SAMPLE_SYMBOLS` 并保存 `REAL_UNIVERSE_PRESET=mini`、`small`、`medium` 或 `full`。其中 `full` 表示沪深 A 股全市场，不含北交所。结束日期留空表示尽量拉取到最新可得日期；修改结束日期后，只有“保存并更新数据”会让数据库最新行情日期变化。

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
python -m core.jobs.diagnose_streamlit_startup
python scripts/start_streamlit_safe.py --dry-run
python scripts/start_streamlit_safe.py
```

作用：启动本地页面，或在页面黑屏 / DuckDB 文件锁时先做启动诊断。页面显示数据状态、今日选股、因子排名、选股逻辑、回测诊断、观察池和本地备份提示。

`start_streamlit_safe.py` 会检查 8501 端口和 DuckDB 占用，并使用 `--server.headless true --server.fileWatcherType none` 启动。浏览器打开由启动器统一控制，只执行一次 `open http://localhost:8501`；如果 8501 已有服务运行，则不会重复启动第二个 Streamlit 进程。若 `lsof data/a_stock_assistant.duckdb` 显示 `fileprovi/fileproviderd`，说明 DuckDB 可能被 macOS FileProvider 或云同步占用，可考虑迁移到非云同步目录。

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
