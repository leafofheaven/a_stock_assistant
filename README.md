# a_stock_assistant

A 股选股辅助研究项目，用于本地化的数据整理、股票池过滤、因子计算、综合评分、策略回测和 Streamlit 页面展示。

本项目仅用于研究与辅助决策，不构成投资建议，不提供自动交易能力，也不承诺任何收益结果。

## 项目定位

- 面向本地研究流程：安装、测试、运行一键选股 smoke、启动页面。
- 默认不访问真实外部 API；没有真实 Tushare / AKShare 数据时，会使用明确标注的 sample/mock 演示数据展示基本流程。
- 输出内容仅用于模型和流程验证，不应被理解为买入、卖出或持有建议。

## 环境要求

- Python 3.12
- macOS / Linux 本地运行

## 安装步骤

创建虚拟环境：

```bash
python -m venv .venv
```

激活虚拟环境：

```bash
source .venv/bin/activate
```

安装项目依赖：

```bash
pip install -e .
```

如需启动 Streamlit 页面，可安装前端可选依赖：

```bash
pip install -e .[app]
```

## 配置步骤

复制示例配置：

```bash
cp .env.example .env
```

`TUSHARE_TOKEN` 可以为空。当前 MVP 的 smoke test 和演示页面不依赖真实 token，也不会自动访问真实外部 API。

如需手动验证少量真实 Tushare 数据接入，可在 `.env` 中配置：

```env
TUSHARE_TOKEN=你的 Tushare token
DATA_PROVIDER=tushare
REAL_DATA_START_DATE=20240101
REAL_DATA_END_DATE=
REAL_DATA_SAMPLE_SYMBOLS=000001.SZ,600000.SH,000002.SZ
```

`REAL_DATA_END_DATE` 为空时会使用当前日期。当前真实数据接入只拉取
`REAL_DATA_SAMPLE_SYMBOLS` 中的少量股票，用于验证流程，不做全市场长周期下载。

如需手动使用 AKShare 作为备用 / 低成本数据源，可配置：

```env
DATA_PROVIDER=akshare
AKSHARE_SAMPLE_SYMBOLS=000001,600000,000002
AKSHARE_ADJUST=qfq
```

如需保持 Tushare 为主数据源，并在 Tushare 失败或 token 缺失时尝试 AKShare，可配置：

```env
DATA_PROVIDER=tushare
ENABLE_AKSHARE_FALLBACK=true
AKSHARE_SAMPLE_SYMBOLS=000001,600000,000002
AKSHARE_ADJUST=qfq
```

AKShare 当前只用于小范围验证，不保证所有字段与 Tushare 完全一致；部分 AKShare 不稳定或缺失字段会写入空表或空值，并保留 sample smoke test 可用。

AKShare 日线行情当前使用 `stock_zh_a_hist` 做低成本验证。字段完整性可能弱于
Tushare：PE/PB 等估值字段可能为空，复权因子当前可能简化为 `adj_factor=1.0`，
仅用于流程验证，不构成投资建议。

在某些本地网络环境下，AKShare 通过 Python requests 访问东方财富历史行情接口可能失败。
项目会先尝试 AKShare `stock_zh_a_hist`，失败或返回空数据时再通过系统 `curl`
小范围请求东方财富 kline 接口作为 fallback。该 fallback 仅用于少量样本股票的真实数据
验证，不自动交易，不构成投资建议。

## 本地检查命令

运行自动测试：

```bash
python -m pytest
```

运行项目级检查：

```bash
python scripts/check_project.py
```

运行任务检查：

```bash
python scripts/check_task.py task11
```

Task 12 收尾验收也可以运行：

```bash
python scripts/check_task.py task12
```

## 一键运行命令

手动更新少量真实 Tushare 数据到 DuckDB：

```bash
python -m core.jobs.update_real_data
```

诊断本地 DuckDB 是否足够完成真实数据端到端验证：

```bash
python -m core.jobs.diagnose_real_data
```

运行每日选股 smoke 入口：

```bash
python -m core.jobs.run_daily_selection
```

当前 MVP 在没有真实数据库结果或真实评分/选股结果不足时使用 sample 数据输出摘要，摘要包括运行日期、数据来源、股票池数量、评分股票数量、候选股票数量、候选股票示例和结果保存说明。

## 真实数据端到端验证

第一步，按需在 `.env` 中选择数据源并保持小范围样本股票：

