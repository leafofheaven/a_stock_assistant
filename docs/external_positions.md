# 外部模拟持仓导入与交易计划匹配

本功能用于把同花顺、雪球模拟组合或其他工具手工导出的 CSV 持仓 / 交易记录导入本地 DuckDB，再与本项目已经计算出的买入区间、止损位、目标价位和观察池状态做匹配。它只读取用户提供的本地 CSV 文件，不登录外部平台，不读取 cookie，不接券商，不自动交易。

## 生成模板

```bash
python -m core.jobs.generate_external_position_template
```

默认生成：

- `reports/templates/external_trades_template.csv`
- `reports/templates/external_position_snapshots_template.csv`

这两个文件就是外部模拟持仓的导入模板。

模板字段可以映射外部模拟平台导出的常见列。股票代码支持 `000725`、`000725.SZ`、`603986`、`603986.SH` 等格式；北交所 / BSE / BJ 代码默认不导入。

## 导入交易记录

```bash
python -m core.jobs.import_external_trades --file path/to/external_trades.csv
```

交易记录会写入 `external_trades`。重复导入同一条记录会按稳定 ID 更新，不重复新增。

## 导入持仓快照

```bash
python -m core.jobs.import_external_positions --file path/to/external_position_snapshots.csv
```

持仓快照会写入 `external_position_snapshots`，并自动匹配：

- 股票基础信息；
- 最新本地行情；
- `entry_zone_snapshots` 中的买入区间、止损位、目标价位；
- 观察池记录。

如果外部 CSV 中 `current_price` 为空，系统会尝试用本地最新收盘价补齐。无法识别的股票会保留记录，并在 `match_note` 中标记 `unknown_symbol`。

## 重新匹配

```bash
python -m core.jobs.match_external_positions
```

当重新计算了买入区间或更新了观察池后，可以运行该命令刷新外部模拟持仓的匹配结果。

## 诊断与导出

```bash
python -m core.jobs.diagnose_external_positions
python -m core.jobs.export_external_position_report --format all
```

诊断会输出平台数量、账户数量、持仓数量、总市值、总盈亏、接近止损、跌破止损、达到目标价、成本高于买入区间、数据不足等数量。

导出报告会生成 Markdown / JSON / CSV，内容包括：

- 当前模拟持仓；
- 成本价、当前价、盈亏；
- 买入区间、止损位、目标价位；
- 风险状态；
- 匹配说明。

## 风险状态

- `entered_in_zone`：成本价位于参考买入区间；
- `near_stop_loss`：当前价距离止损位较近；
- `hit_stop_loss`：当前价已低于或等于止损位；
- `hit_target`：当前价已达到或超过目标价位；
- `chased_high`：成本价高于买入区间且追高风险较高；
- `insufficient_data`：缺少买入区间或当前价等必要数据；
- `normal`：正常跟踪。

这些状态只用于个人研究和复盘，不是自动交易指令。

## Streamlit 页面

Streamlit 中的“外部模拟持仓导入”页面支持：

- 下载交易记录模板；
- 下载持仓快照模板；
- 预览上传或粘贴的 CSV / TSV；
- 查看最新持仓快照的匹配结果。

正式写入仍建议使用命令行导入，避免页面启动时执行写入任务。

## 一键验收

```bash
python scripts/verify_task.py task50
```

该命令串行执行测试、项目检查、Task 50 检查、模板生成、外部持仓诊断、外部持仓报告导出和日常工作流重算，避免并发访问同一个 DuckDB 文件。
