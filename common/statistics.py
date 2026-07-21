"""
统计计算模块 — 价格统计、临界买点、频次分析等。
"""

from datetime import datetime
from typing import Any

import numpy as np
import pandas as pd

from config import CRITICAL_BUY_PREMIUM


def calc_price_stats(price_series: pd.Series) -> dict:
    """
    计算价格序列的核心统计指标。
    返回包含均值、标准差、中位数、众数、极值等的字典。
    """
    mean = float(price_series.mean())
    std = float(price_series.std())
    median = float(price_series.median())

    mode_series = price_series.mode()
    mode_val = float(mode_series.iloc[0]) if not mode_series.empty else mean

    p_min = float(price_series.min())
    p_max = float(price_series.max())
    count = len(price_series)

    # 标准差区间
    std1_upper = mean + std
    std1_lower = mean - std
    std2_upper = mean + 2 * std
    std2_lower = mean - 2 * std

    # 分位数（更稳健的极端值替代方案）
    p10 = float(price_series.quantile(0.10))
    p25 = float(price_series.quantile(0.25))
    p75 = float(price_series.quantile(0.75))
    p90 = float(price_series.quantile(0.90))

    return {
        "mean": mean,
        "std": std,
        "median": median,
        "mode": mode_val,
        "min": p_min,
        "max": p_max,
        "count": count,
        "p10": p10,
        "p25": p25,
        "p75": p75,
        "p90": p90,
        "std1_upper": std1_upper,
        "std1_lower": std1_lower,
        "std2_upper": std2_upper,
        "std2_lower": std2_lower,
    }


def calc_critical_buy_point(price_min: float,
                            price_10pct: float | None = None,
                            volatility: float | None = None,
                            premium: float = CRITICAL_BUY_PREMIUM) -> dict:
    """
    计算临界买点。

    改进公式：
    - 基础买点 = min(最低价, 10%分位值) × 溢价系数
    - 如果提供了波动率(std/mean)，高波动品种自动提高安全边际

    返回 {"buy_point": float, "premium_pct": float, "base_price": float}
    """
    # 使用最低价和 10% 分位值的较小者，避免极端闪崩低价的干扰
    if price_10pct is not None and price_10pct > 0:
        base = min(price_min, price_10pct * 1.05)  # 允许分位值略低于 min（不可能），取 min
        base = price_min  # 保守起见，仍以最低价为基准，仅用分位值做参考
    else:
        base = price_min

    # 根据波动率动态调整溢价：波动率每 10%，额外增加 2% 安全边际
    adjusted_premium = premium
    if volatility is not None and volatility > 0:
        adjusted_premium += max(0, (volatility - 0.20) * 0.20)

    buy_point = base * adjusted_premium
    premium_pct = (buy_point - base) / base * 100 if base > 0 else 0

    return {
        "buy_point": round(buy_point, 3),
        "premium_pct": round(premium_pct, 1),
        "base_price": round(base, 3),
        "adjusted_premium": round(adjusted_premium, 4),
    }


def calc_ema_weighted_mean(price_series: pd.Series, span: int = 60) -> float:
    """EMA 加权均值 — 近期数据权重更高。"""
    if len(price_series) < span:
        return float(price_series.mean())
    return float(price_series.ewm(span=span, adjust=False).mean().iloc[-1])


def create_freq_dataframe(price_series: pd.Series, bins: int = 21,
                          price_label: str = "股价区间(元)") -> pd.DataFrame:
    """
    将价格序列分箱，生成频次统计 DataFrame。
    """
    cut = pd.cut(price_series, bins=bins, include_lowest=True)
    freq = cut.value_counts(sort=False)
    bin_edges = cut.cat.categories.left.tolist() + [cut.cat.categories.right[-1]]
    bin_labels = [f"[{bin_edges[i]:.2f}, {bin_edges[i + 1]:.2f})" for i in range(len(bin_edges) - 1)]

    return pd.DataFrame({
        price_label: bin_labels,
        "出现频次(交易日数)": freq.values,
    })


def find_bin_index(value: float, bin_labels: list[str]) -> int:
    """
    找到某价格所属的区间索引。
    bin_labels 格式: "[left, right)"
    """
    for i, label in enumerate(bin_labels):
        clean = label.strip("[]()")
        parts = clean.split(",")
        if len(parts) != 2:
            continue
        try:
            left, right = float(parts[0]), float(parts[1])
        except ValueError:
            continue
        if left <= value < right:
            return i
    # 兜底：找最接近的
    for i, label in enumerate(bin_labels):
        clean = label.strip("[]()")
        parts = clean.split(",")
        if len(parts) != 2:
            continue
        try:
            left, right = float(parts[0]), float(parts[1])
        except ValueError:
            continue
        if left <= value <= right:
            return i
    return max(0, len(bin_labels) - 1)


def build_summary(stats: dict, latest_price: float, latest_date: str,
                  crit_1y: dict, crit_2y: dict, crit_3y: dict) -> dict:
    """
    将统计结果 + 临界买点整合为汇总字典，供 Excel 输出使用。
    """
    def pos_label(price: float, crit: dict) -> str:
        return "低于" if price <= crit["buy_point"] else "高于"

    return {
        "最新收盘价": f"{latest_price:.2f}",
        "最新交易日期": latest_date,
        "近3年均价": f"{stats['mean']:.2f}",
        "近3年中位数": f"{stats['median']:.2f}",
        "近3年众数": f"{stats['mode']:.2f}",
        "近3年标准差": f"{stats['std']:.2f}",
        "近3年交易日数": stats["count"],
        "近1年最低价": f"{stats.get('min_1y', 0):.2f}",
        "近1年临界买点": f"{crit_1y['buy_point']:.2f}",
        "近1年临界溢价": f"{crit_1y['premium_pct']:.1f}%",
        "近2年最低价": f"{stats.get('min_2y', 0):.2f}",
        "近2年临界买点": f"{crit_2y['buy_point']:.2f}",
        "近2年临界溢价": f"{crit_2y['premium_pct']:.1f}%",
        "近3年最低价": f"{stats['min']:.2f}",
        "近3年临界买点": f"{crit_3y['buy_point']:.2f}",
        "近3年临界溢价": f"{crit_3y['premium_pct']:.1f}%",
        "最新价与均值差异": f"{latest_price - stats['mean']:.2f}",
        "最新价与均值差异%": f"{(latest_price - stats['mean']) / stats['mean'] * 100:.2f}%",
        "均值±1标准差区间": f"[{stats['std1_lower']:.2f}, {stats['std1_upper']:.2f}]",
        "均值±2标准差区间": f"[{stats['std2_lower']:.2f}, {stats['std2_upper']:.2f}]",
        "相对近1年临界点位置": pos_label(latest_price, crit_1y),
        "相对近2年临界点位置": pos_label(latest_price, crit_2y),
        "相对近3年临界点位置": pos_label(latest_price, crit_3y),
        "距近1年临界点": f"{abs(latest_price - crit_1y['buy_point']):.2f}",
        "距近2年临界点": f"{abs(latest_price - crit_2y['buy_point']):.2f}",
        "距近3年临界点": f"{abs(latest_price - crit_3y['buy_point']):.2f}",
        "分析时间": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
