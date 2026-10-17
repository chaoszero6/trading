"""
PaperTrader — Live paper trading engine using Angel One WebSocket LTP.
Pre-fetches option tokens at init, monitors trends every 15 min,
enters/exits trades with real-time pricing. No BS approximations.
"""
import sys, os, json, math, time, threading, sqlite3, warnings
from datetime import datetime, timedelta
from pathlib import Path
import pandas as pd
import numpy as np
import yfinance as yf
warnings.filterwarnings('ignore')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.angel_bridge import AngelOneBridge
from config import get_next_next_weekly_expiry
from core.technical_indicators import rsi as _rsi
from core.gpu_candlestick import fetch_and_predict

DB_PATH = Path(__file__).parent.parent / "data" / "papertrades.db"

_ws_lock = threading.Lock()

LOT_SIZES = {"NIFTY": 65, "BANKNIFTY": 30}
EXPIRIES = {
    "NIFTY": {"weekly": get_next_next_weekly_expiry("NIFTY"), "monthly": "30JUN26"},
    "BANKNIFTY": {"weekly": get_next_next_weekly_expiry("BANKNIFTY"), "monthly": "30JUN26"},
}
STRIKE_RANGES = {
    "NIFTY": list(range(23200, 24300, 50)),
    "BANKNIFTY": list(range(53000, 55500, 100)),
}


