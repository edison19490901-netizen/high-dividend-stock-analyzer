"""
高股息率股票筛选 + 买点计算
取代原有的 筛选并算买点.py

流程:
1. 筛选股息率 > threshold、市值 > min_mv 的股票
2. 计算 250 日/周均线位置
3. 对每只计算 1/2/3 年统计指标 + 临界买点
4. 输出多 Sheet Excel 报告
"""

import argparse
import os
import sys
import time
from datetime import datetime
from typing import Any

# Fix Windows GBK encoding for emoji
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import pandas as pd

from common import setup_logging
from common.data_fetcher import (
    get_daily_basic, get_latest_trade_date, get_all_stock_names,
    get_ma_value, get_daily, get_stock_multi_period, _rate_limit,
)
from common.statistics import (
    calc_price_stats, calc_critical_buy_point, build_summary,
)
from common.excel_writer import ExcelReport
from config import (
    DIVIDEND_THRESHOLD, MIN_MARKET_CAP,
    PRICE_FILTER_MIN, PRICE_FILTER_MAX,
    CRITICAL_BUY_PREMIUM, OUTPUT_DIR_SCREENER,
)

logger = setup_logging("screener")


def screen_high_dividend_stocks(
    dividend_threshold: float = DIVIDEND_THRESHOLD,
    min_market_cap: int = MIN_MARKET_CAP,
    price_filter_min: float = PRICE_FILTER_MIN,
    price_filter_max: float = PRICE_FILTER_MAX,
) -> pd.DataFrame:
    """
    筛选高股息率股票。

    返回 DataFrame，包含股票代码、名称、股息率、市值、最新价、均线位置等。
    """
    trade_date = get_latest_trade_date()
    logger.info("最新交易日: %s", trade_date)

    print(f"正在获取 {trade_date} 的市场数据...")
    df = get_daily_basic(trade_date)
    if df.empty:
        logger.warning("%s 无数据", trade_date)
        return pd.DataFrame()

    total = len(df)
    df["total_mv_billion"] = df["total_mv"] / 10000

    # 筛选
    cond = (df["dv_ttm"] > dividend_threshold) & (df["total_mv_billion"] > min_market_cap)
    result = df[cond].copy().sort_values("dv_ttm", ascending=False)

    print(f"筛选条件: 股息率 > {dividend_threshold}%, 市值 > {min_market_cap} 亿")
    print(f"满足条件: {len(result)}/{total} 只")

    if result.empty:
        return result

    # 批量获取股票名称
    codes = result["ts_code"].tolist()
    name_map = get_all_stock_names(codes)
    result["name"] = [name_map.get(c, c.split(".")[0]) for c in codes]

    # 计算 250 日均线和周均线
    print("正在计算 250 日均线/周均线...")
    ma250_list = []
    week_ma250_list = []
    for i, (_, row) in enumerate(result.iterrows()):
        code = row["ts_code"]
        print(f"  [{i + 1}/{len(result)}] {row['name']} ({code})")
        ma250_list.append(get_ma_value(code, trade_date, 250, "daily"))
        week_ma250_list.append(get_ma_value(code, trade_date, 250, "weekly"))
        time.sleep(0.2)

    result["250日均线(元)"] = ma250_list
    result["250周均线(元)"] = week_ma250_list

    # 价格位置
    result["小周期差异(%)"] = (result["close"] / result["250日均线(元)"] - 1) * 100
    result["大周期差异(%)"] = (result["close"] / result["250周均线(元)"] - 1) * 100
    result["小周期差异(%)"] = result["小周期差异(%)"].round(2)
    result["大周期差异(%)"] = result["大周期差异(%)"].round(2)

    # 二次筛选
    filter_cond = (
        (result["小周期差异(%)"] >= price_filter_min) &
        (result["小周期差异(%)"] <= price_filter_max) &
        (result["大周期差异(%)"] >= price_filter_min) &
        (result["大周期差异(%)"] <= price_filter_max)
    )
    result = result[filter_cond].copy()

    # 列重命名
    col_map = {
        "ts_code": "股票代码", "name": "股票名称", "close": "最新价(元)",
        "dv_ttm": "股息率TTM(%)", "dv_ratio": "股息率(%)",
        "total_mv_billion": "总市值(亿元)",
        "250日均线(元)": "250日均线(元)", "250周均线(元)": "250周均线(元)",
        "小周期差异(%)": "小周期差异(%)", "大周期差异(%)": "大周期差异(%)",
    }
    result = result.rename(columns={k: v for k, v in col_map.items() if k in result.columns})

    # 数值取整
    for col in ["最新价(元)", "股息率TTM(%)", "总市值(亿元)", "250日均线(元)", "250周均线(元)"]:
        if col in result.columns:
            result[col] = result[col].round(2)

    return result


