"""
统一批量分析引擎 — 支持 ETF 和个股。
取代原有的 ETF日价统计频次分析02.py 和 日价统计频次分析03.py。

用法:
    python batch_analysis.py                    # 分析 targets.yaml 中所有标的
    python batch_analysis.py --mode stock       # 仅分析个股
    python batch_analysis.py --mode etf         # 仅分析 ETF
    python batch_analysis.py --code 000651.SZ   # 分析单只
"""

import argparse
import os
import sys
from datetime import datetime
from typing import Any

# Fix Windows GBK encoding for emoji
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import pandas as pd

from common import setup_logging
from common.data_fetcher import (
    get_daily, get_etf_daily, get_latest_trade_date, get_daily_basic,
    get_ma_value, get_all_stock_names, batch_fetch,
)
from common.statistics import (
    calc_price_stats, calc_critical_buy_point, create_freq_dataframe,
)
from common.chart_utils import create_density_chart
from common.excel_writer import (
    ExcelReport, build_stats_sheet, build_investment_advice_sheet,
)
from config import (
    CRITICAL_BUY_PREMIUM, CHART_BINS,
    OUTPUT_DIR_STOCKS, OUTPUT_DIR_ETFS,
)
from targets import STOCK_TARGETS, ETF_TARGETS

logger = setup_logging("batch_analysis")


# ===================== 工具函数 =====================

def _get_date_str(df: pd.DataFrame, col: str, target_value: float) -> str:
    """从 DataFrame 中找到某列等于指定值的首行日期。"""
    if df.empty:
        return "未知"
    match = df.loc[df[col] == target_value, "trade_date"]
    if not match.empty:
        return match.iloc[0].strftime("%Y-%m-%d")
    return "未知"


def _make_summary_row(result: dict) -> dict:
    """将单只分析结果转为汇总行。"""
    s = result["stats"]
    return {
        "代码": result["code"],
        "名称": result["name"],
        "类型": result.get("target_type", "stock"),
        "最新价": s["latest_price"],
        "最新日期": s["latest_trade_date"],
        "均价": round(s["mean"], 2),
        "最低价": round(s["min"], 2),
        "最低日期": s.get("min_date_str", ""),
        "临界买点": round(s.get("critical_buy_point", 0), 2),
        "溢价%": s.get("buy_point_premium", 0),
        "价差%": round(s.get("price_diff_pct", 0), 2),
        "交易天数": s["count"],
    }


def _print_advice(stats: dict, name: str):
    """打印投资建议到控制台。"""
    latest = stats["latest_price"]
    print(f"\n📊 {name} 简要结果:")
    print(f"   最新价: {latest:.2f} 元 ({stats['latest_trade_date']})")
    print(f"   最低价: {stats['min']:.2f} 元 ({stats.get('min_date_str', '未知')})")
    crit = stats.get("critical_buy_point", 0)
    prem = stats.get("buy_point_premium", 0)
    print(f"   临界买点: {crit:.2f} 元 (溢价{prem:.1f}%)")

    if latest <= crit:
        print(f"   ✅ 当前价格低于临界买点，低于 {crit - latest:.2f} 元")
    else:
        print(f"   ⚠️ 当前价格高于临界买点，高于 {latest - crit:.2f} 元")

    # 位置判断
    p_min = stats["min"]
    if latest <= p_min * 1.05:
        print(f"   🎯 当前价格非常接近历史最低点")
    elif latest <= p_min * 1.10:
        print(f"   🔍 当前价格在较低位置")
    elif latest <= stats["mean"]:
        print(f"   💡 当前价格低于历史均值")
    else:
        print(f"   📈 当前价格高于历史均值")


# ===================== 单只分析 =====================

