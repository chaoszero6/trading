"""
VWAP Pullback Breakout Strategy — trades index options on 5-min VWAP pullback setups.
- VWAP as trend filter (price above = long bias, below = short bias)
- HHLH / LHLL market structure confirmation
- Pullback toward VWAP → breakout candle → entry
- SL at recent swing low, target 2R
- Quality scoring: only highest-quality setup at a time
- Volume + risk filters to avoid false signals
"""

import sqlite3
import time
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import requests

from config import NSE_SYMBOL_MAP

logger = logging.getLogger(__name__)

IST = timezone(timedelta(hours=5, minutes=30))
DB_PATH = Path("data/vwap_pb.db")
WEBHOOK_URL = "https://discord.com/api/webhooks/1511217504964444253/-l8tBiLe6Q0Ne3injvTK9miE5zAc2I3ZGiib59G6u3J8kUZvhGSKc__0G1GOs7vBA7p8"

SYMBOLS = ["NIFTY", "BANKNIFTY"]
CHECK_INTERVAL = 300

# Risk limits
MAX_SL_POINTS = {"NIFTY": 120, "BANKNIFTY": 300}
MIN_AVG_VOLUME = 100
CAPITAL = 50000
MAX_RISK_PCT = 0.01
MAX_CONSECUTIVE_LOSSES = 2
MAX_DAILY_LOSS_PCT = 0.03


def _now_ist():
    return datetime.now(IST)


def _market_open():
    t = _now_ist()
    if t.weekday() >= 5:
        return False
    open_t = t.replace(hour=9, minute=15, second=0)
    close_t = t.replace(hour=15, minute=30, second=0)
    return open_t <= t <= close_t


def _init_db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("""
        CREATE TABLE IF NOT EXISTS vwap_trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            symbol TEXT NOT NULL,
            direction TEXT NOT NULL,
            index_name TEXT,
            strike INTEGER,
            option_type TEXT,
            entry_premium REAL,
            entry_spot REAL,
            sl REAL,
            target REAL,
            trigger_price REAL,
            pullback_low REAL,
            pullback_high REAL,
            breakout_candle_high REAL,
            breakout_candle_low REAL,
            swing_low REAL,
            quality_score REAL,
            rationale TEXT,
            status TEXT DEFAULT 'SETUP',
            exit_premium REAL,
            exit_reason TEXT,
            pnl REAL,
            created_at TEXT DEFAULT (datetime('now'))
        )
    """)
    conn.commit()
    return conn


def _send_discord(content):
    if not WEBHOOK_URL:
        return
    try:
        requests.post(WEBHOOK_URL, json={"content": content[:1900]}, timeout=5)
    except Exception as e:
        logger.error(f"Discord send failed: {e}")


def fetch_candles(symbol, interval="5m", period="10d"):
    """Fetch 5-min candles via yfinance, convert to IST, filter to market hours."""
    import yfinance as yf
    yf_sym = {"NIFTY": "^NSEI", "BANKNIFTY": "^NSEBANK"}.get(symbol, f"{symbol}.NS")
    try:
        df = yf.download(yf_sym, period=period, interval=interval, progress=False)
        if df is None or not isinstance(df, pd.DataFrame) or df.empty:
            return None
        df = df.copy()
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.droplevel(1)
        df.columns = [str(c).lower() for c in df.columns]

        if df.index.tz is not None:
            df.index = df.index.tz_convert("Asia/Kolkata")
        else:
            df.index = pd.to_datetime(df.index).tz_localize("UTC").tz_convert("Asia/Kolkata")
        df.index.name = "timestamp"

        df = df.between_time("09:15", "15:30")
        if len(df) < 15:
            return None
        return df
    except Exception as e:
        logger.warning(f"fetch_candles {symbol}: {e}")
        return None


def compute_vwap(df):
    """Add VWAP (equal-weighted TP) and deviation columns."""
    df["tp"] = (df["high"] + df["low"] + df["close"]) / 3
    vol = df["volume"].values
    if vol.max() > 0:
        df["vwap"] = (df["tp"] * df["volume"]).cumsum() / df["volume"].cumsum()
    else:
        df["vwap"] = df["tp"].expanding().mean()
    df["vwap_diff"] = ((df["close"] - df["vwap"]) / df["vwap"]) * 100
    return df


