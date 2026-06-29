# 沪深 A 股全市场股票池

本项目支持两类真实数据股票池：

- `mini / small / medium`：样本池，用于低成本验证真实数据链路。
- `full`：沪深 A 股全市场，不含北交所。

`full` 模式覆盖上交所主板、深交所主板、创业板、科创板；默认不覆盖北交所 / BSE / BJ，也不纳入 8 开头、4 开头等北交所股票。

## 配置

使用 full 模式前，建议确认 `.env`：

```bash
DATA_PROVIDER=akshare
AKSHARE_SAMPLE_SYMBOLS=
REAL_UNIVERSE_PRESET=full
INCLUDE_BSE=false
MIN_LISTING_DAYS=120
MIN_AVG_AMOUNT_20D=100000000
MIN_MEDIAN_AMOUNT_20D=50000000
MIN_LATEST_AMOUNT=30000000
MIN_TRADED_DAYS_20D=18
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

优先级规则：

- 如果 `AKSHARE_SAMPLE_SYMBOLS` 不为空，系统优先使用自定义股票池，`REAL_UNIVERSE_PRESET=full` 不生效。
- 如果 `AKSHARE_SAMPLE_SYMBOLS` 为空，且 `REAL_UNIVERSE_PRESET=full`，系统会从 AKShare 获取沪深 A 股基础列表。

## 可交易过滤

full 模式获取股票基础列表后，会先剔除：

- ST / `*ST`；
- 退市整理、退市、明显异常名称；
- 北交所股票。

随后根据本地行情重新计算可交易状态：

- 上市时间不少于 `MIN_LISTING_DAYS`，默认 120 天；
- 近 20 日有效成交天数 `traded_days_20d >= 18`；
- 近 20 日平均成交额 `avg_amount_20d >= 100000000`；
- 近 20 日成交额中位数 `median_amount_20d >= 50000000`；
- 最新成交额 `latest_amount >= 30000000`。

停牌股票不是永久剔除。每次数据更新和过滤时都会重新计算，复牌后如果重新满足成交连续性和流动性规则，会重新纳入可交易股票池。

## 日常命令

```bash
python -m core.jobs.update_real_data
python -m core.jobs.diagnose_update_batch
python -m core.jobs.run_daily_workflow --doctor-before-run --skip-update --format all
streamlit run web/streamlit_app.py --server.port 8501
```

页面中的“参数设置 / 本地控制台”也可以选择 `full`。点击“保存并更新数据”后，仍沿用现有实时进度显示：当前批次、成功数、失败数、跳过数和实时日志都会逐步展示。

## full 模式更新稳定性

Task 47 后，`REAL_UNIVERSE_PRESET=full` 的数据更新按批次执行，适合沪深 A 股全市场较大的股票池：

- `FULL_UPDATE_BATCH_SIZE`：full 模式每批处理股票数，默认 50；
- `FULL_UPDATE_LOOKBACK_DAYS`：full 模式默认只更新最近窗口，默认 250 天；
- `FULL_UPDATE_MAX_RETRIES`：单批失败后的最大重试次数，默认 2；
- `FULL_UPDATE_SLEEP_SECONDS`：批次之间的限速间隔；
- `FULL_UPDATE_RESUME=true`：断点续跑，已有目标结束日期行情的股票会跳过。
- `FULL_UPDATE_MAX_SYMBOLS`：本次最多处理股票数，默认 0 表示不限制，适合真实小批量验收；
- `FULL_UPDATE_MAX_BATCHES`：本次最多处理批次数，默认 0 表示不限制；
- `ENABLE_STOCK_BASIC_ENRICHMENT=false`：默认不逐只调用 AKShare `stock_individual_info_em` 做基础增强；
- `FULL_ENABLE_STOCK_BASIC_ENRICHMENT=false`：full 模式默认关闭逐只基础增强，避免 4987 只股票在增强阶段阻塞行情更新。
- `ENABLE_VALUATION_ENRICHMENT=false`：默认不调用额外估值快照接口做 PE/PB 网络增强；
- `FULL_ENABLE_VALUATION_ENRICHMENT=false`：full 模式默认关闭 `stock_a_lg_indicator`、`stock_zh_a_spot_em` 等额外估值增强，避免 daily_basic 阶段阻塞行情更新。

全市场更新可能耗时较长。终端和 Streamlit 页面会显示当前批次、当前股票、成功数、失败数、跳过数和剩余数量。单只或单批股票失败不会中断整个任务，失败股票会进入最终摘要。

full 模式会直接使用 AKShare 基础股票列表中的 `ts_code`、`symbol`、`name`、`market`、`exchange` 等基础字段进入行情更新队列。逐只基础增强只是可选增强，不影响 `daily_price`、`daily_basic`、`adj_factor` 更新。

full 模式的基础股票池解析优先使用专用沪深 A 股列表请求，本地 DuckDB `stock_basic` 只补充字段，不决定 full universe 边界；专用列表失败时才回退本地缓存并给出 warning。该路径不调用 AKShare `stock_info_a_code_name`，避免其内部请求北交所 `stock_info_bj_name_code` 导致 full 更新在 stock_basic 阶段阻塞。`INCLUDE_BSE=false` 时不会纳入北交所。

full 模式下 `daily_basic` 会优先写入可稳定取得的基础字段，例如 `turnover_rate`。PE/PB、总市值、流通市值等估值字段允许为空；这不会阻断 `daily_price`、`daily_basic`、`adj_factor` 主行情更新。需要小范围验证估值补全时，可以手动打开 `FULL_ENABLE_VALUATION_ENRICHMENT=true`，但不建议在 full 首次补库时开启。

续跑建议：

```bash
python -m core.jobs.update_real_data
python -m core.jobs.diagnose_update_batch
```

`diagnose_update_batch` 会区分基础股票池数量、已有行情数量、缺行情数量、最新行情不足数量和可运行选股数量。已有行情不足的股票会在下次更新中继续尝试补齐。

小批量真实验收可以临时指定：

```bash
FULL_UPDATE_BATCH_SIZE=20 FULL_UPDATE_MAX_SYMBOLS=20 FULL_UPDATE_MAX_RETRIES=1 FULL_UPDATE_LOOKBACK_DAYS=250 python -m core.jobs.update_real_data
python -m core.jobs.diagnose_update_batch
```

初始补库会优先处理完全没有 `daily_price` 的股票；已有行情但最新不足的股票排在后面。这样小批量验收后，已有行情股票数量应增加，缺数据股票数量应减少。

日志中有三个不同口径：

- `full 基础股票池数量`：完整沪深 A 股 full universe 数量，通常约 4987，只受基础列表和 ST / 退市 / 北交所过滤影响；
- `待处理队列`：缺数据股票和最新行情不足股票组成的续跑队列；
- `本次计划处理`：受 `FULL_UPDATE_MAX_SYMBOLS` 或 `FULL_UPDATE_MAX_BATCHES` 限制后的实际处理数量。

`FULL_UPDATE_MAX_SYMBOLS=20` 只限制“本次计划处理”，不会改变 full 基础股票池数量。

## 限制

- full 模式第一版只做沪深 A 股，不含北交所。
- 首次运行需要下载更多股票，耗时会明显高于样本池。
- 默认不追求全量长历史下载，full 模式优先更新最近窗口。
- 过滤结果只用于个人本地研究和候选生成，不自动交易。
