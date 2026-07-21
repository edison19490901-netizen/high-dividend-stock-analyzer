"""
生成 HTML 看板 — 从 Excel 汇总数据渲染交互式仪表盘。
"""

import json
import os
from datetime import datetime
from pathlib import Path

import pandas as pd


def find_latest_summary(directory: str) -> str | None:
    """找到最新的汇总 Excel（跳过锁文件）。"""
    if not os.path.exists(directory):
        return None
    files = sorted(
        [f for f in os.listdir(directory)
         if "汇总" in f and f.endswith(".xlsx") and not f.startswith("~$")],
        reverse=True,
    )
    return os.path.join(directory, files[0]) if files else None


def load_data():
    """加载所有分析数据。"""
    base = Path("output")

    stock_summary = find_latest_summary(str(base / "company_batch_analysis"))
    etf_summary = find_latest_summary(str(base / "ETF_batch_analysis"))

    stocks = []
    etfs = []

    if stock_summary:
        df = pd.read_excel(stock_summary, sheet_name="汇总统计")
        stocks = df.to_dict(orient="records")
        # 也加载投资建议
        try:
            df_advice = pd.read_excel(stock_summary, sheet_name="投资建议汇总")
            advice_map = {}
            for _, row in df_advice.iterrows():
                advice_map[row["名称"]] = {
                    "position": row.get("相对位置", ""),
                    "advice": row.get("投资建议", ""),
                    "diff": row.get("价格差异", 0),
                }
            for s in stocks:
                name = s.get("名称", "")
                if name in advice_map:
                    s["position"] = advice_map[name]["position"]
                    s["advice"] = advice_map[name]["advice"]
                    s["diff_to_crit"] = advice_map[name]["diff"]
        except Exception:
            pass

    if etf_summary:
        df = pd.read_excel(etf_summary, sheet_name="汇总统计")
        etfs = df.to_dict(orient="records")
        try:
            df_advice = pd.read_excel(etf_summary, sheet_name="投资建议汇总")
            advice_map = {}
            for _, row in df_advice.iterrows():
                advice_map[row["名称"]] = {
                    "position": row.get("相对位置", ""),
                    "advice": row.get("投资建议", ""),
                    "diff": row.get("价格差异", 0),
                }
            for e in etfs:
                name = e.get("名称", "")
                if name in advice_map:
                    e["position"] = advice_map[name]["position"]
                    e["advice"] = advice_map[name]["advice"]
                    e["diff_to_crit"] = advice_map[name]["diff"]
        except Exception:
            pass

    # 按低估→高估排序：
    #   低于临界买点的在前（gap 越大的越低估，排最前）
    #   高于临界买点的在后（gap 越小的越接近买点）
    def sort_key(item):
        position = str(item.get("position", "高于"))
        diff = _safe_float(item.get("diff_to_crit", 0))
        if position == "低于":
            # 低于临界: gap 越大越低估 → 负值大的排前
            return (-diff - 100000, "")
        else:
            # 高于临界: gap 越小越接近买点 → 正值小的排前
            return (diff, "")
    for lst in [stocks, etfs]:
        lst.sort(key=sort_key)

    # 计算摘要
    stock_below = [s for s in stocks if s.get("position") == "低于"]
    etf_below = [e for e in etfs if e.get("position") == "低于"]

    return {
        "stocks": stocks,
        "etfs": etfs,
        "stock_count": len(stocks),
        "etf_count": len(etfs),
        "stock_below": stock_below,
        "etf_below": etf_below,
        "stock_below_count": len(stock_below),
        "etf_below_count": len(etf_below),
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "data_date": stocks[0].get("最新日期", "") if stocks else "",
    }


def _safe_float(v, default=0) -> float:
    try:
        return float(v)
    except (ValueError, TypeError):
        return default


def _badge_class(position: str) -> str:
    return "badge-low" if position == "低于" else "badge-high"


def _row_class(position: str) -> str:
    return "row-buy" if position == "低于" else ""


