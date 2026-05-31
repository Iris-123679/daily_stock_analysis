#!/usr/bin/env python3
"""
股票深度分析增强脚本 v5
功能：财务指标、技术分析(含评分系统)、资金异动、基本面透视、DCF估值、AI智能分析
数据源：AKShare（百度估值 + 东方财富 + 新浪）+ SiliconFlow (DeepSeek) AI分析
支持：A股 + 港股
v5新增：AI大模型分析（市场情绪、新闻解读、操作建议、风险提示）
"""

import json
import os
import sys
import time
import traceback
import urllib.request
import urllib.parse
import urllib.error
from datetime import datetime, timedelta
from typing import Optional, List, Tuple

import akshare as ak
import numpy as np
import pandas as pd

# 请求间隔和重试配置
REQUEST_DELAY = 3
MAX_RETRIES = 3

# PushPlus 微信推送配置
PUSHPLUS_TOKEN = os.environ.get("PUSHPLUS_TOKEN", "f667d88c4b68458cb0b81f0bb4f40b97")
PUSHPLUS_API = "http://www.pushplus.plus/send"

# SiliconFlow AI 分析配置
SILICONFLOW_API_KEY = os.environ.get("SILICONFLOW_API_KEY", "sk-klnitjvsylnsvnonjtgnwsbafjtczzrprvrappeblditflqy")
SILICONFLOW_API_URL = "https://api.siliconflow.cn/v1/chat/completions"
SILICONFLOW_MODEL = os.environ.get("AI_MODEL", "deepseek-ai/DeepSeek-V3")