```env
DATA_PROVIDER=tushare
REAL_DATA_SAMPLE_SYMBOLS=000001.SZ,600000.SH,000002.SZ
```

或使用 AKShare 小范围验证：

```env
DATA_PROVIDER=akshare
AKSHARE_SAMPLE_SYMBOLS=000001,600000,000002
```

第二步，依次运行：

```bash
python -m core.jobs.update_real_data
python -m core.jobs.diagnose_real_data
python -m core.jobs.run_daily_selection
streamlit run web/streamlit_app.py
```

判断当前使用 sample 数据还是真实数据：

- 命令输出中 `数据来源: sample 数据（演示）` 表示已回退 sample 数据；
- 命令输出中包含 `本地 DuckDB 真实数据` 表示已读取本地真实数据；
- Streamlit 页面顶部会显示当前数据来源；如果是 sample，会明确标注“演示数据”；如果是真实数据，会显示最新交易日期。

当前真实数据端到端验证只拉少量股票，不做全市场长周期下载。不构成投资建议，不自动交易。

## 真实数据日常使用流程

日常验证时建议固定按以下顺序执行：

1. 配置 `.env`，选择 `DATA_PROVIDER=tushare` 或 `DATA_PROVIDER=akshare`，并保持样本股票范围较小。
2. 更新真实数据：

```bash
python -m core.jobs.update_real_data
```

3. 诊断数据状态：

```bash
python -m core.jobs.diagnose_real_data
```

4. 诊断因子结果：

```bash
python -m core.jobs.diagnose_factors
```

5. 运行选股：

```bash
python -m core.jobs.run_daily_selection
```

6. 启动页面：

```bash
streamlit run web/streamlit_app.py
```

判断当前使用 sample 数据还是真实数据：

- `数据来源: sample 数据（演示）` 表示当前展示的是演示数据；
- `真实数据不足，已回退 sample 数据` 表示本地真实数据不足，流程已自动回退；
- `本地 DuckDB 真实数据` 表示当前读取的是本地真实数据。

当前仅支持少量股票验证，不建议直接全市场长周期运行。不构成投资建议，不自动交易。

## 真实因子结果校验

完成真实数据更新后，可以运行因子诊断命令：

```bash
python -m core.jobs.update_real_data
python -m core.jobs.diagnose_real_data
python -m core.jobs.diagnose_factors
python -m core.jobs.run_daily_selection
streamlit run web/streamlit_app.py
```

`diagnose_factors` 会输出当前 `DATA_PROVIDER`、DuckDB 路径、当前使用的数据类型、最新行情日期、股票池数量、可计算因子的股票数量、各因子非空率、NaN 数量、最大值、最小值、均值、中位数、`total_score` 非空股票数量、Top 10 综合评分股票、异常值提示和下一步建议。

判断当前数据类型：

- `sample 数据（演示）`：仅使用内置演示数据；
- `akshare 本地 DuckDB 真实数据`：读取 AKShare / 东方财富 fallback 写入的本地真实数据；
- `tushare 本地 DuckDB 真实数据`：读取 Tushare 写入的本地真实数据；
- `真实数据不足，已回退 sample 数据`：本地真实数据不足，流程使用演示数据保证 smoke test 可运行。

AKShare fallback 限制：

- 当前只验证少量样本股票，不适合全市场长周期直接运行；
- `pe` / `pb` 可能为空，基本面分项可能偏低或为空；
- `adj_factor` 可能简化为 `1.0`；
- 仅用于真实数据链路试运行，不适合作为正式投资决策依据。

本项目仅用于研究与辅助决策，不构成投资建议，不自动交易。

## 真实回测结果校验

完成真实数据与因子诊断后，可以运行最小真实回测诊断：

```bash
python -m core.jobs.update_real_data
python -m core.jobs.diagnose_real_data
python -m core.jobs.diagnose_factors
python -m core.jobs.run_daily_selection
python -m core.jobs.diagnose_backtest
streamlit run web/streamlit_app.py
```

`diagnose_backtest` 会读取本地 DuckDB 中的真实 `daily_price`，使用现有因子与综合评分逻辑生成少量样本股票评分结果，构建等权组合，并调用已有回测引擎输出 annual_return、max_drawdown、sharpe_ratio、win_rate、turnover、equity_curve 行数、交易记录行数和持仓记录行数。

当前回测只基于少量样本股票真实数据试运行；AKShare fallback 字段有限，`pe` / `pb` 可能为空，`adj_factor` 可能简化为 `1.0`。回测结果仅用于验证本地数据链路和代码流程，不代表正式投资策略表现，不构成投资建议，不自动交易。