def render_dashboard(data: dict) -> str:
    """渲染完整的 HTML 看板。"""
    stocks_json = json.dumps(data["stocks"], ensure_ascii=False, default=str)
    etfs_json = json.dumps(data["etfs"], ensure_ascii=False, default=str)

    # 构建表格行
    def stock_rows(items: list, is_etf: bool = False) -> str:
        if not items:
            return '<tr><td colspan="9" style="text-align:center;color:#888;">暂无数据</td></tr>'
        rows_html = []
        for i, item in enumerate(items):
            name = item.get("名称", "")
            code = item.get("代码", "")
            latest = _safe_float(item.get("最新价"))
            avg = _safe_float(item.get("均价"))
            low = _safe_float(item.get("最低价"))
            crit = _safe_float(item.get("临界买点"))
            premium = item.get("溢价%", 0)
            pct = _safe_float(item.get("价差%"))
            days = item.get("交易天数", 0)
            position = item.get("position", "高于")
            diff = _safe_float(item.get("diff_to_crit"))

            badge = f'<span class="{_badge_class(position)}">{position}</span>'
            pct_class = "pct-pos" if pct >= 0 else "pct-neg"
            pct_sign = "+" if pct >= 0 else ""

            # 进度条：当前价 vs 临界买点
            if crit > 0:
                bar_pct = min(100, max(0, (latest - low) / (crit - low) * 100 if crit > low else 50))
            else:
                bar_pct = 50

            rows_html.append(f"""
            <tr class="{_row_class(position)}" onclick="highlightRow(this)">
                <td>{i + 1}</td>
                <td class="name-cell" title="{code}">{name}<span class="code-sub">{code}</span></td>
                <td class="num">{latest:.2f}</td>
                <td class="num">{avg:.2f}</td>
                <td class="num">{crit:.2f}</td>
                <td class="num">{pct_sign}{pct:.1f}%</td>
                <td class="num">{diff:+.2f}</td>
                <td>{badge}</td>
                <td>
                    <div class="mini-bar">
                        <div class="mini-bar-fill" style="width:{bar_pct}%;background:{'#22c55e' if position == '低于' else '#ef4444'}"></div>
                    </div>
                </td>
            </tr>""")
        return "\n".join(rows_html)

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="theme-color" content="#0f172a">
<title>高股息 + 高价值 + 低价格 分析看板</title>
<style>
:root {{
    --bg: #0f172a;
    --card: #1e293b;
    --border: #334155;
    --text: #e2e8f0;
    --text-secondary: #94a3b8;
    --green: #22c55e;
    --red: #ef4444;
    --yellow: #eab308;
    --blue: #3b82f6;
    --purple: #a855f7;
}}
* {{ margin:0; padding:0; box-sizing:border-box; }}
body {{
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif;
    background: var(--bg);
    color: var(--text);
    min-height: 100vh;
    line-height: 1.6;
}}
.container {{ max-width:1400px; margin:0 auto; padding:20px; }}

/* Header */
.header {{
    text-align: center;
    padding: 40px 20px 30px;
    border-bottom: 1px solid var(--border);
    margin-bottom: 30px;
}}
.header h1 {{ font-size:2rem; font-weight:700; margin-bottom:8px; }}
.header .subtitle {{ color: var(--text-secondary); font-size:0.95rem; }}
.header .date-badge {{
    display: inline-block;
    margin-top: 12px;
    padding: 4px 16px;
    border-radius: 20px;
    background: var(--blue);
    color: #fff;
    font-size: 0.85rem;
}}

/* Stat Cards */
.stat-grid {{
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
    gap: 16px;
    margin-bottom: 30px;
}}
.stat-card {{
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: 12px;
    padding: 20px;
    text-align: center;
}}
.stat-card .stat-value {{ font-size:2rem; font-weight:700; }}
.stat-card .stat-label {{ color: var(--text-secondary); font-size:0.85rem; margin-top:4px; }}
.stat-card.green .stat-value {{ color: var(--green); }}
.stat-card.red .stat-value {{ color: var(--red); }}
.stat-card.yellow .stat-value {{ color: var(--yellow); }}
.stat-card.blue .stat-value {{ color: var(--blue); }}

/* Section */
.section {{
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: 16px;
    overflow: hidden;
    margin-bottom: 24px;
}}
.section-header {{
    padding: 20px 24px;
    border-bottom: 1px solid var(--border);
    display: flex;
    align-items: center;
    justify-content: space-between;
}}
.section-header h2 {{ font-size:1.2rem; font-weight:600; }}
.section-header .count {{ font-size:0.85rem; color: var(--text-secondary); }}
.section-body {{ padding: 0; overflow-x: auto; }}