class PaperTrader:
    def __init__(self, angel_bridge=None, prefetch=False):
        if angel_bridge:
            self.ab = angel_bridge
        else:
            self.ab = AngelOneBridge()
            self.ab.authenticate()
        self.token_cache = {}
        self.positions = []
        self.trade_log = []
        self.last_check_time = ""
        self.running = False
        self._init_db()
        self._load_open_positions()
        if prefetch:
            self._prefetch_tokens()

    def _init_db(self):
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(DB_PATH) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS trades (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT, index_name TEXT, strike INTEGER,
                    option_type TEXT, entry_ltp REAL, entry_spot REAL,
                    sl REAL, target REAL, exit_ltp REAL, exit_spot REAL,
                    exit_reason TEXT, pnl REAL, held_minutes REAL,
                    entry_signal TEXT, rsi REAL, vwap_diff REAL,
                    expiry TEXT, exit_timestamp TEXT,
                    gpu_score INTEGER, gpu_bullish INTEGER, gpu_bearish INTEGER
                )
            """)
            for col in ["exit_timestamp", "gpu_score", "gpu_bullish", "gpu_bearish"]:
                try:
                    conn.execute(f"ALTER TABLE trades ADD COLUMN {col} TEXT")
                except Exception:
                    pass
            conn.execute("""
                CREATE TABLE IF NOT EXISTS token_cache (
                    symbol TEXT PRIMARY KEY, token TEXT, expiry TEXT,
                    strike INTEGER, optype TEXT, cached_at TEXT
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS trade_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT, index_name TEXT, strike INTEGER,
                    option_type TEXT, entry_ltp REAL, entry_spot REAL,
                    sl REAL, target REAL, exit_ltp REAL, exit_spot REAL,
                    exit_reason TEXT, pnl REAL, held_minutes REAL,
                    entry_signal TEXT, rsi REAL, vwap_diff REAL,
                    expiry TEXT, exit_timestamp TEXT,
                    gpu_score INTEGER, gpu_bullish INTEGER, gpu_bearish INTEGER,
                    archived_at TEXT DEFAULT (datetime('now'))
                )
            """)
            conn.commit()

    def _load_open_positions(self):
        """Load unclosed positions from DB into self.positions."""
        try:
            with sqlite3.connect(DB_PATH) as conn:
                rows = conn.execute(
                    "SELECT id, timestamp, index_name, strike, option_type, "
                    "entry_ltp, entry_spot, sl, target, entry_signal, expiry "
                    "FROM trades WHERE exit_ltp IS NULL"
                ).fetchall()
            for row in rows:
                pos = {
                    "id": row[0],
                    "timestamp": row[1],
                    "index": row[2],
                    "strike": row[3],
                    "type": row[4],
                    "entry_ltp": row[5],
                    "entry_spot": row[6],
                    "sl": row[7],
                    "target": row[8],
                    "entry_signal": row[9],
                    "expiry": row[10] or EXPIRIES.get(row[2], {}).get("weekly", ""),
                    "peak_ltp": row[5],
                    "trail_activated": False,
                    "exit_ltp": None,
                    "exit_spot": None,
                    "exit_reason": None,
                    "pnl": None,
                    "held_minutes": None,
                }
                self.positions.append(pos)
                # Pre-cache token for this position so WS LTP works on first check
                sym = "NIFTY" if pos["index"] == "NIFTY" else "BANKNIFTY"
                tsym = f"{sym}{pos['expiry']}{pos['strike']}{pos['type']}"
                if tsym not in self.token_cache:
                    with sqlite3.connect(DB_PATH) as conn:
                        row = conn.execute(
                            "SELECT token FROM token_cache WHERE symbol=?", (tsym,)
                        ).fetchone()
                        if row:
                            self.token_cache[tsym] = row[0]
            if rows:
                print(f"[PT] Loaded {len(rows)} open position(s) from DB", flush=True)
        except Exception as e:
            print(f"[PT] Error loading positions: {e}", flush=True)

    def _prefetch_tokens(self):
        """Pre-fetch all option tokens for NIFTY + BANKNIFTY key strikes."""
        print("[PT] Pre-fetching option tokens...")
        count = 0
        for index in ["NIFTY", "BANKNIFTY"]:
            expiry = EXPIRIES[index]["weekly"]
            sym = "NIFTY" if index == "NIFTY" else "BANKNIFTY"
            for strike in STRIKE_RANGES[index]:
                for optype in ["CE", "PE"]:
                    tsym = f"{sym}{expiry}{strike}{optype}"
                    for attempt in range(2):
                        try:
                            tokens = self.ab.search_scrip("NFO", tsym)
                            if tokens:
                                token = tokens[0]["symboltoken"]
                                with sqlite3.connect(DB_PATH) as conn:
                                    conn.execute(
                                        "INSERT OR REPLACE INTO token_cache VALUES (?,?,?,?,?,?)",
                                        (tsym, token, expiry, strike, optype, datetime.now().isoformat()),
                                    )
                                self.token_cache[tsym] = token
                                count += 1
                                break
                            time.sleep(0.5)
                        except Exception:
                            time.sleep(0.5)
        print(f"[PT] Cached {count} option tokens")

    def get_ltp(self, index, strike, optype, expiry=None):
        """Get real-time LTP via WebSocket using cached token.
        Defaults to weekly expiry; pass a custom expiry for monthly."""
        if expiry is None:
            expiry = EXPIRIES[index]["weekly"]
        sym = "NIFTY" if index == "NIFTY" else "BANKNIFTY"
        tsym = f"{sym}{expiry}{strike}{optype}"

        # Check cache
        token = self.token_cache.get(tsym)
        if not token:
            with sqlite3.connect(DB_PATH) as conn:
                row = conn.execute(
                    "SELECT token FROM token_cache WHERE symbol=?", (tsym,)
                ).fetchone()
                if row:
                    token = row[0]
                    self.token_cache[tsym] = token

        if not token:
            for attempt in range(2):
                try:
                    tokens = self.ab.search_scrip("NFO", tsym)
                    if tokens:
                        token = tokens[0]["symboltoken"]
                        self.token_cache[tsym] = token
                        with sqlite3.connect(DB_PATH) as conn:
                            conn.execute(
                                "INSERT OR REPLACE INTO token_cache VALUES (?,?,?,?,?,?)",
                                (tsym, token, expiry, strike, optype, datetime.now().isoformat()),
                            )
                            conn.commit()
                        break
                    time.sleep(1)
                except Exception:
                    time.sleep(1)

        if not token:
            return None

        # Use REST getLtpData endpoint (faster, no WS race conditions)
        try:
            return self.ab.get_ltp("NFO", tsym, token)
        except Exception:
            return None

    def get_spot(self, index="NIFTY"):
        """Get current spot price via LTP endpoint."""
        if index == "NIFTY":
            return self.ab.get_ltp("NSE", "NIFTY", "99926000")
        else:
            return self.ab.get_banknifty_ltp()

    def evaluate_trend(self, index="NIFTY"):
        """Evaluate trend using GPU-accelerated candlestick + technicals."""
        spot = self.get_spot(index)
        if not spot:
            return None

        # 1. Technical analysis from 1m bars
        ticker = "^NSEI" if index == "NIFTY" else "^NSEBANK"
        df = yf.download(ticker, period="1d", interval="1m", progress=False)
        bars = []
        if not df.empty:
            for i, (idx, row) in enumerate(df.iterrows()):
                ts = idx.to_pydatetime() + timedelta(hours=5, minutes=30)
                if ts.hour < 9 or (ts.hour == 9 and ts.minute < 15) or ts.hour >= 15 and ts.minute > 30:
                    continue
                c = float(row["Close"].iloc[0]) if isinstance(row["Close"], pd.Series) else float(row["Close"])
                v = float(row["Volume"].iloc[0]) if isinstance(row["Volume"], pd.Series) else float(row["Volume"])
                bars.append({"c": c, "v": v})

        bdf = pd.DataFrame(bars) if bars else pd.DataFrame()
        sma10_slope, rsi, vwap_d, above_vwap = 0, 50, 0, False

        if len(bdf) >= 15:
            bdf["sma10"] = bdf["c"].rolling(10).mean()
            bdf["rsi14"] = _rsi(pd.Series(bdf["c"].values), 14).values
            bdf["vwap"] = (bdf["c"] * bdf["v"]).cumsum() / bdf["v"].cumsum()
            bdf["vwap_diff"] = ((bdf["c"] - bdf["vwap"]) / bdf["vwap"]) * 100
            last = bdf.iloc[-1]
            sma10_slope = float(last["sma10"] - bdf["sma10"].iloc[-5])
            rsi = float(last["rsi14"]) if not np.isnan(float(last["rsi14"])) else 50
            vwap_d = float(last["vwap_diff"]) if not np.isnan(float(last["vwap_diff"])) else 0
            above_vwap = bool(last["c"] > last["vwap"])

        # 2. GPU candlestick on Nifty50 constituents
        print(f"[GPU] Scanning Nifty50 constituents for confirmation...")
        nifty50 = [
            'RELIANCE','TCS','HDFCBANK','INFY','HINDUNILVR','ICICIBANK','ITC',
            'BHARTIARTL','KOTAKBANK','BAJFINANCE','LT','WIPRO','AXISBANK','MARUTI',
            'SUNPHARMA','TITAN','HCLTECH','ULTRACEMCO','ASIANPAINT','NTPC','M&M',
            'POWERGRID','JSWSTEEL','TRENT','NESTLEIND','ONGC','COALINDIA','BAJAJFINSV',
            'ADANIPORTS','ADANIENT','HAL','BPCL','BAJAJ-AUTO','SIEMENS',
            'TATASTEEL','HDFCLIFE','DIVISLAB','DRREDDY','CIPLA','GRASIM',
            'HEROMOTOCO','BRITANNIA','EICHERMOT','TATACONSUM','APOLLOHOSP','TECHM'
        ]
        try:
            gpu_result = fetch_and_predict(nifty50, period="2mo")
            top_buys = gpu_result.get("top_buys", [])
            top_sells = gpu_result.get("top_sells", [])
            gpu_bullish = len(top_buys)
            gpu_bearish = len(top_sells)
            gpu_score = gpu_bullish - gpu_bearish

            # Top confirmed stocks for logging
            top_buy_names = [r["symbol"] for r in top_buys[:5]]
            top_sell_names = [r["symbol"] for r in top_sells[:5]]
        except Exception as e:
            gpu_score = 0
            gpu_bullish = gpu_bearish = 0
            top_buy_names = top_sell_names = []

        # 3. Combine signals
        signal = "NEUTRAL"
        confidence = "LOW"

        # Bullish: above VWAP + SMA10 rising + RSI rising + GPU supports
        if above_vwap and sma10_slope > 2 and rsi > 40 and gpu_score > 0:
            signal = "BUY_CE"
            confidence = "HIGH" if gpu_score > 5 else "MEDIUM"
        # Bearish: below VWAP + SMA10 falling + RSI falling + GPU supports
        elif not above_vwap and sma10_slope < -2 and rsi < 60 and gpu_score < 0:
            signal = "BUY_PE"
            confidence = "HIGH" if gpu_score < -5 else "MEDIUM"
        # Weak signals — try technical-only
        elif above_vwap and sma10_slope > 2 and rsi > 40 and len(bdf) >= 15 and rsi > bdf["rsi14"].iloc[-3]:
            signal = "BUY_CE"
            confidence = "LOW"
        elif not above_vwap and sma10_slope < -2 and rsi < 60 and len(bdf) >= 15 and rsi < bdf["rsi14"].iloc[-3]:
            signal = "BUY_PE"
            confidence = "LOW"

        return {
            "signal": signal,
            "confidence": confidence,
            "spot": round(float(spot), 1),
            "rsi": round(rsi, 1),
            "vwap_diff": round(vwap_d, 2),
            "above_vwap": above_vwap,
            "gpu_bullish": gpu_bullish,
            "gpu_bearish": gpu_bearish,
            "gpu_score": gpu_score,
            "top_buys": top_buy_names,
            "top_sells": top_sell_names,
        }

    def _trail_sl(self, pos, ltp):
        """Trail stop-loss as position goes in profit.
        Locks in 70% of max profit once price moves 3% above entry.
        """
        entry = pos["entry_ltp"]
        peak = pos.get("peak_ltp", entry)

        # Track new peak
        if ltp > peak:
            peak = ltp
            pos["peak_ltp"] = peak

        # Target hit at 6% gain
        if peak >= entry * 1.06:
            return "target"

        # Trail SL: once 3% above entry, trail at 30% of max gain (locks 70%)
        if peak > entry * 1.03:
            new_sl = peak - (peak - entry) * 0.30
            old_sl = pos.get("sl", 0)
            if new_sl > old_sl:
                pos["sl"] = round(new_sl, 1)
                if not pos.get("trail_activated"):
                    pos["trail_activated"] = True
                    print(f"[PT] 🔄 Trailing SL activated: ₹{old_sl:.1f} → ₹{pos['sl']:.1f} (peak={peak:.1f})")

        return None

    def check_open_positions(self):
        """Check all open positions for SL/target hits with trailing."""
        for pos in self.positions[:]:
            ltp = self.get_ltp(pos["index"], pos["strike"], pos["type"])
            if ltp is None:
                continue
            spot = self.get_spot(pos["index"])

            # Trail stoploss first
            trail_result = self._trail_sl(pos, ltp)
            if trail_result == "target":
                pos["exit_ltp"] = ltp
                pos["exit_spot"] = spot
                pos["exit_reason"] = "TARGET_HIT"
                pos["pnl"] = round((ltp - pos["entry_ltp"]) * LOT_SIZES.get(pos["index"], 65), 0)
                pos["held_minutes"] = self._held_minutes(pos["timestamp"])
                self._save_trade(pos)
                self.trade_log.append(pos)
                self.positions.remove(pos)
                print(f"[PT] ✅ TARGET HIT: {pos['strike']}{pos['type']} @ ₹{ltp} (P&L ₹{pos['pnl']:+.0f})")
                continue

            # Check SL / target
            if ltp <= pos["sl"]:
                pos["exit_ltp"] = ltp
                pos["exit_spot"] = spot
                pos["exit_reason"] = "SL_HIT"
                pos["pnl"] = round((ltp - pos["entry_ltp"]) * LOT_SIZES.get(pos["index"], 65), 0)
                pos["held_minutes"] = self._held_minutes(pos["timestamp"])
                self._save_trade(pos)
                self.trade_log.append(pos)
                self.positions.remove(pos)
                print(f"[PT] ❌ SL HIT: {pos['strike']}{pos['type']} @ ₹{ltp} (P&L ₹{pos['pnl']:+.0f})")
            elif ltp >= pos["target"]:
                pos["exit_ltp"] = ltp
                pos["exit_spot"] = spot
                pos["exit_reason"] = "TARGET_HIT"
                pos["pnl"] = round((ltp - pos["entry_ltp"]) * LOT_SIZES.get(pos["index"], 65), 0)
                pos["held_minutes"] = self._held_minutes(pos["timestamp"])
                self._save_trade(pos)
                self.trade_log.append(pos)
                self.positions.remove(pos)
                print(f"[PT] ✅ TARGET HIT: {pos['strike']}{pos['type']} @ ₹{ltp} (P&L ₹{pos['pnl']:+.0f})")

    def _held_minutes(self, ts_str):
        try:
            entry = datetime.fromisoformat(ts_str)
            return round((datetime.now() - entry).total_seconds() / 60, 1)
        except:
            return 0

    def enter_trade(self, index, signal, spot, trend_data):
        """Enter a paper trade with real LTP."""
        is_ce = signal == "BUY_CE"
        optype = "CE" if is_ce else "PE"
        atm = round(spot / 50) * 50
        strike = atm + 100 if is_ce else atm - 100

        ltp = self.get_ltp(index, strike, optype)
        if ltp is None or ltp < 5:
            return None

        sl_price = round(ltp * 0.90, 1)
        target_price = round(ltp * 1.06, 1)

        strategies = []
        if trend_data.get("above_vwap"):
            strategies.append("① VWAP/SMA10/RSI Trend: Above VWAP, SMA10 rising, RSI bullish")
        else:
            strategies.append("① VWAP/SMA10/RSI Trend: Below VWAP, SMA10 falling, RSI bearish")
        gpu = trend_data.get("gpu_score", 0)
        b = trend_data.get("gpu_bullish", 0)
        s2 = trend_data.get("gpu_bearish", 0)
        if gpu > 0:
            strategies.append(f"② GPU Candlestick: {gpu} bullish bias ({b}B/{s2}S)")
        elif gpu < 0:
            strategies.append(f"② GPU Candlestick: {gpu} bearish bias ({b}B/{s2}S)")
        else:
            strategies.append("② GPU Candlestick: Neutral")

        pos = {
            "timestamp": datetime.now().isoformat(),
            "index": index,
            "expiry": EXPIRIES.get(index, {}).get("weekly", ""),
            "strike": strike,
            "type": optype,
            "entry_ltp": ltp,
            "entry_spot": spot,
            "sl": sl_price,
            "target": target_price,
            "peak_ltp": ltp,
            "trail_activated": False,
            "exit_ltp": None,
            "exit_spot": None,
            "exit_reason": None,
            "pnl": None,
            "held_minutes": None,
            "entry_signal": signal,
            "rsi": trend_data.get("rsi"),
            "vwap_diff": trend_data.get("vwap_diff"),
            "strategies_used": "\n".join(strategies),
            "gpu_score": trend_data.get("gpu_score"),
            "gpu_bullish": trend_data.get("gpu_bullish"),
            "gpu_bearish": trend_data.get("gpu_bearish"),
        }
        self.positions.append(pos)
        self._save_trade(pos)
        self._send_entry_notification(pos)
        print(f"[PT] ✅ ENTRY: {strike}{optype} @ ₹{ltp} (spot={spot})")
        return pos

    def _send_entry_notification(self, pos):
        import requests
        wh = os.environ.get("DISCORD_WEBHOOK", "")
        if not wh:
            return
        dir_str = "🟢 CALL" if pos.get("type") == "CE" else "🔴 PUT"
        embed = {
            "title": f"{dir_str} NEW POSITION OPENED — {pos.get('index')} {pos.get('strike')}{pos.get('type')}",
            "color": 0x00FF88,
            "fields": [
                {"name": "Entry Premium", "value": f"₹{pos['entry_ltp']:.1f}", "inline": True},
                {"name": "Spot at Entry", "value": f"₹{pos['entry_spot']:,.0f}", "inline": True},
                {"name": "Stop Loss", "value": f"₹{pos['sl']:.1f}", "inline": True},
                {"name": "Target", "value": f"₹{pos['target']:.1f}", "inline": True},
                {"name": "RSI", "value": str(pos.get('rsi', 'N/A')), "inline": True},
                {"name": "Signal", "value": pos.get('entry_signal', 'N/A'), "inline": True},
                {"name": "Expiry", "value": pos.get('expiry', 'N/A'), "inline": True},
            ],
            "footer": {"text": f"PaperTrader • {pos.get('timestamp', '')}"},
        }
        gs = pos.get("gpu_score")
        gb = pos.get("gpu_bullish")
        gs2 = pos.get("gpu_bearish")
        if gs is not None:
            embed["fields"].append({"name": "GPU Score", "value": f"{gs:d} ({gb:d}B/{gs2:d}S)", "inline": True})
        strat = pos.get("strategies_used")
        if strat:
            embed["fields"].append({"name": "Strategies Triggered", "value": strat, "inline": False})
        try:
            resp = requests.post(wh, json={"embeds": [embed]}, timeout=5)
        except Exception:
            pass

    def _save_trade(self, pos):
        is_exit = pos.get("exit_ltp") is not None
        exit_ts = datetime.now().isoformat() if is_exit else None
        with sqlite3.connect(DB_PATH) as conn:
            if is_exit and pos.get("id"):
                # Exit: UPDATE the existing entry row (1 row per trade)
                conn.execute(
                    """UPDATE trades SET exit_ltp=?, exit_spot=?, exit_reason=?,
                       pnl=?, held_minutes=?, exit_timestamp=?
                       WHERE id=? AND exit_ltp IS NULL""",
                    (
                        pos.get("exit_ltp"),
                        pos.get("exit_spot"),
                        pos.get("exit_reason"),
                        pos.get("pnl"),
                        pos.get("held_minutes"),
                        exit_ts,
                        pos.get("id"),
                    ),
                )
            else:
                # Entry: INSERT new row and capture id
                cursor = conn.execute(
                    """INSERT INTO trades (timestamp, index_name, strike, option_type,
                       entry_ltp, entry_spot, sl, target, exit_ltp, exit_spot,
                       exit_reason, pnl, held_minutes, entry_signal, rsi, vwap_diff,
                       expiry, exit_timestamp, gpu_score, gpu_bullish, gpu_bearish)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        pos.get("timestamp"),
                        pos.get("index"),
                        pos.get("strike"),
                        pos.get("type"),
                        pos.get("entry_ltp"),
                        pos.get("entry_spot"),
                        pos.get("sl"),
                        pos.get("target"),
                        None,  # exit_ltp
                        None,  # exit_spot
                        None,  # exit_reason
                        None,  # pnl
                        None,  # held_minutes
                        pos.get("entry_signal"),
                        pos.get("rsi"),
                        pos.get("vwap_diff"),
                        pos.get("expiry"),
                        None,  # exit_timestamp
                        pos.get("gpu_score"),
                        pos.get("gpu_bullish"),
                        pos.get("gpu_bearish"),
                    ),
                )
                pos["id"] = cursor.lastrowid  # Store id back for exit UPDATE

            # Auto-archive completed trades to history
            if is_exit:
                conn.execute(
                    """INSERT INTO trade_history (timestamp, index_name, strike, option_type,
                       entry_ltp, entry_spot, sl, target, exit_ltp, exit_spot,
                       exit_reason, pnl, held_minutes, entry_signal, rsi, vwap_diff,
                       expiry, exit_timestamp, gpu_score, gpu_bullish, gpu_bearish)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        pos.get("timestamp"),
                        pos.get("index"),
                        pos.get("strike"),
                        pos.get("type"),
                        pos.get("entry_ltp"),
                        pos.get("entry_spot"),
                        pos.get("sl"),
                        pos.get("target"),
                        pos.get("exit_ltp"),
                        pos.get("exit_spot"),
                        pos.get("exit_reason"),
                        pos.get("pnl"),
                        pos.get("held_minutes"),
                        pos.get("entry_signal"),
                        pos.get("rsi"),
                        pos.get("vwap_diff"),
                        pos.get("expiry"),
                        exit_ts,
                        pos.get("gpu_score"),
                        pos.get("gpu_bullish"),
                        pos.get("gpu_bearish"),
                    ),
                )
            conn.commit()

    def close_all_eod(self):
        """Close all open positions at EOD with real LTP."""
        for pos in self.positions[:]:
            ltp = self.get_ltp(pos["index"], pos["strike"], pos["type"])
            spot = self.get_spot(pos["index"])
            pos["exit_ltp"] = ltp or pos["entry_ltp"]
            pos["exit_spot"] = spot
            pos["exit_reason"] = "EOD_CLOSE"
            pos["pnl"] = round(((ltp or pos["entry_ltp"]) - pos["entry_ltp"]) * LOT_SIZES.get(pos["index"], 65), 0)
            pos["held_minutes"] = self._held_minutes(pos["timestamp"])
            self._save_trade(pos)
            self.trade_log.append(pos)
        self.positions.clear()
        print(f"[PT] EOD: {len(self.trade_log)} trades closed")

    def get_summary(self):
        """Get formatted summary of all trades (today only)."""
        lines = []
        total_pnl = 0.0
        wins = 0
        losses = 0
        with sqlite3.connect(DB_PATH) as conn:
            rows = conn.execute(
                "SELECT * FROM trades WHERE date(timestamp) = date('now','localtime') ORDER BY id"
            ).fetchall()
            if not rows:
                return "No trades today."

            lines.append(f"📊 **Paper Trading — {datetime.now().strftime('%d %b %Y')}**")
            lines.append(f"**Open positions:** {len(self.positions)}")
            lines.append("")

            for r in rows:
                pnl = float(r[12] or 0)
                total_pnl += pnl
                if pnl > 0:
                    wins += 1
                elif pnl < 0:
                    losses += 1
                sym = "✅" if pnl > 0 else "❌" if pnl < 0 else "⏳"
                ts = str(r[1])[11:16] if r[1] else "?"
                idx = str(r[2] or "NIFTY")
                strike = int(r[3] or 0)
                optype = str(r[4] or "?")
                entry = float(r[5] or 0)
                exit_ = r[8]
                reason = str(r[10] or "OPEN")
                lines.append(
                    f"{sym} {ts} **{strike}{optype}** entry=₹{entry:.0f}"
                    + (f" exit=₹{float(exit_):.0f} P&L=₹{pnl:+,.0f} ({reason})" if exit_ else " **OPEN**")
                )

            lines.append("")
            if len(rows) > 0:
                wp = wins / (wins + losses) * 100 if (wins + losses) > 0 else 0
                lines.append(f"🏆 {wins}W / {losses}L | P&L: ₹{total_pnl:+,.0f} | Win%: {wp:.0f}%")
        return "\n".join(lines)

    def get_pnl_history(self, days=30):
        """Get day-wise P&L from trade_history (all completed trades, never lost)."""
        rows = []
        with sqlite3.connect(DB_PATH) as conn:
            cur = conn.execute("""
                SELECT date(timestamp) as day,
                       count(*) as trades,
                       sum(CASE WHEN pnl > 0 THEN 1 ELSE 0 END) as wins,
                       sum(CASE WHEN pnl < 0 THEN 1 ELSE 0 END) as losses,
                       sum(CASE WHEN pnl IS NOT NULL THEN pnl ELSE 0 END) as pnl
                FROM trade_history
                WHERE timestamp >= datetime('now', ? || ' days', 'localtime')
                GROUP BY day ORDER BY day
            """, (f'-{days}',))
            rows = cur.fetchall()
        return rows