def detect_sideways(df, lookback=12):
    """Check no-trade conditions: sideways, choppy, VWAP chop, extreme vol.
    Returns (is_no_trade, reason)."""
    if df is None or len(df) < lookback:
        return False, None
    window = df.iloc[-lookback:]

    reasons = []

    # Extreme volatility — too dangerous
    atr = (window["high"] - window["low"]).mean() / window["close"].mean() * 100
    if atr > 2.5:
        reasons.append(f"Extreme vol {atr:.2f}%")

    # VWAP chop: price oscillates around VWAP without clear direction
    vwap_diff = window["vwap_diff"].values
    crossovers = sum(1 for j in range(1, len(vwap_diff)) if vwap_diff[j - 1] * vwap_diff[j] < 0)
    avg_diff = abs(vwap_diff).mean()
    if crossovers >= 5 and avg_diff < 0.5:
        reasons.append(f"VWAP chop ({crossovers}x cross, avg diff {avg_diff:.2f}%)")

    # VWAP hugged: too tight to VWAP — no clear edge
    if avg_diff < 0.15:
        reasons.append(f"VWAP hugged ({avg_diff:.3f}%)")

    if reasons:
        return True, " | ".join(reasons)
    return False, None


def find_swing_points(df, lookback=2):
    """Identify swing highs and swing lows in the DataFrame."""
    highs = df["high"].values
    lows = df["low"].values
    n = len(highs)

    swing_highs = []
    swing_lows = []

    for i in range(lookback, n - lookback):
        if all(highs[i] > highs[i - j] for j in range(1, lookback + 1)) and \
           all(highs[i] > highs[i + j] for j in range(1, lookback + 1)):
            swing_highs.append({"index": i, "price": float(highs[i]), "type": "high"})

        if all(lows[i] < lows[i - j] for j in range(1, lookback + 1)) and \
           all(lows[i] < lows[i + j] for j in range(1, lookback + 1)):
            swing_lows.append({"index": i, "price": float(lows[i]), "type": "low"})

    return swing_highs, swing_lows


def check_hhlh(swing_lows, swing_highs):
    """Check for Higher High / Higher Low uptrend structure.
    Returns (confirmed, last_swing_low, last_swing_high)."""
    if len(swing_lows) < 2 or len(swing_highs) < 2:
        return False, None, None

    recent_lows = sorted(swing_lows, key=lambda x: -x["index"])[:3]
    recent_highs = sorted(swing_highs, key=lambda x: -x["index"])[:3]

    hl_higher = recent_lows[0]["price"] > recent_lows[1]["price"] if len(recent_lows) >= 2 else True
    hh_higher = recent_highs[0]["price"] > recent_highs[1]["price"] if len(recent_highs) >= 2 else True

    return hl_higher and hh_higher, recent_lows[0]["price"], recent_highs[0]["price"]


def check_lhll(swing_lows, swing_highs):
    """Check for Lower High / Lower Low downtrend structure."""
    if len(swing_lows) < 2 or len(swing_highs) < 2:
        return False, None, None

    recent_lows = sorted(swing_lows, key=lambda x: -x["index"])[:3]
    recent_highs = sorted(swing_highs, key=lambda x: -x["index"])[:3]

    ll_lower = recent_lows[0]["price"] < recent_lows[1]["price"] if len(recent_lows) >= 2 else True
    lh_lower = recent_highs[0]["price"] < recent_highs[1]["price"] if len(recent_highs) >= 2 else True

    return ll_lower and lh_lower, recent_lows[0]["price"], recent_highs[0]["price"]


def detect_pullback(df, from_idx, lookback=8):
    """Find a pullback within the last `lookback` candles ending at `from_idx`.
    Returns (pullback_low, pullback_high, pullback_len) or None."""
    start = max(0, from_idx - lookback)
    window = df.iloc[start:from_idx + 1]
    if len(window) < 4:
        return None

    closes = window["close"].values
    highs = window["high"].values
    lows = window["low"].values
    vwap = window["vwap"].values

    trend_dir = "up" if closes[-1] > vwap[-1] else "down"

    pb_candles = []
    for j in range(1, len(window)):
        prev_close = closes[j - 1]
        curr_close = closes[j]

        if trend_dir == "up":
            if curr_close < prev_close and curr_close < vwap[j] * 1.005:
                pb_candles.append(j)
        else:
            if curr_close > prev_close and curr_close > vwap[j] * 0.995:
                pb_candles.append(j)

    if len(pb_candles) < 2:
        return None

    pb_indices = [start + c for c in pb_candles]
    pb_high = float(df.iloc[pb_indices]["high"].max())
    pb_low = float(df.iloc[pb_indices]["low"].min())

    return {"low": pb_low, "high": pb_high, "count": len(pb_candles)}


