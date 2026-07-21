"""
Tushare 数据获取层 — 带重试、限流、并发、缓存。
"""

import functools
import hashlib
import json
import sqlite3
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable

import pandas as pd
import tushare as ts

from config import (
    TUSHARE_TOKEN, TUSHARE_API_URL, REQUEST_TIMEOUT,
    MAX_RETRIES, RETRY_DELAY, RETRY_BACKOFF,
    MAX_CONCURRENT_WORKERS, API_CALL_DELAY,
    CACHE_DIR, CACHE_ENABLED, CACHE_TTL_HOURS,
)

from common import setup_logging

logger = setup_logging("data_fetcher")

# ===================== Tushare 初始化 =====================
pro = ts.pro_api(token=TUSHARE_TOKEN, timeout=REQUEST_TIMEOUT)
if TUSHARE_API_URL:
    pro._DataApi__http_url = TUSHARE_API_URL

# ===================== 重试装饰器 =====================
def retry(max_tries: int = MAX_RETRIES, delay: float = RETRY_DELAY,
          backoff: float = RETRY_BACKOFF):
    """带指数退避的重试装饰器。"""
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            last_exc = None
            current_delay = delay
            for attempt in range(1, max_tries + 1):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    last_exc = e
                    if attempt < max_tries:
                        logger.warning(
                            "%s 失败 (第 %d/%d 次): %s，%0.1fs 后重试",
                            func.__name__, attempt, max_tries, e, current_delay,
                        )
                        time.sleep(current_delay)
                        current_delay *= backoff
                    else:
                        logger.error(
                            "%s 全部 %d 次重试失败: %s",
                            func.__name__, max_tries, e,
                        )
            raise last_exc  # type: ignore[misc]
        return wrapper
    return decorator


# ===================== 限流 =====================
_last_call_time = 0.0

def _rate_limit():
    global _last_call_time
    now = time.time()
    elapsed = now - _last_call_time
    if elapsed < API_CALL_DELAY:
        time.sleep(API_CALL_DELAY - elapsed)
    _last_call_time = time.time()


# ===================== SQLite 缓存 =====================
def _cache_db_path() -> Path:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return CACHE_DIR / "api_cache.db"

def _cache_key(func_name: str, args: tuple, kwargs: dict) -> str:
    raw = json.dumps({"f": func_name, "a": args, "k": kwargs}, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode()).hexdigest()