/* Table */
table {{
    width: 100%;
    border-collapse: collapse;
    font-size: 0.9rem;
}}
th {{
    text-align: left;
    padding: 14px 16px;
    background: rgba(255,255,255,0.03);
    color: var(--text-secondary);
    font-weight: 500;
    font-size: 0.8rem;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    border-bottom: 1px solid var(--border);
    white-space: nowrap;
}}
td {{
    padding: 12px 16px;
    border-bottom: 1px solid rgba(255,255,255,0.04);
}}
tr:hover {{ background: rgba(255,255,255,0.03); cursor:pointer; }}
tr.row-buy {{ background: rgba(34,197,94,0.06); }}
tr.row-buy:hover {{ background: rgba(34,197,94,0.10); }}

.name-cell {{ font-weight:500; }}
.code-sub {{ display:block; font-size:0.75rem; color:var(--text-secondary); font-weight:400; }}
.num {{ font-variant-numeric: tabular-nums; text-align:right; font-family:"SF Mono","JetBrains Mono",monospace; }}

/* Badge */
.badge-low {{
    display:inline-block;
    padding:2px 10px;
    border-radius:12px;
    font-size:0.8rem;
    font-weight:600;
    background:rgba(34,197,94,0.15);
    color:var(--green);
}}
.badge-high {{
    display:inline-block;
    padding:2px 10px;
    border-radius:12px;
    font-size:0.8rem;
    font-weight:600;
    background:rgba(239,68,68,0.12);
    color:var(--red);
}}

/* Mini bar */
.mini-bar {{
    width:80px;
    height:6px;
    background:rgba(255,255,255,0.08);
    border-radius:3px;
    overflow:hidden;
}}
.mini-bar-fill {{ height:100%; border-radius:3px; transition:width 0.5s; }}

/* Pct colors */
.pct-pos {{ color: var(--red); }}
.pct-neg {{ color: var(--green); }}

/* Alerts */
.alert-list {{
    padding: 20px 24px;
    display: flex;
    flex-wrap: wrap;
    gap: 12px;
}}
.alert-item {{
    padding: 12px 20px;
    border-radius: 10px;
    background: rgba(34,197,94,0.08);
    border: 1px solid rgba(34,197,94,0.2);
    font-size:0.9rem;
}}
.alert-item .alert-name {{ font-weight:600; }}
.alert-item .alert-detail {{ color: var(--text-secondary); font-size:0.8rem; margin-top:2px; }}

/* Tabs */
.tabs {{
    display: flex;
    gap: 0;
    border-bottom: 1px solid var(--border);
    margin-bottom: 0;
}}
.tab {{
    padding: 12px 24px;
    cursor: pointer;
    border: none;
    background: none;
    color: var(--text-secondary);
    font-size:0.9rem;
    border-bottom: 2px solid transparent;
    transition: all 0.2s;
}}
.tab:hover {{ color: var(--text); }}
.tab.active {{ color: var(--text); border-bottom-color: var(--blue); }}

/* Footer */
.footer {{
    text-align: center;
    padding: 30px;
    color: var(--text-secondary);
    font-size: 0.8rem;
}}

/* Search */
.search-box {{
    padding: 8px 16px;
    border-radius: 8px;
    border: 1px solid var(--border);
    background: rgba(255,255,255,0.05);
    color: var(--text);
    font-size:0.9rem;
    width: 220px;
    outline: none;
}}
.search-box:focus {{ border-color: var(--blue); }}

