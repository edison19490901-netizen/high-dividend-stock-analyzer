"""
一键执行全部分析流程。

用法:
    python run_all.py                       # 运行全部
    python run_all.py --skip-screener        # 跳过高股息筛选
    python run_all.py --skip-intraday        # 跳过日内分析
"""

import argparse
import sys
import traceback
from datetime import datetime

# Fix Windows GBK encoding for emoji
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from common import setup_logging

logger = setup_logging("run_all")


def main():
    parser = argparse.ArgumentParser(description="一键执行全部分析")
    parser.add_argument("--skip-screener", action="store_true", help="跳过高股息筛选")
    parser.add_argument("--skip-batch", action="store_true", help="跳过批量分析")
    parser.add_argument("--skip-intraday", action="store_true", help="跳过日内分时分析")
    parser.add_argument("--mode", choices=["stock", "etf", "all"], default="all",
                        help="批量分析模式 (default: all)")
    parser.add_argument("--intraday-code", default="003816.SZ",
                        help="日内分析股票代码 (default: 003816.SZ)")
    parser.add_argument("--intraday-name", default="中国广核",
                        help="日内分析股票名称")
    args = parser.parse_args()

    start_time = datetime.now()
    print("=" * 60)
    print("  高股息 + 高价值 + 低价格 分析系统")
    print(f"  启动时间: {start_time.strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    results = {"screener": None, "batch": None, "intraday": None}

    # ── 1. 高股息筛选 ──
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
            logger.error("筛选分析失败: %s", e)
            traceback.print_exc()
            results["screener"] = f"FAILED: {e}"
    else:
        print("\n⏭️ 跳过高股息筛选")

    # ── 2. 批量分析 ──
    if not args.skip_batch:
        print("\n" + "=" * 60)
        print("  [2/3] 批量 ETF / 个股统计分析")
        print("=" * 60)
        try:
            import batch_analysis
            batch_analysis.run_batch(mode=args.mode)
            results["batch"] = "OK"
        except Exception as e:
            logger.error("批量分析失败: %s", e)
            traceback.print_exc()
            results["batch"] = f"FAILED: {e}"
    else:
        print("\n⏭️ 跳过批量分析")

    # ── 3. 分时分析 ──
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
            traceback.print_exc()
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
