"""
一键执行全部分析流程。

用法:
    python run_all.py                              # 筛选 + 批量 + 分时
    python run_all.py --stock-list my_stocks.csv   # 筛选基础上追加自选股
    python run_all.py --skip-screener              # 跳过高股息筛选
"""

import argparse
import csv
import os
import sys
import traceback
from datetime import datetime
from pathlib import Path

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from common import setup_logging

logger = setup_logging("run_all")

SCREENED_CSV = "output/screened_stocks.csv"


def _merge_extra_stocks(screened_file: str, extra_file: str) -> str:
    """
    以筛选结果为基准，追加手动列表中不在筛选结果中的新股票（按 code 去重）。
    """
    codes_seen: set[str] = set()
    merged: list[tuple[str, str]] = []

    for fpath in [screened_file, extra_file]:
        if not os.path.exists(fpath):
            continue
        with open(fpath, "r", encoding="utf-8-sig") as f:
            for row in csv.reader(f):
                if not row or len(row) < 2:
                    continue
                code, name = row[0].strip(), row[1].strip()
                if code.startswith("#") or code.lower() == "code":
                    continue
                if code not in codes_seen:
                    codes_seen.add(code)
                    merged.append((code, name))

    merged_path = Path("output") / "merged_stocks.csv"
    merged_path.parent.mkdir(exist_ok=True)
    with open(merged_path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["code", "name"])
        writer.writerows(merged)

    logger.info("合并后共 %d 只个股", len(merged))
    return str(merged_path)


def main():
    parser = argparse.ArgumentParser(description="一键执行全部分析")
    parser.add_argument("--skip-screener", action="store_true")
    parser.add_argument("--skip-batch", action="store_true")
    parser.add_argument("--skip-intraday", action="store_true")
    parser.add_argument("--stock-list", type=str, default=None,
                        help="追加的自选股 CSV/TXT")
    parser.add_argument("--etf-list", type=str, default=None,
                        help="自定义 ETF 列表 CSV/TXT")
    parser.add_argument("--intraday-code", default="003816.SZ")
    parser.add_argument("--intraday-name", default="中国广核")
    args = parser.parse_args()

    start_time = datetime.now()
    print("=" * 60)
    print("  高股息 + 高价值 + 低价格 分析系统")
    print(f"  启动时间: {start_time.strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    results = {"screener": None, "batch": None, "intraday": None}

    # ── 1. 筛选 ──
    stock_list = args.stock_list
    if not args.skip_screener:
        print("\n" + "=" * 60)
        print("  [1/3] 高股息率股票筛选 (Baostock)")
        print("=" * 60)
        try:
            import screener_baostock
            screener_baostock.main()
            results["screener"] = "OK"
        except SystemExit:
            pass
        except Exception as e:
            logger.error("筛选失败: %s", e)
            results["screener"] = f"FAILED: {e}"

        # 筛选结果 + 追加自选股
        if os.path.exists(SCREENED_CSV):
            if args.stock_list:
                stock_list = _merge_extra_stocks(SCREENED_CSV, args.stock_list)
                print(f"  📋 筛选结果 + 追加自选 → {stock_list}")
            else:
                stock_list = SCREENED_CSV
                print(f"  📋 筛选结果: {SCREENED_CSV}")
    else:
        print("\n⏭️ 跳过高股息筛选")

    # ── 2. 批量分析 ──
    if not args.skip_batch:
        print("\n" + "=" * 60)
        print("  [2/3] 批量 ETF / 个股统计分析")
        print("=" * 60)
        try:
            import batch_analysis
            batch_analysis.run_batch(
                stock_list=stock_list,
                etf_list=args.etf_list,
            )
            results["batch"] = "OK"
        except Exception as e:
            logger.error("批量分析失败: %s", e)
            traceback.print_exc()
            results["batch"] = f"FAILED: {e}"
    else:
        print("\n⏭️ 跳过批量分析")

    # ── 3. 分时 ──
    if not args.skip_intraday:
        print("\n" + "=" * 60)
        print("  [3/3] 分时数据统计分析")
        print("=" * 60)
        try:
            import intraday_analysis
            intraday_analysis.analyze_intraday(
                args.intraday_code, args.intraday_name,
            )
            results["intraday"] = "OK"
        except Exception as e:
            logger.error("日内分析失败: %s", e)
            results["intraday"] = f"FAILED: {e}"
    else:
        print("\n⏭️ 跳过分时分析")

    # ── 报告 ──
    elapsed = (datetime.now() - start_time).total_seconds()
    print("\n" + "=" * 60)
    print(f"  执行完毕 — 耗时 {elapsed:.0f}s")
    for step, status in results.items():
        emoji = "✅" if status == "OK" else ("❌" if status else "⏭️")
        print(f"  {emoji} {step}: {status or '跳过'}")
    print("=" * 60)


if __name__ == "__main__":
    main()