/* Responsive — 手机适配 */
@media (max-width:768px) {{
    .container {{ padding:8px; }}
    .header {{ padding:20px 10px 16px; }}
    .header h1 {{ font-size:1.2rem; }}
    .header .subtitle {{ font-size:0.8rem; }}
    .stat-grid {{ grid-template-columns: repeat(2, 1fr); gap:8px; }}
    .stat-card {{ padding:14px 10px; }}
    .stat-card .stat-value {{ font-size:1.4rem; }}
    .stat-card .stat-label {{ font-size:0.7rem; }}

    /* 追加自选 — 上下堆叠 */
    #addStockSection, #addEtfSection {{ min-width:100%; }}

    /* 表格 — 横向滚动 */
    .section-body {{ overflow-x:auto; -webkit-overflow-scrolling:touch; }}
    table {{ font-size:0.72rem; white-space:nowrap; }}
    th, td {{ padding:6px 8px; }}

    /* 隐藏次要列（均价、强度条在小屏上太拥挤） */
    th:nth-child(4), td:nth-child(4),  /* 均价 */
    th:nth-child(9), td:nth-child(9)   /* 强度条 */
    {{ display:none; }}

    /* 搜索框全宽 */
    .search-box {{ width:140px; font-size:0.8rem; }}

    /* 买入信号卡片 */
    .alert-item {{ padding:8px 14px; font-size:0.8rem; }}
    .alert-item .alert-name {{ font-size:0.85rem; }}

    /* 标签页 */
    .tab {{ padding:10px 16px; font-size:0.8rem; }}

    /* 按钮加大触控区 */
    button {{ min-height:36px; }}

    /* 追加区域输入框全宽 */
    #addStockSection input, #addEtfSection input {{ width:100% !important; margin-bottom:6px; }}
}}

/* 超小屏（<400px）进一步精简 */
@media (max-width:400px) {{
    th:nth-child(6), td:nth-child(6) {{ display:none; }} /* 价差% */
    .stat-grid {{ grid-template-columns: 1fr 1fr; gap:6px; }}
    .stat-card .stat-value {{ font-size:1.2rem; }}
}}
</style>
</head>
<body>

