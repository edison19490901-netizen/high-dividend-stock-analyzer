"""
Baostock 免费数据源 — 不需要 token，支持 ETF、个股、基本面。

作为 Tushare 权限不足时的补充：
- ETF 日线（Tushare fund_daily 需付费，baostock 免费）
- 基本面筛选（Tushare daily_basic 频率受限，baostock 免费）
"""

import functools
import time
from datetime import datetime, timedelta
from typing import Any

import baostock as bs
import pandas as pd

from common import setup_logging

logger = setup_logging("baostock")

_last_call = 0.0
_MIN_INTERVAL = 0.3  # 请求间隔


def _rate_limit():
    global _last_call
    now = time.time()
    elapsed = now - _last_call
    if elapsed < _MIN_INTERVAL:
        time.sleep(_MIN_INTERVAL - elapsed)
    _last_call = time.time()


def _ensure_login():
    """确保已登录 baostock。"""
    _rate_limit()
    bs.login()


def _ensure_logout():
    """登出以释放连接。"""
    try:
        bs.logout()
    except Exception:
        pass


# ===================== 代码格式转换 =====================

def _to_baostock_code(ts_code: str) -> str:
    """
    Tushare 代码 → Baostock 代码。
    '000651.SZ' → 'sz.000651'
    '600941.SH' → 'sh.600941'
    '159928.SZ' → 'sz.159928'
    """
    parts = ts_code.split(".")
    if len(parts) == 2:
        return f"{parts[1].lower()}.{parts[0]}"
    return ts_code


def _from_baostock_code(bs_code: str) -> str:
    """
    Baostock 代码 → Tushare 代码。
    'sz.000651' → '000651.SZ'
    """
    parts = bs_code.split(".")
    if len(parts) == 2:
        return f"{parts[1]}.{parts[0].upper()}"
    return bs_code


def _normalize_date(date_str: str) -> str:
    """将 YYYYMMDD 或 YYYY-MM-DD 统一转为 YYYY-MM-DD。"""
    date_str = date_str.strip().replace("-", "")
    if len(date_str) == 8:
        return f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]}"
    return date_str


# ===================== 日线数据 =====================

def get_daily(ts_code: str, start_date: str, end_date: str,
              fields: str = "date,open,high,low,close,volume,amount") -> pd.DataFrame:
    """
    获取个股/ETF 日线数据（baostock 两者都支持）。
    """
    bs_code = _to_baostock_code(ts_code)
    # 字段映射: baostock 用 date 而非 trade_date
    bs_fields = fields.replace("trade_date", "date")
    start_date = _normalize_date(start_date)
    end_date = _normalize_date(end_date)

    try:
        _ensure_login()
        rs = bs.query_history_k_data_plus(
            bs_code, bs_fields,
            start_date=start_date, end_date=end_date,
            frequency="d", adjustflag="2",  # 前复权
        )
        if rs.error_code != "0":
            logger.warning("baostock 查询 %s 失败: %s", ts_code, rs.error_msg)
            return pd.DataFrame()

        rows = rs.get_data()
        if rows.empty:
            return pd.DataFrame()

        # 类型转换
        numeric_cols = ["open", "high", "low", "close", "volume", "amount"]
        for c in numeric_cols:
            if c in rows.columns:
                rows[c] = pd.to_numeric(rows[c], errors="coerce")

        if "date" in rows.columns:
            rows.rename(columns={"date": "trade_date"}, inplace=True)
            rows["trade_date"] = pd.to_datetime(rows["trade_date"])

        rows = rows.sort_values("trade_date").reset_index(drop=True)
        return rows

    except Exception as e:
        logger.error("baostock 获取 %s 失败: %s", ts_code, e)
        return pd.DataFrame()
    finally:
        _ensure_logout()


# ===================== ETF 日线（直接复用 get_daily） =====================

def get_etf_daily(etf_code: str, start_date: str, end_date: str,
                  fields: str = "date,open,high,low,close,volume,amount") -> pd.DataFrame:
    """ETF 日线 — baostock 对 ETF 和个股用同一个接口。"""
    return get_daily(etf_code, start_date, end_date, fields)


# ===================== 基本面筛选 =====================

def get_stock_basic_info() -> pd.DataFrame:
    """
    获取全市场股票基本信息（含市值）。
    """
    try:
        _ensure_login()
        # 获取交易日
        today = datetime.now().strftime("%Y-%m-%d")
        yesterday = (datetime.now() - timedelta(days=5)).strftime("%Y-%m-%d")

        # 尝试获取最新交易日估值数据
        rs = bs.query_stock_industry()
        if rs.error_code != "0":
            logger.warning("baostock 行业查询失败: %s", rs.error_msg)
            return pd.DataFrame()

        industries = rs.get_data()

        # 获取全量股价和市值
        all_data = []
        # 分页查询沪深 A 股
        for code_prefix in ["sh", "sz"]:
            page = 1
            while page <= 50:  # 安全上限
                _rate_limit()
                rs_k = bs.query_history_k_data_plus(
                    f"{code_prefix}.000001" if code_prefix == "sh" else f"{code_prefix}.000001",
                    "date,code,close",
                    start_date=yesterday, end_date=today,
                    frequency="d", adjustflag="2",
                )
                break  # 改用逐只查询方式
            break

        return industries

    except Exception as e:
        logger.error("baostock 基本面查询失败: %s", e)
        return pd.DataFrame()
    finally:
        _ensure_logout()