def analyze_screened_stock(code: str, name: str, dividend: float,
                           market_cap: float, latest_price: float,
                           ma250: float, week_ma250: float,
                           cycle_diff: float, week_cycle_diff: float,
                           years: int = 3) -> dict | None:
    """
    对筛出的股票做深度统计分析。
    """
    data = get_stock_multi_period(code, years)
    if data["3y"].empty:
        return None

    df_3y = data["3y"]

    # 各周期临界买点
    def calc_for_period(df_p: pd.DataFrame) -> dict:
        if df_p.empty:
            return {"min": 0, "buy_point": 0, "premium_pct": 0}
        s = calc_price_stats(df_p["close"])
        vol = s["std"] / s["mean"] if s["mean"] > 0 else 0
        crit = calc_critical_buy_point(s["min"], s["p10"], vol)
        return {"min": s["min"], "buy_point": crit["buy_point"], "premium_pct": crit["premium_pct"]}

    c1y = calc_for_period(data["1y"])
    c2y = calc_for_period(data["2y"])
    c3y = calc_for_period(data["3y"])

    stats_3y = calc_price_stats(df_3y["close"])
    latest_price_actual = float(df_3y["close"].iloc[-1])
    latest_date = df_3y["trade_date"].iloc[-1].strftime("%Y-%m-%d")

    crit_1y = {"buy_point": c1y["buy_point"], "premium_pct": c1y["premium_pct"]}
    crit_2y = {"buy_point": c2y["buy_point"], "premium_pct": c2y["premium_pct"]}
    crit_3y = {"buy_point": c3y["buy_point"], "premium_pct": c3y["premium_pct"]}

    # 把 1y/2y min 注入 stats_3y
    stats_3y["min_1y"] = c1y["min"]
    stats_3y["min_2y"] = c2y["min"]

    summary = build_summary(stats_3y, latest_price_actual, latest_date, crit_1y, crit_2y, crit_3y)

    return {
        "代码": code,
        "名称": name,
        "股息率TTM(%)": dividend,
        "总市值(亿元)": market_cap,
        "最新价(元)": latest_price,
        "250日均线(元)": ma250,
        "250周均线(元)": week_ma250,
        "小周期差异(%)": cycle_diff,
        "大周期差异(%)": week_cycle_diff,
        **summary,
    }