<div class="container">

    <!-- Header -->
    <div class="header">
        <h1>📊 高股息 + 高价值 + 低价格 分析看板</h1>
        <div class="subtitle">20 只蓝筹股 + 17 只 ETF 批量统计分析</div>
        <div class="date-badge">📅 数据日期: {data["data_date"]} &nbsp;|&nbsp; 生成于 {data["generated_at"]}</div>
    </div>

    <!-- Stat Cards -->
    <div class="stat-grid">
        <div class="stat-card blue">
            <div class="stat-value">{data["stock_count"]}</div>
            <div class="stat-label">📈 分析个股</div>
        </div>
        <div class="stat-card green">
            <div class="stat-value">{data["stock_below_count"]}</div>
            <div class="stat-label">🎯 低于临界买点（个股）</div>
        </div>
        <div class="stat-card blue">
            <div class="stat-value">{data["etf_count"]}</div>
            <div class="stat-label">📊 分析 ETF</div>
        </div>
        <div class="stat-card yellow">
            <div class="stat-value">{data["etf_below_count"]}</div>
            <div class="stat-label">🔍 低于临界买点（ETF）</div>
        </div>
    </div>

    <!-- Add Stock & ETF -->
    <div style="display:grid; grid-template-columns:1fr 1fr; gap:24px; margin-bottom:24px;">
        <!-- 追加个股 -->
        <div class="section" id="addStockSection">
            <div class="section-header">
                <h2>➕ 追加自选股</h2>
                <span class="count" id="addedStockCount" style="display:none"></span>
            </div>
            <div style="padding:12px 20px; display:flex; gap:8px; align-items:center; flex-wrap:wrap;">
                <input type="text" id="addStockCode" placeholder="代码 (如 601398.SH)" style="padding:8px 12px; border-radius:8px; border:1px solid #334155; background:rgba(255,255,255,0.05); color:#e2e8f0; width:170px; outline:none;">
                <input type="text" id="addStockName" placeholder="名称 (可选)" style="padding:8px 12px; border-radius:8px; border:1px solid #334155; background:rgba(255,255,255,0.05); color:#e2e8f0; width:120px; outline:none;">
                <button onclick="addTarget('stock')" style="padding:8px 16px; border-radius:8px; border:none; background:#3b82f6; color:#fff; cursor:pointer; font-size:0.85rem;">追加</button>
                <span id="addStockStatus" style="color:#94a3b8; font-size:0.8rem;"></span>
            </div>
        </div>
        <!-- 追加 ETF -->
        <div class="section" id="addEtfSection">
            <div class="section-header">
                <h2>📊 追加 ETF</h2>
                <span class="count" id="addedEtfCount" style="display:none"></span>
            </div>
            <div style="padding:12px 20px; display:flex; gap:8px; align-items:center; flex-wrap:wrap;">
                <input type="text" id="addEtfCode" placeholder="代码 (如 510050.SH)" style="padding:8px 12px; border-radius:8px; border:1px solid #334155; background:rgba(255,255,255,0.05); color:#e2e8f0; width:170px; outline:none;">
                <input type="text" id="addEtfName" placeholder="名称 (可选)" style="padding:8px 12px; border-radius:8px; border:1px solid #334155; background:rgba(255,255,255,0.05); color:#e2e8f0; width:120px; outline:none;">
                <button onclick="addTarget('etf')" style="padding:8px 16px; border-radius:8px; border:none; background:#8b5cf6; color:#fff; cursor:pointer; font-size:0.85rem;">追加</button>
                <span id="addEtfStatus" style="color:#94a3b8; font-size:0.8rem;"></span>
            </div>
        </div>
    </div>

    <!-- Buy Alerts -->
    {f'''<div class="section">
        <div class="section-header"><h2>🎯 买入信号 — 个股低于临界买点 ({data["stock_below_count"]})</h2></div>
        <div class="alert-list">
            {''.join(f'<div class="alert-item"><div class="alert-name">{s.get("名称","")} ({s.get("代码","")})</div><div class="alert-detail">低于临界买点 {_safe_float(s.get("diff_to_crit")):.2f} 元 | 最新价 {_safe_float(s.get("最新价")):.2f} vs 临界点 {_safe_float(s.get("临界买点")):.2f}</div></div>' for s in data["stock_below"])}
        </div>
    </div>''' if data["stock_below"] else ''}
    {f'''<div class="section">
        <div class="section-header"><h2>🎯 买入信号 — ETF 低于临界买点 ({data["etf_below_count"]})</h2></div>
        <div class="alert-list">
            {''.join(f'<div class="alert-item"><div class="alert-name">{e.get("名称","")} ({e.get("代码","")})</div><div class="alert-detail">低于临界买点 {_safe_float(e.get("diff_to_crit")):.2f} 元 | 最新价 {_safe_float(e.get("最新价")):.2f} vs 临界点 {_safe_float(e.get("临界买点")):.2f}</div></div>' for e in data["etf_below"])}
        </div>
    </div>''' if data["etf_below"] else ''}

    <!-- Tabs -->
    <div class="section">
        <div class="section-header">
            <h2>📋 详细数据</h2>
            <div style="display:flex;align-items:center;gap:16px;">
                <input type="text" class="search-box" id="searchInput" placeholder="🔍 搜索名称或代码..." oninput="filterTable()">
                <span class="count" id="rowCount"></span>
            </div>
        </div>
        <div class="tabs">
            <button class="tab active" onclick="switchTab('stocks')">📈 个股 ({data["stock_count"]})</button>
            <button class="tab" onclick="switchTab('etfs')">📊 ETF ({data["etf_count"]})</button>
        </div>
        <div class="section-body">
            <!-- Stocks Table -->
            <div id="tab-stocks">
            <table>
                <thead>
                    <tr>
                        <th>#</th>
                        <th>名称 / 代码</th>
                        <th style="text-align:right">最新价</th>
                        <th style="text-align:right">均价</th>
                        <th style="text-align:right">临界买点</th>
                        <th style="text-align:right">价差%</th>
                        <th style="text-align:right">距临界点</th>
                        <th>位置</th>
                        <th>强度</th>
                    </tr>
                </thead>
                <tbody id="stockTableBody">
                    {stock_rows(data["stocks"])}
                </tbody>
            </table>
            </div>
            <!-- ETFs Table -->
            <div id="tab-etfs" style="display:none;">
            <table>
                <thead>
                    <tr>
                        <th>#</th>
                        <th>名称 / 代码</th>
                        <th style="text-align:right">最新价</th>
                        <th style="text-align:right">均价</th>
                        <th style="text-align:right">临界买点</th>
                        <th style="text-align:right">价差%</th>
                        <th style="text-align:right">距临界点</th>
                        <th>位置</th>
                        <th>强度</th>
                    </tr>
                </thead>
                <tbody id="etfTableBody">
                    {stock_rows(data["etfs"], is_etf=True)}
                </tbody>
            </table>
            </div>
        </div>
    </div>

    <!-- Footer -->
    <div class="footer">
        临界买点 = 对应周期最低价 × (1.15 + 波动率调整) &nbsp;|&nbsp;
        数据源: Tushare + Baostock &nbsp;|&nbsp;
        仅供参考，不构成投资建议
    </div>

