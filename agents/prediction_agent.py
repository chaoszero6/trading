"""
Prediction Agent — directional predictor for NIFTY, BANKNIFTY, and constituents.
Modes:
  15m    — 15-min candle prediction
  daily  — daily directional bias
  volume — 5-min + volume/price action signals
  live   — real-time via Angel One API
"""

import sqlite3
import logging
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

from config import NSE_SYMBOL_MAP, NIFTY50_CONSTITUENTS, BANKNIFTY_CONSTITUENTS
from core.gpu_candlestick import detect_all_patterns
from core.gpu_signals import batch_rsi, batch_macd

logger = logging.getLogger(__name__)

PREDICTION_DB = Path("data/predictions.db")

INDEX_SYMBOLS = ["NIFTY", "BANKNIFTY"]
CONSTITUENTS = sorted(set(
    list(NIFTY50_CONSTITUENTS.keys()) +
    list(BANKNIFTY_CONSTITUENTS.keys())
))
ALL_SYMBOLS = sorted(set(INDEX_SYMBOLS + CONSTITUENTS))

YF_SYMBOL_MAP = {
    "NIFTY": "^NSEI",
    "BANKNIFTY": "^NSEBANK",
    "M&M": "M%26M.NS",
}

YF_MAX_PERIOD = {"5m": "60d", "15m": "60d", "1d": "1y"}
DIRECTION_THRESHOLD = {"5m": 0.003, "15m": 0.004, "daily": 0.008, "volume": 0.003}
LOOKBACK_MIN = {"5m": 30, "15m": 25, "daily": 20, "volume": 30}


def init_db():
    PREDICTION_DB.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(PREDICTION_DB))
    conn.execute("""
        CREATE TABLE IF NOT EXISTS predictions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT NOT NULL,
            timestamp TEXT NOT NULL,
            mode TEXT NOT NULL DEFAULT '5m',
            predicted_direction TEXT NOT NULL,
            confidence REAL,
            score REAL,
            predicted_price REAL,
            actual_next_close REAL,
            actual_direction TEXT,
            correct INTEGER,
            signals TEXT,
            rsi REAL,
            backtest_id INTEGER DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now'))
        )
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_pred_sym_time
        ON predictions(symbol, timestamp)
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS backtest_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_date TEXT DEFAULT (datetime('now')),
            mode TEXT NOT NULL DEFAULT '5m',
            symbols_processed INTEGER,
            total_predictions INTEGER,
            correct_predictions INTEGER,
            accuracy REAL,
            high_conf_count INTEGER,
            high_conf_correct INTEGER,
            high_conf_accuracy REAL
        )
    """)
    # Migrate existing tables if columns missing
    cols = [r[1] for r in conn.execute("PRAGMA table_info(predictions)")]
    if "mode" not in cols:
        conn.execute("ALTER TABLE predictions ADD COLUMN mode TEXT NOT NULL DEFAULT '5m'")
    cols2 = [r[1] for r in conn.execute("PRAGMA table_info(backtest_runs)")]
    if "mode" not in cols2:
        conn.execute("ALTER TABLE backtest_runs ADD COLUMN mode TEXT NOT NULL DEFAULT '5m'")
    conn.commit()
    return conn


def _actual_direction(current_close, next_close, threshold):
    change = (next_close - current_close) / current_close
    if change > threshold:
        return "UP"
    elif change < -threshold:
        return "DOWN"
    return "SIDEWAYS"


def _map_to_direction(pred_dict):
    d = pred_dict["direction"]
    if d == "BUY":
        return "UP"
    elif d == "SELL":
        return "DOWN"
    return "SIDEWAYS"


def _normalize_df(df):
    if not isinstance(df, pd.DataFrame):
        return None
    df = df.copy()
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.droplevel(1)
    df.columns = [str(c).lower() for c in df.columns]
    if df.index.tz is not None:
        df.index = df.index.tz_localize(None)
    df.index.name = "timestamp"
    return df


def fetch_yfinance(symbols, interval="5m", period=None):
    if period is None:
        period = YF_MAX_PERIOD.get(interval, "60d")
    if interval == "1d":
        period = "1y"
    import yfinance as yf
    result = {}
    n = len(symbols)
    for i, sym in enumerate(symbols, 1):
        yf_sym = YF_SYMBOL_MAP.get(sym, f"{sym}.NS")
        try:
            df = yf.download(yf_sym, period=period, interval=interval, progress=False)
            if df is not None and isinstance(df, pd.DataFrame) and not df.empty:
                df = _normalize_df(df)
                result[sym] = df
                logger.info(f"[{i}/{n}] {sym}: {len(df)} candles")
            else:
                logger.warning(f"[{i}/{n}] {sym}: no data")
        except Exception as e:
            logger.warning(f"[{i}/{n}] {sym}: error - {e}")
    return result