def pushplus_send(title: str, content: str, template: str = "html") -> bool:
    """通过 PushPlus 推送消息到微信"""
    if not PUSHPLUS_TOKEN:
        print("  [INFO] PushPlus Token 未配置，跳过推送")
        return False
    try:
        data = json.dumps({
            "token": PUSHPLUS_TOKEN,
            "title": title,
            "content": content,
            "template": template,
        }).encode("utf-8")
        req = urllib.request.Request(
            PUSHPLUS_API,
            data=data,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            result = json.loads(resp.read().decode("utf-8"))
            if result.get("code") == 200:
                print(f"  📱 微信推送成功")
                return True
            else:
                print(f"  [WARN] 推送失败: {result.get('msg', '未知错误')}")
                return False
    except Exception as e:
        print(f"  [WARN] PushPlus 推送异常: {e}")
        return False


def ak_request(func, *args, retries=MAX_RETRIES, delay=REQUEST_DELAY, **kwargs):
    """带重试的 AKShare 请求封装"""
    for attempt in range(retries):
        try:
            time.sleep(delay)
            result = func(*args, **kwargs)
            return result
        except Exception as e:
            err_msg = str(e)
            if 'NoneType' in err_msg:
                # 东方财富页面解析失败，重试没意义
                raise
            if attempt < retries - 1:
                wait = delay * (attempt + 2)  # 递增等待
                print(f"    [RETRY {attempt+1}/{retries}] {func.__name__}: 等待{wait}s...")
                time.sleep(wait)
            else:
                raise


# ============================================================
# 股票类型判断 & 名称映射
# ============================================================

HK_CODES = {"09868", "01810", "01788"}

# 硬编码名称映射，避免每次都请求 stock_individual_info_em
STOCK_NAMES = {
    "601899": "紫金矿业",
    "000426": "兴业银锡",
    "002714": "牧原股份",
    "000582": "北部湾港",
    "688063": "派能科技",
    "688122": "西部超导",
    "09868": "小鹏集团-W",
    "01810": "小米集团-W",
    "01788": "国泰君安国际",
}


def is_hk_stock(code: str) -> bool:
    return code in HK_CODES


def get_stock_name(code: str) -> str:
    return STOCK_NAMES.get(code, code)


# ============================================================
# 工具函数
# ============================================================

def safe_float(val, default=None):
    try:
        if val is None or (isinstance(val, float) and np.isnan(val)):
            return default
        if isinstance(val, str) and (val == '-' or val == '' or val.strip() == ''):
            return default
        return float(str(val).replace(',', '').replace('%', ''))
    except (ValueError, TypeError):
        return default


def format_pct(val):
    if val is None:
        return "N/A"
    return f"{val:+.2f}%" if val != 0 else "0.00%"


def format_money(val, unit='亿'):
    if val is None:
        return "N/A"
    if abs(val) >= 10000 and unit == '亿':
        return f"{val/10000:.2f}万亿"
    return f"{val:.2f}{unit}"


# ============================================================
# 1. 财务指标分析
# ============================================================

def get_financial_indicators_a(stock_code: str) -> dict:
    result = {
        "pe_ttm": None, "pb": None, "ps_ttm": None,
        "roe": None, "gross_margin": None, "net_margin": None,
        "debt_ratio": None, "current_ratio": None,
        "revenue_yoy": None, "profit_yoy": None,
        "dv_ratio": None,
        "valuation_level": "N/A",
    }

    # 百度估值（不受东方财富限流影响）
    try:
        df_pe = ak_request(ak.stock_zh_valuation_baidu, symbol=stock_code, indicator="市盈率(TTM)", period="近一年")
        if df_pe is not None and not df_pe.empty:
            result["pe_ttm"] = safe_float(df_pe.iloc[-1]["value"])

        df_pb = ak_request(ak.stock_zh_valuation_baidu, symbol=stock_code, indicator="市净率", period="近一年")
        if df_pb is not None and not df_pb.empty:
            result["pb"] = safe_float(df_pb.iloc[-1]["value"])
    except Exception as e:
        print(f"  [WARN] 获取估值指标失败: {e}")

    # 财务分析指标（东方财富，可能被限流）
    try:
        df_fin = ak_request(ak.stock_financial_analysis_indicator, symbol=stock_code, start_year="2024")
        if df_fin is not None and not df_fin.empty:
            latest_fin = df_fin.iloc[0]
            result["roe"] = safe_float(latest_fin.get("净资产收益率(%)"))
            result["gross_margin"] = safe_float(latest_fin.get("销售毛利率(%)"))
            result["net_margin"] = safe_float(latest_fin.get("销售净利率(%)"))
            result["debt_ratio"] = safe_float(latest_fin.get("资产负债率(%)"))
            result["current_ratio"] = safe_float(latest_fin.get("流动比率"))
            result["revenue_yoy"] = safe_float(latest_fin.get("主营业务收入增长率(%)"))
            result["profit_yoy"] = safe_float(latest_fin.get("净利润增长率(%)"))
    except Exception as e:
        print(f"  [WARN] 获取财务分析指标失败: {e}")

    pe = result.get("pe_ttm")
    if pe is not None and pe > 0:
        if pe < 15: result["valuation_level"] = "低估值"
        elif pe < 30: result["valuation_level"] = "合理估值"
        elif pe < 60: result["valuation_level"] = "偏高估值"
        else: result["valuation_level"] = "高估值"

    return result


def get_financial_indicators_hk(stock_code: str) -> dict:
    result = {
        "pe_ttm": None, "pb": None, "ps_ttm": None,
        "roe": None, "gross_margin": None, "net_margin": None,
        "debt_ratio": None, "current_ratio": None,
        "revenue_yoy": None, "profit_yoy": None,
        "dv_ratio": None,
        "valuation_level": "N/A",
    }

    try:
        df_pe = ak_request(ak.stock_hk_valuation_baidu, symbol=stock_code, indicator="市盈率(TTM)", period="近一年")
        if df_pe is not None and not df_pe.empty:
            result["pe_ttm"] = safe_float(df_pe.iloc[-1]["value"])

        df_pb = ak_request(ak.stock_hk_valuation_baidu, symbol=stock_code, indicator="市净率", period="近一年")
        if df_pb is not None and not df_pb.empty:
            result["pb"] = safe_float(df_pb.iloc[-1]["value"])
    except Exception as e:
        print(f"  [WARN] 港股估值指标获取失败: {e}")

    try:
        df_fin = ak_request(ak.stock_hk_financial_indicator_em, symbol=stock_code)
        if df_fin is not None and not df_fin.empty:
            latest = df_fin.iloc[0]
            result["roe"] = safe_float(latest.get("股东权益回报率(%)"))
            result["net_margin"] = safe_float(latest.get("销售净利率(%)"))
            result["revenue_yoy"] = safe_float(latest.get("营业总收入滚动环比增长(%)"))
            result["profit_yoy"] = safe_float(latest.get("净利润滚动环比增长(%)"))
            result["dv_ratio"] = safe_float(latest.get("股息率TTM(%)"))
            if result["pe_ttm"] is None:
                result["pe_ttm"] = safe_float(latest.get("市盈率"))
            if result["pb"] is None:
                result["pb"] = safe_float(latest.get("市净率"))
    except Exception as e:
        print(f"  [WARN] 港股财务指标获取失败: {e}")

    pe = result.get("pe_ttm")
    if pe is not None and pe > 0:
        if pe < 15: result["valuation_level"] = "低估值"
        elif pe < 30: result["valuation_level"] = "合理估值"
        elif pe < 60: result["valuation_level"] = "偏高估值"
        else: result["valuation_level"] = "高估值"

    return result


def get_financial_indicators(stock_code: str) -> dict:
    if is_hk_stock(stock_code):
        return get_financial_indicators_hk(stock_code)
    return get_financial_indicators_a(stock_code)


# ============================================================
# 2. 技术分析
# ============================================================

def calc_ema(data, period):
    return data.ewm(span=period, adjust=False).mean()

def calc_macd(close, fast=12, slow=26, signal=9):
    ema_fast = calc_ema(close, fast)
    ema_slow = calc_ema(close, slow)
    dif = ema_fast - ema_slow
    dea = calc_ema(dif, signal)
    macd_hist = 2 * (dif - dea)
    return dif, dea, macd_hist

def calc_rsi(close, period=14):
    delta = close.diff()
    gain = delta.where(delta > 0, 0)
    loss = -delta.where(delta < 0, 0)
    avg_gain = gain.rolling(window=period, min_periods=period).mean()
    avg_loss = loss.rolling(window=period, min_periods=period).mean()
    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    return rsi

def calc_boll(close, period=20, std_dev=2):
    mid = close.rolling(window=period).mean()
    std = close.rolling(window=period).std()
    upper = mid + std_dev * std
    lower = mid - std_dev * std
    return upper, mid, lower


def get_technical_analysis(stock_code: str) -> dict:
    result = {
        "price": None, "change_pct": None,
        "ma5": None, "ma10": None, "ma20": None, "ma60": None,
        "macd_dif": None, "macd_dea": None, "macd_hist": None, "macd_signal": "",
        "rsi_14": None, "rsi_signal": "",
        "boll_upper": None, "boll_mid": None, "boll_lower": None, "boll_position": "",
        "trend": "N/A",
        "support": None, "resistance": None,
        # v4: 评分系统
        "bias_ma5": None, "bias_ma10": None, "bias_ma20": None,
        "volume_ratio_5d": None, "volume_status": "",
        "signal_score": None, "buy_signal": "", "signal_reasons": [], "risk_factors": [],
    }

    try:
        end_date = datetime.now().strftime("%Y%m%d")
        start_date = (datetime.now() - timedelta(days=180)).strftime("%Y%m%d")

        if is_hk_stock(stock_code):
            df = ak_request(ak.stock_hk_hist, symbol=stock_code, period="daily",
                            start_date=start_date, end_date=end_date, adjust="qfq")
        else:
            df = ak_request(ak.stock_zh_a_hist, symbol=stock_code, period="daily",
                            start_date=start_date, end_date=end_date, adjust="qfq")

        if df is None or df.empty:
            return result

        close = df["收盘"].astype(float)
        latest_close = close.iloc[-1]
        prev_close = close.iloc[-2] if len(close) > 1 else latest_close

        result["price"] = round(latest_close, 2)
        result["change_pct"] = round((latest_close - prev_close) / prev_close * 100, 2)

        result["ma5"] = round(close.rolling(5).mean().iloc[-1], 2) if len(close) >= 5 else None
        result["ma10"] = round(close.rolling(10).mean().iloc[-1], 2) if len(close) >= 10 else None
        result["ma20"] = round(close.rolling(20).mean().iloc[-1], 2) if len(close) >= 20 else None
        result["ma60"] = round(close.rolling(60).mean().iloc[-1], 2) if len(close) >= 60 else None

        dif, dea, macd_hist = calc_macd(close)
        result["macd_dif"] = round(dif.iloc[-1], 3) if not dif.empty else None
        result["macd_dea"] = round(dea.iloc[-1], 3) if not dea.empty else None
        result["macd_hist"] = round(macd_hist.iloc[-1], 3) if not macd_hist.empty else None

        if len(macd_hist) >= 2:
            if macd_hist.iloc[-1] > 0 and macd_hist.iloc[-2] <= 0:
                result["macd_signal"] = "金叉（看多）"
            elif macd_hist.iloc[-1] < 0 and macd_hist.iloc[-2] >= 0:
                result["macd_signal"] = "死叉（看空）"
            elif macd_hist.iloc[-1] > 0:
                result["macd_signal"] = "多头运行"
            else:
                result["macd_signal"] = "空头运行"

        rsi = calc_rsi(close)
        result["rsi_14"] = round(rsi.iloc[-1], 1) if not rsi.empty and not pd.isna(rsi.iloc[-1]) else None
        rsi_val = result["rsi_14"]
        if rsi_val is not None:
            if rsi_val > 70: result["rsi_signal"] = "超买（注意回调风险）"
            elif rsi_val > 50: result["rsi_signal"] = "偏强"
            elif rsi_val > 30: result["rsi_signal"] = "偏弱"
            else: result["rsi_signal"] = "超卖（关注反弹机会）"

        upper, mid, lower = calc_boll(close)
        result["boll_upper"] = round(upper.iloc[-1], 2) if not upper.empty else None
        result["boll_mid"] = round(mid.iloc[-1], 2) if not mid.empty else None
        result["boll_lower"] = round(lower.iloc[-1], 2) if not lower.empty else None

        if result["boll_upper"] and result["boll_lower"]:
            boll_range = result["boll_upper"] - result["boll_lower"]
            if boll_range > 0:
                pos = (latest_close - result["boll_lower"]) / boll_range
                if pos > 0.9: result["boll_position"] = f"上轨附近（{pos:.0%}位，压力区）"
                elif pos > 0.5: result["boll_position"] = f"中上区间（{pos:.0%}位）"
                elif pos > 0.1: result["boll_position"] = f"中下区间（{pos:.0%}位）"
                else: result["boll_position"] = f"下轨附近（{pos:.0%}位，支撑区）"

        ma5_above_ma20 = result["ma5"] is not None and result["ma20"] is not None and result["ma5"] > result["ma20"]
        macd_positive = result["macd_hist"] is not None and result["macd_hist"] > 0
        rsi_above_50 = rsi_val is not None and rsi_val > 50

        signals = [
            "均线多头" if ma5_above_ma20 else "均线空头",
            "MACD多头" if macd_positive else "MACD空头",
            "RSI偏强" if rsi_above_50 else "RSI偏弱",
        ]
        bullish = sum([ma5_above_ma20, macd_positive, rsi_above_50])
        result["trend"] = f"偏多（{'+'.join(signals)}）" if bullish >= 2 else f"偏空（{'+'.join(signals)}）"

        result["support"] = result["boll_lower"]
        result["resistance"] = result["boll_upper"]

        # ===== v4: 买入信号评分系统 =====
        # 参考 daily_stock_analysis 项目的 _generate_signal 逻辑
        # 评分维度: 趋势(30) + 乖离率(20) + 量能(15) + 支撑(10) + MACD(15) + RSI(10) = 100
        score = 0
        reasons = []
        risks = []

        # --- 趋势评分(30分) ---
        ma5, ma10, ma20 = result["ma5"], result["ma10"], result["ma20"]
        if ma5 and ma10 and ma20:
            if ma5 > ma10 > ma20:
                trend_score = 26
                reasons.append(f"✅ 多头排列 MA5>MA10>MA20")
            elif ma5 > ma10:
                trend_score = 18
                reasons.append("⚡ 弱势多头，MA5>MA10")
            elif ma5 < ma10 < ma20:
                trend_score = 4
                risks.append("⚠️ 空头排列 MA5<MA10<MA20")
            elif ma5 < ma10:
                trend_score = 8
                risks.append("⚠️ 弱势空头")
            else:
                trend_score = 12
                reasons.append("均线缠绕，趋势不明")
        else:
            trend_score = 12
        score += trend_score

        # --- 乖离率评分(20分) ---
        if result["price"] and ma5 and ma5 > 0:
            bias_ma5 = (result["price"] - ma5) / ma5 * 100
            result["bias_ma5"] = round(bias_ma5, 2)
            if bias_ma5 < -3:
                score += 8
                risks.append(f"⚠️ 乖离率过大({bias_ma5:.1f}%)，可能破位")
            elif bias_ma5 < 0:
                score += 20
                reasons.append(f"✅ 价格略低于MA5({bias_ma5:.1f}%)，回踩买点")
            elif bias_ma5 < 2:
                score += 18
                reasons.append(f"✅ 价格贴近MA5({bias_ma5:.1f}%)，介入好时机")
            elif bias_ma5 < 5:
                score += 14
                reasons.append(f"⚡ 价格略高于MA5({bias_ma5:.1f}%)，可小仓介入")
            else:
                score += 4
                risks.append(f"❌ 乖离率过高({bias_ma5:.1f}%)，严禁追高！")

        if result["price"] and ma10 and ma10 > 0:
            result["bias_ma10"] = round((result["price"] - ma10) / ma10 * 100, 2)
        if result["price"] and ma20 and ma20 > 0:
            result["bias_ma20"] = round((result["price"] - ma20) / ma20 * 100, 2)

        # --- 量能评分(15分) ---
        if len(df) >= 6:
            vol_col = "成交量" if "成交量" in df.columns else "volume"
            vol_5d_avg = df[vol_col].iloc[-6:-1].mean()
            latest_vol = df[vol_col].iloc[-1]
            if vol_5d_avg > 0:
                vol_ratio = latest_vol / vol_5d_avg
                result["volume_ratio_5d"] = round(vol_ratio, 2)

                change = result["change_pct"] or 0
                if vol_ratio >= 1.5 and change > 0:
                    score += 12
                    result["volume_status"] = "放量上涨"
                    reasons.append("✅ 放量上涨，多头力量强劲")
                elif vol_ratio >= 1.5 and change <= 0:
                    score += 0
                    result["volume_status"] = "放量下跌"
                    risks.append("⚠️ 放量下跌，注意风险")
                elif vol_ratio <= 0.7 and change <= 0:
                    score += 15
                    result["volume_status"] = "缩量回调"
                    reasons.append("✅ 缩量回调，主力洗盘")
                elif vol_ratio <= 0.7 and change > 0:
                    score += 6
                    result["volume_status"] = "缩量上涨"
                else:
                    score += 10
                    result["volume_status"] = "量能正常"

        # --- 支撑评分(10分) ---
        if result["price"] and ma5 and ma5 > 0:
            ma5_dist = abs(result["price"] - ma5) / ma5
            if ma5_dist <= 0.02 and result["price"] >= ma5:
                score += 5
                reasons.append("✅ MA5支撑有效")
        if result["price"] and ma10 and ma10 > 0:
            ma10_dist = abs(result["price"] - ma10) / ma10
            if ma10_dist <= 0.02 and result["price"] >= ma10:
                score += 5
                reasons.append("✅ MA10支撑有效")

        # --- MACD评分(15分) ---
        macd_sig = result["macd_signal"]
        if "金叉" in macd_sig and "看多" in macd_sig:
            score += 12
            reasons.append(f"✅ MACD金叉")
        elif "金叉" in macd_sig:
            score += 12
            reasons.append(f"✅ MACD金叉")
        elif "多头" in macd_sig:
            score += 8
            reasons.append("✓ MACD多头运行")
        elif "死叉" in macd_sig:
            score += 0
            risks.append("⚠️ MACD死叉")
        elif "空头" in macd_sig:
            score += 2
            risks.append("⚠️ MACD空头运行")
        else:
            score += 5

        # --- RSI评分(10分) ---
        rsi_val = result["rsi_14"]
        if rsi_val is not None:
            if rsi_val < 30:
                score += 10
                reasons.append(f"⭐ RSI超卖({rsi_val:.1f})，反弹机会大")
            elif rsi_val < 40:
                score += 3
            elif rsi_val <= 60:
                score += 5
            elif rsi_val <= 70:
                score += 8
                reasons.append(f"✅ RSI强势({rsi_val:.1f})")
            else:
                score += 0
                risks.append(f"⚠️ RSI超买({rsi_val:.1f})，回调风险")

        # --- 综合判断 ---
        result["signal_score"] = score
        result["signal_reasons"] = reasons
        result["risk_factors"] = risks

        # 数据不足时评分无意义
        if result["price"] is None:
            result["signal_score"] = None
            result["buy_signal"] = "数据不足"
            result["signal_reasons"] = []
            result["risk_factors"] = ["技术数据获取失败，无法评分"]
        elif score >= 75:
            result["buy_signal"] = "强烈买入"
        elif score >= 60:
            result["buy_signal"] = "买入"
        elif score >= 45:
            result["buy_signal"] = "持有/观望"
        elif score >= 30:
            result["buy_signal"] = "观望"
        elif score >= 15:
            result["buy_signal"] = "卖出"
        else:
            result["buy_signal"] = "强烈卖出"

    except Exception as e:
        print(f"  [WARN] 技术分析失败: {e}")

    return result


# ============================================================
# 3. 资金异动
# ============================================================

def get_fund_flow(stock_code: str) -> dict:
    result = {
        "main_net_inflow": None, "main_net_pct": None,
        "super_net": None, "big_net": None, "medium_net": None, "small_net": None,
        "recent_5d_main": [],
        "signal": "",
    }

    if is_hk_stock(stock_code):
        result["signal"] = "港股暂不支持A股资金流向数据"
        return result

    try:
        df = ak_request(ak.stock_individual_fund_flow, stock=stock_code,
                        market="sh" if stock_code.startswith("6") else "sz")
        if df is not None and not df.empty:
            latest = df.iloc[-1]
            result["main_net_inflow"] = safe_float(latest.get("主力净流入-净额"))
            result["main_net_pct"] = safe_float(latest.get("主力净流入-净占比"))
            result["super_net"] = safe_float(latest.get("超大单净流入-净额"))
            result["big_net"] = safe_float(latest.get("大单净流入-净额"))
            result["medium_net"] = safe_float(latest.get("中单净流入-净额"))
            result["small_net"] = safe_float(latest.get("小单净流入-净额"))

            for i in range(min(5, len(df))):
                row = df.iloc[-(i+1)]
                date_str = str(row.get("日期", row.get("date", "")))[:10]
                main_val = safe_float(row.get("主力净流入-净额"))
                result["recent_5d_main"].append({"date": date_str, "value": main_val})

            main_inflow = result["main_net_inflow"]
            if main_inflow is not None:
                result["signal"] = "主力净流入，资金关注" if main_inflow > 0 else "主力净流出，资金撤离"
    except Exception as e:
        print(f"  [WARN] 资金流向获取失败: {e}")

    return result


# ============================================================
# 4. 基本面透视
# ============================================================

def get_fundamentals_a(stock_code: str) -> dict:
    result = {
        "latest_quarter": "",
        "revenue": None, "revenue_yoy": None,
        "net_profit": None, "profit_yoy": None,
        "eps": None, "bvps": None,
        "quarters": [],
        "industry": "", "industry_rank": "",
    }

    try:
        df = ak_request(ak.stock_yjbb_em, date=datetime.now().strftime("%Y%m%d"))
        if df is not None and not df.empty:
            stock_df = df[df["股票代码"] == stock_code]
            if not stock_df.empty:
                latest = stock_df.iloc[0]
                result["latest_quarter"] = str(latest.get("报告期", ""))
                rev = safe_float(latest.get("营业收入-营业收入"))
                result["revenue"] = round(rev / 1e8, 2) if rev is not None else None
                result["revenue_yoy"] = safe_float(latest.get("营业收入-同比增长"))
                npr = safe_float(latest.get("净利润-净利润"))
                result["net_profit"] = round(npr / 1e8, 2) if npr is not None else None
                result["profit_yoy"] = safe_float(latest.get("净利润-同比增长"))
                result["eps"] = safe_float(latest.get("每股收益"))
                result["bvps"] = safe_float(latest.get("每股净资产"))

                for i in range(min(4, len(stock_df))):
                    row = stock_df.iloc[i]
                    r = safe_float(row.get("营业收入-营业收入"))
                    n = safe_float(row.get("净利润-净利润"))
                    result["quarters"].append({
                        "quarter": str(row.get("报告期", "")),
                        "revenue": round(r / 1e8, 2) if r is not None else None,
                        "profit": round(n / 1e8, 2) if n is not None else None,
                        "profit_yoy": safe_float(row.get("净利润-同比增长")),
                    })
    except Exception as e:
        print(f"  [WARN] 业绩数据获取失败: {e}")

    return result


def get_fundamentals_hk(stock_code: str) -> dict:
    result = {
        "latest_quarter": "",
        "revenue": None, "revenue_yoy": None,
        "net_profit": None, "profit_yoy": None,
        "eps": None, "bvps": None,
        "quarters": [],
        "industry": "", "industry_rank": "",
    }

    try:
        df = ak_request(ak.stock_hk_financial_indicator_em, symbol=stock_code)
        if df is not None and not df.empty:
            latest = df.iloc[0]
            result["eps"] = safe_float(latest.get("基本每股收益(元)"))
            result["bvps"] = safe_float(latest.get("每股净资产(元)"))
            npr = safe_float(latest.get("净利润"))
            result["net_profit"] = round(npr / 1e8, 2) if npr is not None else None
            rev = safe_float(latest.get("营业总收入"))
            result["revenue"] = round(rev / 1e8, 2) if rev is not None else None
            result["revenue_yoy"] = safe_float(latest.get("营业总收入滚动环比增长(%)"))
            result["profit_yoy"] = safe_float(latest.get("净利润滚动环比增长(%)"))
    except Exception as e:
        print(f"  [WARN] 港股基本面获取失败: {e}")

    return result


def get_fundamentals(stock_code: str) -> dict:
    if is_hk_stock(stock_code):
        return get_fundamentals_hk(stock_code)
    return get_fundamentals_a(stock_code)


# ============================================================
# 5. DCF 估值
# ============================================================

def calc_dcf_valuation(stock_code: str) -> dict:
    result = {
        "method": "两阶段DCF（增长+永续）",
        "fcf_per_share": None, "growth_rate_5y": None,
        "terminal_growth": 0.03, "discount_rate": 0.10,
        "intrinsic_value": None, "current_price": None,
        "margin_of_safety": None, "verdict": "",
        "assumptions": [],
    }

    if is_hk_stock(stock_code):
        result["verdict"] = "港股DCF估值暂不支持（需A股财报格式）"
        return result

    try:
        df_cash = ak_request(ak.stock_cash_flow_sheet_by_report_em, symbol=stock_code)
        if df_cash is None or df_cash.empty:
            result["verdict"] = "无法获取现金流数据"
            return result

        recent = df_cash.head(4)

        operating_cf_col = None
        for col in df_cash.columns:
            if "经营活动产生的现金流量净额" in str(col):
                operating_cf_col = col
                break

        capex_col = None
        for col in df_cash.columns:
            if "购建固定资产" in str(col) and "无形资产" in str(col):
                capex_col = col
                break

        if operating_cf_col is None:
            result["verdict"] = "无法识别经营活动现金流列"
            return result

        fcfs = []
        for _, row in recent.iterrows():
            ocf = safe_float(row.get(operating_cf_col), default=0)
            capex = safe_float(row.get(capex_col), default=0) if capex_col else 0
            fcfs.append(ocf - abs(capex))

        if not fcfs or all(f == 0 for f in fcfs):
            result["verdict"] = "自由现金流数据不足"
            return result

        latest_fcf = fcfs[0]

        total_shares = None
        try:
            df_info = ak_request(ak.stock_individual_info_em, symbol=stock_code)
            if df_info is not None and not df_info.empty:
                for _, row in df_info.iterrows():
                    if "总股本" in str(row.iloc[0]):
                        total_shares = safe_float(row.iloc[1])
                        break
        except:
            pass

        if total_shares and total_shares > 0:
            result["fcf_per_share"] = round(latest_fcf / total_shares, 4)
        else:
            total_shares = 1e9

        growth_rate = 0.10
        try:
            df_fin = ak_request(ak.stock_financial_analysis_indicator, symbol=stock_code, start_year="2023")
            if df_fin is not None and not df_fin.empty:
                rev_yoy = safe_float(df_fin.iloc[0].get("主营业务收入增长率(%)"))
                if rev_yoy is not None and rev_yoy > 0:
                    growth_rate = min(rev_yoy / 100, 0.30)
        except:
            pass

        result["growth_rate_5y"] = round(growth_rate * 100, 1)

        r = result["discount_rate"]
        g1 = growth_rate
        g_term = result["terminal_growth"]

        pv_fcf = sum(latest_fcf * (1 + g1) ** i / (1 + r) ** i for i in range(1, 6))
        terminal_value = latest_fcf * (1 + g1) ** 5 * (1 + g_term) / (r - g_term)
        pv_terminal = terminal_value / (1 + r) ** 5

        result["intrinsic_value"] = round((pv_fcf + pv_terminal) / total_shares, 2)

        # 当前价格从技术分析结果拿（已经请求过了，避免重复请求）
        try:
            end_date = datetime.now().strftime("%Y%m%d")
            start_date = (datetime.now() - timedelta(days=7)).strftime("%Y%m%d")
            df_price = ak_request(ak.stock_zh_a_hist, symbol=stock_code, period="daily",
                                  start_date=start_date, end_date=end_date, adjust="qfq")
            if df_price is not None and not df_price.empty:
                result["current_price"] = round(safe_float(df_price.iloc[-1]["收盘"]), 2)
        except:
            pass

        if result["current_price"] and result["intrinsic_value"]:
            mos = (result["intrinsic_value"] - result["current_price"]) / result["intrinsic_value"] * 100
            result["margin_of_safety"] = round(mos, 1)
            if mos > 30: result["verdict"] = f"低估（安全边际{mos:.0f}%，内在价值远高于现价）"
            elif mos > 10: result["verdict"] = f"合理偏低（安全边际{mos:.0f}%）"
            elif mos > -10: result["verdict"] = f"合理偏高（安全边际{mos:.0f}%）"
            else: result["verdict"] = f"高估（安全边际{mos:.0f}%，现价远超内在价值）"

        result["assumptions"] = [
            f"未来5年增长率: {g1*100:.1f}%",
            f"永续增长率: {g_term*100:.1f}%",
            f"折现率(WACC): {r*100:.1f}%",
            f"最近年度自由现金流: {format_money(latest_fcf/1e8)}",
        ]

    except Exception as e:
        result["verdict"] = f"DCF计算失败: {e}"
        print(f"  [WARN] DCF估值失败: {e}")

    return result


# ============================================================
# 6. AI 大模型分析
# ============================================================

def ai_analyze_stock(stock_code: str, financial: dict, technical: dict,
                     fund_flow: dict, fundamentals: dict, dcf: dict) -> dict:
    """使用 DeepSeek 大模型生成综合分析报告"""
    result = {
        "market_sentiment": "",       # 市场情绪判断
        "operation_advice": "",       # 操作建议
        "risk_warning": "",           # 风险提示
        "key_catalyst": "",           # 关键催化
        "target_price_analysis": "",  # 目标价分析
        "summary": "",               # 综合评述
        "model": SILICONFLOW_MODEL,
    }

    if not SILICONFLOW_API_KEY:
        result["summary"] = "⚠️ AI分析未启用（未配置 SILICONFLOW_API_KEY）"
        return result

    stock_name = get_stock_name(stock_code)
    market_tag = "港股" if is_hk_stock(stock_code) else "A股"
    price_unit = "港元" if is_hk_stock(stock_code) else "元"

    # 构建结构化 prompt
    prompt = f"""你是一位专业的{market_tag}投资分析师，请基于以下数据分析 {stock_name}({stock_code}) 的投资价值。

## 基本面数据
- PE(TTM): {financial.get('pe_ttm', 'N/A')} | PB: {financial.get('pb', 'N/A')}
- ROE: {financial.get('roe', 'N/A')}% | 净利率: {financial.get('net_margin', 'N/A')}%
- 营收同比: {financial.get('revenue_yoy', 'N/A')}% | 净利润同比: {financial.get('profit_yoy', 'N/A')}%
- 估值判断: {financial.get('valuation_level', 'N/A')}
- 股息率: {financial.get('dv_ratio', 'N/A')}%

## 技术面数据
- 最新价: {technical.get('price', 'N/A')} {price_unit} | 涨跌幅: {technical.get('change_pct', 'N/A')}%
- MA5: {technical.get('ma5', 'N/A')} | MA10: {technical.get('ma10', 'N/A')} | MA20: {technical.get('ma20', 'N/A')} | MA60: {technical.get('ma60', 'N/A')}
- MACD: {technical.get('macd_signal', 'N/A')} (DIF: {technical.get('macd_dif', 'N/A')}, DEA: {technical.get('macd_dea', 'N/A')})
- RSI(14): {technical.get('rsi_14', 'N/A')} ({technical.get('rsi_signal', 'N/A')})
- 布林带位置: {technical.get('boll_position', 'N/A')}
- 综合趋势: {technical.get('trend', 'N/A')}
- 乖离率(MA5): {technical.get('bias_ma5', 'N/A')}%
- 量能状态: {technical.get('volume_status', 'N/A')} | 量比: {technical.get('volume_ratio_5d', 'N/A')}

## 买入信号评分
- 综合评分: {technical.get('signal_score', 'N/A')}/100
- 信号等级: {technical.get('buy_signal', 'N/A')}
- 看多理由: {'; '.join(technical.get('signal_reasons') or [])}
- 风险因素: {'; '.join(technical.get('risk_factors') or [])}

## 资金面数据
- 主力净流入: {fund_flow.get('main_net_inflow', 'N/A')}
- 资金信号: {fund_flow.get('signal', 'N/A')}

## 业绩数据
- 最新报告期: {fundamentals.get('latest_quarter', 'N/A')}
- 营业收入: {fundamentals.get('revenue', 'N/A')}亿 | 净利润: {fundamentals.get('net_profit', 'N/A')}亿
- EPS: {fundamentals.get('eps', 'N/A')} | 每股净资产: {fundamentals.get('bvps', 'N/A')}

## DCF估值（仅A股）
- 内在价值: {dcf.get('intrinsic_value', 'N/A')} | 当前价格: {dcf.get('current_price', 'N/A')}
- 安全边际: {dcf.get('margin_of_safety', 'N/A')}% | 估值判断: {dcf.get('verdict', 'N/A')}

---

请用JSON格式输出分析结果，严格遵循以下结构（不要输出其他内容）：
{{
  "market_sentiment": "市场情绪判断（1-2句话，如：当前处于XX阶段，市场情绪XX）",
  "operation_advice": "操作建议（1-2句话，如：建议XX仓位XX，止损位XX）",
  "risk_warning": "风险提示（1-2句话，如：需关注XX风险，若XX则应XX）",
  "key_catalyst": "关键催化（1句话，如：近期需关注XX事件/数据）",
  "target_price_analysis": "目标价分析（1句话，结合估值和技术面给出合理区间）",
  "summary": "综合评述（3-5句话，涵盖基本面+技术面+资金面+估值，给出明确结论）"
}}"""

    try:
        req_data = json.dumps({
            "model": SILICONFLOW_MODEL,
            "messages": [
                {"role": "system", "content": "你是一位资深A股/港股投资分析师，擅长基本面+技术面+资金面三维分析。请严格按JSON格式输出，不要包含markdown代码块标记。"},
                {"role": "user", "content": prompt}
            ],
            "temperature": 0.3,
            "max_tokens": 800,
        }).encode("utf-8")

        req = urllib.request.Request(
            SILICONFLOW_API_URL,
            data=req_data,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {SILICONFLOW_API_KEY}",
            },
        )

        with urllib.request.urlopen(req, timeout=30) as resp:
            resp_data = json.loads(resp.read().decode("utf-8"))
            content = resp_data["choices"][0]["message"]["content"].strip()

            # 清理可能的 markdown 代码块标记
            if content.startswith("```"):
                content = content.split("\n", 1)[-1]
            if content.endswith("```"):
                content = content.rsplit("```", 1)[0]
            if content.startswith("json"):
                content = content[4:].strip()

            # 解析 JSON
            ai_result = json.loads(content)

            result["market_sentiment"] = ai_result.get("market_sentiment", "")
            result["operation_advice"] = ai_result.get("operation_advice", "")
            result["risk_warning"] = ai_result.get("risk_warning", "")
            result["key_catalyst"] = ai_result.get("key_catalyst", "")
            result["target_price_analysis"] = ai_result.get("target_price_analysis", "")
            result["summary"] = ai_result.get("summary", "")

    except json.JSONDecodeError as e:
        # JSON 解析失败时，尝试直接使用原始内容
        result["summary"] = f"AI分析返回格式异常，原始内容: {content[:200] if 'content' in dir() else str(e)}"
        print(f"  [WARN] AI分析JSON解析失败: {e}")
    except Exception as e:
        result["summary"] = f"⚠️ AI分析调用失败: {e}"
        print(f"  [WARN] AI分析失败: {e}")

    return result


