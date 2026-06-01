import pandas as pd
import numpy as np


def rsi(series, period=14):
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.rolling(window=period, min_periods=period).mean()
    avg_loss = loss.rolling(window=period, min_periods=period).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))
    return rsi


def macd(series, fast=12, slow=26, signal=9):
    ema_fast = series.ewm(span=fast).mean()
    ema_slow = series.ewm(span=slow).mean()
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal).mean()
    histogram = macd_line - signal_line
    return macd_line, signal_line, histogram


def bollinger_bands(series, period=20, std_dev=2):
    sma = series.rolling(window=period).mean()
    std = series.rolling(window=period).std()
    upper = sma + std_dev * std
    lower = sma - std_dev * std
    return upper, sma, lower


def atr(df, period=14):
    high_low = df["High"] - df["Low"]
    high_close = abs(df["High"] - df["Close"].shift())
    low_close = abs(df["Low"] - df["Close"].shift())
    tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    return tr.rolling(window=period).mean()


def support_resistance(series, window=10):
    levels = {}
    rolling_min = series.rolling(window=window, center=True).min()
    rolling_max = series.rolling(window=window, center=True).max()
    levels["support"] = rolling_min.iloc[-1]
    levels["resistance"] = rolling_max.iloc[-1]
    return levels


def get_signal(series):
    r = rsi(series)
    macd_line, signal_line, hist = macd(series)
    bb_upper, bb_mid, bb_lower = bollinger_bands(series)
    current_price = series.iloc[-1]

    signals = []

    if not r.empty and not pd.isna(r.iloc[-1]):
        if r.iloc[-1] < 30:
            signals.append(("OVERSOLD", f"RSI={r.iloc[-1]:.1f}"))
        elif r.iloc[-1] > 70:
            signals.append(("OVERBOUGHT", f"RSI={r.iloc[-1]:.1f}"))

    if not pd.isna(hist.iloc[-1]) and not pd.isna(hist.iloc[-2]):
        if hist.iloc[-1] > 0 and hist.iloc[-2] <= 0:
            signals.append(("MACD_BULLISH", "MACD crossed above signal"))
        elif hist.iloc[-1] < 0 and hist.iloc[-2] >= 0:
            signals.append(("MACD_BEARISH", "MACD crossed below signal"))

    if current_price <= bb_lower.iloc[-1]:
        signals.append(("BB_BOUNCE", "Price at lower band"))
    elif current_price >= bb_upper.iloc[-1]:
        signals.append(("BB_REJECT", "Price at upper band"))

    return signals
