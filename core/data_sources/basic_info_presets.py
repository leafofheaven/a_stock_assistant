"""Local static stock basic-info presets for controlled real-data validation."""

from __future__ import annotations

from typing import Any

import pandas as pd

from core.data_sources.universe_presets import get_universe_preset, to_akshare_symbol, to_ts_code


BASIC_INFO_PRESETS: dict[str, dict[str, Any]] = {
    "000001": {"name": "平安银行", "industry": "银行", "list_date": "19910403"},
    "000002": {"name": "万  科Ａ", "industry": "房地产开发", "list_date": "19910129"},
    "000063": {"name": "中兴通讯", "industry": "通信设备", "list_date": "19971118"},
    "000333": {"name": "美的集团", "industry": "家用电器", "list_date": "20130918"},
    "000651": {"name": "格力电器", "industry": "家用电器", "list_date": "19961118"},
    "000725": {"name": "京东方Ａ", "industry": "光学光电子", "list_date": "20010112"},
    "000858": {"name": "五 粮 液", "industry": "白酒", "list_date": "19980427"},
    "002027": {"name": "分众传媒", "industry": "广告营销", "list_date": "20040804"},
    "002142": {"name": "宁波银行", "industry": "银行", "list_date": "20070719"},
    "002230": {"name": "科大讯飞", "industry": "软件开发", "list_date": "20080512"},
    "002415": {"name": "海康威视", "industry": "计算机设备", "list_date": "20100528"},
    "002475": {"name": "立讯精密", "industry": "消费电子", "list_date": "20100915"},
    "002594": {"name": "比亚迪", "industry": "汽车整车", "list_date": "20110630"},
    "002714": {"name": "牧原股份", "industry": "养殖业", "list_date": "20140128"},
    "300014": {"name": "亿纬锂能", "industry": "电池", "list_date": "20091030"},
    "300015": {"name": "爱尔眼科", "industry": "医疗服务", "list_date": "20091030"},
    "300059": {"name": "东方财富", "industry": "互联网金融", "list_date": "20100319"},
    "300122": {"name": "智飞生物", "industry": "生物制品", "list_date": "20100928"},
    "300124": {"name": "汇川技术", "industry": "自动化设备", "list_date": "20100928"},
    "300274": {"name": "阳光电源", "industry": "光伏设备", "list_date": "20111102"},
    "300750": {"name": "宁德时代", "industry": "电池", "list_date": "20180611"},
    "600000": {"name": "浦发银行", "industry": "银行", "list_date": "19991110"},
    "600009": {"name": "上海机场", "industry": "机场航运", "list_date": "19980218"},
    "600036": {"name": "招商银行", "industry": "银行", "list_date": "20020409"},
    "600050": {"name": "中国联通", "industry": "通信服务", "list_date": "20021009"},
    "600519": {"name": "贵州茅台", "industry": "白酒", "list_date": "20010827"},
    "600585": {"name": "海螺水泥", "industry": "水泥建材", "list_date": "20020207"},
    "600887": {"name": "伊利股份", "industry": "食品饮料", "list_date": "19960312"},
    "601318": {"name": "中国平安", "industry": "保险", "list_date": "20070301"},
    "688981": {"name": "中芯国际", "industry": "半导体", "list_date": "20200716"},
}


def get_basic_info(symbol: str) -> dict[str, Any]:
    """Return local basic-info preset for one symbol or an empty dict."""
    raw = to_akshare_symbol(symbol)
    item = BASIC_INFO_PRESETS.get(raw)
    if not item:
        return {}
    ts_code = to_ts_code(raw)
    return {
        "ts_code": ts_code,
        "symbol": raw,
        "name": item.get("name"),
        "area": item.get("area", pd.NA),
        "industry": item.get("industry"),
        "market": _market_from_ts_code(ts_code),
        "list_date": item.get("list_date"),
        "delist_date": item.get("delist_date", pd.NA),
        "is_hs": item.get("is_hs", pd.NA),
    }


def get_basic_info_for_preset(preset_name: str) -> pd.DataFrame:
    """Return local basic-info rows for one universe preset."""
    rows = [get_basic_info(symbol) for symbol in get_universe_preset(preset_name)]
    return pd.DataFrame([row for row in rows if row])


def enrich_with_basic_info_presets(stock_basic: pd.DataFrame) -> tuple[pd.DataFrame, list[dict[str, str]]]:
    """Fill missing stock_basic fields from local presets.

    Existing provider values take precedence. Returned warnings describe symbols
    not covered by the local preset table.
    """
    if stock_basic.empty or "ts_code" not in stock_basic.columns:
        return stock_basic, []
    result = stock_basic.copy()
    for column in ["symbol", "name", "area", "industry", "market", "list_date", "delist_date", "is_hs"]:
        if column not in result.columns:
            result[column] = pd.NA
    warnings: list[dict[str, str]] = []
    for index, row in result.iterrows():
        ts_code = str(row.get("ts_code", ""))
        preset = get_basic_info(ts_code)
        if not preset:
            warnings.append(
                {
                    "symbol": ts_code,
                    "provider": "local_preset",
                    "failed_stage": "stock_basic_preset_fallback_missing",
                    "error_message": "local basic info preset is missing",
                }
            )
            continue
        for column in ["symbol", "name", "area", "industry", "market", "list_date", "delist_date", "is_hs"]:
            if _is_missing(result.at[index, column]) and not _is_missing(preset.get(column)):
                result.at[index, column] = preset[column]
    return result, warnings


def _market_from_ts_code(ts_code: str) -> str:
    return "上交所" if str(ts_code).endswith(".SH") else "深交所"


def _is_missing(value: Any) -> bool:
    if value is None:
        return True
    try:
        if pd.isna(value):
            return True
    except (TypeError, ValueError):
        pass
    return str(value).strip() == ""