def main():
    parser = argparse.ArgumentParser(description="高股息率股票筛选 + 买点分析")
    parser.add_argument("--dividend", type=float, default=DIVIDEND_THRESHOLD,
                        help=f"股息率阈值 (default: {DIVIDEND_THRESHOLD}%%)")
    parser.add_argument("--market-cap", type=int, default=MIN_MARKET_CAP,
                        help=f"最低市值 亿 (default: {MIN_MARKET_CAP})")
    parser.add_argument("--premium", type=float, default=CRITICAL_BUY_PREMIUM,
                        help=f"临界买点溢价倍数 (default: {CRITICAL_BUY_PREMIUM})")
    args = parser.parse_args()

    print("=" * 60)
    print("高股息率股票筛选与分析")
    print(f"股息率 > {args.dividend}% | 市值 > {args.market_cap} 亿")
    print("=" * 60)

    # 第一步：筛选
    df_screened = screen_high_dividend_stocks(
        dividend_threshold=args.dividend,
        min_market_cap=args.market_cap,
    )

    if df_screened.empty:
        print("无符合条件的股票")
        return

    print(f"\n共 {len(df_screened)} 只股票符合条件:")
    for i, (_, row) in enumerate(df_screened.iterrows(), 1):
        print(f"  {i}. {row['股票名称']} ({row['股票代码']}) "
              f"股息率: {row['股息率TTM(%)']}% 市值: {row['总市值(亿元)']}亿")

    # 第二步：逐只深入分析
    print(f"\n正在逐只分析统计指标...")
    all_results = []
    for i, (_, row) in enumerate(df_screened.iterrows(), 1):
        code = row["股票代码"]
        name = row["股票名称"]
        print(f"  [{i}/{len(df_screened)}] {name} ({code})")
        try:
            r = analyze_screened_stock(
                code, name,
                row.get("股息率TTM(%)", 0),
                row.get("总市值(亿元)", 0),
                row.get("最新价(元)", 0),
                row.get("250日均线(元)", ""),
                row.get("250周均线(元)", ""),
                row.get("小周期差异(%)", ""),
                row.get("大周期差异(%)", ""),
            )
            if r:
                all_results.append(r)
        except Exception as e:
            logger.error("分析 %s 失败: %s", name, e)
        time.sleep(0.5)

    if not all_results:
        print("无成功分析结果")
        return

    # 第三步：写 Excel
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    trade_date = get_latest_trade_date()
    os.makedirs(OUTPUT_DIR_SCREENER, exist_ok=True)

    excel_path = OUTPUT_DIR_SCREENER / f"高股息率股票统计汇总_{trade_date}_{timestamp}.xlsx"

    summary_df = pd.DataFrame(all_results)
    # 去重列
    summary_df = summary_df.loc[:, ~summary_df.columns.duplicated()]

    report = ExcelReport(str(excel_path))
    report.add_sheet("统计指标汇总", summary_df)
    report.add_sheet("筛选股票列表", df_screened)

    # 分析说明
    info = pd.DataFrame([
        ["分析说明", "高股息率股票的统计指标汇总"],
        ["筛选条件", f"股息率 > {args.dividend}%, 市值 > {args.market_cap} 亿"],
        ["价格位置", f"250日/周线差异: {PRICE_FILTER_MIN}% ~ {PRICE_FILTER_MAX}%"],
        ["统计周期", "近1年、2年、3年"],
        ["临界买点", f"对应周期最低价 × {args.premium}"],
        ["分析时间", datetime.now().strftime("%Y-%m-%d %H:%M:%S")],
        ["", ""],
        ["列说明", "溢价% = 临界买点相对最低价的溢价百分比"],
        ["", "标准差区间基于正态分布，±1σ约68%，±2σ约95%"],
    ], columns=["项目", "说明"])
    report.add_sheet("分析说明", info)

    # 投资建议
    advice_rows = []
    for r in all_results:
        try:
            latest = float(r["最新收盘价"])
            c1y = float(r["近1年临界买点"])
            c2y = float(r["近2年临界买点"])
            c3y = float(r["近3年临界买点"])
        except (ValueError, KeyError):
            continue

        below = []
        if latest <= c1y: below.append("近1年")
        if latest <= c2y: below.append("近2年")
        if latest <= c3y: below.append("近3年")

        advice = "，".join(below) + "，建议关注" if below else "高于所有临界点"
        advice_rows.append([r["名称"], f"{latest:.2f}", f"{c1y:.2f}", f"{c2y:.2f}",
                            f"{c3y:.2f}", advice])

    advice_df = pd.DataFrame(advice_rows,
                             columns=["股票名称", "最新价", "近1年临界点", "近2年临界点",
                                      "近3年临界点", "投资建议"])
    report.add_sheet("投资建议", advice_df)
    report.save()

    print(f"\n✅ 分析完成！共 {len(all_results)} 只股票")
    print(f"✅ 结果已保存: {excel_path}")

    # 打印简要
    print(f"\n{'=' * 60}")
    print("简要分析结果:")
    for i, r in enumerate(all_results, 1):
        name = r["名称"]
        latest = r["最新收盘价"]
        c1y = r["近1年临界买点"]
        c2y = r["近2年临界买点"]
        c3y = r["近3年临界买点"]
        print(f"\n{i}. {name}: 最新价 {latest}")
        print(f"   临界点: 1年={c1y}  2年={c2y}  3年={c3y}")
        below = []
        try:
            if float(latest) <= float(c1y): below.append("近1年")
            if float(latest) <= float(c2y): below.append("近2年")
            if float(latest) <= float(c3y): below.append("近3年")
        except ValueError:
            pass
        if below:
            print(f"   ✅ 低于: {', '.join(below)}")
        else:
            print(f"   ⚠️ 高于所有临界点")


if __name__ == "__main__":
    main()