## 真实股票样本扩容与批量更新

真实数据试运行可以通过固定预设股票池做中小规模批量验证，不做全市场下载。

mini 配置：

```env
DATA_PROVIDER=akshare
AKSHARE_SAMPLE_SYMBOLS=
REAL_UNIVERSE_PRESET=mini
REAL_BATCH_SIZE=10
REAL_BATCH_SLEEP_SECONDS=0
REAL_MAX_RETRIES=1
REAL_REQUEST_TIMEOUT_SECONDS=30
```

small 配置：

```env
DATA_PROVIDER=akshare
AKSHARE_SAMPLE_SYMBOLS=
REAL_UNIVERSE_PRESET=small
REAL_BATCH_SIZE=10
REAL_BATCH_SLEEP_SECONDS=0.2
REAL_MAX_RETRIES=2
REAL_REQUEST_TIMEOUT_SECONDS=30
```

medium 配置：

```env
DATA_PROVIDER=akshare
AKSHARE_SAMPLE_SYMBOLS=
REAL_UNIVERSE_PRESET=medium
REAL_BATCH_SIZE=10
REAL_BATCH_SLEEP_SECONDS=0.5
REAL_MAX_RETRIES=2
REAL_REQUEST_TIMEOUT_SECONDS=30
```

优先级：如果 `AKSHARE_SAMPLE_SYMBOLS` 显式配置了股票列表，则优先使用该列表；只有当 `AKSHARE_SAMPLE_SYMBOLS` 为空时，才会根据 `REAL_UNIVERSE_PRESET` 选择 `mini` / `small` / `medium` 预设样本。

批量更新命令：

```bash
python -m core.jobs.update_real_data
```

批量诊断命令：

```bash
python -m core.jobs.diagnose_update_batch
```

完整真实试运行命令：

```bash
python -m core.jobs.update_real_data
python -m core.jobs.diagnose_real_data
python -m core.jobs.diagnose_update_batch
python -m core.jobs.diagnose_factors
python -m core.jobs.run_daily_selection
python -m core.jobs.diagnose_backtest
```

限制：当前仅用于少量真实股票试运行，不做全市场下载；AKShare fallback 的 `pe` / `pb` 可能为空，`adj_factor` 当前可能简化为 `1.0`；不构成投资建议，不自动交易。

## 真实运行工作流与报告导出

完成真实数据配置后，可以用统一工作流串联更新、诊断、因子校验、选股试运行和回测诊断，并在 `reports/` 下生成可留档报告。

完整真实运行：

```bash
python -m core.jobs.run_real_workflow
```

跳过数据更新，仅基于本地 DuckDB 运行：

```bash
python -m core.jobs.run_real_workflow --skip-update
```

不运行回测诊断：

```bash
python -m core.jobs.run_real_workflow --no-backtest
```

指定报告目录：

```bash
python -m core.jobs.run_real_workflow --report-dir reports
```

生成 JSON 报告：

```bash
python -m core.jobs.run_real_workflow --format json
```

报告输出位置：

```text
reports/
```

报告内容包括：

- 数据更新摘要；
- 批量覆盖诊断；
- 真实数据诊断；
- 因子诊断；
- 选股结果；
- 回测诊断；
- 数据质量提示；
- 风险提示。

工作流中的每一步都会标记为 `success`、`partial_success`、`skipped` 或 `failed`。某一步失败时，后续可执行的诊断步骤仍会继续运行，并在最终报告中记录原因。Streamlit 的“数据更新状态”页面会读取最近一份 workflow 报告并展示整体状态、数据来源、最新行情日期、覆盖率、候选股票数量、是否回退 sample 和报告路径；页面不会触发外部数据更新。

限制：该工作流只封装已有本地命令，不新增选股策略、不新增因子、不接雪球、不接券商、不自动交易。AKShare fallback 数据字段有限，`pe` / `pb` 可能为空，`adj_factor` 可能简化为 `1.0`；`small` / `medium` 仍为样本级真实试运行，不是全市场生产级数据系统，不构成投资建议。

## 候选股票人工复核清单与结果导出

可以将当前候选股票导出为人工复核清单，帮助理解候选结果中的综合评分、因子分、原始因子和数据质量提示。该报告只用于研究和复核，不构成投资建议。

单独导出候选复核报告：

```bash
python -m core.jobs.export_selection_review
```