</div>

<script>
let currentTab = 'stocks';
function switchTab(tab) {{
    currentTab = tab;
    document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
    document.querySelectorAll('.tab')[tab === 'stocks' ? 0 : 1].classList.add('active');
    document.getElementById('tab-stocks').style.display = tab === 'stocks' ? '' : 'none';
    document.getElementById('tab-etfs').style.display = tab === 'etfs' ? '' : 'none';
    filterTable();
}}

function filterTable() {{
    const query = document.getElementById('searchInput').value.toLowerCase();
    const tbody = document.getElementById(currentTab === 'stocks' ? 'stockTableBody' : 'etfTableBody');
    const rows = tbody.querySelectorAll('tr');
    let visible = 0;
    rows.forEach(row => {{
        const text = row.textContent.toLowerCase();
        if (query === '' || text.includes(query)) {{
            row.style.display = '';
            visible++;
        }} else {{
            row.style.display = 'none';
        }}
    }});
    document.getElementById('rowCount').textContent = '显示 ' + visible + ' / ' + rows.length;
}}

function highlightRow(tr) {{
    tr.style.transition = 'background 0.3s';
    tr.style.background = 'rgba(59,130,246,0.2)';
    setTimeout(() => {{
        tr.style.background = '';
        tr.classList.contains('row-buy') ? tr.style.background = '' : '';
    }}, 600);
}}

// ── 追加自选（个股 & ETF） ──
const LS_STOCKS = 'dashboard_added_stocks';
const LS_ETFS = 'dashboard_added_etfs';
let addedStocks = JSON.parse(localStorage.getItem(LS_STOCKS) || '[]');
let addedEtfs = JSON.parse(localStorage.getItem(LS_ETFS) || '[]');

function loadAdded() {{
    addedStocks.forEach(s => insertRow(s, 'stock', true));
    addedEtfs.forEach(e => insertRow(e, 'etf', true));
    updateAddedCounts();
}}

function addTarget(type) {{
    const codeId = type === 'stock' ? 'addStockCode' : 'addEtfCode';
    const nameId = type === 'stock' ? 'addStockName' : 'addEtfName';
    const statusId = type === 'stock' ? 'addStockStatus' : 'addEtfStatus';
    const list = type === 'stock' ? addedStocks : addedEtfs;
    const lsKey = type === 'stock' ? LS_STOCKS : LS_ETFS;

    const code = document.getElementById(codeId).value.trim();
    const name = document.getElementById(nameId).value.trim() || code;
    const status = document.getElementById(statusId);
    if (!code) {{ status.textContent = '请输入代码'; return; }}
    if (list.find(s => s.code === code)) {{ status.textContent = '已存在'; return; }}

    status.textContent = '⏳ 分析中...';
    status.style.color = '#eab308';

    // 检测是否在本地文件模式
    if (window.location.protocol === 'file:') {{
        status.textContent = '请通过 web 服务访问: python web_app.py';
        status.style.color = '#ef4444';
        return;
    }}

    fetch('/analyze', {{
        method: 'POST',
        headers: {{'Content-Type': 'application/json'}},
        body: JSON.stringify({{code: code, name: name}})
    }})
    .then(r => r.json())
    .then(data => {{
        if (data.ok && data.stats) {{
            const s = data.stats;
            list.push(s);
            localStorage.setItem(lsKey, JSON.stringify(list));
            insertRow(s, type, false);
            updateAddedCounts();
            document.getElementById(codeId).value = '';
            document.getElementById(nameId).value = '';
            status.textContent = '✅ ' + s.name;
            status.style.color = '#22c55e';
            updateStatCards();
        }} else {{
            status.textContent = '❌ ' + (data.error || '失败');
            status.style.color = '#ef4444';
        }}
    }})
    .catch(e => {{
        status.textContent = '❌ ' + e.message;
        status.style.color = '#ef4444';
    }});
}}

