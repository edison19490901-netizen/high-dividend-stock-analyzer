"""
定时任务脚本 — 分析完成后发送通知。
供 Render Cron Job 使用。
"""
import os
import subprocess
import sys
import urllib.request
import json
from pathlib import Path

BARK_KEY = os.getenv("BARK_KEY", "")
WECHAT_KEY = os.getenv("WECHAT_KEY", "")


def notify(title: str, body: str = ""):
    try:
        import urllib.parse
        if BARK_KEY:
            urllib.request.urlopen(
                f"https://api.day.app/{BARK_KEY}/{urllib.parse.quote(title)}/{urllib.parse.quote(body)}",
                timeout=10,
            )
        if WECHAT_KEY:
            data = json.dumps({"title": title, "desp": body}).encode()
            req = urllib.request.Request(
                f"https://sctapi.ftqq.com/{WECHAT_KEY}.send",
                data=data,
                headers={"Content-Type": "application/json"},
            )
            urllib.request.urlopen(req, timeout=10)
    except Exception as e:
        print(f"[notify] failed: {e}")


def run():
    print("Starting daily analysis...")
    r1 = subprocess.run(
        [sys.executable, "run_all.py", "--skip-screener", "--skip-intraday"],
        capture_output=False,
        env={**os.environ, "PYTHONUNBUFFERED": "1"},
    )
    r2 = subprocess.run(
        [sys.executable, "generate_dashboard.py"],
        capture_output=False,
    )

    # 清理锁文件
    lock = Path("output") / ".analysis_running"
    if lock.exists():
        lock.unlink()

    # 收集结果摘要
    summary = ""
    try:
        import pandas as pd
        for label, dir_name in [("个股", "company_batch_analysis"), ("ETF", "ETF_batch_analysis")]:
            p = Path("output") / dir_name
            if not p.exists():
                continue
            files = sorted(p.glob("*汇总*.xlsx"))
            if files:
                df = pd.read_excel(files[-1], sheet_name="投资建议汇总")
                below = df[df["相对位置"] == "低于"] if "相对位置" in df.columns else df.iloc[:0]
                summary += f"{label}: {len(df)} 只, 买入信号 {len(below)} 只\n"
                for _, row in below.iterrows():
                    summary += f"  - {row['名称']} 低于临界 {row['价格差异']}元\n"
    except Exception as e:
        summary = f"分析完成 (exit={r1.returncode},{r2.returncode})"

    notify("📊 每日分析完成", summary or "分析完成")


if __name__ == "__main__":
    run()
