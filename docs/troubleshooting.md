# 常见问题排查

所有命令默认先执行：

```bash
cd /Users/wanghao/Documents/股票
source .venv/bin/activate
```

## .env 不存在

现象：配置读取不到预期数据源。

原因：还没有复制示例配置。

检查命令：

```bash
ls -la .env .env.example
```

处理命令：

```bash
cp .env.example .env
```

## DATA_PROVIDER 仍然是 tushare

现象：想用 AKShare，但命令输出 `DATA_PROVIDER: tushare`。

原因：`.env` 未修改或终端环境变量覆盖了 `.env`。

检查命令：

```bash
python -m core.jobs.diagnose_local_state
```

处理命令：编辑 `.env`，设置：

```env
DATA_PROVIDER=akshare
```

## TUSHARE_TOKEN 为空

现象：Tushare 更新无法进行。

原因：没有填写 token。

检查命令：

```bash
python -m core.jobs.update_real_data
```

处理命令：如暂时不使用 Tushare，改用：

```env
DATA_PROVIDER=akshare
```

## AKShare 请求失败

现象：`update_real_data` 输出 AKShare 请求失败。

原因：AKShare 或底层东方财富请求在当前网络环境失败。

检查命令：

```bash
python -m core.jobs.update_real_data
python -m core.jobs.diagnose_real_data
```

处理命令：保持小样本，稍后重试：

```env
AKSHARE_SAMPLE_SYMBOLS=000001,600000,000002
```

## 东方财富接口走代理失败

现象：Python requests 失败，但系统 curl 可能可用。

原因：本地代理或网络栈差异。

检查命令：

```bash
python -m core.jobs.update_real_data
```

处理命令：项目会在 AKShare 失败时尝试系统 curl fallback；仍失败时先检查网络和代理。

## Clash Verge 代理问题

现象：接口连接异常、超时或 RemoteDisconnected。

原因：代理规则影响 Python 请求。

检查命令：

```bash
python -m core.jobs.update_real_data
```

处理命令：临时调整代理规则后重试，或只运行本地诊断：

```bash
python -m core.jobs.run_real_workflow --skip-update
```

## daily_price 为 0

现象：诊断显示 `daily_price 行数: 0`。

原因：真实数据更新未成功或样本股票无数据。

检查命令：

```bash
python -m core.jobs.diagnose_real_data
python -m core.jobs.diagnose_update_batch
```

处理命令：

```bash
python -m core.jobs.update_real_data
```

## run_daily_selection 回退 sample

现象：输出显示回退 sample。

原因：真实数据不足、字段缺失或股票池为空。

检查命令：

```bash
python -m core.jobs.diagnose_real_data
python -m core.jobs.diagnose_factors
python -m core.jobs.diagnose_data_quality
```

处理命令：先补真实数据，再运行：

```bash
python -m core.jobs.update_real_data
python -m core.jobs.run_daily_selection
```

## 股票池过滤为空

现象：股票池数量为 0。

原因：样本太少、数据日期不匹配、成交额或停牌过滤导致全部排除。

检查命令：

```bash
python -m core.jobs.diagnose_factors
```

处理命令：扩大小样本：

```env
AKSHARE_SAMPLE_SYMBOLS=
REAL_UNIVERSE_PRESET=small
```

## pe/pb 为空

现象：基本面分项为空或偏低。

原因：AKShare fallback 不保证 PE/PB 字段完整；补全接口失败或样本股票缺少估值记录时也会为空。

检查命令：

```bash
python -m core.jobs.diagnose_data_quality
python -m core.jobs.diagnose_factors
```

处理命令：确认 `.env` 中开启补全后重新更新数据：

```env
ENABLE_REAL_BASIC_ENRICHMENT=true
ENABLE_REAL_VALUATION_ENRICHMENT=true
```

```bash
python -m core.jobs.update_real_data
```

如果仍为空，这是当前 AKShare 小范围验证的已知限制，流程不会因此崩溃。

## fundamental_score 为空

现象：因子诊断中 `fundamental_score` 非空率为 0。

原因：通常是 `daily_basic` 缺失，或 `pe` / `pb` 缺失。

检查命令：

```bash
python -m core.jobs.diagnose_data_quality
python -m core.jobs.diagnose_factors
```

处理命令：先补数据；仍缺失时按数据质量提示人工复核，不影响其他分项和总流程。

## total_score=None

现象：观察池里显示无综合评分。

原因：本地没有持久化评分表，或该股票当前评分不可用。

检查命令：

```bash
python -m core.jobs.diagnose_factors
python -m core.jobs.diagnose_watchlist
```

处理命令：

```bash
python -m core.jobs.run_daily_selection
python -m core.jobs.track_watchlist
```

## reports/ 或 backups/ 出现在 git status

现象：`git status` 显示运行生成文件。

原因：忽略规则异常或文件已被跟踪。

检查命令：

```bash
git status --short
git status --ignored --short reports data backups .env
```

处理命令：不要提交这些目录；确认 `.gitignore` 包含相关规则。

## 误把占位符命令粘进终端

现象：`reports/review_template_xxx.csv` 或 `backups/a_stock_backup_xxx` 找不到。

原因：`xxx` 是占位符。

检查命令：

```bash
ls reports
python -m core.jobs.list_backups
```

处理命令：替换成真实文件名或真实备份目录。

## GitHub 没有可合并 PR

现象：GitHub 无法创建或合并 PR。

原因：分支未推送、base 不对或检查未通过。

检查命令：

```bash
git status --short --branch
git branch --show-current
```

处理命令：确认当前 Task 分支已 push。

## Codex 改完但没有 commit

现象：本地有改动但 GitHub 看不到。

原因：未提交或未推送。

检查命令：

```bash
git status --short
```

处理命令：等待当前 Task 完成后由 Codex 提交和推送。

## 分支错乱

现象：在错误分支上运行或改动。

原因：没有从最新 `origin/main` 创建 Task 分支。

检查命令：

```bash
git branch --show-current
git status --short --branch
```

处理命令：先不要继续改动，确认当前 Task 分支。

## Numbers 保存 CSV 的问题

现象：导入复核模板时报字段缺失或乱码。

原因：Numbers 可能改列名、编码或保存格式。

检查命令：

```bash
python -m core.jobs.import_review_decisions --file reports/review_template_xxx.csv --dry-run
```

处理命令：保持原列名，导出 CSV 后先 dry-run。

## restore_local_data 没有 --force 不会恢复

现象：恢复命令执行后数据库没变。

原因：恢复默认 dry-run，不覆盖当前数据库。

检查命令：

```bash
python -m core.jobs.restore_local_data --backup-dir backups/a_stock_backup_xxx --dry-run
```

处理命令：

```bash
python -m core.jobs.restore_local_data --backup-dir backups/a_stock_backup_xxx --force
```
