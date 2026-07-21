"""
基于 Baostock 的高股息率股票筛选器（完全免费，无频率限制）。

替代 Tushare daily_basic（免费用户 1次/小时限制太严格）。
"""

import time
from datetime import datetime, timedelta
from pathlib import Path

import baostock as bs
import pandas as pd

from common import setup_logging
from config import DIVIDEND_THRESHOLD, MIN_MARKET_CAP

logger = setup_logging("screener_bs")

# 高股息候选板块：银行、电力、煤炭、港口公路、石化、消费
HIGH_DIV_SECTORS = [
    # 银行 (高股息主力)
    "601398.SH", "601939.SH", "601288.SH", "601988.SH", "600036.SH",
    "601328.SH", "600016.SH", "600000.SH", "601166.SH", "601818.SH",
    "002142.SZ", "600919.SH", "601229.SH", "600926.SH", "601838.SH",
    "601169.SH", "600015.SH", "601998.SH", "601658.SH", "601077.SH",
    # 电力 / 能源
    "600900.SH", "600011.SH", "600886.SH", "600023.SH", "600025.SH",
    "600795.SH", "601985.SH", "003816.SZ", "600905.SH", "601619.SH",
    # 煤炭
    "601088.SH", "601898.SH", "600188.SH", "601225.SH", "601699.SH",
    # 石油
    "601857.SH", "600028.SH", "601808.SH",
    # 高速 / 港口 / 铁路
    "600377.SH", "600012.SH", "600548.SH", "001965.SZ",
    "601000.SH", "600033.SH", "600269.SH", "601006.SH",
    # 家电
    "000651.SZ", "000333.SZ", "600690.SH",
    # 医药 / 消费
    "000999.SZ", "600887.SH", "000895.SZ", "002032.SZ",
    # 地产 / 建材
    "001979.SZ", "600048.SH", "000002.SZ",
    # 通信
    "601728.SH", "600941.SH",
    # 有色
    "000630.SZ", "600362.SH", "601899.SH",
    # 保险
    "601318.SH", "601628.SH", "601601.SH",
]


def _to_bs_code(ts_code: str) -> str:
    parts = ts_code.split(".")
    return f"{parts[1].lower()}.{parts[0]}" if len(parts) == 2 else ts_code


def _get_annual_dividend(bs_code: str, year: str) -> float:
    """获取某只股票某年的每股分红（税前）。"""
    rs_div = bs.query_dividend_data(code=bs_code, year=year, yearType="operate")
    if rs_div.error_code != "0":
        return 0.0
    df_div = rs_div.get_data()
    if df_div.empty:
        return 0.0
    div_col = "dividCashPsBeforeTax"
    if div_col not in df_div.columns:
        return 0.0
    return pd.to_numeric(df_div[div_col], errors="coerce").sum()


def screen_high_dividend(dividend_threshold: float = DIVIDEND_THRESHOLD,
                         min_market_cap: float = MIN_MARKET_CAP) -> pd.DataFrame:
    """
    使用 baostock 筛选高股息率股票。
    遍历候选池，查询最新价和分红，计算股息率。
    """
    end_date = datetime.now()
    lookback = end_date - timedelta(days=90)
    start_str = lookback.strftime("%Y-%m-%d")
    end_str = end_date.strftime("%Y-%m-%d")

    print(f"\nScanning {len(HIGH_DIV_SECTORS)} candidates...", flush=True)
    print(f"Criteria: dividend > {dividend_threshold}%, market cap > {min_market_cap}B", flush=True)
    print(f"Price range: {start_str} ~ {end_str}\n", flush=True)

    bs.login()
    results = []

    for i, ts_code in enumerate(HIGH_DIV_SECTORS, 1):
        bs_code = _to_bs_code(ts_code)
        name = ts_code

        try:
            # 1. Latest price
            time.sleep(0.25)
            rs = bs.query_history_k_data_plus(
                bs_code, "date,close", start_date=start_str, end_date=end_str,
                frequency="d", adjustflag="2",
            )
            if rs.error_code != "0":
                continue
            df_price = rs.get_data()
            if df_price.empty:
                continue

            df_price["close"] = pd.to_numeric(df_price["close"], errors="coerce")
            df_price.dropna(subset=["close"], inplace=True)
            if df_price.empty:
                continue
            latest_price = float(df_price["close"].iloc[-1])

            # 2. Dividend (2025 + 2024)
            time.sleep(0.25)
            div_2025 = _get_annual_dividend(bs_code, "2025")
            time.sleep(0.25)
            div_2024 = _get_annual_dividend(bs_code, "2024")
            dividend = div_2025 if div_2025 > 0 else div_2024

            if dividend <= 0 or latest_price <= 0:
                continue

            div_yield = (dividend / latest_price) * 100
            if div_yield < dividend_threshold:
                continue

            # 3. Stock name
            time.sleep(0.25)
            rs_name = bs.query_stock_basic(code=bs_code)
            if rs_name.error_code == "0":
                df_name = rs_name.get_data()
                if not df_name.empty and "code_name" in df_name.columns:
                    name = df_name["code_name"].iloc[0]

            print(f"  [{i:3d}/{len(HIGH_DIV_SECTORS)}] {name} ({ts_code}) "
                  f"yield={div_yield:.1f}%  price={latest_price:.2f}  div={dividend:.4f}", flush=True)

            results.append({
                "股票代码": ts_code,
                "股票名称": name,
                "股息率TTM(%)": round(div_yield, 2),
                "最新价(元)": round(latest_price, 2),
                "近一年分红(元)": round(dividend, 4),
                "数据日期": datetime.now().strftime("%Y-%m-%d"),
            })

        except Exception as e:
            logger.debug("%s query failed: %s", ts_code, e)
            continue

    bs.logout()

    df_result = pd.DataFrame(results)
    if not df_result.empty:
        df_result = df_result.sort_values("股息率TTM(%)", ascending=False)
        df_result["总市值(亿元)"] = "N/A"

    return df_result


def main():
    import sys
    if sys.platform == "win32":
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    print("=" * 60)
    print("高股息率股票筛选 (Baostock 免费数据源)")
    print(f"筛选条件: 股息率 > {DIVIDEND_THRESHOLD}%, 市值 > {MIN_MARKET_CAP} 亿")
    print(f"候选池: {len(HIGH_DIV_SECTORS)} 只")
    print("=" * 60)

    df = screen_high_dividend()

    if df.empty:
        print("\n未找到符合条件的股票。")
        return

    print(f"\n{'=' * 60}")
    print(f"共筛选出 {len(df)} 只高股息股票:")
    print(f"{'=' * 60}")
    for _, row in df.iterrows():
        print(f"  {row['股票名称']:8s} ({row['股票代码']:12s})  股息率: {row['股息率TTM(%)']:5.1f}%  "
              f"最新价: {row['最新价(元)']:6.2f}  分红: {row['近一年分红(元)']:6.4f}")

    # 保存 CSV
    output_dir = Path("output")
    output_dir.mkdir(exist_ok=True)
    csv_path = output_dir / f"高股息筛选结果_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    df.to_csv(csv_path, index=False, encoding="utf-8-sig")
    print(f"\n结果已保存: {csv_path}")


if __name__ == "__main__":
    main()
