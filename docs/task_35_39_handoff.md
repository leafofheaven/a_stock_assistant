# Task 35-39 状态与交接说明

本页记录 Task 35 至 Task 39 的最终状态，方便日常使用和后续继续开发。当前范围只涉及参数设置、选股逻辑解释、运行进度展示、AKShare 基础信息兼容修复和检查脚本补充；没有修改选股公式、因子权重或候选排序。

## Task 35：简化参数设置流程

- Streamlit 的“参数设置 / 本地控制台”支持查看和修改常用 `.env` 参数。
- 支持自定义股票池和预设股票池切换。
- 支持修改开始日期、结束日期、样本规模和常用运行方式。
- 页面会显示“参数日期 vs 数据库日期”，用于判断是否需要更新真实数据。
- 三个按钮含义固定：
  - 保存参数：只保存 `.env`，不运行命令。
  - 保存并本地重算：保存 `.env`，只基于本地 DuckDB 重新生成报告。
  - 保存并更新数据：保存 `.env`，运行完整日常流程并更新真实行情。

## Task 36：选股逻辑说明页

- Streamlit 已提供“选股逻辑”页。
- 命令行可运行 `python -m core.jobs.explain_selection_logic`。
- 页面和命令会展示 `total_score` 公式、因子权重、候选排序原因、主要贡献因子和弱项。
- 解释层只读取当前本地评分结果，不改变选股结果。
- 详细说明见 [selection_logic.md](selection_logic.md)。

## Task 37：实时进度显示

- `core/runtime/progress.py` 提供统一进度行格式。
- `update_real_data` 和 `run_daily_workflow` 会输出稳定的 `[progress]` 行。
- Streamlit 本地控制台逐行显示命令输出，不再等命令结束后一次性显示。
- 页面会显示当前运行步骤、当前股票或子任务、成功/失败/跳过数量、实时日志和最终报告路径。

示例：

```text
[progress] step=update_real_data current=000001.SZ success=1 failed=0 skipped=0 message=...
```

看到这类日志表示任务正在运行，不是卡住。

## Task 38：AKShare 基础信息补全兼容修复

- AKShare `stock_individual_info_em` 返回结构不稳定时，不再依赖固定列数。
- 基础信息增强会先规范化为 `item` / `value` / `extra` 标准结构，再提取行业、市场、上市日期等字段。
- 兼容 2 列、3 列、语义列名和空 DataFrame。
- 如果 AKShare 增强字段不可用，会使用已有 `stock_basic` 字段和本地 preset fallback。
- 单只股票基础信息补全失败不影响主行情更新。
- 用户可见 warning 应保持简洁，例如“AKShare 基础增强字段缺失，已使用基础股票信息兜底。”。

## Task 39：检查项与交接文档补充

- `scripts/check_task.py` 增加 `task39`。
- `python scripts/check_task.py task39` 用于检查 Task 35-39 状态文档和关键说明是否存在。
- 检查重点包括：
  - Task 35-39 状态说明；
  - Chrome 本地控制台使用流程；
  - 保存参数 / 保存并本地重算 / 保存并更新数据；
  - 选股逻辑说明；
  - 实时进度 `[progress]`；
  - AKShare 基础增强字段缺失 warning 解释；
  - 不修改选股公式、因子权重和候选排序的边界说明。

## 当前日常使用流程

启动页面：

```bash
streamlit run web/streamlit_app.py
```

进入“参数设置 / 本地控制台”后：

1. 查看当前参数、数据源、股票池和日期。
2. 如需调整股票池或日期，先修改页面表单。
3. 只想保存设置时，点击“保存参数”。
4. 已有本地数据、只想重新生成候选和报告时，点击“保存并本地重算”。
5. 改了股票池或结束日期、需要拉取新行情时，点击“保存并更新数据”。
6. 运行时观察实时进度、日志、成功/失败/跳过数量和最终报告路径。
7. 运行后查看 `reports/daily_workflow_*.md`、候选复核报告和观察池报告。

常用完整命令：

```bash
python -m core.jobs.run_daily_workflow --doctor-before-run --backup-before-run --format all
```

只用本地 DuckDB、不更新行情：

```bash
python -m core.jobs.run_daily_workflow --doctor-before-run --skip-update --format all
```

单独更新真实数据：

```bash
python -m core.jobs.update_real_data
```

## 常见 warning 解释

### AKShare 基础增强字段缺失

含义：AKShare 基础信息接口返回结构或字段不完整，系统已使用基础股票信息或本地 preset 兜底。

影响：不影响 `daily_price`、`daily_basic`、选股、候选复核和观察池主流程。可用 `python -m core.jobs.diagnose_data_quality` 查看行业、市场和上市日期完整率。

### 估值补全接口不可用

含义：当前 AKShare 版本或网络环境下，某些 PE/PB 补全接口不可用。

影响：PE/PB 可能为空。日报优先看最新交易日完整率；如果当前候选和观察池已有 PE/PB，不需要因为全历史完整率低而误判当前数据缺失。

### 自定义股票池覆盖预设股票池

含义：`AKSHARE_SAMPLE_SYMBOLS` 不为空时，它优先于 `REAL_UNIVERSE_PRESET`。

处理：想使用 small / medium 预设时，在页面中选择“使用预设股票池”，或手动清空 `.env` 中的 `AKSHARE_SAMPLE_SYMBOLS`。

### 参数日期与数据库日期不一致

含义：`.env` 中目标日期已变，但本地 DuckDB 还没有对应日期的数据。

处理：点击“保存并更新数据”，或运行 `python -m core.jobs.update_real_data`。

## 边界

- 当前功能仍是个人本地 A 股选股辅助工具。
- 仅供个人研究使用，不自动交易。
- 不接券商，不自动下单。
- 不修改选股公式、不修改因子权重、不改变候选排序。
- 不提交 `reports/`、`data/`、`backups/`、`.env`、DuckDB 或本地运行生成文件。