导出前 10 只：

```bash
python -m core.jobs.export_selection_review --top-n 10
```

指定格式：

```bash
python -m core.jobs.export_selection_review --format markdown
python -m core.jobs.export_selection_review --format json
python -m core.jobs.export_selection_review --format csv
python -m core.jobs.export_selection_review --format all
```

在完整工作流中导出：

```bash
python -m core.jobs.run_real_workflow --skip-update --export-selection-review
```

报告输出位置：

```text
reports/
```

`selection_review` 报告包含：

- 候选股票；
- 综合评分；
- 因子分；
- 原始因子；
- 数据质量提示；
- 入选原因摘要；
- 人工复核要点；
- 风险提示。

限制：报告不构成投资建议，不自动交易，不提供目标价，不保证收益。AKShare fallback 数据字段有限，`pe` / `pb` 可能为空；`small` / `medium` 仍为样本级真实试运行。

## 人工复核结果回填与观察池管理

`review_decisions` 表用于记录人工复核结论，并形成可持续跟踪的本地观察池。该功能只保存人工判断，不生成买入建议、目标价、收益承诺或交易指令。

导出人工复核模板：

```bash
python -m core.jobs.export_review_template
```

导入人工复核结果：

```bash
python -m core.jobs.import_review_decisions --file reports/review_template_xxx.csv
```

dry-run 校验：

```bash
python -m core.jobs.import_review_decisions --file reports/review_template_xxx.csv --dry-run
```

诊断观察池：

```bash
python -m core.jobs.diagnose_watchlist
```

导出观察池：

```bash
python -m core.jobs.export_watchlist
```

在完整工作流中导出模板：

```bash
python -m core.jobs.run_real_workflow --skip-update --export-review-template
```

在完整工作流中导出观察池：

```bash
python -m core.jobs.run_real_workflow --skip-update --export-watchlist
```

## 观察池跟踪与变化报告

`watchlist_snapshots` 表用于记录 active watch 股票的本地跟踪快照。该功能只基于本地 DuckDB 中已有的行情和评分数据，不访问外部接口，不生成交易方向判断，不自动交易。

生成观察池跟踪 snapshot：

```bash
python -m core.jobs.track_watchlist
```

生成 snapshot 后同时导出变化报告：

```bash
python -m core.jobs.track_watchlist --export-report --format all
```

单独导出观察池变化报告：

```bash
python -m core.jobs.export_watchlist_tracking_report --format all
```

在完整工作流中执行观察池跟踪：

```bash
python -m core.jobs.run_real_workflow --skip-update --track-watchlist
```

在完整工作流中跟踪并导出变化报告：

```bash
python -m core.jobs.run_real_workflow --skip-update --track-watchlist --export-watchlist-tracking
```

变化报告会展示：

- 当前数据来源；
- snapshot_date；
- active watch 股票数量；
- latest_close、total_score；
- 加入观察后或首次 snapshot 后的价格变化；
- 综合评分、趋势分、动量分、流动性分、波动率分变化；
- 数据质量提示；
- 人工复核提示。

限制：观察池变化报告仅用于人工复核和数据质量检查，不构成投资建议，不提供价格预期，不作收益承诺，不包含交易执行指令。AKShare fallback 数据字段有限，`pe` / `pb` 可能为空；`adj_factor` 可能简化为 1.0。

## 观察池状态调整与复核记录管理

`review_decision_history` 表用于保存观察池状态调整历史。每次通过命令修改 `review_decisions` 当前状态时，会追加一条历史记录，便于后续复盘。

修改观察状态：

```bash
python -m core.jobs.update_review_decision --ts-code 002475.SZ --decision watch --reason "继续观察"
```

排除：

```bash
python -m core.jobs.update_review_decision --ts-code 002475.SZ --decision exclude --reason "人工排除"
```

归档：

```bash
python -m core.jobs.update_review_decision --ts-code 002475.SZ --archive --reason "归档观察"
```

重新激活：

```bash
python -m core.jobs.update_review_decision --ts-code 002475.SZ --reactivate --reason "重新观察"
```

查看复核历史：

```bash
python -m core.jobs.diagnose_review_history
python -m core.jobs.diagnose_review_history --ts-code 002475.SZ
```

在完整工作流中查看复核历史：

```bash
python -m core.jobs.run_real_workflow --skip-update --diagnose-review-history
```

说明：本项目为个人本地 A 股选股辅助工具，用于数据整理、因子观察、候选复核和观察池跟踪，不包含自动交易功能。

