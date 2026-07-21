"""
efinance 免费 ETF 数据源 — fund API 无需 token，支持 10+ 年净值数据。

与 baostock 互补：
- baostock: 仅 6 个月 ETF K线（2026-01 起）
- efinance fund API: 13 年 ETF 净值（2013 年起），但只有日净值，无 OHLC
"""

import time
from datetime import datetime, timedelta

import efinance as ef
import pandas as pd

from common import setup_logging

logger = setup_logging("efinance")

_last_call = 0.0
_MIN_INTERVAL = 0.5


def _rate_limit():
    global _last_call
    now = time.time()
    elapsed = now - _last_call
    if elapsed < _MIN_INTERVAL:
        time.sleep(_MIN_INTERVAL - elapsed)
    _last_call = time.time()


def get_etf_daily(etf_code: str, start_date: str, end_date: str,
                  fields: str = "trade_date,open,high,low,close,vol,amount") -> pd.DataFrame:
    """
    获取 ETF 日线数据。
    使用 efinance fund API（免费，13 年历史）。

    返回列: trade_date, close(=净值), open, high, low, vol(=0), amount(=0)
    注意：open/high/low/vol/amount 用 close 填充（API 无 OHLC 数据）。
    """
    try:
        code_clean = etf_code.split(".")[0]  # '159928.SZ' -> '159928'
        _rate_limit()
        df = ef.fund.get_quote_history(code_clean)

        if df is None or df.empty:
            logger.warning("efinance %s 无数据", etf_code)
            return pd.DataFrame()

        # 重命名列
        df = df.rename(columns={
            "日期": "trade_date",
            "单位净值": "close",
        })
        df["trade_date"] = pd.to_datetime(df["trade_date"])

        # 过滤日期范围
        if start_date:
            start_dt = pd.to_datetime(datetime.strptime(start_date, "%Y%m%d").strftime("%Y-%m-%d"))
            df = df[df["trade_date"] >= start_dt]
        if end_date:
            end_dt = pd.to_datetime(datetime.strptime(end_date, "%Y%m%d").strftime("%Y-%m-%d"))
            df = df[df["trade_date"] <= end_dt]

        if df.empty:
            return pd.DataFrame()

        # 填充 OHLC（净值只有 close，open/high/low 用 close 代替）
        df["open"] = df["close"]
        df["high"] = df["close"]
        df["low"] = df["close"]
        df["vol"] = 0
        df["amount"] = 0

        df = df.sort_values("trade_date").reset_index(drop=True)

        # 返回需要的列
        required = ["trade_date", "open", "high", "low", "close", "vol", "amount"]
        result_cols = [c for c in required if c in df.columns]
        return df[result_cols]

    except Exception as e:
        logger.error("efinance ETF %s 获取失败: %s", etf_code, e)
        return pd.DataFrame()