# ============================================================
# 报告生成
# ============================================================

def build_push_summary(stock_code: str, financial: dict, technical: dict,
                       fund_flow: dict, fundamentals: dict, dcf: dict,
                       ai_analysis: dict = None) -> tuple:
    """构建微信推送摘要，返回 (title, html_content)"""
    stock_name = get_stock_name(stock_code)
    market_tag = "港股" if is_hk_stock(stock_code) else "A股"
    price_unit = "港元" if is_hk_stock(stock_code) else "元"
    now = datetime.now().strftime("%Y-%m-%d %H:%M")

    title = f"📊 {stock_name}({stock_code}) 分析摘要"

    def v(val, suffix=""):
        if val is None:
            return "N/A"
        return f"{val}{suffix}"

    def vp(val):
        """格式化百分比"""
        if val is None:
            return "N/A"
        return f"{val:+.2f}%" if val != 0 else "0.00%"

    def vm(val):
        """格式化金额（亿）"""
        if val is None:
            return "N/A"
        return f"{val:.2f}亿"

    # 估值颜色
    val_level = financial.get("valuation_level", "N/A")
    val_color = "#4CAF50" if "低" in val_level else "#FF9800" if "偏高" in val_level else "#F44336" if "高" in val_level else "#2196F3"

    # MACD 信号颜色
    macd_sig = technical.get("macd_signal", "")
    macd_color = "#4CAF50" if "金叉" in macd_sig or "多头" in macd_sig else "#F44336" if "死叉" in macd_sig or "空头" in macd_sig else "#999"

    # RSI 信号颜色
    rsi_sig = technical.get("rsi_signal", "")
    rsi_color = "#F44336" if "超买" in rsi_sig else "#4CAF50" if "超卖" in rsi_sig else "#2196F3"

    # 资金信号
    fund_sig = fund_flow.get("signal", "")
    fund_color = "#4CAF50" if "流入" in fund_sig else "#F44336" if "流出" in fund_sig else "#999"

    html = f"""
    <div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; max-width: 600px; margin: 0 auto; padding: 10px;">
      <div style="background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; padding: 16px; border-radius: 12px; margin-bottom: 12px;">
        <h2 style="margin:0 0 4px 0; font-size: 20px;">📊 {stock_name}({stock_code})</h2>
        <p style="margin:0; font-size: 13px; opacity: 0.85;">{market_tag} | {now}</p>
      </div>

      <div style="background: #f8f9fa; border-radius: 10px; padding: 14px; margin-bottom: 10px;">
        <h3 style="margin:0 0 8px 0; font-size: 15px; color: #333;">💰 财务指标</h3>
        <table style="width:100%; font-size:13px; border-collapse:collapse;">
          <tr><td style="padding:3px 0; color:#666;">PE(TTM)</td><td style="text-align:right; font-weight:bold;">{v(financial.get('pe_ttm'))}</td>
              <td style="padding:3px 8px; color:#666;">PB</td><td style="text-align:right; font-weight:bold;">{v(financial.get('pb'))}</td></tr>
          <tr><td style="padding:3px 0; color:#666;">ROE</td><td style="text-align:right; font-weight:bold;">{v(financial.get('roe'), '%')}</td>
              <td style="padding:3px 8px; color:#666;">净利率</td><td style="text-align:right; font-weight:bold;">{v(financial.get('net_margin'), '%')}</td></tr>
          <tr><td style="padding:3px 0; color:#666;">营收同比</td><td style="text-align:right; font-weight:bold;">{vp(financial.get('revenue_yoy'))}</td>
              <td style="padding:3px 8px; color:#666;">净利润同比</td><td style="text-align:right; font-weight:bold;">{vp(financial.get('profit_yoy'))}</td></tr>
        </table>
        <div style="margin-top:8px; padding:6px 10px; background:{val_color}; color:white; border-radius:6px; text-align:center; font-weight:bold; font-size:14px;">
          估值判断: {val_level}
        </div>
      </div>

      <div style="background: #f8f9fa; border-radius: 10px; padding: 14px; margin-bottom: 10px;">
        <h3 style="margin:0 0 8px 0; font-size: 15px; color: #333;">📈 技术分析</h3>
        <table style="width:100%; font-size:13px; border-collapse:collapse;">
          <tr><td style="padding:3px 0; color:#666;">最新价</td><td style="text-align:right; font-weight:bold;">{v(technical.get('price'))} {price_unit}</td>
              <td style="padding:3px 8px; color:#666;">涨跌幅</td><td style="text-align:right; font-weight:bold;">{vp(technical.get('change_pct'))}</td></tr>
          <tr><td style="padding:3px 0; color:#666;">MA5/MA20</td><td style="text-align:right;">{v(technical.get('ma5'))} / {v(technical.get('ma20'))}</td>
              <td style="padding:3px 8px; color:#666;">趋势</td><td style="text-align:right; font-weight:bold;">{technical.get('trend', 'N/A')}</td></tr>
        </table>
        <div style="display:flex; gap:8px; margin-top:8px;">
          <div style="flex:1; padding:6px; background:{macd_color}; color:white; border-radius:6px; text-align:center; font-size:12px; font-weight:bold;">
            MACD: {macd_sig or 'N/A'}
          </div>
          <div style="flex:1; padding:6px; background:{rsi_color}; color:white; border-radius:6px; text-align:center; font-size:12px; font-weight:bold;">
            RSI: {v(technical.get('rsi_14'))} {rsi_sig}
          </div>
        </div>
      </div>

      <div style="background: #f8f9fa; border-radius: 10px; padding: 14px; margin-bottom: 10px;">
        <h3 style="margin:0 0 8px 0; font-size: 15px; color: #333;">🔥 信号评分</h3>
        <div style="text-align:center; margin-bottom:8px;">
          <span style="font-size:28px; font-weight:bold; color:{'#4CAF50' if (technical.get('signal_score') or 0) >= 60 else '#FF9800' if (technical.get('signal_score') or 0) >= 45 else '#F44336'};">{v(technical.get('signal_score'))}</span>
          <span style="font-size:14px; color:#666;">/100</span>
        </div>
        <div style="padding:6px 10px; background:{'#4CAF50' if '买入' in (technical.get('buy_signal') or '') else '#FF9800' if '持有' in (technical.get('buy_signal') or '') or '观望' in (technical.get('buy_signal') or '') else '#F44336'}; color:white; border-radius:6px; text-align:center; font-weight:bold; font-size:14px;">
          {technical.get('buy_signal') or 'N/A'}
        </div>
        <div style="font-size:11px; color:#666; margin-top:6px;">
          {'; '.join((technical.get('signal_reasons') or [])[:3]) or ''}
        </div>
      </div>

      <div style="background: #f8f9fa; border-radius: 10px; padding: 14px; margin-bottom: 10px;">
        <h3 style="margin:0 0 8px 0; font-size: 15px; color: #333;">💸 资金异动</h3>
        <div style="padding:6px 10px; background:{fund_color}; color:white; border-radius:6px; text-align:center; font-weight:bold; font-size:13px;">
          {fund_sig or 'N/A'}
        </div>
        <table style="width:100%; font-size:13px; border-collapse:collapse; margin-top:6px;">
          <tr><td style="padding:2px 0; color:#666;">主力净流入</td><td style="text-align:right; font-weight:bold;">{vm(fund_flow.get('main_net_inflow')/1e8) if fund_flow.get('main_net_inflow') else 'N/A'}</td></tr>
          <tr><td style="padding:2px 0; color:#666;">超大单</td><td style="text-align:right;">{vm(fund_flow.get('super_net')/1e8) if fund_flow.get('super_net') else 'N/A'}</td></tr>
          <tr><td style="padding:2px 0; color:#666;">大单</td><td style="text-align:right;">{vm(fund_flow.get('big_net')/1e8) if fund_flow.get('big_net') else 'N/A'}</td></tr>
        </table>
      </div>"""

    # DCF 部分（仅 A 股显示）
    if not is_hk_stock(stock_code) and dcf.get("intrinsic_value"):
        dcf_verdict = dcf.get("verdict", "N/A")
        dcf_color = "#4CAF50" if "低估" in dcf_verdict else "#FF9800" if "合理" in dcf_verdict else "#F44336"
        html += f"""
      <div style="background: #f8f9fa; border-radius: 10px; padding: 14px; margin-bottom: 10px;">
        <h3 style="margin:0 0 8px 0; font-size: 15px; color: #333;">🎯 DCF估值</h3>
        <table style="width:100%; font-size:13px; border-collapse:collapse;">
          <tr><td style="padding:2px 0; color:#666;">内在价值</td><td style="text-align:right; font-weight:bold;">{v(dcf.get('intrinsic_value'))} {price_unit}</td></tr>
          <tr><td style="padding:2px 0; color:#666;">当前价格</td><td style="text-align:right;">{v(dcf.get('current_price'))} {price_unit}</td></tr>
          <tr><td style="padding:2px 0; color:#666;">安全边际</td><td style="text-align:right;">{v(dcf.get('margin_of_safety'), '%')}</td></tr>
        </table>
        <div style="margin-top:6px; padding:6px 10px; background:{dcf_color}; color:white; border-radius:6px; text-align:center; font-weight:bold; font-size:13px;">
          {dcf_verdict}
        </div>
      </div>"""

    # AI 分析部分
    if ai_analysis:
        ai_summary = ai_analysis.get("summary", "")
        ai_advice = ai_analysis.get("operation_advice", "")
        ai_risk = ai_analysis.get("risk_warning", "")
        ai_sentiment = ai_analysis.get("market_sentiment", "")
        ai_catalyst = ai_analysis.get("key_catalyst", "")
        ai_target = ai_analysis.get("target_price_analysis", "")
        ai_model = ai_analysis.get("model", "")

        html += f"""
      <div style="background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%); border-radius: 10px; padding: 14px; margin-bottom: 10px; color: white;">
        <h3 style="margin:0 0 8px 0; font-size: 15px; color: #00d4ff;">🤖 AI 智能分析 <span style="font-size:10px; color:#888;">({ai_model})</span></h3>
        <div style="font-size:13px; line-height:1.6; color:#e0e0e0;">
          <div style="margin-bottom:6px;">
            <span style="color:#00d4ff;">📋 综合评述</span><br/>
            {ai_summary or 'N/A'}
          </div>
          <div style="display:flex; gap:8px; margin-bottom:6px;">
            <div style="flex:1; padding:6px 8px; background:rgba(76,175,80,0.2); border-radius:6px; border-left:3px solid #4CAF50;">
              <span style="color:#4CAF50; font-size:11px;">💡 操作建议</span><br/>
              <span style="font-size:12px;">{ai_advice or 'N/A'}</span>
            </div>
            <div style="flex:1; padding:6px 8px; background:rgba(244,67,54,0.2); border-radius:6px; border-left:3px solid #F44336;">
              <span style="color:#F44336; font-size:11px;">⚠️ 风险提示</span><br/>
              <span style="font-size:12px;">{ai_risk or 'N/A'}</span>
            </div>
          </div>
          {"<div style='font-size:12px; color:#aaa;'><span style=color:#FF9800>🎯</span> " + ai_sentiment + "</div>" if ai_sentiment else ""}
          {"<div style='font-size:12px; color:#aaa;'><span style=color:#9C27B0>🔑</span> " + ai_catalyst + "</div>" if ai_catalyst else ""}
          {"<div style='font-size:12px; color:#aaa;'><span style=color:#2196F3>🎯</span> " + ai_target + "</div>" if ai_target else ""}
        </div>
      </div>"""

    html += """
      <p style="text-align:center; font-size:11px; color:#999; margin-top:8px;">
        ⚠️ 仅供参考，不构成投资建议 | AI股票分析增强系统 v5
      </p>
    </div>"""

    return title, html