def quality_score(setup, df, avg_volume):
    """Score a setup 0-10. Higher = better quality."""
    score = 5.0

    entry = setup["trigger_price"]
    sl = setup["sl"]
    risk_pct = abs(entry - sl) / entry * 100

    # 1. Tight SL is better
    if risk_pct < 0.15:
        score += 2
    elif risk_pct < 0.25:
        score += 1
    elif risk_pct > 0.4:
        score -= 1

    # 2. Clean trend structure = more points
    if setup.get("trend_confirmed"):
        score += 2

    # 3. VWAP proximity: entry near VWAP = better pullback
    vwap_diff = abs(setup.get("vwap_diff", 0))
    if vwap_diff < 0.3:
        score += 1.5
    elif vwap_diff < 0.6:
        score += 0.5
    else:
        score -= 0.5

    # 4. Volume confirmation (bonus only; index data may have no volume)
    vol = setup.get("volume_ratio", 1)
    if vol > 1.5 and avg_volume > MIN_AVG_VOLUME:
        score += 0.5

    # 5. Breakout candle strength
    if setup.get("breakout_body_pct", 0) > 0.7:
        score += 1
    elif setup.get("breakout_body_pct", 0) > 0.5:
        score += 0.5

    return round(min(max(score, 0), 10), 1)


