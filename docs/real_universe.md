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

## 限制

- full 模式第一版只做沪深 A 股，不含北交所。
- 首次运行需要下载更多股票，耗时会明显高于样本池。
- 第一版不追求全量长历史下载，建议保持较短日期区间或最近窗口。
- 过滤结果只用于个人本地研究和候选生成，不自动交易。