def get_dividend_data(code: str, year: str = "2025") -> pd.DataFrame:
    """
    获取单只股票的分红数据。

    返回 DataFrame，含 dividend（每股分红）等字段。
    """
    try:
        _ensure_login()
        bs_code = _to_baostock_code(code)
        rs = bs.query_dividend_data(code=bs_code, year=year, yearType="operate")
        if rs.error_code != "0":
            return pd.DataFrame()
        return rs.get_data()
    except Exception as e:
        logger.error("baostock 分红查询 %s 失败: %s", code, e)
        return pd.DataFrame()
    finally:
        _ensure_logout()


def get_latest_trade_date() -> str:
    """获取最近交易日，返回 YYYYMMDD 格式。"""
    try:
        _ensure_login()
        today = datetime.now()
        for offset in range(10):
            d = (today - timedelta(days=offset)).strftime("%Y-%m-%d")
            rs = bs.query_history_k_data_plus(
                "sh.000001", "date", start_date=d, end_date=d, frequency="d",
            )
            if rs.error_code == "0" and not rs.get_data().empty:
                return d.replace("-", "")
        return today.strftime("%Y%m%d")
    except Exception:
        return datetime.now().strftime("%Y%m%d")
    finally:
        _ensure_logout()


def get_all_stocks_snapshot() -> pd.DataFrame:
    """
    获取全市场 A 股快照（股价、市值、PE 等）。
    用于股息率筛选。
    """
    try:
        _ensure_login()
        today_str = datetime.now().strftime("%Y-%m-%d")

        # 分批获取沪深 A 股日线估值数据
        all_rows = []
        for prefix, exchange in [("sh", "沪市"), ("sz", "深市")]:
            # 获取该交易所所有 A 股代码
            _rate_limit()
            rs = bs.query_stock_basic(code_name=f"{prefix}.000001")
            if rs.error_code != "0":
                continue

            # 用上证综指/深证成指做参考
            # 实际改用 query_all_stock 获取全量
            pass

        # 使用更可靠的方法：逐日查询当日行情
        _rate_limit()
        rs = bs.query_all_stock(day=today_str)
        if rs.error_code == "0":
            return rs.get_data()

        return pd.DataFrame()
    except Exception as e:
        logger.error("baostock 快照查询失败: %s", e)
        return pd.DataFrame()
    finally:
        _ensure_logout()


# ===================== 分时数据 =====================

def get_intraday(ts_code: str, start_date: str, end_date: str,
                 freq: str = "5") -> pd.DataFrame:
    """
    获取分钟级数据。
    baostock 支持: "5"(5分钟), "15", "30", "60"
    """
    bs_code = _to_baostock_code(ts_code)
    start_date = _normalize_date(start_date)
    end_date = _normalize_date(end_date)
    freq_map = {"1min": "5", "5min": "5", "15min": "15", "30min": "30", "60min": "60"}
    bs_freq = freq_map.get(freq, "5")

    try:
        _ensure_login()
        rs = bs.query_history_k_data_plus(
            bs_code,
            "date,time,open,high,low,close,volume,amount",
            start_date=start_date, end_date=end_date,
            frequency=bs_freq, adjustflag="2",
        )
        if rs.error_code != "0":
            logger.warning("baostock 分时查询 %s 失败: %s", ts_code, rs.error_msg)
            return pd.DataFrame()

        df = rs.get_data()
        if df.empty:
            return df

        # 合并 date + time → trade_time
        # baostock time 格式: "20260701093500000" (年月日时分秒毫秒)
        raw_time = df["time"].astype(str)
        # 截断到秒级: 取前 14 位 (YYYYMMDDHHMMSS)
        clean_time = raw_time.str[:14]
        df["trade_time"] = pd.to_datetime(clean_time, format="%Y%m%d%H%M%S", errors="coerce")
        numeric_cols = ["open", "high", "low", "close", "volume", "amount"]
        for c in numeric_cols:
            if c in df.columns:
                df[c] = pd.to_numeric(df[c], errors="coerce")

        df = df.sort_values("trade_time").reset_index(drop=True)
        return df
    except Exception as e:
        logger.error("baostock 分时获取 %s 失败: %s", ts_code, e)
        return pd.DataFrame()
    finally:
        _ensure_logout()


# ===================== 多周期数据（复用逻辑） =====================

def get_stock_multi_period(stock_code: str, years: int = 3) -> dict[str, pd.DataFrame]:
    """
    获取近 1/2/3 年日线，从 baostock 一次拉取后在内存切片。
    """
    end_date = datetime.now()
    start = end_date - timedelta(days=years * 365 + 60)
    start_str = start.strftime("%Y-%m-%d")
    end_str = end_date.strftime("%Y-%m-%d")

    df_full = get_daily(stock_code, start_str, end_str)
    if df_full.empty:
        return {"1y": pd.DataFrame(), "2y": pd.DataFrame(), "3y": pd.DataFrame()}

    def slice_period(df: pd.DataFrame, n_years: int) -> pd.DataFrame:
        cutoff = end_date - timedelta(days=n_years * 365)
        return df[df["trade_date"] >= cutoff].reset_index(drop=True)

    return {
        "1y": slice_period(df_full, 1),
        "2y": slice_period(df_full, 2),
        "3y": df_full,
    }
