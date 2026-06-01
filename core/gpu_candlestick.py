"""
GPU-Accelerated Candlestick Pattern Recognition & Next-Move Prediction
Detects patterns across all Nifty 50 / Bank Nifty constituents in parallel.
"""
import math
import numpy as np
import pandas as pd
from numba import cuda

THREADS = 256


@cuda.jit
def _detect_dojis(open_p, high_p, low_p, close_p, body_pct, output):
    i = cuda.grid(1)
    if i >= close_p.shape[0]:
        return
    o = open_p[i]
    h = high_p[i]
    l = low_p[i]
    c = close_p[i]
    body = o - c
    if body < 0:
        body = -body
    up = h
    if o > c:
        up = up - o
    else:
        up = up - c
    lo = o if o < c else c
    lo = lo - l
    candle_range = h - l
    if candle_range <= 0:
        output[i] = 0
        return
    body_ratio = body / candle_range
    if body_ratio <= body_pct:
        if up > lo * 2:
            output[i] = 3
        elif lo > up * 2:
            output[i] = 4
        else:
            output[i] = 1
    else:
        output[i] = 0


@cuda.jit
def _detect_engulfing(open_p, close_p, output):
    i = cuda.grid(1)
    if i >= close_p.shape[0] or i < 1:
        return
    prev_o = open_p[i-1]
    prev_c = close_p[i-1]
    curr_o = open_p[i]
    curr_c = close_p[i]
    prev_body = prev_c - prev_o
    curr_body = curr_c - curr_o
    if prev_body < 0 and curr_body > 0:
        if curr_c > prev_o and curr_o < prev_c:
            output[i] = 1
            return
    if prev_body > 0 and curr_body < 0:
        if curr_c < prev_o and curr_o > prev_c:
            output[i] = -1
            return
    output[i] = 0


@cuda.jit
def _detect_hammer(open_p, high_p, low_p, close_p, output):
    i = cuda.grid(1)
    if i >= close_p.shape[0]:
        return
    o = open_p[i]
    h = high_p[i]
    l = low_p[i]
    c = close_p[i]
    body = o - c
    if body < 0:
        body = -body
    lower_wick = o if o < c else c
    lower_wick = lower_wick - l
    upper_wick = h
    if o > c:
        upper_wick = upper_wick - o
    else:
        upper_wick = upper_wick - c
    candle_range = h - l
    if candle_range <= 0 or body <= 0:
        output[i] = 0
        return
    if lower_wick >= body * 2 and upper_wick <= body * 0.3:
        output[i] = 1
    elif upper_wick >= body * 2 and lower_wick <= body * 0.3:
        output[i] = -1
    else:
        output[i] = 0


def detect_all_patterns(df):
    o = np.ascontiguousarray(df["Open"].values).ravel().astype(np.float64)
    h = np.ascontiguousarray(df["High"].values).ravel().astype(np.float64)
    l = np.ascontiguousarray(df["Low"].values).ravel().astype(np.float64)
    c = np.ascontiguousarray(df["Close"].values).ravel().astype(np.float64)
    n = len(c)

    doji = np.zeros(n, dtype=np.int32)
    engulf = np.zeros(n, dtype=np.int32)
    hammer = np.zeros(n, dtype=np.int32)

    threads = min(THREADS, n)
    blocks = (n + threads - 1) // threads

    _detect_dojis[blocks, threads](o, h, l, c, 0.1, doji)
    _detect_engulfing[blocks, threads](o, c, engulf)
    _detect_hammer[blocks, threads](o, h, l, c, hammer)
    cuda.synchronize()

    return doji, engulf, hammer