def _compute_volume_signals(close, high, low, volume, idx):
    """Compute volume-based signals at index idx."""
    signals = []
    score_boost = 0.0

    lookback_start = max(0, idx - 20)
    avg_vol = float(np.mean(volume[lookback_start:idx + 1]))
    curr_vol = float(volume[idx])

    if avg_vol > 0:
        vol_ratio = curr_vol / avg_vol
        if vol_ratio > 1.5:
            signals.append(f"Vol x{vol_ratio:.1f}x avg")
            score_boost += 1.0
        elif vol_ratio > 1.2:
            signals.append(f"Vol x{vol_ratio:.1f}x avg")
            score_boost += 0.5
        elif vol_ratio < 0.5:
            signals.append(f"Low vol x{vol_ratio:.1f}")
            score_boost -= 0.5

    cum_tp_vol = 0.0
    cum_vol = 0.0
    for j in range(max(0, idx - 19), idx + 1):
        tp_val = (high[j] + low[j] + close[j]) / 3
        cum_tp_vol += tp_val * volume[j]
        cum_vol += volume[j]

    if cum_vol > 0:
        vwap = cum_tp_vol / cum_vol
        if close[idx] > vwap * 1.002:
            score_boost += 0.5
            signals.append("Above VWAP")
        elif close[idx] < vwap * 0.998:
            score_boost -= 0.5
            signals.append("Below VWAP")

    return score_boost, signals


def predict_from_arrays(close, high, low, open_p, doji_arr, engulf_arr, hammer_arr,
                        rsi_arr, hist_arr, idx, symbol="", volume=None):
    i = idx
    current_close = float(close[i])

    score = 0.0
    signals_list = []

    if engulf_arr[i] == 1:
        score += 3
        signals_list.append("Bullish Engulfing")
    elif engulf_arr[i] == -1:
        score -= 3
        signals_list.append("Bearish Engulfing")

    if hammer_arr[i] == 1:
        score += 2
        signals_list.append("Hammer")
    elif hammer_arr[i] == -1:
        score -= 2
        signals_list.append("Shooting Star")

    last_3_doji = doji_arr[max(0, i - 2):i + 1]
    if 1 in last_3_doji:
        if doji_arr[i] == 3:
            score += 1
            signals_list.append("Gravestone Doji")
        elif doji_arr[i] == 4:
            score += 1
            signals_list.append("Dragonfly Doji")
        else:
            signals_list.append("Doji")

    current_rsi = float(rsi_arr[i])
    prev_rsi = float(rsi_arr[i - 1]) if i > 0 else 50
    if current_rsi < 30:
        score += 2
        signals_list.append(f"RSI oversold ({current_rsi:.0f})")
    elif current_rsi > 70:
        score -= 2
        signals_list.append(f"RSI overbought ({current_rsi:.0f})")
    elif current_rsi > 50 and current_rsi > prev_rsi:
        score += 1
        signals_list.append(f"RSI rising ({current_rsi:.0f})")
    elif current_rsi <= 50 and current_rsi < prev_rsi:
        score -= 1
        signals_list.append(f"RSI falling ({current_rsi:.0f})")

    curr_macd_h = float(hist_arr[i])
    prev_macd_h = float(hist_arr[i - 1]) if i > 0 else 0
    if prev_macd_h <= 0 and curr_macd_h > 0:
        score += 1.5
        signals_list.append("MACD bullish crossover")
    elif prev_macd_h >= 0 and curr_macd_h < 0:
        score -= 1.5
        signals_list.append("MACD bearish crossover")

    lookback = max(0, i - 19)
    support = float(np.min(low[lookback:i + 1]))
    resistance = float(np.max(high[lookback:i + 1]))
    near_support = (current_close - support) / current_close < 0.02
    near_resistance = (resistance - current_close) / current_close < 0.02
    if near_support and score >= 0:
        score += 1
        signals_list.append("Near support")
    if near_resistance and score <= 0:
        score -= 1
        signals_list.append("Near resistance")

    if volume is not None:
        vol_boost, vol_sigs = _compute_volume_signals(close, high, low, volume, i)
        score += vol_boost
        signals_list.extend(vol_sigs)

    if score >= 3:
        pred_dir = "BUY"
        confidence = min(abs(score) / 6, 1.0)
    elif score <= -3:
        pred_dir = "SELL"
        confidence = min(abs(score) / 6, 1.0)
    elif score >= 1:
        pred_dir = "BUY"
        confidence = 0.3
    elif score <= -1:
        pred_dir = "SELL"
        confidence = 0.3
    else:
        pred_dir = "HOLD"
        confidence = 0.0

    return {
        "direction": pred_dir,
        "confidence": round(confidence, 2),
        "score": round(score, 1),
        "signals": ", ".join(signals_list) if signals_list else "No clear pattern",
        "rsi": round(current_rsi, 1),
        "price": round(current_close, 2),
    }