## 本地数据备份与恢复

本项目为个人本地研究工具，用于数据整理、候选复核和观察池跟踪，不自动交易。建议在重要更新前备份 DuckDB。

诊断本地状态：

```bash
python -m core.jobs.diagnose_local_state
```

创建备份：

```bash
python -m core.jobs.backup_local_data
```

创建带 reports 的备份：

```bash
python -m core.jobs.backup_local_data --include-reports
```

查看备份：

```bash
python -m core.jobs.list_backups
```

恢复前 dry-run：

```bash
python -m core.jobs.restore_local_data --backup-dir backups/a_stock_backup_xxx --dry-run
```

强制恢复：

```bash
python -m core.jobs.restore_local_data --backup-dir backups/a_stock_backup_xxx --force
```

清理生成报告 dry-run：

```bash
python -m core.jobs.clean_generated_reports
```

实际清理生成报告：

```bash
python -m core.jobs.clean_generated_reports --force
```

工作流前自动备份：

```bash
python -m core.jobs.run_real_workflow --backup-before-run
```

备份目录默认位于 `backups/`，其中包含 DuckDB 文件、安全元数据、表行数摘要和可选 reports 副本。备份不会保存 `.env` 原文或 token。

`decision` 支持以下取值：

- `watch`：加入观察；
- `pass`：暂不关注；
- `exclude`：排除；
- `needs_data`：需要补充数据；
- `pending`：待复核。

限制：本功能只记录人工复核结论，不自动交易，不提供目标价，不保证收益，不构成投资建议。AKShare fallback 数据字段有限；`small` / `medium` 仍为样本级真实试运行。

## 前端启动命令

请在项目根目录执行以下命令启动 Streamlit 页面：

```bash
streamlit run web/streamlit_app.py
```

页面顶部会显示“仅用于研究与辅助决策，不构成投资建议”。无真实数据时，页面会使用演示数据或友好空状态，避免空白页面。

## 页面说明

- 今日选股：展示候选股票、分项得分、综合分、选择原因和风险提示，支持行业筛选、综合分排序和 CSV 导出。
- 个股详情：输入股票代码后展示基础信息、最近行情、近 20 日 / 60 日涨跌幅、成交额、换手率和因子得分。
- 因子排名：按交易日期和行业查看趋势、动量、流动性、基本面、波动风险和综合分排名。
- 策略回测：展示参数、净值曲线、核心指标、年度收益、交易记录和持仓记录。
- 数据更新状态：展示最新行情日期、最新因子日期、最新选股结果日期、核心表行数和最近任务状态。

## sample/mock 数据说明

`core/sample_data.py` 提供少量合成演示数据，覆盖：

- 股票基础信息；
- 日线行情；
- daily_basic；
- 因子评分；
- 选股结果；
- 回测结果。

所有 sample/mock 数据均标注为“演示数据”，只用于本地 smoke test 和页面结构展示，不代表真实行情、真实财务数据或任何投资观点。

## 当前 MVP 限制

- sample 数据规模很小，只用于验证流程能跑通。
- 默认只会在手动运行 `python -m core.jobs.update_real_data` 且配置 `TUSHARE_TOKEN` 后连接 Tushare。
- 当前真实数据接入只拉取少量样本股票，不接雪球，不做全市场长周期下载。
- AKShare 仅作为备用 / 低成本数据源，不覆盖 Tushare 主流程。
- 当前一键任务在无真实数据库结果时不写入 DuckDB，只输出演示摘要。
- Streamlit 页面第一版偏展示和 smoke 验证，不包含复杂交互和生产级数据刷新。
- 回测结果可展示 sample 结构，但不代表真实策略表现。
- 不包含自动下单、券商接口或任何交易执行功能。

## 后续开发建议

- 将真实数据更新任务、因子计算任务、选股任务和 DuckDB 结果保存串联成稳定流水线。
- 为 Streamlit 页面增加真实数据库读取和刷新状态展示。
- 增加更完整的数据校验、任务日志和异常恢复。
- 扩展回测参数配置和结果导出。
- 在接入真实数据前补充 token、数据授权和隐私保护说明。

## 风险声明

本项目输出的任何选股结果、评分结果和回测结果均不代表未来收益。用户需要自行判断市场风险、流动性风险、模型失效风险、数据质量风险和交易执行风险。

本项目仅用于研究与辅助决策，不构成投资建议。第一阶段不得自动下单。