def analyze_single_stock(code: str, name: str, years: int = 3,
                         output_dir: str | None = None) -> dict | None:
    """
    分析单只个股（多周期：1/2/3年）。
    只拉一次 3 年数据，在内存中切片。
    """
    from common.data_fetcher import get_stock_multi_period
    from config import OUTPUT_DIR_STOCKS

    output_dir = output_dir or str(OUTPUT_DIR_STOCKS)

    end_date = datetime.now()
    data = get_stock_multi_period(code, years)

    if data["3y"].empty:
        logger.warning("%s %s 无数据", code, name)
        return None

    # 各周期统计
    period_stats = {}
    for key, label in [("1y", "近1年"), ("2y", "近2年"), ("3y", "近3年")]:
        df_p = data[key]
        if df_p.empty:
            continue
        stats_p = calc_price_stats(df_p["close"])
        vol = stats_p["std"] / stats_p["mean"] if stats_p["mean"] > 0 else 0
        crit = calc_critical_buy_point(stats_p["min"], stats_p["p10"], vol)
        period_stats[key] = {
            **stats_p,
            **crit,
            f"price_min_{key}": stats_p["min"],
            f"price_max_{key}": stats_p["max"],
            f"critical_buy_point_{key}": crit["buy_point"],
            f"buy_point_premium_{key}": crit["premium_pct"],
            f"min_date_str_{key}": _get_date_str(df_p, "close", stats_p["min"]),
            f"max_date_str_{key}": _get_date_str(df_p, "close", stats_p["max"]),
            f"total_days_{key}": stats_p["count"],
        }

    # 以 3 年为基准统计
    base = period_stats.get("3y", calc_price_stats(data["3y"]["close"]))
    df_3y = data["3y"]
    latest_price = float(df_3y["close"].iloc[-1])
    latest_date = df_3y["trade_date"].iloc[-1].strftime("%Y-%m-%d")

    # 合并所有统计
    merged = {
        **base,
        "latest_price": latest_price,
        "latest_trade_date": latest_date,
        "price_diff_abs": latest_price - base["mean"],
        "price_diff_pct": (latest_price - base["mean"]) / base["mean"] * 100 if base["mean"] else 0,
        "min_date_str": _get_date_str(df_3y, "close", base["min"]),
    }
    # 合并各周期数据
    for key, pstats in period_stats.items():
        merged.update(pstats)

    # 为不使用多周期的下游函数提供简单别名
    merged.setdefault("critical_buy_point", merged.get("critical_buy_point_3y", 0))
    merged.setdefault("buy_point_premium", merged.get("buy_point_premium_3y", 0))

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    os.makedirs(output_dir, exist_ok=True)

    # 频次统计
    freq_df = create_freq_dataframe(df_3y["close"], bins=CHART_BINS, price_label="股价区间(元)")

    # 图表
    chart_path = os.path.join(output_dir, f"chart_{code}_{timestamp}.png")
    create_density_chart(
        df_3y["close"], merged, name, chart_path,
        freq_df=freq_df, multi_period=True, years=years,
    )

    # Excel
    excel_path = os.path.join(
        output_dir,
        f"{name}_{code}_{datetime.now().strftime('%Y')}-{datetime.now().strftime('%Y')}近{years}年股价分析_{timestamp}.xlsx",
    )
    report = ExcelReport(excel_path)
    report.add_sheet("原始股价数据(近3年)", df_3y)
    if not data["2y"].empty and not data["2y"].equals(df_3y):
        report.add_sheet("原始股价数据(近2年)", data["2y"])
    if not data["1y"].empty and not data["1y"].equals(df_3y):
        report.add_sheet("原始股价数据(近1年)", data["1y"])

    stats_sheet = build_stats_sheet(merged, code, name, years=years, multi_period=True)
    report.add_sheet("统计指标与标准差", stats_sheet)
    report.add_sheet("股价区间频次统计", freq_df, chart_path=chart_path)
    report.add_sheet("投资建议", build_investment_advice_sheet(merged, multi_period=True))
    report.save()
    report.cleanup_charts()

    _print_advice(merged, name)
    return {"code": code, "name": name, "target_type": "stock", "stats": merged}


