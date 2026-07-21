"""
全局配置管理 — 从 .env 文件和环境变量加载配置。
"""

import os
from pathlib import Path
from dotenv import load_dotenv

# 加载 .env 文件
env_path = Path(__file__).parent / ".env"
load_dotenv(dotenv_path=env_path, override=False)


def _env_float(key: str, default: float) -> float:
    try:
        return float(os.getenv(key, default))
    except (ValueError, TypeError):
        return default


def _env_int(key: str, default: int) -> int:
    try:
        return int(os.getenv(key, default))
    except (ValueError, TypeError):
        return default


# ===================== Tushare API =====================
TUSHARE_TOKEN = os.getenv("TUSHARE_TOKEN", "")
TUSHARE_API_URL = os.getenv("TUSHARE_API_URL", "") or ""

# ===================== 分析参数 =====================
DIVIDEND_THRESHOLD = _env_float("DIVIDEND_THRESHOLD", 5.0)        # 股息率阈值 (%)
MIN_MARKET_CAP = _env_int("MIN_MARKET_CAP", 500)                   # 最低市值 (亿)
CRITICAL_BUY_PREMIUM = _env_float("CRITICAL_BUY_PREMIUM", 1.15)    # 临界买点溢价倍数
PRICE_FILTER_MIN = _env_float("PRICE_FILTER_MIN", -20)             # 价格位置筛选下限 (%)
PRICE_FILTER_MAX = _env_float("PRICE_FILTER_MAX", 20)              # 价格位置筛选上限 (%)

# ===================== 图表参数 =====================
CHART_DPI = 300
CHART_BINS = 21
CHART_FIGSIZE_WIDE = (18, 10)
CHART_FIGSIZE_NORMAL = (16, 8)

# ===================== 网络 / 性能 =====================
REQUEST_TIMEOUT = 30
MAX_RETRIES = 3
RETRY_DELAY = 2.0
RETRY_BACKOFF = 2.0
MAX_CONCURRENT_WORKERS = 3
API_CALL_DELAY = 0.3          # 请求间隔 (秒)，用于限流

# ===================== 缓存 =====================
CACHE_DIR = Path(__file__).parent / ".cache"
CACHE_ENABLED = True
CACHE_TTL_HOURS = 6            # 日线数据缓存 6 小时

# ===================== 日志 =====================
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
LOG_DIR = Path(__file__).parent / "logs"

# ===================== 输出 =====================
OUTPUT_DIR_STOCKS = Path(__file__).parent / "output" / "company_batch_analysis"
OUTPUT_DIR_ETFS = Path(__file__).parent / "output" / "ETF_batch_analysis"
OUTPUT_DIR_SCREENER = Path(__file__).parent / "output" / "high_divde_company_batch_analysis"
OUTPUT_DIR_INTRADAY = Path(__file__).parent / "output" / "company"
