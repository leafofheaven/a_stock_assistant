# v0.1 本地日常使用版 Release Notes

发布时间：待用户合并后确认。

v0.1 是当前项目的阶段封版，定位为个人本地 A 股选股辅助工具，用于数据整理、因子观察、候选复核、观察池跟踪和本地复盘。仅供个人研究使用，不自动交易。

## 当前核心能力

- 真实数据更新：支持 Tushare / AKShare，AKShare 场景下具备东方财富 curl fallback。
- 基础信息补全：支持本地 preset fallback，补齐样本股票的名称、行业、市场和上市日期。
- PE/PB 估值补全：优先补齐最新交易日估值字段，供候选复核、观察池和日报使用。
- 因子评分：支持基础趋势、动量、流动性、波动和基本面评分，以及综合评分。
- 候选复核：导出候选复核报告、CSV 模板，并导入人工复核结果。
- 观察池：支持 watch / pass / exclude / needs_data 等人工状态，刷新评分并导出观察池报告。
- 观察池跟踪：保存 snapshot，导出价格、评分和估值变化报告。
- 一键日报：`run_daily_workflow` 串联更新、诊断、选股、候选复核、观察池和综合日报。
- 本地备份：支持 DuckDB 备份、备份列表、dry-run 恢复和 force 恢复。
- doctor 体检：检查 `.env`、DuckDB、核心表、`reports/.gitkeep`、备份、报告和误提交风险。

## 当前限制

- 仅用于个人本地研究和复盘，不面向公众发布。
- 不自动交易，不接券商，不生成自动下单指令。
- 不做全市场长周期下载，当前股票池仍是 sample / small / medium 试运行阶段。
- PE/PB 当前优先补最新交易日，全历史 `daily_basic` 估值字段可能为空。
- AKShare / 东方财富接口可能受网络环境影响，失败时需重试或改用本地数据模式。
- `adj_factor` 在 AKShare fallback 下可能简化为 `1.0`。
- 当前策略和因子为基础版本，不代表正式投资策略表现。

## 推荐日常命令

```bash
python -m core.jobs.doctor_daily_run --pre-run
python -m core.jobs.run_daily_workflow --doctor-before-run --backup-before-run --format all
python -m core.jobs.doctor_daily_run --post-run
```

只用本地数据、不更新：

```bash
python -m core.jobs.run_daily_workflow --doctor-before-run --skip-update --format all
```

## 推荐备份命令

```bash
python -m core.jobs.backup_local_data --label before_change
python -m core.jobs.list_backups
```

恢复前先 dry-run：

```bash
python -m core.jobs.restore_local_data --backup-dir backups/a_stock_backup_xxx --dry-run
```

确认后再 force：

```bash
python -m core.jobs.restore_local_data --backup-dir backups/a_stock_backup_xxx --force
```

## 推荐清理命令

```bash
python -m core.jobs.clean_generated_reports --force
```

或手动保留 `reports/.gitkeep`：

```bash
find reports -type f ! -name ".gitkeep" -delete
```

不要使用 `rm -rf reports`。

## 已知风险

- `.env`、`data/`、`backups/`、报告生成文件不应提交到 Git。
- 没有备份时，恢复和误删数据库的风险较高。
- 复制文档命令时不要把终端提示符一起粘进去。
- `partial_success` 通常表示某一步失败但报告已生成，应先看日报中的步骤摘要和 doctor 建议。

## 后续可选方向

- 扩大真实股票样本，但仍避免一次性全市场长周期下载。
- 增强估值字段历史补全。
- 增加更多数据质量可视化。
- 优化 Streamlit 页面交互和报告阅读体验。
- 合并后如需打版本标签，可由用户手动执行：

```bash
git tag v0.1
git push origin v0.1
```