def predict_next(df, symbol=""):
    patterns = {}

    doji, engulf, hammer = detect_all_patterns(df)

    last_doji = doji[-1]
    last_engulf = engulf[-1]
    last_hammer = hammer[-1]
    last_3_doji = doji[-3:]

    from core.technical_indicators import rsi as _rsi, macd as _macd

    c = np.ascontiguousarray(df["Close"].values).ravel()
    close_series = pd.Series(c)
    current_price = float(c[-1])

    rsi_vals = _rsi(close_series, 14)
    macd_line, sig_line, hist_vals = _macd(close_series, 12, 26, 9)

    current_rsi = rsi_vals.iloc[-1] if not pd.isna(rsi_vals.iloc[-1]) else 50
    prev_rsi = rsi_vals.iloc[-2] if len(rsi_vals) > 1 and not pd.isna(rsi_vals.iloc[-2]) else 50
    curr_macd_h = hist_vals.iloc[-1]
    prev_macd_h = hist_vals.iloc[-2] if len(hist_vals) > 1 else 0

    score = 0
    signals = []

    if last_engulf == 1:
        score += 3
        signals.append("Bullish Engulfing 🔥")
    elif last_engulf == -1:
        score -= 3
        signals.append("Bearish Engulfing 🔥")

    if last_hammer == 1:
        score += 2
        signals.append("Hammer (bullish reversal)")
    elif last_hammer == -1:
        score -= 2
        signals.append("Shooting Star (bearish reversal)")

    if 1 in last_3_doji:
        if last_doji == 3:
            score += 1
            signals.append("Gravestone Doji (bearish)")
        elif last_doji == 4:
            score += 1
            signals.append("Dragonfly Doji (bullish)")
        else:
            signals.append("Doji (indecision)")

    rsi_signal = ""
    if current_rsi < 30:
        score += 2
        rsi_signal = f"RSI oversold ({current_rsi:.0f})"
    elif current_rsi > 70:
        score -= 2
        rsi_signal = f"RSI overbought ({current_rsi:.0f})"
    elif current_rsi > current_rsi - 5 and prev_rsi < current_rsi:
        score += 1
        rsi_signal = f"RSI rising ({current_rsi:.0f})"
    elif current_rsi < current_rsi + 5 and prev_rsi > current_rsi:
        score -= 1
        rsi_signal = f"RSI falling ({current_rsi:.0f})"
    if rsi_signal:
        signals.append(rsi_signal)

    if prev_macd_h <= 0 and curr_macd_h > 0:
        score += 1.5
        signals.append("MACD bullish crossover")
    elif prev_macd_h >= 0 and curr_macd_h < 0:
        score -= 1.5
        signals.append("MACD bearish crossover")

    low_arr = np.ascontiguousarray(df["Low"].values).ravel()
    high_arr = np.ascontiguousarray(df["High"].values).ravel()
    support = float(pd.Series(low_arr).rolling(20).min().iloc[-1])
    resistance = float(pd.Series(high_arr).rolling(20).max().iloc[-1])
    near_support = (current_price - support) / current_price < 0.02
    near_resistance = (resistance - current_price) / current_price < 0.02
    if near_support and score >= 0:
        score += 1
        signals.append("Near support")
    if near_resistance and score <= 0:
        score -= 1
        signals.append("Near resistance")

    if score >= 3:
        direction = "BUY"
        confidence = min(abs(score) / 6, 1.0)
    elif score <= -3:
        direction = "SELL"
        confidence = min(abs(score) / 6, 1.0)
    elif score >= 1:
        direction = "BUY"
        confidence = 0.3
    elif score <= -1:
        direction = "SELL"
        confidence = 0.3
    else:
        direction = "HOLD"
        confidence = 0

    return {
        "symbol": symbol,
        "price": round(current_price, 2),
        "direction": direction,
        "confidence": round(confidence, 2),
        "score": score,
        "signals": signals or ["No clear pattern"],
        "rsi": round(current_rsi, 1),
        "support": round(support, 2),
        "resistance": round(resistance, 2),
    }


def batch_predict(symbols, df_dict):
    results = []
    for sym in symbols:
        df = df_dict.get(sym)
        if df is not None and len(df) >= 30:
            try:
                r = predict_next(df, sym)
                results.append(r)
            except Exception as e:
                results.append({"symbol": sym, "direction": "HOLD",
                                "confidence": 0, "signals": [f"Error: {e}"]})
    return results


def rank_predictions(results, top_n=5):
    buys = sorted([r for r in results if r["direction"] == "BUY"],
                  key=lambda x: -x["confidence"])
    sells = sorted([r for r in results if r["direction"] == "SELL"],
                   key=lambda x: -x["confidence"])
    return {"top_buys": buys[:top_n], "top_sells": sells[:top_n]}


def fetch_and_predict(symbols_dict, period="2mo"):
    import yfinance as yf
    df_dict = {}
    print(f"[GPU] Fetching data for {len(symbols_dict)} symbols...")
    for sym in symbols_dict:
        try:
            yf_sym = f"{sym}.NS"
            df = yf.download(yf_sym, period=period, interval="1d", progress=False)
            if not df.empty:
                df_dict[sym] = df
        except Exception:
            continue
    print(f"[GPU] Got data for {len(df_dict)} symbols")
    results = batch_predict(symbols_dict, df_dict)
    return rank_predictions(results)