function insertRow(s, type, isRestore) {{
    const tbody = document.getElementById(type === 'stock' ? 'stockTableBody' : 'etfTableBody');
    const pos = s.position || (s.latest_price <= s.critical_buy_point ? '低于' : '高于');
    const diff = s.diff_to_crit || Math.abs(s.latest_price - s.critical_buy_point);
    const pct = s.mean ? ((s.latest_price - s.mean) / s.mean * 100).toFixed(1) : '0.0';
    const crit = s.critical_buy_point || 0;
    const barPct = crit > 0 ? Math.min(100, Math.max(0, (s.latest_price - (s.min||s.latest_price)) / (crit - (s.min||s.latest_price)) * 100 || 50)) : 50;

    const rowClass = pos === '低于' ? 'row-buy' : '';
    const badgeClass = pos === '低于' ? 'badge-low' : 'badge-high';
    const pctClass = parseFloat(pct) >= 0 ? 'pct-pos' : 'pct-neg';

    const tr = document.createElement('tr');
    tr.className = rowClass + ' added-row';
    tr.innerHTML = `
        <td><span style="color:#a855f7;font-size:0.7rem;">自选</span></td>
        <td class="name-cell" title="${{s.code}}">${{s.name}}<span class="code-sub">${{s.code}}</span></td>
        <td class="num">${{s.latest_price.toFixed(2)}}</td>
        <td class="num">${{(s.mean || 0).toFixed(2)}}</td>
        <td class="num">${{crit.toFixed(2)}}</td>
        <td class="num ${{pctClass}}">${{parseFloat(pct)>=0?'+':''}}${{pct}}%</td>
        <td class="num">${{pos==='低于'?'-':'+'}}${{diff.toFixed(2)}}</td>
        <td><span class="${{badgeClass}}">${{pos}}</span></td>
        <td><div class="mini-bar"><div class="mini-bar-fill" style="width:${{barPct}}%;background:${{pos==='低于'?'#22c55e':'#ef4444'}}"></div></div></td>
        <td><button onclick="removeTarget('${{s.code}}','${{type}}')" style="background:none;border:none;color:#ef4444;cursor:pointer;font-size:0.8rem;" title="移除">✕</button></td>
    `;
    tr.onclick = function() {{ highlightRow(this); }};
    tbody.insertBefore(tr, tbody.firstChild);

    if (!isRestore) {{
        tr.style.background = 'rgba(168,85,247,0.15)';
        setTimeout(() => tr.style.background = '', 2000);
    }}
}}

function removeTarget(code, type) {{
    const list = type === 'stock' ? addedStocks : addedEtfs;
    const key = type === 'stock' ? LS_STOCKS : LS_ETFS;
    if (type === 'stock') addedStocks = list.filter(s => s.code !== code);
    else addedEtfs = list.filter(e => e.code !== code);
    localStorage.setItem(key, JSON.stringify(type === 'stock' ? addedStocks : addedEtfs));
    document.querySelectorAll('.added-row').forEach(r => {{
        if (r.textContent.includes(code)) r.remove();
    }});
    updateAddedCounts();
    updateStatCards();
}}

function updateAddedCounts() {{
    ['Stock','Etf'].forEach(t => {{
        const el = document.getElementById('added' + t + 'Count');
        const n = t === 'Stock' ? addedStocks.length : addedEtfs.length;
        if (el) {{ el.style.display = n > 0 ? '' : 'none'; el.textContent = '已追加 ' + n + ' 只'; }}
    }});
}}

function updateStatCards() {{
    const stockBelow = document.querySelectorAll('#stockTableBody .badge-low').length;
    const etfBelow = document.querySelectorAll('#etfTableBody .badge-low').length;
    const cards = document.querySelectorAll('.stat-card .stat-value');
    if (cards.length >= 4) {{ cards[1].textContent = stockBelow; cards[3].textContent = etfBelow; }}
}}

// Init
loadAdded();
document.getElementById('rowCount').textContent = '显示 ' + document.querySelectorAll('#stockTableBody tr').length + ' / ' + document.querySelectorAll('#stockTableBody tr').length;
</script>

</body>
</html>"""


def main():
    import sys
    if sys.platform == "win32":
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    print("Loading analysis data...")
    data = load_data()
    print(f"Stocks: {data['stock_count']} (buy: {data['stock_below_count']}) | ETFs: {data['etf_count']} (buy: {data['etf_below_count']})")

    html = render_dashboard(data)

    output_path = Path("output/dashboard.html")
    output_path.write_text(html, encoding="utf-8")
    print(f"Dashboard saved: {output_path}")
    print(f"Open in browser: file:///{output_path.absolute()}")


if __name__ == "__main__":
    main()