def detect_setups(symbol, df):
    """Main setup detection: trend, pullback, breakout, entry/SL/target.
    Returns (setups, no_trade_reason)."""
    if df is None or len(df) < 25:
        return [], None

    df = compute_vwap(df)

    # --- No-trade checks ---
    no_trade, nt_reason = detect_sideways(df)
    if no_trade:
        return [], nt_reason

    swing_highs, swing_lows = find_swing_points(df)

    hhlh_ok, last_swing_low, last_swing_high = check_hhlh(swing_lows, swing_highs)
    lhll_ok, last_ll_low, last_lh_high = check_lhll(swing_lows, swing_highs)

    i = len(df) - 1
    current = df.iloc[i]
    above_vwap = current["close"] > current["vwap"]
    below_vwap = current["close"] < current["vwap"]

    avg_volume = float(df["volume"].iloc[-20:].mean()) if "volume" in df.columns else MIN_AVG_VOLUME

    setups = []
    no_trade_reasons = []

    # --- LONG SETUP ---
    if above_vwap and hhlh_ok:
        pb = detect_pullback(df, i)
        if pb is None:
            no_trade_reasons.append("No pullback detected")
        else:
            breakout = current
            pb_high = pb["high"]
            pb_low = pb["low"]

            # Hard filter: pullback must hold above swing low
            if last_swing_low and pb_low <= last_swing_low:
                no_trade_reasons.append(f"Pullback broke swing low (₹{pb_low:.0f} ≤ ₹{last_swing_low:.0f})")
            elif breakout["close"] <= pb_high:
                no_trade_reasons.append(f"Close ₹{breakout['close']:.0f} not above pullback high ₹{pb_high:.0f}")
            else:
                body_pct = abs(breakout["close"] - breakout["open"]) / (breakout["high"] - breakout["low"]) if (breakout["high"] - breakout["low"]) > 0 else 0.5
                if body_pct <= 0.5:
                    no_trade_reasons.append(f"Weak body ({body_pct:.0%})")
                else:
                    trigger = float(breakout["high"]) + 0.05
                    swing_low = last_swing_low if last_swing_low else pb_low
                    sl_price = min(swing_low, pb_low) - 0.05
                    risk = trigger - sl_price
                    target = trigger + 2 * risk

                    if risk <= 0 or risk > MAX_SL_POINTS.get(symbol, 120):
                        no_trade_reasons.append(f"SL too wide ({risk:.0f} pts)")
                    else:
                        vol_ratio = float(breakout["volume"]) / avg_volume if avg_volume > 0 else 1
                        rr = (target - trigger) / risk if risk > 0 else 0

                        # Hard filter: volume (skip if index data has no volume)
                        has_volume = avg_volume > MIN_AVG_VOLUME
                        if has_volume and vol_ratio < 1.2:
                            no_trade_reasons.append(f"Low volume ({vol_ratio:.1f}x)")
                        elif rr < 2.0:
                            no_trade_reasons.append(f"R:R {rr:.1f} < 2.0")
                        else:
                            setup = {
                                "symbol": symbol, "direction": "LONG",
                                "trigger_price": round(trigger, 2),
                                "sl": round(sl_price, 2),
                                "target": round(target, 2),
                                "pullback_low": round(pb_low, 2),
                                "pullback_high": round(pb_high, 2),
                                "swing_low": round(swing_low, 2),
                                "breakout_candle_high": round(float(breakout["high"]), 2),
                                "breakout_candle_low": round(float(breakout["low"]), 2),
                                "vwap_diff": round(float(breakout["vwap_diff"]), 2),
                                "spot": round(float(breakout["close"]), 2),
                                "trend_confirmed": hhlh_ok,
                                "volume_ratio": round(vol_ratio, 1),
                                "breakout_body_pct": round(body_pct, 2),
                                "risk_pct": round(risk / trigger * 100, 2),
                                "rr": rr,
                            }
                            setup["quality"] = quality_score(setup, df, avg_volume)
                            setup["rationale"] = (
                                f"Uptrend (HHLH) | Above VWAP (+{setup['vwap_diff']:+.1f}%) | "
                                f"Pullback to ₹{pb_low:.0f} (held swing low) | "
                                f"Bullish close ₹{breakout['close']:.0f} > pullback high ₹{pb_high:.0f} | "
                                f"Entry ₹{trigger:.0f} | SL ₹{sl_price:.0f} ({setup['risk_pct']:.2f}%) | "
                                f"Target ₹{target:.0f} (2R) | "
                                f"Vol {setup['volume_ratio']:.1f}x avg | Body {body_pct:.0%} | "
                                f"Confidence {setup['quality']}/10"
                            )
                            setups.append(setup)

    # --- SHORT SETUP ---
    if below_vwap and lhll_ok:
        pb = detect_pullback(df, i)
        if pb is None:
            no_trade_reasons.append("No retracement detected")
        else:
            breakout = current
            pb_high = pb["high"]
            pb_low = pb["low"]

            # Hard filter: retracement must hold below swing high
            if last_lh_high and pb_high >= last_lh_high:
                no_trade_reasons.append(f"Retracement broke swing high (₹{pb_high:.0f} ≥ ₹{last_lh_high:.0f})")
            elif breakout["close"] >= pb_low:
                no_trade_reasons.append(f"Close ₹{breakout['close']:.0f} not below pullback low ₹{pb_low:.0f}")
            else:
                body_pct = abs(breakout["close"] - breakout["open"]) / (breakout["high"] - breakout["low"]) if (breakout["high"] - breakout["low"]) > 0 else 0.5
                if body_pct <= 0.5:
                    no_trade_reasons.append(f"Weak body ({body_pct:.0%})")
                else:
                    trigger = float(breakout["low"]) - 0.05
                    swing_high = last_lh_high if last_lh_high else pb_high
                    sl_price = max(swing_high, pb_high) + 0.05
                    risk = sl_price - trigger
                    target = trigger - 2 * risk

                    if risk <= 0 or risk > MAX_SL_POINTS.get(symbol, 300):
                        no_trade_reasons.append(f"SL too wide ({risk:.0f} pts)")
                    else:
                        vol_ratio = float(breakout["volume"]) / avg_volume if avg_volume > 0 else 1
                        rr = (sl_price - trigger) / risk if risk > 0 else 0

                        has_volume = avg_volume > MIN_AVG_VOLUME
                        if has_volume and vol_ratio < 1.2:
                            no_trade_reasons.append(f"Low volume ({vol_ratio:.1f}x)")
                        elif rr < 2.0:
                            no_trade_reasons.append(f"R:R {rr:.1f} < 2.0")
                        else:
                            setup = {
                                "symbol": symbol, "direction": "SHORT",
                                "trigger_price": round(trigger, 2),
                                "sl": round(sl_price, 2),
                                "target": round(target, 2),
                                "pullback_low": round(pb_low, 2),
                                "pullback_high": round(pb_high, 2),
                                "swing_low": round(pb_low, 2),
                                "breakout_candle_high": round(float(breakout["high"]), 2),
                                "breakout_candle_low": round(float(breakout["low"]), 2),
                                "vwap_diff": round(float(breakout["vwap_diff"]), 2),
                                "spot": round(float(breakout["close"]), 2),
                                "trend_confirmed": lhll_ok,
                                "volume_ratio": round(vol_ratio, 1),
                                "breakout_body_pct": round(body_pct, 2),
                                "risk_pct": round(risk / trigger * 100, 2),
                                "rr": rr,
                            }
                            setup["quality"] = quality_score(setup, df, avg_volume)
                            setup["rationale"] = (
                                f"Downtrend (LHLL) | Below VWAP ({setup['vwap_diff']:+.1f}%) | "
                                f"Retrace to ₹{pb_high:.0f} (held swing high) | "
                                f"Bearish close ₹{breakout['close']:.0f} < pullback low ₹{pb_low:.0f} | "
                                f"Entry ₹{trigger:.0f} | SL ₹{sl_price:.0f} ({setup['risk_pct']:.2f}%) | "
                                f"Target ₹{target:.0f} (2R) | "
                                f"Vol {setup['volume_ratio']:.1f}x avg | Body {body_pct:.0%} | "
                                f"Confidence {setup['quality']}/10"
                            )
                            setups.append(setup)

    if not setups and no_trade_reasons:
        return [], "; ".join(no_trade_reasons)

    return setups, None


