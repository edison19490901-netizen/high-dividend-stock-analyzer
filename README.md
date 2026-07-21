# 📊 High Dividend × High Value × Low Price

A股高股息率蓝筹股 & ETF 批量量化分析工具。

一键完成：高股息筛选 → 多周期统计分析 → 临界买点计算 → Excel 报告 + HTML 看板。

---

## ✨ 功能

- 🔍 **高股息筛选** — 遍历 60+ 只高股息候选股，自动计算股息率并筛选（Baostock，免费）
- 📈 **个股深度分析** — 近 1/2/3 年日线统计（均值、标准差、分位数、价格分布密度图）
- 📊 **ETF 分析** — 近 3 年净值数据统计（efinance，免费）
- 🎯 **临界买点** — `最低价 × (1.15 + 波动率调整)`，多周期独立计算
- 📋 **Excel 报告** — 每只标的独立 Excel（原始数据 + 统计指标 + 密度图 + 投资建议）
- 🌐 **HTML 看板** — 深色主题交互式仪表盘，搜索/筛选/标签切换

## 📸 看板预览

```
┌──────────────────────────────────────────────┐
│  📊 高股息 + 高价值 + 低价格 分析看板          │
│  📅 数据日期: 2026-07-20 | 生成于 ...          │
├────────┬────────┬────────┬──────────────────┤
│ 18 个股 │ 4 买入 │ 17 ETF │ 3 买入           │
├────────┴────────┴────────┴──────────────────┤
│ 🎯 买入信号                                  │
│ ┌──────────────────────────────────────┐     │
│ │ 海尔智家  低于 0.78 元                 │     │
│ │ 中国移动  低于 3.25 元                 │     │
│ │ ...                                   │     │
│ └──────────────────────────────────────┘     │
│ 📋 [个股(18)] [ETF(17)]  🔍 搜索...          │
│ # │ 名称    │ 最新价 │ 均价 │ 临界点 │ 位置  │
│ 1 │ 格力电器 │ 40.58  │40.26 │ 35.42  │ 高于  │
│ 2 │ 海尔智家 │ 21.46  │25.26 │ 22.24  │🟢低于 │
│ ...                                          │
└──────────────────────────────────────────────┘
```

## 🚀 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 配置 Tushare Token

```bash
cp .env.example .env
# 编辑 .env，填入 Tushare Token（注册地址: https://tushare.pro）
```

> **注意**: 仅个股日线需要 Tushare（免费账户即可）。ETF 和分红筛选使用 Baostock/efinance，无需额外配置。

### 3. 运行

```bash
# 一键执行全部
python run_all.py

# 或分步执行
python screener_baostock.py          # 高股息筛选
python batch_analysis.py --mode all  # 批量分析个股+ETF
python intraday_analysis.py --code 003816.SZ --name 中国广核  # 分时分析

# 生成 HTML 看板
python generate_dashboard.py
```

## 📁 项目结构

```
├── run_all.py                  # 一键入口
├── config.py                   # 全局配置（从 .env 加载）
├── targets.py                  # 分析标的列表（个股 + ETF）
├── generate_dashboard.py       # HTML 看板生成器
├── requirements.txt            # Python 依赖
├── .env.example                # 配置模板
│
├── batch_analysis.py           # 统一批量分析引擎（个股 + ETF）
├── screener_baostock.py        # 高股息筛选器（Baostock）
├── screener.py                 # 高股息筛选器（Tushare，备选）
├── intraday_analysis.py        # 分时数据分析
│
├── common/                     # 公共模块
│   ├── __init__.py             # 日志、字体检测
│   ├── data_fetcher.py         # 数据获取层（Tushare + 缓存）
│   ├── baostock_source.py      # Baostock 数据源
│   ├── efinance_source.py      # efinance ETF 数据源
│   ├── statistics.py           # 统计指标 + 临界买点
│   ├── chart_utils.py          # 密度图生成
│   └── excel_writer.py         # Excel 报告构建器
│
└── output/                     # 输出目录（gitignore）
    ├── dashboard.html          # HTML 看板
    ├── company_batch_analysis/ # 个股 Excel 报告
    ├── ETF_batch_analysis/     # ETF Excel 报告
    └── company/                # 分时分析报告
```

## 📊 数据源

| 数据 | 来源 | 覆盖 | 说明 |
|---|---|---|---|
| 个股日线 | Tushare `pro.daily()` | 近 3 年 | 需 token（免费） |
| ETF 净值 | efinance `fund` API | 近 3 年 | 免费，无需配置 |
| 分红数据 | Baostock | 2024-2025 | 免费，无需配置 |
| 分时数据 | Baostock 5 分钟线 | 近 10 日 | 免费，无需配置 |

> ETF 使用净值（NAV）代替收盘价。对于 ETF 估值分析，净值与市价误差通常 <1%。

## 🔧 自定义

### 新增分析标的

编辑 `targets.py`:

```python
STOCK_TARGETS = [
    {"code": "000651.SZ", "name": "格力电器"},
    {"code": "600900.SH", "name": "长江电力"},
    # 添加更多...
]

ETF_TARGETS = [
    {"code": "159928.SZ", "name": "中证消费ETF"},
    # 添加更多...
]
```

### 调整分析参数

编辑 `.env`:

```bash
DIVIDEND_THRESHOLD=5      # 股息率阈值 (%)
MIN_MARKET_CAP=500         # 最低市值 (亿)
CRITICAL_BUY_PREMIUM=1.15  # 临界买点溢价系数
```

### 新增高股息候选池

编辑 `screener_baostock.py` 中的 `HIGH_DIV_SECTORS` 列表。

## ⚠️ 免责声明

本工具仅供学习和研究使用，**不构成投资建议**。所有分析结果基于历史数据，过往表现不代表未来收益。投资有风险，入市需谨慎。

## 📄 License

MIT
