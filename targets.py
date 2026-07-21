"""
分析标的配置 — 新增/删除标的只需修改此文件。
"""

# ===================== 个股列表 =====================
STOCK_TARGETS: list[dict[str, str]] = [
    {"code": "000651.SZ", "name": "格力电器"},
    {"code": "000333.SZ", "name": "美的集团"},
    {"code": "600690.SH", "name": "海尔智家"},
    {"code": "601728.SH", "name": "中国电信"},
    {"code": "003816.SZ", "name": "中国广核"},
    {"code": "601985.SH", "name": "中国核电"},
    {"code": "600795.SH", "name": "国电电力"},
    {"code": "601919.SH", "name": "中远海控"},
    {"code": "600916.SH", "name": "中国黄金"},
    {"code": "000001.SZ", "name": "平安银行"},
    {"code": "601000.SH", "name": "唐山港"},
    {"code": "000999.SZ", "name": "华润三九"},
    {"code": "600900.SH", "name": "长江电力"},
    {"code": "600011.SH", "name": "华能国际"},
    {"code": "600886.SH", "name": "国投电力"},
    {"code": "600887.SH", "name": "伊利股份"},
    {"code": "600941.SH", "name": "中国移动"},
    {"code": "000429.SZ", "name": "粤高速A"},
    {"code": "000630.SZ", "name": "铜陵有色"},
    {"code": "601857.SH", "name": "中国石油"},
]


# ===================== ETF 列表 =====================
ETF_TARGETS: list[dict[str, str]] = [
    {"code": "159928.SZ", "name": "中证消费ETF"},
    {"code": "515790.SH", "name": "光伏ETF"},
    {"code": "515220.SH", "name": "煤炭ETF国泰"},
    {"code": "159915.SZ", "name": "创业板ETF"},
    {"code": "159611.SZ", "name": "电力ETF"},
    {"code": "159516.SZ", "name": "半导体设备ETF国泰"},
    {"code": "512880.SH", "name": "证券ETF"},
    {"code": "159692.SZ", "name": "证券东财ETF"},
    {"code": "512660.SH", "name": "军工ETF"},
    {"code": "516080.SH", "name": "创新药ETF"},
    {"code": "516770.SH", "name": "游戏ETF华泰博瑞"},
    {"code": "516010.SH", "name": "游戏ETF国泰"},
    {"code": "515880.SH", "name": "通信ETF"},
    {"code": "588780.SH", "name": "科创芯片设计ETF国联安"},
    {"code": "159848.SZ", "name": "证券国联ETF"},
    {"code": "159741.SZ", "name": "恒科ETF嘉实"},
    {"code": "588080.SH", "name": "科创50ETF易方达"},
]