def get_spot(symbol):
    """Get current spot price via Angel One."""
    from core.angel_bridge import get_angel_bridge
    bridge = get_angel_bridge()
    if not bridge._authenticated:
        bridge.authenticate()
    info = NSE_SYMBOL_MAP.get("NIFTY 50" if symbol == "NIFTY" else "BANK NIFTY")
    if not info:
        return None
    return bridge.get_ltp(info["exchange"], info["symbol"], info["token"])


def execute_entry(setup, spot):
    """Execute option entry via Angel One for a triggered setup."""
    from core.angel_bridge import get_angel_bridge
    from config import get_next_next_weekly_expiry
    import re

    bridge = get_angel_bridge()
    if not bridge._authenticated:
        if not bridge.authenticate():
            return None

    symbol = setup["symbol"]
    direction = setup["direction"]
    optype = "CE" if direction == "LONG" else "PE"

    if symbol == "NIFTY":
        strike = round(spot / 50) * 50
        expiry = get_next_next_weekly_expiry("NIFTY")
        m = re.match(r'(\d+)([A-Z]+)(\d+)', expiry)
        if m:
            expiry = f"{m.group(1)}{m.group(2)}20{m.group(3)}"
    else:
        strike = round(spot / 100) * 100
        expiry = get_next_next_weekly_expiry("BANKNIFTY")
        m = re.match(r'(\d+)([A-Z]+)(\d+)', expiry)
        if m:
            expiry = f"{m.group(1)}{m.group(2)}20{m.group(3)}"

    opt_ltp = bridge.get_option_ltp(symbol, expiry, str(strike), optype)
    if opt_ltp is None or opt_ltp < 1:
        logger.warning(f"Could not get option LTP for {symbol} {strike}{optype}")
        return None

    risk_points = abs(setup["trigger_price"] - setup["sl"]) * 0.5
    sl_premium = round(opt_ltp - risk_points, 1)
    target_premium = round(opt_ltp + 2 * risk_points, 1)
    if sl_premium < 1:
        sl_premium = round(opt_ltp * 0.5, 1)
        target_premium = round(opt_ltp * 2.0, 1)

    trade = {
        "timestamp": _now_ist().strftime("%Y-%m-%d %H:%M:%S"),
        "symbol": f"{symbol} {strike}{optype}",
        "index_name": symbol, "strike": strike, "option_type": optype,
        "direction": direction, "entry_premium": opt_ltp, "entry_spot": spot,
        "sl": sl_premium, "target": target_premium,
        "trigger_price": setup["trigger_price"],
        "pullback_low": setup.get("pullback_low"),
        "pullback_high": setup.get("pullback_high"),
        "swing_low": setup.get("swing_low"),
        "breakout_candle_high": setup.get("breakout_candle_high"),
        "breakout_candle_low": setup.get("breakout_candle_low"),
        "swing_low": setup.get("swing_low"),
        "quality_score": setup.get("quality"),
        "rationale": setup.get("rationale", ""),
        "status": "OPEN",
    }
    return trade


