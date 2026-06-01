"""
GPU-Accelerated Technical Indicators & Signal Generation
Computes RSI, MACD, Bollinger Bands for all Nifty 50 stocks in parallel.
"""
import math
import numpy as np
import pandas as pd
from numba import cuda
from numba import float64, int64

THREADS = 256


@cuda.jit
def _gpu_rsi(prices, period, output):
    i = cuda.grid(1)
    n = prices.shape[0]
    if i >= n or prices[i] <= 0:
        return
    gains = 0.0
    losses = 0.0
    count = 0
    for j in range(max(0, i - period), i):
        if j <= 0:
            continue
        diff = prices[j] - prices[j - 1]
        if diff > 0:
            gains += diff
        else:
            losses -= diff
        count += 1
    if count > 0 and losses != 0:
        rs = (gains / count) / (losses / count)
        output[i] = 100.0 - 100.0 / (1.0 + rs)
    elif count > 0 and losses == 0:
        output[i] = 100.0


def batch_rsi(prices_array, period=14):
    n = len(prices_array)
    result = np.zeros(n, dtype=np.float64)
    threads = min(THREADS, n)
    blocks = (n + threads - 1) // threads
    _gpu_rsi[blocks, threads](prices_array.astype(np.float64), period, result)
    cuda.synchronize()
    return result


@cuda.jit
def _gpu_macd(prices, fast, slow, signal, macd_out, signal_out, hist_out):
    i = cuda.grid(1)
    n = prices.shape[0]
    if i >= n:
        return
    if i < slow:
        macd_out[i] = 0
        signal_out[i] = 0
        hist_out[i] = 0
        return

    def ema(data, span, idx):
        alpha = 2.0 / (span + 1)
        val = data[0]
        for k in range(1, idx + 1):
            val = data[k] * alpha + val * (1 - alpha)
        return val

    ema_fast = ema(prices[:i + 1], fast, i)
    ema_slow = ema(prices[:i + 1], slow, i)
    macd_out[i] = ema_fast - ema_slow

    if i >= signal:
        macd_series = macd_out[:i + 1]
        macd_series_copy = cuda.local.array(1024, dtype=float64)
        n_copy = min(i + 1, 1024)
        for k in range(n_copy):
            macd_series_copy[k] = macd_series[k]
        signal_out[i] = ema(macd_series_copy, signal, n_copy - 1)
        hist_out[i] = macd_out[i] - signal_out[i]


def batch_macd(prices_array, fast=12, slow=26, signal=9):
    n = len(prices_array)
    macd = np.zeros(n, dtype=np.float64)
    sig = np.zeros(n, dtype=np.float64)
    hist = np.zeros(n, dtype=np.float64)
    threads = min(THREADS, n)
    blocks = (n + threads - 1) // threads
    _gpu_macd[blocks, threads](prices_array.astype(np.float64),
                                 fast, slow, signal, macd, sig, hist)
    cuda.synchronize()
    return macd, sig, hist


def generate_signals(symbol, df):
    """Compute all indicators and return BUY/SELL signal for one symbol."""
    if df is None or len(df) < 50:
        return {"symbol": symbol, "signal": "HOLD", "strength": 0}

    prices = df["Close"].values.astype(np.float64)
    if len(prices) < 50:
        return {"symbol": symbol, "signal": "HOLD", "strength": 0}

    rsi_vals = batch_rsi(prices, 14)
    macd_vals, sig_vals, hist_vals = batch_macd(prices, 12, 26, 9)

    current_rsi = rsi_vals[-1]
    prev_hist = hist_vals[-2] if len(hist_vals) > 2 else 0
    curr_hist = hist_vals[-1]
    current_price = float(prices[-1])

    score = 0
    reasons = []

    if current_rsi > 0:
        if current_rsi < 30:
            score += 2
            reasons.append(f"RSI oversold ({current_rsi:.0f})")
        elif current_rsi > 70:
            score -= 2
            reasons.append(f"RSI overbought ({current_rsi:.0f})")
        elif 40 <= current_rsi <= 60:
            pass

    if prev_hist <= 0 and curr_hist > 0:
        score += 1
        reasons.append("MACD bullish crossover")
    elif prev_hist >= 0 and curr_hist < 0:
        score -= 1
        reasons.append("MACD bearish crossover")

    if score >= 2:
        signal = "BUY"
        strength = min(score / 3, 1.0)
    elif score <= -2:
        signal = "SELL"
        strength = min(abs(score) / 3, 1.0)
    else:
        signal = "HOLD"
        strength = 0

    return {
        "symbol": symbol,
        "price": round(current_price, 2),
        "rsi": round(current_rsi, 1),
        "signal": signal,
        "strength": round(strength, 2),
        "reasons": "; ".join(reasons) if reasons else "No clear signal",
    }


def batch_generate_signals(symbols_dict):
    """Generate signals for multiple stocks using GPU-accelerated indicators."""
    from core.market_data import get_stock_realtime
    import yfinance as yf

    results = []
    for symbol in symbols_dict:
        try:
            yf_sym = f"{symbol}.NS"
            df = yf.download(yf_sym, period="3mo", interval="1d", progress=False)
            if df is not None and not df.empty:
                sig = generate_signals(symbol, df)
                results.append(sig)
        except Exception:
            continue
    return results


def get_top_signals(symbols_dict, top_n=5):
    signals = batch_generate_signals(symbols_dict)
    buys = sorted([s for s in signals if s["signal"] == "BUY"],
                  key=lambda x: -x["strength"])
    sells = sorted([s for s in signals if s["signal"] == "SELL"],
                   key=lambda x: -x["strength"])
    return {
        "top_buys": buys[:top_n],
        "top_sells": sells[:top_n],
        "all": signals,
    }
