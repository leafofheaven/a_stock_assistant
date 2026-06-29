# 持仓池

持仓池用于手工记录已经实际持有的股票，方便在本地页面和报告中查看持仓状态。它只做记录和基础展示，不接券商、不自动交易，也不生成自动卖出规则。

## 字段

每条持仓记录包含：

- `ts_code`
- `name`
- `entry_date`
- `entry_price`
- `quantity`
- `entry_reason`
- `source`：`selection` / `watchlist` / `elder_review` / `manual`
- `entry_total_score`
- `entry_elder_score`
- `initial_stop`
- `plan`
- `status`：`active` / `reduced` / `exited`

状态取值固定为 `active / reduced / exited`，分别用于当前仍在持仓、已减仓记录、已退出记录。
- `created_at`
- `updated_at`

同一 `ts_code` 已存在 active 持仓时，不会重复创建，会提示已存在 active position。

## 导入

先复制模板：

```bash
cp docs/templates/positions_import_template.csv /tmp/positions.csv
```

填写后导入：

```bash
python -m core.jobs.import_positions --file /tmp/positions.csv
```

只校验不写入：

```bash
python -m core.jobs.import_positions --file /tmp/positions.csv --dry-run
```

## 导出

```bash
python -m core.jobs.export_positions
python -m core.jobs.export_positions --format markdown
python -m core.jobs.export_positions --format csv
```

导出报告会写入 `reports/positions_*.md`、`reports/positions_*.csv`、`reports/positions_*.json`。这些是本地生成文件，不应提交到 Git。

## 页面

启动：

```bash
streamlit run web/streamlit_app.py
```

进入“持仓池”标签页，可查看：

- 股票代码；
- 股票名称；
- 买入日期；
- 买入价；
- 最新收盘价；
- 当前盈亏百分比；
- 持仓天数；
- 来源；
- 买入理由；
- 状态。

如果本地行情不足，最新收盘价和盈亏会显示数据不足，不会阻断页面。

## 限制

- 当前只建立持仓池基础框架。
- 不实现复杂卖出复核规则。
- 不接券商。
- 不自动交易。
- 仅供个人研究使用，不自动交易。