class VwapPullbackTrader:
    def __init__(self, db_path=None, webhook_url=WEBHOOK_URL):
        self.db_path = Path(db_path) if db_path else DB_PATH
        self.webhook_url = webhook_url
        self.conn = _init_db()
        self.setups = []
        self.positions = []
        self.trade_log = []
        self.consecutive_losses = 0
        self.daily_pnl = 0.0
        self.no_trade_reason = None
        self._today = _now_ist().strftime("%Y-%m-%d")
        self._load_state()

    def _load_state(self):
        rows = self.conn.execute(
            "SELECT * FROM vwap_trades WHERE status IN ('SETUP','OPEN') ORDER BY id"
        ).fetchall()
        cols = [d[1] for d in self.conn.execute("PRAGMA table_info(vwap_trades)")]
        for r in rows:
            d = dict(zip(cols, r))
            if d["status"] == "SETUP":
                self.setups.append(d)
            elif d["status"] == "OPEN":
                self.positions.append(d)

        # Compute risk state from today's closed trades
        today = _now_ist().strftime("%Y-%m-%d")
        closed = self.conn.execute(
            "SELECT pnl FROM vwap_trades WHERE status='CLOSED' AND date(timestamp)=? ORDER BY id",
            (today,)
        ).fetchall()
        self.daily_pnl = sum(r[0] for r in closed if r[0] is not None)
        # Consecutive losses: count backwards from most recent closed trade
        for r in reversed(closed):
            if r[0] is not None and r[0] < 0:
                self.consecutive_losses += 1
            else:
                break

    def _save_setup(self, setup):
        self.conn.execute("""
            INSERT INTO vwap_trades
                (timestamp, symbol, direction, trigger_price, sl, target,
                 pullback_low, pullback_high, breakout_candle_high,
                 breakout_candle_low, swing_low, quality_score, rationale, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'SETUP')
        """, (
            _now_ist().strftime("%Y-%m-%d %H:%M:%S"),
            setup["symbol"], setup["direction"],
            setup["trigger_price"], setup["sl"], setup["target"],
            setup.get("pullback_low"), setup.get("pullback_high"),
            setup.get("breakout_candle_high"), setup.get("breakout_candle_low"),
            setup.get("swing_low"), setup.get("quality"),
            setup.get("rationale", ""),
        ))
        self.conn.commit()

    def _save_trade(self, trade):
        self.conn.execute("""
            INSERT INTO vwap_trades
                (timestamp, symbol, direction, index_name, strike, option_type,
                 entry_premium, entry_spot, sl, target, trigger_price,
                 pullback_low, pullback_high, breakout_candle_high,
                 breakout_candle_low, swing_low, quality_score, rationale, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'OPEN')
        """, (
            trade["timestamp"], trade["symbol"], trade["direction"],
            trade["index_name"], trade["strike"], trade["option_type"],
            trade["entry_premium"], trade["entry_spot"],
            trade["sl"], trade["target"], trade["trigger_price"],
            trade["pullback_low"], trade["pullback_high"],
            trade["breakout_candle_high"], trade["breakout_candle_low"],
            trade["swing_low"], trade.get("quality_score"),
            trade.get("rationale", ""),
        ))
        self.conn.commit()
        trade_id = self.conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        trade["id"] = trade_id
        self.positions.append(trade)

    def _can_trade(self):
        """Check risk limits before entering a trade. Returns (ok, reason)."""
        if self.positions:
            return False, f"Active position open ({len(self.positions)})"
        if self.consecutive_losses >= MAX_CONSECUTIVE_LOSSES:
            return False, f"2 consecutive losses — trading paused"
        if self.daily_pnl <= -CAPITAL * MAX_DAILY_LOSS_PCT:
            loss_amt = CAPITAL * MAX_DAILY_LOSS_PCT
            return False, f"Daily loss limit hit (₹-{loss_amt:,.0f})"
        # Check if we're in a different day now and reset
        self._reset_daily_if_needed()
        return True, None

    def _reset_daily_if_needed(self):
        today = _now_ist().strftime("%Y-%m-%d")
        if today != self._today:
            self._today = today
            self.consecutive_losses = 0
            self.daily_pnl = 0.0
            self.no_trade_reason = None
            logger.info(f"Risk state reset for new day {today}")

    def _close_trade(self, trade, exit_premium, exit_reason):
        pnl = round(exit_premium - trade["entry_premium"], 1)
        if trade["direction"] == "SHORT":
            pnl = round(trade["entry_premium"] - exit_premium, 1)
        self.conn.execute("""
            UPDATE vwap_trades SET status='CLOSED', exit_premium=?,
                exit_reason=?, pnl=? WHERE id=?
        """, (exit_premium, exit_reason, pnl, trade["id"]))
        self.conn.commit()
        trade["exit_premium"] = exit_premium
        trade["exit_reason"] = exit_reason
        trade["pnl"] = pnl
        self.positions = [p for p in self.positions if p.get("id") != trade["id"]]
        self.trade_log.append(trade)

        # Update risk state
        self._reset_daily_if_needed()
        self.daily_pnl += pnl
        if pnl < 0:
            self.consecutive_losses += 1
        else:
            self.consecutive_losses = 0
        return pnl

    def analyze(self, symbol):
        """Fetch candles and detect setups. Returns (setups, no_trade_reason)."""
        df = fetch_candles(symbol)
        if df is None:
            return [], None
        return detect_setups(symbol, df)

    def get_option_ltp(self, symbol, strike, optype):
        from core.angel_bridge import get_angel_bridge
        from config import get_next_next_weekly_expiry
        import re
        bridge = get_angel_bridge()
        if not bridge._authenticated:
            bridge.authenticate()
        expiry = get_next_next_weekly_expiry(symbol)
        m = re.match(r'(\d+)([A-Z]+)(\d+)', expiry)
        if m:
            expiry = f"{m.group(1)}{m.group(2)}20{m.group(3)}"
        return bridge.get_option_ltp(symbol, expiry, str(strike), optype)

    def check_setups(self):
        """Check if any active setups have been triggered. Enforces risk limits."""
        can_trade, trade_block_reason = self._can_trade()
        if not can_trade:
            if trade_block_reason and self.no_trade_reason != trade_block_reason:
                self.no_trade_reason = trade_block_reason
                msg = f"⛔ **[VP] TRADING PAUSED** — {trade_block_reason}"
                logger.info(msg)
                _send_discord(msg)
            return

        for setup in self.setups[:]:
            spot = get_spot(setup["symbol"])
            if spot is None:
                continue
            triggered = False
            if setup["direction"] == "LONG" and spot >= setup["trigger_price"]:
                triggered = True
            elif setup["direction"] == "SHORT" and spot <= setup["trigger_price"]:
                triggered = True
            if triggered:
                trade = execute_entry(setup, spot)
                if trade:
                    self._save_trade(trade)
                    msg = (
                        f"🟢 **[VP] ENTRY** {setup['symbol']} {setup['direction']}\n"
                        f"   {trade['symbol']} @ ₹{trade['entry_premium']:.1f}\n"
                        f"   Spot: ₹{spot:.0f} | SL: ₹{trade['sl']:.1f} | "
                        f"TGT: ₹{trade['target']:.1f} | R:R 1:2\n"
                        f"   Capital at risk: ₹{(trade['entry_premium'] - trade['sl']) * 50:.0f} "
                        f"({MAX_RISK_PCT*100:.0f}% of ₹{CAPITAL:,})\n"
                        f"   **Rationale:** {setup.get('rationale', 'N/A')[:200]}"
                    )
                    _send_discord(msg)
                    print(msg)
                self.setups.remove(setup)
                self.conn.execute(
                    "DELETE FROM vwap_trades WHERE status='SETUP' AND symbol=? AND direction=?",
                    (setup["symbol"], setup["direction"])
                )
                self.conn.commit()

    def check_positions(self):
        """Check open positions for SL/target hits."""
        for pos in self.positions[:]:
            ltp = self.get_option_ltp(pos["index_name"], pos["strike"], pos["option_type"])
            if ltp is None:
                continue
            direction = pos["direction"]
            premium = pos["entry_premium"]
            sl = pos["sl"]
            target = pos["target"]

            hit_reason = None
            if direction == "LONG":
                if ltp <= sl:
                    hit_reason = "SL_HIT"
                elif ltp >= target:
                    hit_reason = "TARGET_HIT"
            else:
                if ltp >= sl:
                    hit_reason = "SL_HIT"
                elif ltp <= target:
                    hit_reason = "TARGET_HIT"

            if hit_reason:
                exit_prem = ltp
                pnl = self._close_trade(pos, exit_prem, hit_reason)
                emoji = "🔴" if "SL" in hit_reason else "🟢"
                msg = (
                    f"{emoji} **[VP] {hit_reason}** {pos['symbol']}\n"
                    f"   Entry ₹{premium:.1f} → Exit ₹{exit_prem:.1f} | P&L ₹{pnl:+,.0f}"
                )
                _send_discord(msg)
                print(msg)

    def eod_close(self):
        """Close all open positions at market end."""
        for pos in self.positions[:]:
            ltp = self.get_option_ltp(pos["index_name"], pos["strike"], pos["option_type"])
            if ltp is None:
                ltp = pos["entry_premium"] * 0.5
            pnl = self._close_trade(pos, ltp, "EOD_CLOSE")
            msg = (
                f"📊 **[VP] EOD CLOSE** {pos['symbol']}\n"
                f"   Entry ₹{pos['entry_premium']:.1f} → Exit ₹{ltp:.1f} | P&L ₹{pnl:+,.0f}"
            )
            _send_discord(msg)
            print(msg)

    def run_check(self):
        """Single check cycle: analyze, pick best setup, trigger, manage."""
        if not _market_open():
            return

        print(f"[VP] Check at {_now_ist().strftime('%H:%M:%S')}")
        self._reset_daily_if_needed()

        all_no_trade = []
        for sym in SYMBOLS:
            setups, nt_reason = self.analyze(sym)
            if setups:
                for s in setups:
                    dup = any(
                        st["symbol"] == s["symbol"] and st["direction"] == s["direction"]
                        for st in self.setups
                    )
                    if not dup:
                        self.setups.append(s)
                        self._save_setup(s)
                        emoji = "🔵" if s["direction"] == "LONG" else "🔴"
                        msg = (
                            f"{emoji} **[VP] SETUP** {s['symbol']} {s['direction']}\n"
                            f"   Entry: ₹{s['trigger_price']:.1f} | SL: ₹{s['sl']:.1f} | "
                            f"TGT: ₹{s['target']:.1f} (2R)\n"
                            f"   Confidence: {s['quality']}/10 | Risk: {s['risk_pct']:.2f}%\n"
                            f"   **Rationale:** {s['rationale'][:250]}"
                        )
                        _send_discord(msg)
                        print(msg)
            if nt_reason:
                all_no_trade.append(f"{sym}: {nt_reason}")

        if all_no_trade:
            self.no_trade_reason = " | ".join(all_no_trade)
            logger.info(f"NO TRADE: {self.no_trade_reason}")
            print(f"[VP] NO TRADE: {self.no_trade_reason}")

        self.check_setups()
        self.check_positions()

    def get_summary(self):
        """Return formatted summary string."""
        lines = []
        now = _now_ist()
        lines.append(f"**📊 VWAP Pullback Breakout — {now.strftime('%d %b %H:%M')}**")

        # Risk state
        can_trade, block_reason = self._can_trade()
        if not can_trade:
            lines.append(f"⛔ **{block_reason}**")
        elif self.no_trade_reason:
            lines.append(f"⚠️ No active setups — {self.no_trade_reason}")

        # Best setup
        best = None
        if self.setups:
            best = max(self.setups, key=lambda s: s.get("quality_score", 0) or 0)
            lines.append(f"\n**Best Setup:**")
            emoji = "🟦" if best["direction"] == "LONG" else "🟥"
            lines.append(f"  {emoji} {best['symbol']} {best['direction']} "
                         f"@ ₹{best['trigger_price']:.0f} | SL ₹{best['sl']:.0f} | "
                         f"TGT ₹{best['target']:.0f}")
            lines.append(f"  Confidence: {best.get('quality_score', 'N/A')}/10")
            lines.append(f"  {best.get('rationale', '')[:200]}")

        # Open positions
        if self.positions:
            lines.append(f"\n**Open Positions ({len(self.positions)}):**")
            for p in self.positions:
                lines.append(f"  {'🟢' if p['direction']=='LONG' else '🔴'} {p['symbol']} "
                             f"@ ₹{p['entry_premium']:.1f} | SL ₹{p['sl']:.1f} | TGT ₹{p['target']:.1f}")

        # Today's P&L
        today = now.strftime("%Y-%m-%d")
        rows = self.conn.execute(
            "SELECT direction, pnl, exit_reason FROM vwap_trades "
            "WHERE status='CLOSED' AND date(timestamp)=?", (today,)
        ).fetchall()
        if rows:
            wins = sum(1 for r in rows if r[1] and r[1] > 0)
            losses = sum(1 for r in rows if r[1] and r[1] < 0)
            total_pnl = sum(r[1] for r in rows if r[1])
            lines.append(f"\n**Today: {wins}W / {losses}L | P&L ₹{total_pnl:+,.0f}** "
                         f"| Consec losses: {self.consecutive_losses}/2")
        lines.append(f"Capital: ₹{CAPITAL:,} | Max risk/trade: ₹{CAPITAL * MAX_RISK_PCT:,.0f} ({MAX_RISK_PCT*100:.0f}%)")

        return "\n".join(lines) if len(lines) > 2 else "No VP setups today."