def analyze_single_etf(code: str, name: str, years: int = 3,
                       output_dir: str | None = None) -> dict | None:
    """
    分析单只 ETF（单周期）。

    注意：Baostock 免费 ETF 数据仅覆盖约 6 个月（~130 个交易日）。
    若数据不足请求年数，自动使用全部可用数据。
    """
    from config import OUTPUT_DIR_ETFS
    output_dir = output_dir or str(OUTPUT_DIR_ETFS)
    os.makedirs(output_dir, exist_ok=True)

    end_date = datetime.now()
    start_date = end_date - pd.Timedelta(days=years * 365 + 30)
    df = get_etf_daily(code, start_date.strftime("%Y%m%d"), end_date.strftime("%Y%m%d"))

    if df.empty:
        logger.warning("%s %s 无数据", code, name)
        return None

    # 计算实际可用数据年限
    if "trade_date" in df.columns and len(df) > 0:
        actual_days = (df["trade_date"].max() - df["trade_date"].min()).days
        actual_years = max(0.5, round(actual_days / 365, 1))
        if actual_days < years * 200:  # 数据明显不足请求年数时
            logger.info("%s 实际可用数据: %.1f 年 (%d 天)，Baostock ETF 数据始于 2026-01",
                        name, actual_years, len(df))
    else:
        actual_years = float(years)

    stats = calc_price_stats(df["close"])
    vol = stats["std"] / stats["mean"] if stats["mean"] > 0 else 0
    crit = calc_critical_buy_point(stats["min"], stats["p10"], vol)
    latest_price = float(df["close"].iloc[-1])
    latest_date = df["trade_date"].iloc[-1].strftime("%Y-%m-%d")

    merged = {
        **stats,
        **crit,
        "critical_buy_point": crit["buy_point"],       # 别名兼容
        "buy_point_premium": crit["premium_pct"],       # 别名兼容
        "latest_price": latest_price,
        "latest_trade_date": latest_date,
        "price_diff_abs": latest_price - stats["mean"],
        "price_diff_pct": (latest_price - stats["mean"]) / stats["mean"] * 100 if stats["mean"] else 0,
        "min_date_str": _get_date_str(df, "close", stats["min"]),
        "max_date_str": _get_date_str(df, "close", stats["max"]),
    }

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    freq_df = create_freq_dataframe(df["close"], bins=CHART_BINS, price_label="基金价格区间(元)")

    chart_path = os.path.join(output_dir, f"chart_{code}_{timestamp}.png")
    create_density_chart(df["close"], merged, name, chart_path,
                         freq_df=freq_df, multi_period=False, years=years)

    year_str = f"{datetime.now().strftime('%Y')}-{datetime.now().strftime('%Y')}"
    excel_path = os.path.join(
        output_dir, f"{name}_{year_str}近{years}年基金分析_{timestamp}.xlsx",
    )

    report = ExcelReport(excel_path)
    report.add_sheet("原始基金日线数据", df)
    stats_sheet = build_stats_sheet(merged, code, name, years=years, multi_period=False)
    report.add_sheet("统计指标与标准差", stats_sheet)
    report.add_sheet("价格区间频次统计", freq_df, chart_path=chart_path)
    report.add_sheet("投资建议", build_investment_advice_sheet(merged, multi_period=False))
    report.save()
    report.cleanup_charts()

    _print_advice(merged, name)
    return {"code": code, "name": name, "target_type": "etf", "stats": merged}


# ===================== 批量入口 =====================

def run_batch(mode: str = "all", years: int = 3) -> dict:
    """
    批量分析入口。

    参数
    ----
    mode : "stock" / "etf" / "all"
    years : 统计周期（年）

    返回
    ----
    {"stocks": [...], "etfs": [...]}
    """
    all_results: dict[str, list[dict]] = {"stocks": [], "etfs": []}

    # 个股
    if mode in ("stock", "all"):
        stocks = STOCK_TARGETS
        print(f"\n{'=' * 60}")
        print(f"📈 个股批量分析 — {len(stocks)} 只")
        print(f"{'=' * 60}")

        for i, item in enumerate(stocks, 1):
            code = item["code"]
            name = item["name"]
            print(f"\n[{i}/{len(stocks)}] {name} ({code})")
            try:
                result = analyze_single_stock(code, name, years=years)
                if result:
                    all_results["stocks"].append(result)
            except Exception as e:
                logger.error("分析 %s 失败: %s", name, e)

    # ETF
    if mode in ("etf", "all"):
        etfs = ETF_TARGETS
        print(f"\n{'=' * 60}")
        print(f"📊 ETF 批量分析 — {len(etfs)} 只")
        print(f"{'=' * 60}")

        for i, item in enumerate(etfs, 1):
            code = item["code"]
            name = item["name"]
            print(f"\n[{i}/{len(etfs)}] {name} ({code})")
            try:
                result = analyze_single_etf(code, name, years=years)
                if result:
                    all_results["etfs"].append(result)
            except Exception as e:
                logger.error("分析 %s 失败: %s", name, e)

    # 汇总报告
    _write_summary(all_results, mode)

    return all_results


