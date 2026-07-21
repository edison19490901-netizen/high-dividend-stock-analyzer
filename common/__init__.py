"""
公共模块 — 日志配置、字体检测等共享工具。
"""

import logging
import sys
from pathlib import Path
from config import LOG_LEVEL, LOG_DIR


def setup_logging(name: str | None = None) -> logging.Logger:
    """创建按日期分文件的 logger，同时输出到控制台。"""
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    logger = logging.getLogger(name or __name__)
    logger.setLevel(getattr(logging, LOG_LEVEL.upper(), logging.INFO))

    # 避免重复添加 handler
    if logger.handlers:
        return logger

    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # 文件 handler — 按日期
    from datetime import datetime
    log_file = LOG_DIR / f"{datetime.now().strftime('%Y%m%d')}.log"
    fh = logging.FileHandler(log_file, encoding="utf-8")
    fh.setFormatter(formatter)
    logger.addHandler(fh)

    # 控制台 handler
    ch = logging.StreamHandler(sys.stdout)
    ch.setFormatter(formatter)
    logger.addHandler(ch)

    return logger


def detect_chinese_font() -> str:
    """自动检测系统可用中文字体，返回 matplotlib 可用的字体名。"""
    from matplotlib.font_manager import FontManager
    fm = FontManager()
    preferred = ["SimHei", "Microsoft YaHei", "WenQuanYi Micro Hei",
                  "Noto Sans CJK SC", "Source Han Sans SC", "PingFang SC",
                  "STHeiti", "AR PL UMing CN", "WenQuanYi Zen Hei"]
    available = {f.name for f in fm.ttflist}
    for font in preferred:
        if font in available:
            return font
    # Fallback: 无中文字体时返回 sans-serif，至少不报错
    return "sans-serif"