def run_forever():
    """Main loop: runs every 5 min during market hours."""
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s [VP] %(message)s")
    trader = VwapPullbackTrader()
    _send_discord("🤖 **[VP] VWAP Pullback Breakout Strategy started** — monitoring 5-min setups (1% risk, single trade, stop after 2 losses)")
    logger.info("VP Strategy started — all rules active")

    last_check = 0
    while True:
        now = _now_ist()
        if _market_open():
            if time.time() - last_check >= CHECK_INTERVAL:
                try:
                    trader.run_check()
                except Exception as e:
                    logger.error(f"run_check error: {e}", exc_info=True)
                last_check = time.time()

            if now.hour == 15 and now.minute >= 25:
                if trader.positions:
                    trader.eod_close()
                    summary = trader.get_summary()
                    _send_discord(f"📊 **[VP] End of Day**\n{summary}")
                next_day = now.replace(hour=9, minute=15) + timedelta(days=1)
                if next_day.weekday() >= 5:
                    next_day += timedelta(days=2 - next_day.weekday())
                sleep_secs = (next_day - now).total_seconds()
                logger.info(f"EOD — sleeping {sleep_secs/3600:.1f}h")
                time.sleep(sleep_secs)
                last_check = 0
                continue

        sleep_until = CHECK_INTERVAL - (time.time() % CHECK_INTERVAL)
        time.sleep(min(sleep_until, 60))


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "check":
        trader = VwapPullbackTrader()
        trader.run_check()
        print(trader.get_summary())
    elif len(sys.argv) > 1 and sys.argv[1] == "eod":
        trader = VwapPullbackTrader()
        trader.eod_close()
        print(trader.get_summary())
    else:
        run_forever()