def _write_summary(all_results: dict, mode: str):
    """输出汇总 Excel 报告。"""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    for category, results in [("stocks", "股票"), ("etfs", "ETF")]:
        if not all_results[category]:
            continue

        out_dir = OUTPUT_DIR_STOCKS if category == "stocks" else OUTPUT_DIR_ETFS
        out_dir.mkdir(parents=True, exist_ok=True)

        rows = [_make_summary_row(r) for r in all_results[category]]
        summary_df = pd.DataFrame(rows)

        path = out_dir / f"{'股票' if category == 'stocks' else 'ETF'}分析汇总报告_{timestamp}.xlsx"

        with pd.ExcelWriter(path, engine="openpyxl") as writer:
            summary_df.to_excel(writer, sheet_name="汇总统计", index=False)

            # 投资建议汇总
            advice_rows = []
            for r in all_results[category]:
                s = r["stats"]
                latest = s["latest_price"]
                crit = s.get("critical_buy_point", 0)
                pos = "低于" if latest <= crit else "高于"
                advice_rows.append([
                    s.get("name", r["name"]),
                    f"{latest:.2f}",
                    f"{crit:.2f}",
                    f"{abs(latest - crit):.2f}",
                    pos,
                    "低于临界点，建议关注" if latest <= crit else "高于临界点，注意风险",
                ])

            advice_df = pd.DataFrame(
                advice_rows,
                columns=["名称", "最新价", "临界买点", "价格差异", "相对位置", "投资建议"],
            )
            advice_df.to_excel(writer, sheet_name="投资建议汇总", index=False)

            # 按价格差异排序
            advice_df["价格差异_num"] = pd.to_numeric(advice_df["价格差异"], errors="coerce")
            sorted_df = advice_df.sort_values("价格差异_num").drop(columns=["价格差异_num"])
            sorted_df.to_excel(writer, sheet_name="价格差异排序", index=False)

        print(f"\n✅ {category} 汇总已保存: {path}")

        # 打印摘要
        below = [r for r in all_results[category]
                 if r["stats"]["latest_price"] <= r["stats"].get("critical_buy_point", 0)]
        if below:
            print(f"   ✅ {len(below)} 只{category}低于临界买点")
            for r in below:
                s = r["stats"]
                diff = s.get("critical_buy_point", 0) - s["latest_price"]
                print(f"      {r['name']}: 低于 {diff:.2f} 元")
        else:
            print(f"   ⚠️ 没有{category}低于临界买点")


# ===================== CLI =====================

def main():
    parser = argparse.ArgumentParser(description="统一批量分析引擎")
    parser.add_argument("--mode", choices=["stock", "etf", "all"], default="all",
                        help="分析模式 (default: all)")
    parser.add_argument("--code", type=str, default=None,
                        help="分析单只标的（如 000651.SZ 或 515790.SH）")
    parser.add_argument("--name", type=str, default="",
                        help="标的名称（配合 --code 使用）")
    parser.add_argument("--years", type=int, default=3,
                        help="统计周期年数 (default: 3)")
    args = parser.parse_args()

    if args.code:
        # 判断是 ETF 还是个股
        code = args.code.strip()
        name = args.name or code
        if code.startswith(("15", "51", "58")):
            # ETF
            result = analyze_single_etf(code, name, years=args.years)
        else:
            result = analyze_single_stock(code, name, years=args.years)
        if result:
            print(f"\n✅ {name} 分析完成")
        else:
            print(f"\n❌ {name} 分析失败")
    else:
        run_batch(mode=args.mode, years=args.years)
        print("\n✅ 批量分析全部完成！")


if __name__ == "__main__":
    main()