def _init_cache_db():
    db_path = _cache_db_path()
    with sqlite3.connect(str(db_path)) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS cache (
                key TEXT PRIMARY KEY,
                data BLOB,
                created_at REAL
            )
        """)
        conn.commit()

def _cache_get(key: str) -> pd.DataFrame | None:
    if not CACHE_ENABLED:
        return None
    db_path = _cache_db_path()
    try:
        with sqlite3.connect(str(db_path)) as conn:
            row = conn.execute(
                "SELECT data, created_at FROM cache WHERE key = ?", (key,)
            ).fetchone()
            if row is None:
                return None
            data_blob, created_at = row
            age_hours = (time.time() - created_at) / 3600
            if age_hours > CACHE_TTL_HOURS:
                conn.execute("DELETE FROM cache WHERE key = ?", (key,))
                conn.commit()
                return None
            return pd.read_json(data_blob)
    except Exception:
        return None

def _cache_set(key: str, df: pd.DataFrame):
    if not CACHE_ENABLED:
        return
    db_path = _cache_db_path()
    try:
        _init_cache_db()
        with sqlite3.connect(str(db_path)) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO cache (key, data, created_at) VALUES (?, ?, ?)",
                (key, df.to_json(), time.time()),
            )
            conn.commit()
    except Exception as e:
        logger.debug("缓存写入失败: %s", e)

def cached_api(func: Callable) -> Callable:
    """为 API 调用自动添加 SQLite 缓存。"""
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        key = _cache_key(func.__name__, args, kwargs)
        cached = _cache_get(key)
        if cached is not None:
            logger.debug("缓存命中: %s", func.__name__)
            return cached
        _rate_limit()
        result = func(*args, **kwargs)
        if isinstance(result, pd.DataFrame) and not result.empty:
            _cache_set(key, result)
        return result
    return wrapper


# ===================== 数据获取 API =====================

@retry()
@cached_api
def get_daily(ts_code: str, start_date: str, end_date: str,
              fields: str = "trade_date,open,high,low,close,vol,amount") -> pd.DataFrame:
    """获取个股/ETF 日线数据。"""
    df = pro.daily(ts_code=ts_code, start_date=start_date, end_date=end_date, fields=fields)
    if df.empty:
        return df
    df["trade_date"] = pd.to_datetime(df["trade_date"])
    df = df.sort_values("trade_date").reset_index(drop=True)
    return df


def get_etf_daily(etf_code: str, start_date: str, end_date: str,
                  fields: str = "trade_date,open,high,low,close,vol,amount") -> pd.DataFrame:
    """
    获取 ETF 基金日线数据。

    数据源优先级:
    1. efinance fund API — 免费，13 年净值数据（净值 → close）
    2. baostock — 免费，仅 6 个月 K 线（兜底）
    """
    # 先尝试 efinance（完整历史）
    try:
        from common.efinance_source import get_etf_daily as ef_get_etf
        df = ef_get_etf(etf_code, start_date, end_date)
        if not df.empty and len(df) > 50:
            logger.info("ETF %s 使用 efinance，%d 条数据", etf_code, len(df))
            return df
    except Exception as e:
        logger.debug("efinance ETF 失败: %s", e)

    # 回退到 baostock
    from common.baostock_source import get_etf_daily as bs_get_etf
    bs_fields = fields.replace("vol", "volume")
    df = bs_get_etf(etf_code, start_date, end_date, bs_fields)
    if df.empty:
        return df
    if "date" in df.columns and "trade_date" not in df.columns:
        df.rename(columns={"date": "trade_date"}, inplace=True)
    if "trade_date" in df.columns:
        df["trade_date"] = pd.to_datetime(df["trade_date"])
    if "volume" in df.columns and "vol" not in df.columns:
        df.rename(columns={"volume": "vol"}, inplace=True)
    return df


@retry()
@cached_api
def get_weekly(ts_code: str, start_date: str, end_date: str,
               fields: str = "trade_date,close") -> pd.DataFrame:
    """获取周线数据。"""
    df = pro.weekly(ts_code=ts_code, start_date=start_date, end_date=end_date, fields=fields)
    if df.empty:
        return df
    df["trade_date"] = pd.to_datetime(df["trade_date"])
    df = df.sort_values("trade_date").reset_index(drop=True)
    return df


def get_daily_basic(trade_date: str) -> pd.DataFrame:
    """获取某日全市场每日指标（含股息率、市值等）。
    结果缓存到本地 parquet 文件，同一交易日 24h 内不重复请求（绕过 1次/小时限制）。
    """
    cache_file = CACHE_DIR / f"daily_basic_{trade_date}.parquet"
    # 检查文件缓存
    if cache_file.exists():
        age_hours = (time.time() - cache_file.stat().st_mtime) / 3600
        if age_hours < 24:
            logger.info("daily_basic(%s) 使用文件缓存 (%.1fh 前)", trade_date, age_hours)
            return pd.read_parquet(cache_file)

    # 也检查 SQLite 缓存
    key = _cache_key("daily_basic", (trade_date,), {})
    cached = _cache_get(key)
    if cached is not None:
        return cached

    _rate_limit()
    df = pro.daily_basic(trade_date=trade_date)
    if not df.empty:
        # 保存文件缓存
        try:
            df.to_parquet(cache_file, index=False)
        except Exception:
            pass
        _cache_set(key, df)
    return df


@retry()
def get_stock_basic(ts_code: str | None = None,
                    fields: str = "ts_code,name") -> pd.DataFrame:
    """获取股票基本信息。"""
    _rate_limit()
    kwargs = {"fields": fields}
    if ts_code:
        kwargs["ts_code"] = ts_code
    return pro.stock_basic(**kwargs)


def get_intraday(ts_code: str, start_date: str, end_date: str,
                 freq: str = "1min") -> pd.DataFrame:
    """获取分钟分时数据 — Tushare 优先，失败则用 baostock 5分钟线。"""
    # 尝试 Tushare（不缓存分时数据，不重试以避免频率限制雪上加霜）
    try:
        _rate_limit()
        df = ts.pro_bar(ts_code=ts_code, start_date=start_date, end_date=end_date, freq=freq)
        if not df.empty:
            df["trade_time"] = pd.to_datetime(df["trade_time"])
            df = df.sort_values("trade_time").reset_index(drop=True)
            return df
    except Exception as e:
        logger.info("Tushare 分时获取失败，回退到 baostock: %s", str(e)[:80])

    # 回退到 baostock 5分钟线
    try:
        from common.baostock_source import get_intraday as bs_get_intraday
        df = bs_get_intraday(ts_code, start_date, end_date, freq="5")
        if df.empty:
            return df
        # 转换为分时格式（与 Tushare 兼容）
        if "date" in df.columns:
            df.drop(columns=["date"], inplace=True, errors="ignore")
        return df
    except Exception as e:
        logger.error("baostock 分时获取也失败: %s", e)
        return pd.DataFrame()


@retry()
def get_latest_trade_date() -> str:
    """获取最近一个交易日。"""
    today = datetime.now().strftime("%Y%m%d")
    df = pro.daily(trade_date=today, fields="trade_date")
    if not df.empty:
        return today
    yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y%m%d")
    return yesterday


# ===================== 复合业务方法 =====================

def get_stock_multi_period(stock_code: str, years: int = 3) -> dict[str, pd.DataFrame]:
    """
    获取股票的近1/2/3年数据 — 只拉一次3年数据，在内存中切片。
    返回 {"1y": df, "2y": df, "3y": df}
    """
    end_date = datetime.now()
    start_3y = end_date - timedelta(days=years * 365 + 30)  # 多取一些缓冲

    start_str = start_3y.strftime("%Y%m%d")
    end_str = end_date.strftime("%Y%m%d")

    df_full = get_daily(stock_code, start_str, end_str)
    if df_full.empty:
        return {"1y": pd.DataFrame(), "2y": pd.DataFrame(), "3y": pd.DataFrame()}

    df_full = df_full.sort_values("trade_date").reset_index(drop=True)

    def slice_from(df: pd.DataFrame, n_years: int) -> pd.DataFrame:
        cutoff = end_date - timedelta(days=n_years * 365)
        return df[df["trade_date"] >= cutoff].reset_index(drop=True)

    return {
        "1y": slice_from(df_full, 1),
        "2y": slice_from(df_full, 2),
        "3y": df_full,
    }


def batch_fetch(codes: list[str], names: list[str],
                fetcher: Callable, max_workers: int = MAX_CONCURRENT_WORKERS,
                desc: str = "fetch") -> list[dict]:
    """
    并发批量获取数据。
    fetcher(code, name) -> dict | None，失败返回 None 则跳过。
    """
    results: list[dict] = []
    total = len(codes)

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(fetcher, code, name): (code, name)
            for code, name in zip(codes, names)
        }
        for i, future in enumerate(as_completed(futures), 1):
            code, name = futures[future]
            try:
                result = future.result()
                if result is not None:
                    results.append(result)
                    logger.info("[%d/%d] %s %s 成功", i, total, desc, name)
                else:
                    logger.warning("[%d/%d] %s %s 返回空，已跳过", i, total, desc, name)
            except Exception as e:
                logger.error("[%d/%d] %s %s 失败: %s", i, total, desc, name, e)

    return results


def get_all_stock_names(ts_codes: list[str]) -> dict[str, str]:
    """批量获取股票名称映射，一次 API 调用完成。"""
    _rate_limit()
    try:
        df = pro.stock_basic(
            ts_code=",".join(ts_codes),
            fields="ts_code,name",
        )
        if df.empty:
            return {}
        return dict(zip(df["ts_code"], df["name"]))
    except Exception as e:
        logger.warning("批量获取股票名称失败: %s", e)
        return {}


def get_ma_value(ts_code: str, end_date: str, window: int = 250,
                 freq: str = "daily") -> float | None:
    """
    通用均线计算。freq 可选 'daily' / 'weekly'。

    周线均线始终从日线重采样构造，避免 weekly API 的频率限制。
    """
    try:
        if freq == "weekly":
            # 始终从日线构造周线，避免 weekly API 频率限制（免费用户 1次/分钟）
            lookback_days = (window + 30) * 7 + 30
            start = (datetime.strptime(end_date, "%Y%m%d") - timedelta(days=lookback_days)).strftime("%Y%m%d")
            df_daily = get_daily(ts_code, start, end_date, "trade_date,close")
            if len(df_daily) < window * 5:
                return None
            df_daily["trade_date"] = pd.to_datetime(df_daily["trade_date"])
            df_indexed = df_daily.set_index("trade_date").sort_index()
            weekly = df_indexed["close"].resample("W-FRI").last().dropna()
            if len(weekly) < window:
                return None
            return round(float(weekly.rolling(window).mean().iloc[-1]), 2)
        else:
            lookback_days = window + 60
            start = (datetime.strptime(end_date, "%Y%m%d") - timedelta(days=lookback_days)).strftime("%Y%m%d")
            df = get_daily(ts_code, start, end_date, "trade_date,close")
            if len(df) < window:
                return None

        df = df.sort_values("trade_date")
        ma = df["close"].rolling(window).mean().iloc[-1]
        return round(float(ma), 2)
    except Exception as e:
        logger.error("获取 %s 均线失败: %s", ts_code, e)
        return None
