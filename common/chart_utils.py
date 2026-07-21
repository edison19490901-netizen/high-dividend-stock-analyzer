"""
图表工具 — 密度条形图生成，自动适配中文字体。
"""

from pathlib import Path
from typing import Any

import matplotlib
matplotlib.use("Agg")  # 无 GUI 后端
import matplotlib.pyplot as plt
import pandas as pd

from config import CHART_DPI, CHART_BINS, CHART_FIGSIZE_WIDE, CHART_FIGSIZE_NORMAL
from common import detect_chinese_font
from common.statistics import find_bin_index

# 字体初始化（模块加载时执行一次）
_FONT = detect_chinese_font()
plt.rcParams["font.sans-serif"] = [_FONT, "sans-serif"]
plt.rcParams["axes.unicode_minus"] = False


def create_density_chart(
    price_series: pd.Series,
    stats: dict,
    name: str,
    chart_path: str | Path,
    *,
    freq_df: pd.DataFrame | None = None,
    bins: int = CHART_BINS,
    is_intraday: bool = False,
    multi_period: bool = False,
    years: int = 3,
):
    """
    生成价格密度分布条形图并保存为 PNG。

    参数
    ----
    price_series : 价格序列
    stats : 统计指标字典（来自 calc_price_stats）
    name : 股票/ETF 名称
    chart_path : 保存路径
    freq_df : 预计算的频次 DataFrame，为 None 则自动生成
    bins : 分箱数
    is_intraday : 是否为分时数据
    multi_period : 是否展示多周期（1/2/3年）临界点
    years : 统计周期年数
    """
    from common.statistics import create_freq_dataframe

    if freq_df is None:
        freq_df_local = create_freq_dataframe(price_series, bins=bins)
    else:
        freq_df_local = freq_df

    bin_labels = freq_df_local.iloc[:, 0].tolist()
    freq_values = freq_df_local.iloc[:, 1].values

    # 图表尺寸
    figsize = CHART_FIGSIZE_WIDE if multi_period else CHART_FIGSIZE_NORMAL
    plt.figure(figsize=figsize)
    bars = plt.barh(bin_labels, freq_values, color="#2E86AB", alpha=0.8)

    # 标注频次数字
    for bar, cnt in zip(bars, freq_values):
        plt.text(bar.get_width() + 1, bar.get_y() + bar.get_height() / 2,
                 f"{cnt}", va="center", fontsize=10)

    # 关键位置标记
    unit = "元"
    time_label = "分时" if is_intraday else "日"

    key_positions = _build_key_positions(stats, multi_period)

    for key_name, (value, color, alpha) in key_positions:
        if value is None:
            continue
        idx = find_bin_index(value, bin_labels)
        if 0 <= idx < len(bin_labels):
            plt.text(freq_values[idx] + 1, idx,
                     f"← {key_name}: {value:.2f}",
                     va="center", ha="left",
                     color=color, fontweight="bold", fontsize=9, alpha=alpha)

    # 标题
    latest = stats.get("latest_price", 0)
    mean = stats.get("mean", 0)
    diff_abs = stats.get("price_diff_abs", latest - mean)
    diff_pct = stats.get("price_diff_pct", (latest - mean) / mean * 100 if mean else 0)
    p_min = stats.get("min", 0)
    p_mode = stats.get("mode", 0)
    std1_l = stats.get("std1_lower", 0)
    std1_u = stats.get("std1_upper", 0)
    std2_l = stats.get("std2_lower", 0)
    std2_u = stats.get("std2_upper", 0)

    title = (
        f"{name} 近{years}年{time_label}价分布密度条形图\n"
        f"最新价={latest:.2f} {unit} | 均价={mean:.2f} {unit} | 差异={diff_abs:.2f} {unit}({diff_pct:.2f}%)\n"
    )
    if multi_period:
        for period in ["1y", "2y", "3y"]:
            crit_key = f"critical_buy_point_{period}"
            if crit_key in stats and stats[crit_key] is not None:
                title += f"近{period[0]}年临界点={stats[crit_key]:.2f} {unit} | "
        title = title.rstrip(" | ") + "\n"
    else:
        crit = stats.get("critical_buy_point", 0)
        title += f"最低价={p_min:.2f} {unit} | 临界买点={crit:.2f} {unit} | 众数={p_mode:.2f} {unit}\n"

    title += f"±1σ: [{std1_l:.2f}, {std1_u:.2f}]  |  ±2σ: [{std2_l:.2f}, {std2_u:.2f}]"

    plt.title(title, fontsize=12, pad=20)
    plt.xlabel(f"出现频次({time_label}数)", fontsize=12)
    plt.ylabel(f"{time_label}价区间({unit})", fontsize=12)
    plt.grid(axis="x", alpha=0.3)
    plt.tight_layout()

    Path(chart_path).parent.mkdir(parents=True, exist_ok=True)
    plt.savefig(chart_path, dpi=CHART_DPI, bbox_inches="tight")
    plt.close()


def _build_key_positions(stats: dict, multi_period: bool) -> list[tuple[str, tuple]]:
    """构建要标注的关键位置列表。"""
    positions: list[tuple[str, tuple]] = []

    if multi_period:
        # 多周期模式
        color_map = {
            "1y": ("#4ECDC4", 0.7), "2y": ("#45B7AA", 0.6), "3y": ("#1A8C7F", 0.5),
        }
        for period in ["1y", "2y", "3y"]:
            min_key = f"price_min_{period}"
            crit_key = f"critical_buy_point_{period}"
            if min_key in stats and stats[min_key] is not None:
                positions.append((f"近{period[0]}年最低价", (stats[min_key], "#FF6B6B", 1.0)))
            if crit_key in stats and stats[crit_key] is not None:
                c = color_map.get(period, ("#4ECDC4", 0.7))
                positions.append((f"近{period[0]}年临界点", (stats[crit_key], c[0], c[1])))
        if stats.get("mean"):
            positions.append(("均值", (stats["mean"], "#FFD166", 0.4)))
        if stats.get("latest_price"):
            positions.append(("最新价", (stats["latest_price"], "#06D6A0", 0.4)))
    else:
        # 单周期模式
        mapping = [
            ("最小值", stats.get("min"), "#FF6B6B", 1.0),
            ("临界买点", stats.get("critical_buy_point"), "#4ECDC4", 0.8),
            ("均值", stats.get("mean"), "#FFD166", 0.6),
            ("最新价", stats.get("latest_price"), "#06D6A0", 0.4),
        ]
        for name, value, color, alpha in mapping:
            if value is not None:
                positions.append((name, (value, color, alpha)))

    return positions
