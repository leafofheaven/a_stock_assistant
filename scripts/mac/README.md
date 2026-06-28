# Mac 本地启动器

`A股选股助手.command` 是一个轻量双击启动器，用来打开本地 Streamlit 控制台。它不是完整原生 Swift App，不是菜单栏常驻 App，不会自动后台更新，也不是 dmg 安装包。

## 第一次设置

在项目根目录运行：

```bash
chmod +x scripts/mac/A股选股助手.command
```

如果项目路径不是 `/Users/wanghao/Documents/股票`，先编辑 `.command` 文件里的 `PROJECT_DIR`。

## 双击运行

1. 双击 `scripts/mac/A股选股助手.command`；
2. 脚本会进入项目目录并激活 `.venv`；
3. 自动打开 `http://localhost:8501`；
4. 启动 `streamlit run web/streamlit_app.py`；
5. 在 Chrome 中进入“参数设置 / 本地控制台”。

## 参数设置页怎么用

- 自定义股票池：输入 `000001,600000,002475`，保存后系统只更新这些代码。
- 预设股票池：选择 `small` 或 `medium`，保存时会清空 `AKSHARE_SAMPLE_SYMBOLS`。
- 保存参数：只保存 `.env`。
- 保存并本地重算：不联网，只用本地已有数据重新生成报告。
- 保存并更新数据：联网更新真实行情，适合修改股票池或结束日期后使用。

如果页面提示“参数结束日期”晚于“数据库最新行情日期”，需要点击“保存并更新数据”。

## 复制到桌面

可以把 `.command` 文件复制到桌面：

```bash
cp scripts/mac/A股选股助手.command ~/Desktop/
chmod +x ~/Desktop/A股选股助手.command
```

## macOS 提示无法打开

如果 macOS 阻止打开，可右键文件，选择“打开”，再确认运行。也可以在“系统设置 > 隐私与安全性”中允许本次打开。

## 说明

- 数据仍保存在本地 DuckDB 和 `.env`。
- 页面只执行白名单命令，不接券商，不自动交易。
- 清理报告请使用页面按钮或 `python -m core.jobs.clean_generated_reports --force`，不要删除 `reports/.gitkeep`。