def generate_stock_report(stock_code: str) -> tuple:
    """返回 (report_markdown, analysis_data_dict)"""
    stock_name = get_stock_name(stock_code)
    market_tag = "港股" if is_hk_stock(stock_code) else "A股"
    print(f"\n{'='*50}")
    print(f"分析: {stock_name}({stock_code}) [{market_tag}]")
    print(f"{'='*50}")

    print("  [1/6] 财务指标...")
    financial = get_financial_indicators(stock_code)

    print("  [2/6] 技术分析...")
    technical = get_technical_analysis(stock_code)

    print("  [3/6] 资金异动...")
    fund_flow = get_fund_flow(stock_code)

    print("  [4/6] 基本面透视...")
    fundamentals = get_fundamentals(stock_code)

    print("  [5/6] DCF估值...")
    dcf = calc_dcf_valuation(stock_code)

    print("  [6/6] AI智能分析...")
    ai_analysis = ai_analyze_stock(stock_code, financial, technical, fund_flow, fundamentals, dcf)

    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    price_unit = "港元" if is_hk_stock(stock_code) else "元"

    report = f"""# {stock_name}({stock_code}) 深度分析报告
> 生成时间: {now} | 市场: {market_tag}

---

## 1. 财务指标分析

| 指标 | 数值 | 说明 |
|------|------|------|
| PE(TTM) | {financial['pe_ttm'] or 'N/A'} | 市盈率，越低越便宜 |
| PB | {financial['pb'] or 'N/A'} | 市净率，<1为破净 |
| PS(TTM) | {financial['ps_ttm'] or 'N/A'} | 市销率 |
| 股息率 | {financial.get('dv_ratio') or 'N/A'}% | 分红回报率 |
| ROE | {financial['roe'] or 'N/A'}% | 净资产收益率，>15%优秀 |
| 毛利率 | {financial['gross_margin'] or 'N/A'}% | 盈利能力核心指标 |
| 净利率 | {financial['net_margin'] or 'N/A'}% | 最终盈利效率 |
| 资产负债率 | {financial['debt_ratio'] or 'N/A'}% | <60%较安全 |
| 流动比率 | {financial['current_ratio'] or 'N/A'} | >2短期偿债能力强 |
| 营收同比 | {format_pct(financial['revenue_yoy'])} | 成长性指标 |
| 净利润同比 | {format_pct(financial['profit_yoy'])} | 成长性指标 |

**估值判断**: {financial['valuation_level']}

---

## 2. 技术分析

### 价格与趋势
| 指标 | 数值 |
|------|------|
| 最新价 | {technical['price'] or 'N/A'} {price_unit} |
| 涨跌幅 | {format_pct(technical['change_pct'])} |
| MA5 | {technical['ma5'] or 'N/A'} |
| MA10 | {technical['ma10'] or 'N/A'} |
| MA20 | {technical['ma20'] or 'N/A'} |
| MA60 | {technical['ma60'] or 'N/A'} |
| **综合趋势** | **{technical['trend']}** |

### MACD
| 指标 | 数值 | 信号 |
|------|------|------|
| DIF | {technical['macd_dif'] or 'N/A'} | {technical['macd_signal']} |
| DEA | {technical['macd_dea'] or 'N/A'} | |
| MACD柱 | {technical['macd_hist'] or 'N/A'} | |

### RSI
| 指标 | 数值 | 信号 |
|------|------|------|
| RSI(14) | {technical['rsi_14'] or 'N/A'} | {technical['rsi_signal']} |

### 布林带
| 指标 | 数值 |
|------|------|
| 上轨 | {technical['boll_upper'] or 'N/A'} |
| 中轨 | {technical['boll_mid'] or 'N/A'} |
| 下轨 | {technical['boll_lower'] or 'N/A'} |
| 位置 | {technical['boll_position'] or 'N/A'} |

### 关键位
| 类型 | 价位 |
|------|------|
| 支撑位 | {technical['support'] or 'N/A'} |
| 阻力位 | {technical['resistance'] or 'N/A'} |

### 🔥 买入信号评分（v4新增）
| 维度 | 分值 | 说明 |
|------|------|------|
| 综合评分 | **{technical.get('signal_score') or 'N/A'}/100** | {technical.get('buy_signal') or 'N/A'} |
| 乖离率(MA5) | {technical.get('bias_ma5', 'N/A')}% | <3%回踩买点，>5%不追高 |
| 量能状态 | {technical.get('volume_status') or 'N/A'} | 缩量回调最佳 |
| 量比(vs5日) | {technical.get('volume_ratio_5d') or 'N/A'} | >1.5放量，<0.7缩量 |

**看多理由**: {'; '.join(technical.get('signal_reasons') or []) or '无'}
**风险提示**: {'; '.join(technical.get('risk_factors') or []) or '无'}

---

## 3. 资金异动

### 今日资金流向
| 类型 | 净流入 |
|------|--------|
| 超大单 | {format_money(fund_flow['super_net']/1e8) if fund_flow['super_net'] else 'N/A'} |
| 大单 | {format_money(fund_flow['big_net']/1e8) if fund_flow['big_net'] else 'N/A'} |
| 中单 | {format_money(fund_flow['medium_net']/1e8) if fund_flow['medium_net'] else 'N/A'} |
| 小单 | {format_money(fund_flow['small_net']/1e8) if fund_flow['small_net'] else 'N/A'} |
| **主力合计** | **{format_money(fund_flow['main_net_inflow']/1e8) if fund_flow['main_net_inflow'] else 'N/A'}** |

**资金信号**: {fund_flow['signal'] or 'N/A'}

### 近5日主力净流入趋势
| 日期 | 主力净流入(亿) |
|------|---------------|
"""

    for item in fund_flow.get("recent_5d_main", []):
        val = item.get("value", 0)
        report += f"| {item.get('date', 'N/A')} | {format_money(val/1e8) if val else 'N/A'} |\n"

    report += f"""
---

## 4. 基本面透视

### 最新季度业绩
| 指标 | 数值 |
|------|------|
| 报告期 | {fundamentals['latest_quarter'] or 'N/A'} |
| 营业收入 | {format_money(fundamentals['revenue']) if fundamentals['revenue'] else 'N/A'} |
| 营收同比 | {format_pct(fundamentals['revenue_yoy'])} |
| 净利润 | {format_money(fundamentals['net_profit']) if fundamentals['net_profit'] else 'N/A'} |
| 净利润同比 | {format_pct(fundamentals['profit_yoy'])} |
| 每股收益 | {fundamentals['eps'] or 'N/A'} |
| 每股净资产 | {fundamentals['bvps'] or 'N/A'} |

### 行业归属
| 项目 | 信息 |
|------|------|
| 所属行业 | {fundamentals['industry'] or 'N/A'} |
| 行业排名 | {fundamentals['industry_rank'] or 'N/A'} |
"""

    if fundamentals.get("quarters"):
        report += "\n### 近4季度业绩趋势\n| 季度 | 营收(亿) | 净利润(亿) | 净利润同比 |\n|------|---------|-----------|----------|\n"
        for q in fundamentals["quarters"]:
            report += f"| {q.get('quarter', 'N/A')} | {q.get('revenue', 'N/A')} | {q.get('profit', 'N/A')} | {format_pct(q.get('profit_yoy'))} |\n"

    report += f"""
---

## 5. DCF 估值

### 估值结果
| 指标 | 数值 |
|------|------|
| 每股自由现金流 | {dcf['fcf_per_share'] or 'N/A'} |
| 内在价值 | **{dcf['intrinsic_value'] or 'N/A'}** |
| 当前价格 | {dcf['current_price'] or 'N/A'} |
| 安全边际 | {dcf['margin_of_safety'] or 'N/A'}% |
| **估值判断** | **{dcf['verdict'] or 'N/A'}** |

### 模型假设
| 参数 | 值 |
|------|-----|
"""

    for assumption in dcf.get("assumptions", []):
        parts = assumption.split(':', 1)
        if len(parts) == 2:
            report += f"| {parts[0]} | {parts[1].strip()} |\n"

    report += f"""
> ⚠️ DCF估值高度依赖假设参数，仅供参考，不构成投资建议。建议调整增长率/折现率做敏感性分析。

---

## 6. AI 智能分析

> 模型: {ai_analysis.get('model', 'N/A')}

### 📋 综合评述
{ai_analysis.get('summary', 'N/A')}

### 💡 操作建议
{ai_analysis.get('operation_advice', 'N/A')}

### ⚠️ 风险提示
{ai_analysis.get('risk_warning', 'N/A')}

### 市场情绪
{ai_analysis.get('market_sentiment', 'N/A')}

### 🔑 关键催化
{ai_analysis.get('key_catalyst', 'N/A')}

### 🎯 目标价分析
{ai_analysis.get('target_price_analysis', 'N/A')}

---

*报告由 AI 股票分析增强系统 v5 自动生成*
"""

    return report, {
        "financial": financial,
        "technical": technical,
        "fund_flow": fund_flow,
        "fundamentals": fundamentals,
        "dcf": dcf,
        "ai_analysis": ai_analysis,
    }


