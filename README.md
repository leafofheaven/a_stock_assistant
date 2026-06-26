# a_stock_assistant

A 股选股投资辅助软件，用于本地化的数据整理、因子研究、选股评分、策略回测和结果展示。

本项目仅用于投资研究与辅助决策，不提供自动交易能力，也不构成投资建议。

## 安装方式

建议使用 Python 3.12。

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .[dev]
```

如果只验证项目骨架，也可以执行：

```bash
pip install -e .
```

## 环境变量配置

复制示例配置：

```bash
cp .env.example .env
```

根据需要填写 Tushare token、数据目录和日志等级。

## 如何更新数据

后续任务会实现真实数据更新逻辑。目标命令为：

```bash
python -m core.jobs.update_daily_data
```

## 如何运行选股

后续任务会实现完整选股流程。目标命令为：

```bash
python -m core.jobs.run_daily_selection
```

## 如何启动页面

后续任务会实现 Streamlit 页面。目标命令为：

```bash
streamlit run web/streamlit_app.py
```

## 如何运行测试

```bash
python -m pytest
```

## 如何运行质量检查

运行项目级检查：

```bash
python scripts/check_project.py
```

运行指定任务检查，例如 Task 4：

```bash
python scripts/check_task.py task4
```

## 当前限制

- 当前仅完成 Task 1 项目骨架。
- 暂未实现配置读取、数据源调用、DuckDB 存储、因子计算、选股策略、回测引擎和页面展示。
- 测试不访问真实外部 API。
- 不包含任何自动下单或券商交易接口。

## 风险声明

本项目输出的任何选股结果、评分结果和回测结果均不代表未来收益。用户需要自行判断市场风险、流动性风险、模型失效风险和交易执行风险。
