import logging
from datetime import datetime
from typing import Optional

import yfinance as yf
import pandas as pd
import pytz

from config import GLOBAL_INDICES, NSE_SYMBOL_MAP, SECTORS_IMPACT
from core.angel_bridge import get_angel_bridge

IST = pytz.timezone("Asia/Kolkata")
logger = logging.getLogger(__name__)

_angel = get_angel_bridge()
_angel_available = _angel.authenticate()


def _yf_scalar(df):
    if df is None or df.empty:
        return None
    val = df["Close"].iloc[-1]
    while isinstance(val, pd.Series):
        val = val.iloc[-1]
    return float(val)


def get_nifty_realtime() -> Optional[float]:
    if _angel_available:
        return _angel.get_nifty_ltp()
    try:
        df = yf.download("^NSEI", period="1d", interval="1m", progress=False)
        return _yf_scalar(df)
    except Exception:
        pass
    return None


def get_banknifty_realtime() -> Optional[float]:
    if _angel_available:
        return _angel.get_banknifty_ltp()
    try:
        df = yf.download("^NSEBANK", period="1d", interval="1m", progress=False)
        return _yf_scalar(df)
    except Exception:
        pass
    return None


def get_nifty_candles(interval: str = "5m", days: int = 5) -> Optional[pd.DataFrame]:
    angel_map = {"1m": "1", "5m": "5", "15m": "15", "30m": "30", "1h": "60", "1d": "ONE_DAY"}
    if _angel_available:
        a_interval = angel_map.get(interval, "5")
        return _angel.get_nifty_candles(interval=a_interval, days=days)
    yf_map = {"5m": "5m", "15m": "15m", "1h": "60m", "1d": "1d"}
    yf_period = {"5m": "7d", "15m": "15d", "60m": "1mo", "1d": "3mo"}
    p = yf_period.get(yf_map.get(interval, "5m"), "7d")
    i = yf_map.get(interval, "5m")
    try:
        df = yf.download("^NSEI", period=p, interval=i, progress=False)
        return df if not df.empty else None
    except Exception:
        return None


def get_stock_realtime(symbol: str) -> Optional[float]:
    if _angel_available:
        return _angel.get_stock_future_ltp(symbol)
    yf_sym = f"{symbol}.NS"
    try:
        df = yf.download(yf_sym, period="1d", interval="1m", progress=False)
        return _yf_scalar(df)
    except Exception:
        pass
    return None


def get_global_indices():
    data = {}
    for name, sym in GLOBAL_INDICES.items():
        try:
            df = yf.download(sym, period="5d", interval="1d", progress=False)
            if df.empty:
                continue
            close_curr = _yf_scalar(df)
            close_prev = _yf_scalar(df.iloc[:-1]) if len(df) >= 2 else close_curr
            if close_curr and close_prev:
                change = ((close_curr - close_prev) / close_prev) * 100
                data[name] = {"price": round(close_curr, 2),
                              "change_pct": round(change, 2)}
        except Exception:
            continue
    return data


def _get_yf_price(yf_sym):
    try:
        df = yf.download(yf_sym, period="2d", interval="1d", progress=False)
        return _yf_scalar(df)
    except Exception:
        return None


def get_market_summary():
    summary = {
        "indian_indices": {},
        "global_indices": {},
        "timestamp": datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S %Z"),
    }

    yf_fallback = {"NIFTY 50": "^NSEI", "BANK NIFTY": "^NSEBANK", "SENSEX": "^BSESN"}
    for name, info in NSE_SYMBOL_MAP.items():
        price = None
        if _angel_available:
            price = _angel.get_ltp(info["exchange"], info["symbol"])
        if not price and name in yf_fallback:
            price = _get_yf_price(yf_fallback[name])
        if price is not None:
            summary["indian_indices"][name] = {"price": round(float(price), 2)}

    summary["global_indices"] = get_global_indices()
    return summary


def get_sector_prices():
    sector_data = {}
    for sector, info in SECTORS_IMPACT.items():
        stocks = info["stocks"]
        prices = {}
        for sym in stocks:
            price = get_stock_realtime(sym)
            if price:
                prices[sym] = price
        if prices:
            sector_data[sector] = prices
    return sector_data


def get_nifty_option_chain(expiry: str = ""):
    if _angel_available:
        info = NSE_SYMBOL_MAP.get("NIFTY 50")
        if info:
            return _angel.get_option_chain(info["exchange"], info["symbol"], expiry=expiry)
    try:
        ticker = yf.Ticker("^NSEI")
        expirations = ticker.options
        if expirations:
            target = expirations[0]
            opt = ticker.option_chain(target)
            return {"expiry": target, "calls": opt.calls, "puts": opt.puts}
    except Exception:
        pass
    return None