def run_backtest(symbol, df, conn, backtest_id, mode="5m"):
    if df is None or len(df) < LOOKBACK_MIN[mode]:
        return 0, 0, 0, 0

    threshold = DIRECTION_THRESHOLD[mode]
    min_lookback = LOOKBACK_MIN[mode]

    close = np.ascontiguousarray(df["close"].values, dtype=np.float64)
    high = np.ascontiguousarray(df["high"].values, dtype=np.float64)
    low = np.ascontiguousarray(df["low"].values, dtype=np.float64)
    open_p = np.ascontiguousarray(df["open"].values, dtype=np.float64)
    volume = np.ascontiguousarray(df["volume"].values, dtype=np.float64) if "volume" in df.columns else None

    candle_df = pd.DataFrame({"Open": open_p, "High": high, "Low": low, "Close": close})
    doji_arr, engulf_arr, hammer_arr = detect_all_patterns(candle_df)

    rsi_arr = batch_rsi(close, 14)
    _, _, hist_arr = batch_macd(close, 12, 26, 9)

    total = 0
    correct = 0
    high_conf = 0
    high_conf_correct = 0

    cursor = conn.cursor()
    rows_batch = []

    for i in range(min_lookback, len(df) - 1):
        current_close = float(close[i])
        next_close = float(close[i + 1])
        actual_dir = _actual_direction(current_close, next_close, threshold)

        pred = predict_from_arrays(
            close, high, low, open_p,
            doji_arr, engulf_arr, hammer_arr,
            rsi_arr, hist_arr, i, symbol,
            volume=volume
        )

        pred_direction = _map_to_direction(pred)

        if mode == "daily":
            if pred_direction == "UP" and actual_dir != "DOWN":
                correct_flag = 1
            elif pred_direction == "DOWN" and actual_dir != "UP":
                correct_flag = 1
            elif pred_direction == "SIDEWAYS":
                correct_flag = 1 if actual_dir == "SIDEWAYS" else 0
            else:
                correct_flag = 0
        else:
            correct_flag = 1 if pred_direction == actual_dir else 0

        total += 1
        if correct_flag:
            correct += 1
        if pred["confidence"] >= 0.5:
            high_conf += 1
            if correct_flag:
                high_conf_correct += 1

        timestamp = str(df.index[i])
        if isinstance(df.index, pd.DatetimeIndex):
            timestamp = df.index[i].strftime("%Y-%m-%d %H:%M:%S")

        rows_batch.append((
            symbol, timestamp, mode, pred_direction, pred["confidence"], pred["score"],
            pred["price"], round(next_close, 2),
            actual_dir, correct_flag,
            pred["signals"], pred["rsi"], backtest_id
        ))

    cursor.executemany("""
        INSERT INTO predictions
            (symbol, timestamp, mode, predicted_direction, confidence, score,
             predicted_price, actual_next_close, actual_direction,
             correct, signals, rsi, backtest_id)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, rows_batch)
    conn.commit()

    return total, correct, high_conf, high_conf_correct


def backtest_all(mode="5m", symbols=None, conn=None):
    if conn is None:
        conn = init_db()
    if symbols is None:
        symbols = ALL_SYMBOLS

    yf_interval = {"daily": "1d", "volume": "5m", "15m": "15m", "5m": "5m"}.get(mode, mode)

    label = {"15m": "15-min", "daily": "Daily", "volume": "5-min+Volume", "5m": "5-min"}.get(mode, f"{mode}")
    print(f"\n{'='*60}")
    print(f"  PREDICTION BACKTEST — {label.upper()}")
    print(f"  Symbols: {len(symbols)}")
    print(f"  Threshold: {DIRECTION_THRESHOLD[mode]*100:.1f}%")
    print(f"{'='*60}\n")

    print(f"Fetching {yf_interval} candle data via yfinance...")
    data = fetch_yfinance(symbols, interval=yf_interval)

    if not data:
        print("ERROR: No data fetched. Aborting.")
        return None

    print(f"\nFetched data for {len(data)} symbols. Running backtest...\n")

    cursor = conn.cursor()
    cursor.execute("INSERT INTO backtest_runs (mode, symbols_processed) VALUES (?, ?)",
                   (mode, len(data)))
    backtest_id = cursor.lastrowid
    conn.commit()

    total_all = 0
    correct_all = 0
    high_conf_all = 0
    high_conf_correct_all = 0
    per_symbol = []

    for sym in sorted(data.keys()):
        df = data[sym]
        t, c, hc, hcc = run_backtest(sym, df, conn, backtest_id, mode)
        total_all += t
        correct_all += c
        high_conf_all += hc
        high_conf_correct_all += hcc
        acc = (c / t * 100) if t > 0 else 0
        hc_acc = (hcc / hc * 100) if hc > 0 else 0
        per_symbol.append((sym, t, c, acc, hc, hc_acc))
        print(f"  {sym:12s}  {t:4d} preds  {c:4d} correct  {acc:5.1f}%  "
              f"(high-conf: {hc:3d}/{hcc:3d} = {hc_acc:5.1f}%)")

    overall_acc = (correct_all / total_all * 100) if total_all > 0 else 0
    hc_overall_acc = (high_conf_correct_all / high_conf_all * 100) if high_conf_all > 0 else 0

    cursor.execute("""
        UPDATE backtest_runs SET
            total_predictions=?, correct_predictions=?, accuracy=?,
            high_conf_count=?, high_conf_correct=?, high_conf_accuracy=?
        WHERE id=?
    """, (total_all, correct_all, round(overall_acc, 2),
          high_conf_all, high_conf_correct_all, round(hc_overall_acc, 2),
          backtest_id))
    conn.commit()

    print(f"\n{'─'*60}")
    print(f"  [{label.upper()}] OVERALL: {total_all} preds, {correct_all} correct, "
          f"{overall_acc:.1f}%")
    print(f"  [{label.upper()}] HIGH-CONF: {high_conf_all} preds, "
          f"{high_conf_correct_all} correct, {hc_overall_acc:.1f}%")
    print(f"{'─'*60}\n")

    return {
        "mode": mode,
        "backtest_id": backtest_id,
        "total": total_all,
        "correct": correct_all,
        "accuracy": round(overall_acc, 2),
        "high_conf_total": high_conf_all,
        "high_conf_correct": high_conf_correct_all,
        "high_conf_accuracy": round(hc_overall_acc, 2),
        "per_symbol": per_symbol,
    }


def run_all_backtests(conn=None):
    if conn is None:
        conn = init_db()

    results = {}
    for mode in ["15m", "daily", "volume"]:
        r = backtest_all(mode=mode, conn=conn)
        results[mode] = r

    print("\n" + "=" * 60)
    print("  COMPARISON SUMMARY")
    print("=" * 60)
    print(f"{'Mode':12s} {'Preds':>8s} {'Correct':>8s} {'Acc%':>7s}  "
          f"{'HC':>6s} {'HC_OK':>6s} {'HC%':>7s}")
    print("─" * 60)
    for mode in ["15m", "daily", "volume"]:
        r = results.get(mode)
        if r:
            print(f"{mode:12s} {r['total']:8d} {r['correct']:8d} "
                  f"{r['accuracy']:>6.1f}%  "
                  f"{r['high_conf_total']:6d} {r['high_conf_correct']:6d} "
                  f"{r['high_conf_accuracy']:>6.1f}%")
    print("─" * 60)
    print()

    return results


def predict_daily_live(symbols=None):
    """Predict next-day direction using daily candles (for !daily command / EOD)."""
    if symbols is None:
        symbols = INDEX_SYMBOLS
    print("Fetching daily candle data via yfinance...")
    data = fetch_yfinance(symbols, interval="1d", period="1y")

    results = []
    for sym in symbols:
        df = data.get(sym)
        if df is None or len(df) < 25:
            results.append({
                "symbol": sym, "direction": "HOLD", "confidence": 0,
                "score": 0, "signals": "Insufficient data",
                "rsi": 50, "price": 0
            })
            continue

        close = np.ascontiguousarray(df["close"].values, dtype=np.float64)
        high = np.ascontiguousarray(df["high"].values, dtype=np.float64)
        low = np.ascontiguousarray(df["low"].values, dtype=np.float64)
        open_p = np.ascontiguousarray(df["open"].values, dtype=np.float64)

        candle_df = pd.DataFrame({"Open": open_p, "High": high, "Low": low, "Close": close})
        doji_arr, engulf_arr, hammer_arr = detect_all_patterns(candle_df)
        rsi_arr = batch_rsi(close, 14)
        _, _, hist_arr = batch_macd(close, 12, 26, 9)

        i = len(df) - 1
        pred = predict_from_arrays(close, high, low, open_p, doji_arr, engulf_arr,
                                    hammer_arr, rsi_arr, hist_arr, i, sym)
        pred["symbol"] = sym
        results.append(pred)

    return results


def print_daily_predictions(results):
    """Print daily predictions nicely for Discord embed."""
    if not results:
        return "No daily predictions available."
    lines = []
    for r in results:
        emoji = {"BUY": "🟢", "SELL": "🔴", "HOLD": "⚪"}.get(r["direction"], "⚪")
        conf = r["confidence"]
        if conf >= 0.7:
            stars = "⭐⭐⭐"
        elif conf >= 0.5:
            stars = "⭐⭐"
        elif conf >= 0.3:
            stars = "⭐"
        else:
            stars = ""
        lines.append(
            f"{emoji} **{r['symbol']}**: {r['direction']} "
            f"(conf: {conf:.0%}{stars})"
        )
        lines.append(f"   RSI: {r['rsi']} | Score: {r['score']} | {r['signals'][:80]}")
    return "\n".join(lines)


def predict_live(symbols=None):
    from core.angel_bridge import get_angel_bridge
    if symbols is None:
        symbols = INDEX_SYMBOLS
    bridge = get_angel_bridge()
    if not bridge._authenticated:
        if not bridge.authenticate():
            logger.error("Angel One auth failed")
            return []
    print("Fetching live data via Angel One...")
    data = {}
    for sym in symbols:
        if sym == "NIFTY":
            df = bridge.get_nifty_candles(interval="5", days=5)
        elif sym == "BANKNIFTY":
            df = bridge.get_nifty_candles(interval="5", days=5)
        else:
            cfg = ("NSE", f"{sym}-EQ")
            from_date = (datetime.now() - timedelta(days=5)).strftime("%Y-%m-%d %H:%M")
            to_date = datetime.now().strftime("%Y-%m-%d %H:%M")
            df = bridge.get_candle_data(cfg[0], cfg[1], "FIVE_MINUTE", from_date, to_date)
        if df is not None and not df.empty:
            data[sym] = df
    results = []
    for sym in symbols:
        df = data.get(sym)
        if df is None or len(df) < 30:
            results.append({
                "symbol": sym, "direction": "HOLD", "confidence": 0,
                "score": 0, "signals": "Insufficient data",
                "rsi": 50, "price": 0
            })
            continue
        close = np.ascontiguousarray(df["close"].values, dtype=np.float64)
        high = np.ascontiguousarray(df["high"].values, dtype=np.float64)
        low = np.ascontiguousarray(df["low"].values, dtype=np.float64)
        open_p = np.ascontiguousarray(df["open"].values, dtype=np.float64)
        candle_df = pd.DataFrame({"Open": open_p, "High": high, "Low": low, "Close": close})
        doji_arr, engulf_arr, hammer_arr = detect_all_patterns(candle_df)
        rsi_arr = batch_rsi(close, 14)
        _, _, hist_arr = batch_macd(close, 12, 26, 9)
        i = len(df) - 1
        pred = predict_from_arrays(close, high, low, open_p, doji_arr, engulf_arr,
                                    hammer_arr, rsi_arr, hist_arr, i, sym)
        results.append({"symbol": sym, **pred})
    return results


def print_live_predictions(results):
    if not results:
        print("No predictions available.")
        return
    print(f"\n{'─'*60}")
    print(f"  LIVE 5-min PREDICTIONS  ({datetime.now().strftime('%H:%M:%S')})")
    print(f"{'─'*60}")
    print(f"{'Symbol':12s} {'Dir':6s} {'Conf':6s} {'Score':6s}  {'Signals'}")
    print(f"{'─'*54}")
    for r in results:
        print(f"{r['symbol']:12s} {r['direction']:6s} {r['confidence']:<6.2f} "
              f"{r['score']:<6.1f}  {r['signals'][:50]}")
    print(f"{'─'*60}\n")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s [%(levelname)s] %(message)s")
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "live":
        results = predict_live()
        print_live_predictions(results)
    elif len(sys.argv) > 1 and sys.argv[1] in ("15m", "daily", "volume"):
        conn = init_db()
        backtest_all(mode=sys.argv[1], conn=conn)
    else:
        conn = init_db()
        run_all_backtests(conn=conn)
