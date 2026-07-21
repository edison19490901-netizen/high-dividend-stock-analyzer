"""
分时数据统计分析
取代原有的 分价统计频次分析.py

用法:
    python intraday_analysis.py --code 003816.SZ --name 中国广核 --days 10
    python intraday_analysis.py --code 000651.SZ --name 格力电器
"""

import argparse
import os
import sys
from datetime import datetime, timedelta

# Fix Windows GBK encoding for emoji
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import pandas as pd

from common import setup_logging
from common.data_fetcher import get_intraday
from common.statistics import calc_price_stats, calc_critical_buy_point, create_freq_dataframe
from common.chart_utils import create_density_chart
from common.excel_writer import ExcelReport
from config import CRITICAL_BUY_PREMIUM, CHART_BINS, OUTPUT_DIR_INTRADAY

logger = setup_logging("intraday")


def analyze_intraday(code: str, name: str, recent_days: int = 10,
                     output_dir: str | None = None) -> dict | None:
    """
    分析单只股票的近 N 日分时数据。

    参数
    ----
    code : 股票代码 (如 003816.SZ)
    name : 股票名称
    recent_days : 取最近几个交易日
    output_dir : 输出目录

    返回
    ----
    统计结果字典，失败返回 None
    """
    output_dir = output_dir or str(OUTPUT_DIR_INTRADAY)
    os.makedirs(output_dir, exist_ok=True)

    end_date = datetime.now()
    # 向前多取几天以确保覆盖足够的交易日
    start_date = end_date - timedelta(days=recent_days + 15)
    start_str = start_date.strftime("%Y%m%d")
    end_str = end_date.strftime("%Y%m%d")

    print(f"正在获取 {name} ({code}) 分时数据（Tushare 优先，baostock 5分钟线兜底）...")
    df = get_intraday(code, start_str, end_str, freq="1min")

    if df.empty:
        logger.warning("%s 无分时数据", code)
        return None

    # 筛选最近 N 个交易日
    df["trade_dt"] = df["trade_time"].dt.date
    dates_sorted = sorted(df["trade_dt"].unique(), reverse=True)
    target_dates = dates_sorted[:recent_days]
    df = df[df["trade_dt"].isin(target_dates)].reset_index(drop=True)

    if df.empty:
        logger.warning("%s 筛选后无数据", code)
        return None

    price_series = df["close"]
    stats = calc_price_stats(price_series)
    vol = stats["std"] / stats["mean"] if stats["mean"] > 0 else 0
    crit = calc_critical_buy_point(stats["min"], stats["p10"], vol)

    latest_price = float(df["close"].iloc[-1])
    latest_time = df["trade_time"].iloc[-1].strftime("%Y-%m-%d %H:%M:%S")

    def get_date_str(target_val: float) -> str:
        idx = price_series[price_series == target_val].index
        if len(idx) > 0:
            return df.loc[idx[0], "trade_time"].strftime("%Y-%m-%d %H:%M:%S")
        return "未知"

    merged = {
        **stats,
        **crit,
        "latest_price": latest_price,
        "latest_time": latest_time,
        "price_diff_abs": latest_price - stats["mean"],
        "price_diff_pct": (latest_price - stats["mean"]) / stats["mean"] * 100 if stats["mean"] else 0,
        "min_date_str": get_date_str(stats["min"]),
        "max_date_str": get_date_str(stats["max"]),
    }

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    freq_df = create_freq_dataframe(price_series, bins=CHART_BINS, price_label="股价区间(元)")

    # 图表
    chart_path = os.path.join(output_dir, f"intraday_chart_{code}_{timestamp}.png")
    create_density_chart(
        price_series, merged, name, chart_path,
        freq_df=freq_df, bins=CHART_BINS, is_intraday=True, multi_period=False,
    )

    # Excel
    year_range = f"{start_date.strftime('%Y')}-{end_date.strftime('%Y')}"
    excel_path = os.path.join(
        output_dir,
        f"{name}_{year_range}近{recent_days}日分时分析_{timestamp}.xlsx",
    )

    report = ExcelReport(excel_path)
    report.add_sheet("原始分时数据", df)
    # 手动构建统计 Sheet
    stats_data = [
        ["股票代码", code, "-"],
        ["股票名称", name, "-"],
        ["分时价格均值", f"{stats['mean']:.2f} 元", "-"],
        ["分时价格中位数", f"{stats['median']:.2f} 元", "-"],
        ["分时价格众数", f"{stats['mode']:.2f} 元", "出现频次最高的分时价格"],
        ["分时价格标准差", f"{stats['std']:.2f} 元", "-"],
        ["总分时数据点数", f"{stats['count']} 个", f"近{recent_days}日所有1分钟分时记录"],
        ["分时价格最小值", f"{stats['min']:.2f} 元", f"时间: {merged['min_date_str']}"],
        ["分时价格最大值", f"{stats['max']:.2f} 元", f"时间: {merged['max_date_str']}"],
        ["建议临界买点", f"{crit['buy_point']:.2f} 元",
         f"最小值×{crit.get('adjusted_premium', 1.1):.2f}, 溢价{crit['premium_pct']:.1f}%"],
        [f"最新分时价格（{latest_time}）", f"{latest_price:.2f} 元", "最后一条分时成交价"],
        ["最新价与均值绝对差异", f"{merged['price_diff_abs']:.2f} 元", "最新价 - 分时均价"],
        ["最新价与均值相对差异", f"{merged['price_diff_pct']:.2f}%", "相对均价偏离幅度"],
        ["均值±1倍标准差区间",
         f"[{stats['std1_lower']:.2f}, {stats['std1_upper']:.2f}] 元", "约68%数据在此区间"],
        ["均值±2倍标准差区间",
         f"[{stats['std2_lower']:.2f}, {stats['std2_upper']:.2f}] 元", "约95%数据在此区间"],
    ]
    stats_df = pd.DataFrame(stats_data, columns=["统计指标", "数值/区间", "统计学说明"])
    report.add_sheet("统计指标与标准差", stats_df)
    report.add_sheet("股价区间频次统计", freq_df, chart_path=chart_path)
    report.save()
    report.cleanup_charts()

    # 控制台输出
    print(f"\n✅ {name} 分时分析完成")
    print(f"   统计周期: 近{recent_days}个交易日")
    print(f"   分时数据点: {stats['count']}")
    print(f"   价格范围: {stats['min']:.2f} ~ {stats['max']:.2f}")
    print(f"   临界买点: {crit['buy_point']:.2f} (溢价{crit['premium_pct']:.1f}%)")
    print(f"   最新价: {latest_price:.2f}")
    print(f"   结果: {excel_path}")

    if latest_price <= crit["buy_point"]:
        print(f"   ⭐ 当前价格低于临界买点，可关注！低于 {crit['buy_point'] - latest_price:.2f} 元")
    else:
        print(f"   📈 当前价格高于临界买点 {latest_price - crit['buy_point']:.2f} 元")

    return merged


def main():
    parser = argparse.ArgumentParser(description="分时数据统计分析")
    parser.add_argument("--code", required=True, help="股票代码 (如 003816.SZ)")
    parser.add_argument("--name", default="", help="股票名称")
    parser.add_argument("--days", type=int, default=10, help="近N个交易日 (default: 10)")
    parser.add_argument("--output", default=None, help="输出目录")
    args = parser.parse_args()

    name = args.name or args.code
    result = analyze_intraday(args.code, name, args.days, args.output)
    if result is None:
        print("分析失败，请检查股票代码或网络。")
        return 1
    return 0


if __name__ == "__main__":
    main()