# ============================================================
# 主函数
# ============================================================

def main():
    stock_list_str = os.environ.get("STOCK_LIST", "601899,000426,002714,000582,688063,688122,09868,01810,01788")
    stocks = [s.strip() for s in stock_list_str.split(",") if s.strip()]

    # 是否推送微信（默认推送，设 PUSHPLUS_TOKEN=0 可关闭）
    enable_push = PUSHPLUS_TOKEN and PUSHPLUS_TOKEN != "0"
    
    # 推送模式：single=逐只推送, merged=合并一份推送（默认）
    push_mode = os.environ.get("PUSH_MODE", "merged")

    print(f"准备分析 {len(stocks)} 只股票: {stocks}")
    print(f"AKShare 版本: {ak.__version__}")
    if enable_push:
        print(f"📱 微信推送: 已启用 (模式: {push_mode})")
    else:
        print(f"📱 微信推送: 已关闭")

    success_count = 0
    fail_count = 0
    all_stock_cards = []  # 收集所有股票的推送卡片，最后合并

    for stock_code in stocks:
        try:
            report, analysis_data = generate_stock_report(stock_code)

            output_dir = os.environ.get("REPORT_DIR", "reports")
            os.makedirs(output_dir, exist_ok=True)
            filename = f"enhanced_{stock_code}_{datetime.now().strftime('%Y%m%d')}.md"
            filepath = os.path.join(output_dir, filename)

            with open(filepath, "w", encoding="utf-8") as f:
                f.write(report)

            print(f"  ✅ 报告已保存: {filepath}")

            # 收集推送卡片
            if enable_push:
                push_title, push_html = build_push_summary(
                    stock_code,
                    analysis_data["financial"],
                    analysis_data["technical"],
                    analysis_data["fund_flow"],
                    analysis_data["fundamentals"],
                    analysis_data["dcf"],
                    analysis_data.get("ai_analysis"),
                )
                if push_mode == "single":
                    # 逐只推送模式
                    pushplus_send(push_title, push_html)
                else:
                    # 合并推送模式：收集卡片
                    all_stock_cards.append((push_title, push_html))

            success_count += 1
        except Exception as e:
            print(f"  ❌ 分析失败 {stock_code}: {e}")
            traceback.print_exc()
            fail_count += 1

        # 股票间额外等待
        if stock_code != stocks[-1]:
            print(f"  ⏳ 等待5秒后分析下一只...")
            time.sleep(5)

    # 合并推送：所有股票合并成一份
    if enable_push and success_count > 0:
        now = datetime.now().strftime("%Y-%m-%d %H:%M")
        
        if push_mode == "merged" and all_stock_cards:
            # 合并所有股票卡片为一份推送
            merged_html = f"""
            <div style="font-family: -apple-system, sans-serif; max-width:600px; margin:0 auto; padding:10px;">
              <div style="background:linear-gradient(135deg, #667eea 0%, #764ba2 100%); color:white; padding:16px; border-radius:12px; margin-bottom:12px;">
                <h2 style="margin:0 0 4px 0; font-size:18px;">📊 股票深度分析汇总</h2>
                <p style="margin:0; font-size:13px; opacity:0.85;">{now} | 成功{success_count}只 | 失败{fail_count}只</p>
              </div>
            """
            for i, (title, html) in enumerate(all_stock_cards, 1):
                # 去掉每个卡片的外层 div 包裹，避免嵌套
                card_html = html.strip()
                # 移除最外层 div 的开始和结束标签
                if card_html.startswith('<div style="font-family'):
                    # 找到第一个 > 后面的内容
                    first_gt = card_html.index('>') + 1
                    card_html = card_html[first_gt:]
                    if card_html.endswith('</div>'):
                        card_html = card_html[:-6]
                merged_html += card_html
            
            merged_html += """
              <p style="text-align:center; font-size:11px; color:#999; margin-top:8px;">
                ⚠️ 仅供参考，不构成投资建议 | AI股票分析增强系统 v5
              </p>
            </div>"""
            pushplus_send(f"📊 股票深度分析汇总 ({success_count}只)", merged_html)
        else:
            # 逐只推送模式的汇总
            summary_html = f"""
            <div style="font-family: -apple-system, sans-serif; max-width:600px; margin:0 auto; padding:10px;">
              <div style="background:linear-gradient(135deg, #667eea 0%, #764ba2 100%); color:white; padding:16px; border-radius:12px; margin-bottom:12px;">
                <h2 style="margin:0 0 4px 0; font-size:18px;">📊 今日股票分析汇总</h2>
                <p style="margin:0; font-size:13px; opacity:0.85;">{now} | 成功{success_count}只 | 失败{fail_count}只</p>
              </div>
              <p style="font-size:13px; color:#666; text-align:center;">
                各股详细分析已逐条推送，完整报告请查看本地文件
              </p>
            </div>"""
            pushplus_send("📊 今日股票分析汇总", summary_html)

    print(f"\n{'='*50}")
    print(f"分析完成！成功: {success_count}, 失败: {fail_count}")


if __name__ == "__main__":
    main()
