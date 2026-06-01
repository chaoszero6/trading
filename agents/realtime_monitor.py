"""
Real-Time Market Monitor — Angel One API only.
Monitors NIFTY and BANKNIFTY every 10 min using only working Angel One
endpoints (spot LTP, option LTP via WebSocket, option Greeks).
Strategies use real-time polling + IV/volume data — no yfinance.
Manages trades with trailing SL, sends Discord updates.
"""
import sys, os, json, time, math, threading, sqlite3, warnings, concurrent.futures
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
import pandas as pd
import numpy as np
warnings.filterwarnings('ignore')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Load .env if present
dotenv_path = Path(__file__).parent.parent / ".env"
if dotenv_path.exists():
    with open(dotenv_path) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())

from core.angel_bridge import AngelOneBridge
from agents.paper_trader import PaperTrader, DB_PATH, LOT_SIZES, EXPIRIES
from core.gpu_options import monte_carlo_price, batch_price_all_strikes, monte_carlo_greeks
from core.gpu_candlestick import detect_all_patterns
from core.gpu_signals import batch_rsi, batch_macd

DISCORD_WEBHOOK = os.environ.get("DISCORD_WEBHOOK", "")
MONITOR_HOURS = 2  # fallback if started after market close
CHECK_INTERVAL = 60  # 1 minute — frequent enough for tick-based indicators


class RealTimeMonitor:
    def __init__(self, webhook_url=""):
        self.ab = AngelOneBridge()
        self.ab.authenticate()
        self.pt = PaperTrader(angel_bridge=self.ab)
        self.webhook_url = webhook_url or DISCORD_WEBHOOK

        self.nifty_spot = None
        self.banknifty_spot = None
        self.nifty_ticks = []       # recent spot ticks for momentum
        self.banknifty_ticks = []
        self.start_time = datetime.now()
        self.end_time = self.start_time + timedelta(hours=MONITOR_HOURS)
        self.running = False
        self.update_count = 0
        self.option_ltp_cache = {}
        self._greek_cache = None
        self._greek_cache_time = None
        self._market_quality = None
        self.gpu_sentiment = {}
        self.gpu_chain = None
        self._daily_entry_count = 0
        self._daily_pnl = 0

    def refresh_spots(self):
        try:
            n = self.ab.get_nifty_ltp()
            b = self.ab.get_banknifty_ltp()
            now = time.time()
            if n:
                self.nifty_spot = n
                self.nifty_ticks.append((now, n))
            if b:
                self.banknifty_spot = b
                self.banknifty_ticks.append((now, b))
            # Keep last 2 hours of ticks for GPU RSI/MACD on larger arrays
            cutoff = now - 7200
            self.nifty_ticks = [(t, v) for t, v in self.nifty_ticks if t > cutoff]
            self.banknifty_ticks = [(t, v) for t, v in self.banknifty_ticks if t > cutoff]
        except Exception as e:
            print(f"[MON] refresh_spots error: {e}", flush=True)

    def get_spot(self, index="NIFTY"):
        return self.nifty_spot if index == "NIFTY" else self.banknifty_spot

    def _get_option_ltp(self, index, strike, optype, max_age=30, expiry=None):
        key = f"{index}_{strike}_{optype}_{expiry or ''}"
        now = time.time()
        cached = getattr(self, '_ltp_cache', {}).get(key)
        if cached and now - cached['time'] < max_age:
            return cached['ltp']
        ltp = None
        try:
            ltp = self.pt.get_ltp(index, strike, optype, expiry=expiry)
        except Exception:
            pass
        if ltp is not None:
            if not hasattr(self, '_ltp_cache'):
                self._ltp_cache = {}
            self._ltp_cache[key] = {'ltp': ltp, 'time': now}
            return ltp
        return None

    # ---- Indicator Calculators (tick-based) ----

    @staticmethod
    def _calc_ema(prices, period):
        k = 2 / (period + 1)
        result = [prices[0]]
        for p in prices[1:]:
            result.append(p * k + result[-1] * (1 - k))
        return result

    def _calc_supertrend(self, prices, period=7, multiplier=3):
        if len(prices) < period + 1:
            return None
        tr = [abs(prices[i] - prices[i - 1]) for i in range(1, len(prices))]
        atr = self._calc_ema(tr, period)
        bands_upper, bands_lower = [], []
        for i in range(len(prices)):
            if i < period:
                bands_upper.append(prices[i])
                bands_lower.append(prices[i])
                continue
            mid = prices[i]
            atr_val = atr[i - 1]
            bands_upper.append(mid + multiplier * atr_val)
            bands_lower.append(mid - multiplier * atr_val)
        trend = "up" if prices[-1] > bands_lower[-1] else "down"
        return {"trend": trend, "upper": bands_upper[-1], "lower": bands_lower[-1], "atr": atr[-1]}

    def _calc_rsi_series(self, prices, period=14):
        if len(prices) < period + 1:
            return None
        changes = [prices[i] - prices[i - 1] for i in range(1, len(prices))]
        gains = [max(c, 0) for c in changes]
        losses = [max(-c, 0) for c in changes]
        avg_gain = sum(gains[:period]) / period
        avg_loss = sum(losses[:period]) / period
        rsis = []
        for i in range(period, len(changes)):
            avg_gain = (avg_gain * (period - 1) + gains[i]) / period
            avg_loss = (avg_loss * (period - 1) + losses[i]) / period
            rs = avg_gain / avg_loss if avg_loss > 0 else 100
            rsis.append(100 - (100 / (1 + rs)))
        return rsis  # len = len(prices) - period

    # ---- Confluence Strategy: EMA cross + SuperTrend + RSI ----

    def _trend_confluence_signal(self, index="BANKNIFTY"):
        ticks = self.banknifty_ticks if index == "BANKNIFTY" else self.nifty_ticks
        if len(ticks) < 10:
            return None
        prices = [v for _, v in ticks]

        # 1. EMA cross (10, 30)
        if len(prices) < 10:
            return None
        ema_10 = self._calc_ema(prices, 10)
        ema_30 = self._calc_ema(prices, 30) if len(prices) >= 30 else None
        # If no EMA-30, use SMA-10 as reference
        ema_bull = ema_10[-1] > (ema_30[-1] if ema_30 else sum(prices) / len(prices))

        # 2. SuperTrend (7, 3)
        st = self._calc_supertrend(prices, 7, 3)
        if st is None:
            return None
        st_bull = st["trend"] == "up"

        # 3. RSI (14) with SMA(14)
        rsi_series = self._calc_rsi_series(prices, 14)
        have_rsi = rsi_series is not None and len(rsi_series) >= 14
        rsi_val = rsi_series[-1] if rsi_series else None
        rsi_sma_val = sum(rsi_series[-14:]) / 14 if have_rsi else None
        rsi_bull = rsi_val is not None and have_rsi and rsi_val > 50 and rsi_val > rsi_sma_val and rsi_val < 70
        rsi_bear = rsi_val is not None and have_rsi and rsi_val < 50 and rsi_val < rsi_sma_val and rsi_val > 30

        # Debug
        rsi_str = f"rsi={rsi_val:.1f} rsi_sma={rsi_sma_val:.1f}" if have_rsi else "rsi=N/A"
        print(f"[DBG] {index} prices={len(prices)} ema10={ema_10[-1]:.1f} ema30={(ema_30[-1] if ema_30 else 0):.1f} "
              f"ema_bull={ema_bull} st={st['trend']} st_bull={st_bull} "
              f"{rsi_str} rsi_bull={rsi_bull} "
              f"spot={prices[-1]:.0f}", flush=True)

        # Confluence — RSI confirmation preferred but not required for quick entries
        if ema_bull and st_bull and (rsi_bull or not have_rsi):
            confidence = "HIGH" if have_rsi else "MEDIUM"
            return {
                "signal": "BUY_CE",
                "confidence": confidence,
                "spot": round(float(prices[-1]), 1),
                "strategy": "TREND_CONFLUENCE",
                "index": index,
                "ema_10": round(ema_10[-1], 1),
                "ema_30": round(ema_30[-1] if ema_30 else 0, 1),
                "st_trend": st["trend"],
                "rsi": round(rsi_val, 1) if rsi_val else None,
                "rsi_sma": round(rsi_sma_val, 1) if rsi_sma_val else None,
            }
        if not ema_bull and not st_bull and (rsi_bear or not have_rsi):
            confidence = "HIGH" if have_rsi else "MEDIUM"
            return {
                "signal": "BUY_PE",
                "confidence": confidence,
                "spot": round(float(prices[-1]), 1),
                "strategy": "TREND_CONFLUENCE",
                "index": index,
                "ema_10": round(ema_10[-1], 1),
                "ema_30": round(ema_30[-1] if ema_30 else 0, 1),
                "st_trend": st["trend"],
                "rsi": round(rsi_val, 1) if rsi_val else None,
                "rsi_sma": round(rsi_sma_val, 1) if rsi_sma_val else None,
            }
        return None

    # ---- Angel One Native Strategies (fallback) ----

    def _spot_momentum_signal(self):
        """Detect short-term momentum from last 60s of spot ticks.
        If last 5 ticks all moved up → BUY_CE.
        If last 5 ticks all moved down → BUY_PE.
        """
        ticks_n = self.nifty_ticks[-30:]
        if len(ticks_n) < 10:
            return None

        recent = [v for _, v in ticks_n[-10:]]
        if len(recent) < 5:
            return None

        up_count = sum(1 for i in range(1, len(recent)) if recent[i] > recent[i-1])
        down_count = len(recent) - 1 - up_count

        signal = None
        confidence = "LOW"
        if up_count >= 7:
            signal = "BUY_CE"
            confidence = "HIGH" if up_count >= 8 else "MEDIUM"
        elif down_count >= 7:
            signal = "BUY_PE"
            confidence = "HIGH" if down_count >= 8 else "MEDIUM"

        if not signal:
            return None

        return {
            "signal": signal,
            "confidence": confidence,
            "spot": round(float(self.nifty_spot or 0), 1),
            "strategy": "SPOT_MOMENTUM",
            "index": "NIFTY",
        }

    def _iv_extreme_signal(self):
        """Use BANKNIFTY optionGreek IV for mean-reversion.
        If IV is above 30% → high premium, sell strangle signal (BUY_PE + BUY_CE).
        If IV is below 15% → low premium, directional bias via PCR.
        """
        try:
            expiry = "26MAY2026"
            data = self.ab.get_option_greeks("BANKNIFTY", expiry)
            if not data:
                return None

            total_call_vol = sum(float(d.get("tradeVolume", 0)) for d in data if d.get("optionType") == "CE")
            total_put_vol = sum(float(d.get("tradeVolume", 0)) for d in data if d.get("optionType") == "PE")
            pcr = round(total_put_vol / total_call_vol, 2) if total_call_vol > 0 else 0.8

            # Get ATM IV
            ivs = [float(d.get("impliedVolatility", 0)) / 100 for d in data if float(d.get("impliedVolatility", 0)) > 0]
            avg_iv = np.mean(ivs) if ivs else 0.22

            signal = None
            confidence = "LOW"
            bias_reason = ""

            if avg_iv > 0.30:
                # High IV → sell premium: prefer put if PCR low, call if PCR high
                if pcr < 0.7:
                    signal = "BUY_PE"  # puts undervalued relative to calls
                    bias_reason = f"IV={avg_iv:.1%} PCR={pcr} (low) → PE bias"
                else:
                    signal = "BUY_CE"
                    bias_reason = f"IV={avg_iv:.1%} PCR={pcr} (high) → CE bias"
                confidence = "HIGH" if avg_iv > 0.35 else "MEDIUM"
            elif pcr < 0.6:
                signal = "BUY_PE"
                bias_reason = f"IV={avg_iv:.1%} PCR={pcr} (low PCR=bearish)"
                confidence = "MEDIUM"
            elif pcr > 1.0:
                signal = "BUY_CE"
                bias_reason = f"IV={avg_iv:.1%} PCR={pcr} (high PCR=bullish)"
                confidence = "MEDIUM"

            if not signal:
                return None

            return {
                "signal": signal,
                "confidence": confidence,
                "spot": round(float(self.banknifty_spot or 0), 1),
                "strategy": "IV_PCR",
                "index": "BANKNIFTY",
                "iv": round(avg_iv, 3),
                "pcr": pcr,
            }
        except Exception:
            return None

    def _spot_sma_fast_signal(self):
        """Simple trend: compare current spot to SMA of last 20 ticks.
        Above SMA → BUY_CE. Below SMA → BUY_PE.
        """
        ticks_n = self.nifty_ticks[-30:]
        if len(ticks_n) < 20:
            return None

        prices = [v for _, v in ticks_n]
        sma = sum(prices) / len(prices)
        current = prices[-1]

        signal = None
        confidence = "LOW"
        deviation = ((current - sma) / sma) * 100

        if deviation > 0.1 and current > sma:
            signal = "BUY_CE"
            confidence = "HIGH" if deviation > 0.3 else "MEDIUM"
        elif deviation < -0.1 and current < sma:
            signal = "BUY_PE"
            confidence = "HIGH" if deviation < -0.3 else "MEDIUM"

        if not signal:
            return None

        return {
            "signal": signal,
            "confidence": confidence,
            "spot": round(float(current), 1),
            "strategy": "SMA_FAST",
            "index": "NIFTY",
            "deviation_pct": round(deviation, 2),
        }

    def _expiry_str(self, index):
        """Get expiry string for an index (Tuesday identifier for trading symbol).
        Probes Angel One API to verify the calculated expiry; corrects if needed."""
        key = f"expiry_{index}"
        if hasattr(self, '_expiry_cache') and key in self._expiry_cache:
            return self._expiry_cache[key]

        # Start from the calculated expiry
        calculated = EXPIRIES.get(index, {}).get("weekly", "")
        if not calculated:
            return ""

        sym = "NIFTY" if index == "NIFTY" else "BANKNIFTY"
        base_dt = datetime.strptime(calculated, "%d%b%y")

        # Probe the calculated expiry and ±7 day offsets to find a real one
        candidates = [0, -7, 7]
        for offset in candidates:
            cand = base_dt + timedelta(days=offset)
            exp_str = cand.strftime("%d%b%y").upper()
            try:
                probe = self.ab.search_scrip("NFO", f"{sym}{exp_str}")
                if probe and len(probe) > 0:
                    if not hasattr(self, '_expiry_cache'):
                        self._expiry_cache = {}
                    self._expiry_cache[key] = exp_str
                    return exp_str
            except Exception:
                continue

        # Fallback to calculated
        return calculated

    def _expiry_greek(self, index):
        """Get expiry in DDMMMYYYY format for optionGreek endpoint.
        BN uses Tuesday, NIFTY uses Thursday (actual expiry day)."""
        exp = self._expiry_str(index)
        if not exp:
            return ""
        from datetime import datetime, timedelta
        dt = datetime.strptime(exp, "%d%b%y")
        if index == "NIFTY":
            dt += timedelta(days=2)  # trading symbol Tue → actual expiry Thu
        else:
            dt += timedelta(days=1)  # trading symbol Tue → actual expiry Wed
        return dt.strftime("%d%b%Y").upper()

    def _bs_price(self, S, K, T, sigma, optype='CE'):
        r = 0.065
        sigma = max(sigma, 0.05)
        try:
            mc = monte_carlo_price(S, K, T, r, sigma,
                                   'call' if optype == 'CE' else 'put', n_sims=2000000)
            if mc and mc > 0:
                return round(mc, 1)
        except Exception:
            pass
        from scipy.stats import norm
        if T <= 0 or sigma * math.sqrt(T) < 0.001:
            return max(0, S - K) if optype == 'CE' else max(0, K - S)
        d1 = (math.log(S/K) + (r + 0.5*sigma**2)*T) / (sigma*math.sqrt(T))
        d2 = d1 - sigma*math.sqrt(T)
        if optype == 'CE':
            return S*norm.cdf(d1) - K*math.exp(-r*T)*norm.cdf(d2)
        return K*math.exp(-r*T)*norm.cdf(-d2) - S*norm.cdf(-d1)

    # ---- GPU-Accelerated Methods ----

    def _build_pseudo_bars(self, ticks, interval_sec=60):
        if len(ticks) < 3:
            return None
        df = pd.DataFrame(ticks, columns=['ts', 'price'])
        df['ts'] = pd.to_datetime(df['ts'], unit='s')
        df = df.set_index('ts').sort_index()
        bars = df.resample(f'{interval_sec}s').agg({'price': ['first', 'max', 'min', 'last']}).dropna()
        if len(bars) < 2:
            return None
        bars.columns = ['Open', 'High', 'Low', 'Close']
        return bars

    def _gpu_pattern_strategy(self, index='BANKNIFTY'):
        ticks = self.banknifty_ticks if index == 'BANKNIFTY' else self.nifty_ticks
        bars = self._build_pseudo_bars(ticks)
        if bars is None or len(bars) < 2:
            return None
        doji, engulf, hammer = detect_all_patterns(bars)
        score = 0
        patterns = []
        if len(engulf) > 0 and engulf[-1] == 1:
            score += 2; patterns.append('BULL_ENGULF')
        elif len(engulf) > 0 and engulf[-1] == -1:
            score -= 2; patterns.append('BEAR_ENGULF')
        if len(hammer) > 0 and hammer[-1] == 1:
            score += 1; patterns.append('HAMMER')
        elif len(hammer) > 0 and hammer[-1] == -1:
            score -= 1; patterns.append('SHOOTING_STAR')
        if len(doji) > 0 and doji[-1] > 0:
            patterns.append('DOJI')
        if score >= 2:
            conf = 'HIGH' if score >= 3 else 'MEDIUM'
            return {'signal': 'BUY_CE', 'confidence': conf, 'spot': round(float(ticks[-1][1]), 1),
                    'strategy': 'GPU_PATTERN', 'index': index, 'patterns': patterns, 'score': score}
        if score <= -2:
            conf = 'HIGH' if score <= -3 else 'MEDIUM'
            return {'signal': 'BUY_PE', 'confidence': conf, 'spot': round(float(ticks[-1][1]), 1),
                    'strategy': 'GPU_PATTERN', 'index': index, 'patterns': patterns, 'score': score}
        return None

    def _gpu_macd_strategy(self, index='BANKNIFTY'):
        ticks = self.banknifty_ticks if index == 'BANKNIFTY' else self.nifty_ticks
        if len(ticks) < 26:
            return None
        prices = np.array([v for _, v in ticks], dtype=np.float64)
        macd, sig, hist = batch_macd(prices, 12, 26, 9)
        if len(hist) < 2:
            return None
        curr, prev = hist[-1], hist[-2]
        signal = None
        if prev <= 0 and curr > 0:
            signal = 'BUY_CE'
        elif prev >= 0 and curr < 0:
            signal = 'BUY_PE'
        if signal:
            conf = 'HIGH' if abs(curr) > abs(prev) * 1.5 else 'MEDIUM'
            return {'signal': signal, 'confidence': conf, 'spot': round(float(ticks[-1][1]), 1),
                    'strategy': 'GPU_MACD', 'index': index, 'macd': round(macd[-1], 1), 'hist': round(curr, 1)}
        return None

    def _gpu_refresh_sentiment(self):
        n_prices = np.array([v for _, v in self.nifty_ticks], dtype=np.float64)
        b_prices = np.array([v for _, v in self.banknifty_ticks], dtype=np.float64)
        s = {}
        if len(n_prices) >= 14:
            try:
                n_rsi = batch_rsi(n_prices, 14)
                if len(n_rsi) > 0:
                    s['nifty_rsi'] = round(n_rsi[-1], 1)
            except Exception:
                pass
        if len(b_prices) >= 14:
            try:
                b_rsi = batch_rsi(b_prices, 14)
                if len(b_rsi) > 0:
                    s['banknifty_rsi'] = round(b_rsi[-1], 1)
            except Exception:
                pass
        if len(n_prices) >= 26:
            try:
                _, _, n_hist = batch_macd(n_prices, 12, 26, 9)
                if len(n_hist) > 0:
                    s['nifty_macd_hist'] = round(n_hist[-1], 1)
            except Exception:
                pass
        if len(b_prices) >= 26:
            try:
                _, _, b_hist = batch_macd(b_prices, 12, 26, 9)
                if len(b_hist) > 0:
                    s['banknifty_macd_hist'] = round(b_hist[-1], 1)
            except Exception:
                pass
        self.gpu_sentiment = s

        # GPU: price full BANKNIFTY option chain every cycle (~350MB VRAM usage)
        try:
            spot = self.banknifty_spot
            expiry_g = self._expiry_greek("BANKNIFTY")
            iv_data = self.ab.get_option_greeks("BANKNIFTY", expiry_g)
            if spot and iv_data and len(iv_data) > 0:
                ivs = [float(d.get("impliedVolatility", 0)) / 100
                       for d in iv_data if float(d.get("impliedVolatility", 0)) > 0]
                if ivs:
                    avg_iv = np.mean(ivs)
                    strikes = [s for s in range(int(spot * 0.97 / 100) * 100,
                                                int(spot * 1.03 / 100) * 100 + 1, 100)]
                    T_yrs = self._days_to_expiry("BANKNIFTY") / 365
                    if T_yrs > 0 and len(strikes) >= 3:
                        ce_prices = batch_price_all_strikes(
                            spot, strikes, T_yrs, 0.065, avg_iv, 'call', n_sims=500000)
                        pe_prices = batch_price_all_strikes(
                            spot, strikes, T_yrs, 0.065, avg_iv, 'put', n_sims=500000)
                        self.gpu_chain = {
                            'strikes': strikes,
                            'ce': [round(p, 1) for p in ce_prices],
                            'pe': [round(p, 1) for p in pe_prices],
                            'iv': round(avg_iv, 3),
                        }
        except Exception:
            pass
        return s

    def _option_iv(self, index, strike, optype):
        """Get IV for a specific option strike from optionGreek, with caching."""
        key = f"{index}_{strike}_{optype}"
        now = time.time()
        if hasattr(self, '_iv_cache') and key in self._iv_cache:
            if now - self._iv_cache[key]['time'] < 120:
                return self._iv_cache[key]['iv']
        try:
            expiry_g = self._expiry_greek(index)
            name = "BANKNIFTY" if index == "BANKNIFTY" else "NIFTY"
            data = self.ab.get_option_greeks(name, expiry_g, strike=str(strike), optiontype=optype)
            if data and data[0].get('impliedVolatility'):
                iv = float(data[0]['impliedVolatility']) / 100
                if not hasattr(self, '_iv_cache'):
                    self._iv_cache = {}
                self._iv_cache[key] = {'iv': iv, 'time': now}
                return iv
        except Exception:
            pass
        return None

    def _days_to_expiry(self, index):
        expiry_str = self._expiry_str(index)
        if not expiry_str:
            return 7
        try:
            dt = datetime.strptime(expiry_str, "%d%b%y")
            if index == "NIFTY":
                dt += timedelta(days=2)  # Tue → Thu
            else:
                dt += timedelta(days=1)  # Tue → Wed
            return max(0.5, (dt - datetime.now()).total_seconds() / 86400)
        except:
            return 7

    def _enter_trade_estimate(self, index, signal, spot, trend_data):
        """Enter a paper trade using real LTP only — no BS fallback."""
        is_ce = signal == "BUY_CE"
        optype = "CE" if is_ce else "PE"
        expiry = self._expiry_str(index)

        # Use ATM strike
        if index == "BANKNIFTY":
            strike = round(spot / 100) * 100
        else:
            strike = round(spot / 50) * 50

        sym = "NIFTY" if index == "NIFTY" else "BANKNIFTY"
        tsym = f"{sym}{expiry}{strike}{optype}"

        # Step 1: Verify option exists in Angel One via token lookup
        for attempt in range(2):
            try:
                tokens = self.ab.search_scrip("NFO", tsym)
                if tokens and tokens[0].get("symboltoken"):
                    break
                time.sleep(1)
            except Exception:
                time.sleep(1)
        else:
            print(f"[MON] ⛔ Token not found for {tsym} — skipping entry", flush=True)
            return None

        # Step 2: Verify real LTP from REST API (no BS fallback)
        real_ltp = self._get_option_ltp(index, strike, optype, expiry=expiry)
        if real_ltp is None or real_ltp <= 5:
            print(f"[MON] ⛔ No real LTP for {index} {strike}{optype} ({real_ltp}) — skipping entry", flush=True)
            return None
        premium = round(real_ltp, 1)
        iv = self._option_iv(index, strike, optype)

        premium = max(premium, 5.0)

        # Capital check: total used + new position ≤ ₹50k
        cost = premium * LOT_SIZES.get(index, 65)
        used = sum(p["entry_ltp"] * LOT_SIZES.get(p["index"], 65) for p in self.pt.positions)
        if used + cost > 50000:
            print(f"[MON] ⛔ Capital limit: ₹{used:.0f} used + ₹{cost:.0f} > ₹50k — skipping", flush=True)
            return None
        sl_price = round(premium * 0.6, 1)
        target_price = round(premium * 1.035, 1)

        # WS: real LTP for nearby strikes
        chain_info = ""
        try:
            step = 100 if index == "BANKNIFTY" else 50
            nearby = [strike - 2*step, strike - step, strike, strike + step, strike + 2*step]
            chain_prices = []
            for s in nearby:
                ltp = self._get_option_ltp(index, s, optype, expiry=expiry)
                chain_prices.append(ltp if ltp else None)
            chain_strs = []
            for s, p in zip(nearby, chain_prices):
                if p is not None:
                    chain_strs.append(f"{s}:₹{p:.0f}")
                else:
                    chain_strs.append(f"{s}:N/A")
            chain_info = " | Chain: " + " ".join(chain_strs)
        except Exception as e:
            chain_info = f" | Chain: WS err"

        # GPU: compute Greeks at entry
        entry_delta = entry_gamma = None
        try:
            T_yrs = self._days_to_expiry(index) / 365
            if iv and T_yrs > 0:
                g = monte_carlo_greeks(spot, strike, T_yrs, 0.065, iv,
                                        'call' if is_ce else 'put', n_sims=2000000)
                entry_delta = g.get('delta')
                entry_gamma = g.get('gamma')
        except Exception:
            pass

        pos = {
            "timestamp": datetime.now().isoformat(),
            "index": index,
            "expiry": expiry,
            "strike": strike,
            "type": optype,
            "entry_ltp": premium,
            "entry_spot": spot,
            "entry_iv": iv,
            "entry_delta": entry_delta,
            "entry_gamma": entry_gamma,
            "sl": sl_price,
            "target": target_price,
            "peak_ltp": premium,
            "trail_activated": False,
            "exit_ltp": None,
            "exit_spot": None,
            "exit_reason": None,
            "pnl": None,
            "held_minutes": None,
            "entry_signal": signal,
            "rsi": trend_data.get("rsi"),
            "vwap_diff": trend_data.get("vwap_diff"),
        }
        self.pt.positions.append(pos)
        self.pt._save_trade(pos)
        iv_str = f" IV={iv*100:.0f}%" if iv else ""
        greek_str = ""
        if entry_delta is not None:
            greek_str = f" Δ={entry_delta:.2f} Γ={entry_gamma:.4f}" if entry_gamma else f" Δ={entry_delta:.2f}"
        print(f"[MON] ✅ ENTRY: {index} {expiry} {strike}{optype} @ ₹{premium} ({src},{iv_str}{greek_str}{chain_info} spot={spot})", flush=True)
        return pos

    def _has_open_position_for(self, index, signal):
        CAPITAL = 50000
        optype = signal.replace("BUY_", "")
        used = sum(p["entry_ltp"] * LOT_SIZES.get(p["index"], 65) for p in self.pt.positions)
        if used >= CAPITAL:
            return True
        for p in self.pt.positions:
            if p["index"] == index and p["type"] != optype:
                print(f"[MON] ⛔ {index} {signal} skipped — opposite {p['type']} already open", flush=True)
                return True
            if p["index"] == index and p["type"] == optype and p.get("strike"):
                print(f"[MON] ⛔ {index} {p['strike']}{optype} already open — skipping duplicate", flush=True)
                return True
        return False

    def _evaluate_all_strategies(self):
        signals = []
        for idx in ["BANKNIFTY", "NIFTY"]:
            try:
                result = self._trend_confluence_signal(index=idx)
                if result:
                    signals.append(result)
            except Exception as e:
                print(f"[MON] _trend_confluence_signal({idx}) error: {e}", flush=True)
        for idx in ["BANKNIFTY", "NIFTY"]:
            try:
                result = self._gpu_pattern_strategy(index=idx)
                if result:
                    signals.append(result)
            except Exception as e:
                print(f"[MON] _gpu_pattern_strategy({idx}) error: {e}", flush=True)
        for idx in ["BANKNIFTY", "NIFTY"]:
            try:
                result = self._gpu_macd_strategy(index=idx)
                if result:
                    signals.append(result)
            except Exception as e:
                print(f"[MON] _gpu_macd_strategy({idx}) error: {e}", flush=True)
        try:
            result = self._spot_momentum_signal()
            if result:
                signals.append(result)
        except Exception as e:
            print(f"[MON] _spot_momentum_signal error: {e}", flush=True)
        return signals

    def _send_discord(self, content, embed=None):
        if not self.webhook_url:
            print("[MON] Discord: no webhook URL", flush=True)
            return False
        try:
            import requests
            payload = {"content": str(content)[:1900]}
            if embed:
                payload["embeds"] = [embed] if isinstance(embed, dict) else embed
            print(f"[MON] Discord: sending ({len(str(content))} chars)...", flush=True)
            resp = requests.post(self.webhook_url, json=payload, timeout=10)
            ok = resp.status_code == 204
            print(f"[MON] Discord: {'OK' if ok else 'FAILED'} ({resp.status_code})", flush=True)
            return ok
        except Exception as e:
            print(f"[MON] Discord error: {e}", flush=True)
            return False

    def _est_option_ltp(self, pos):
        """Get real option LTP via WS first, fallback to BS estimate.
        Returns (price, source) where source is 'WS', 'BS', or 'ENTRY'."""
        exp = pos.get("expiry")
        ltp = self._get_option_ltp(pos["index"], pos["strike"], pos["type"], expiry=exp)
        if ltp is not None and ltp > 0:
            return round(ltp, 1), "WS"
        spot_now = self.get_spot(pos["index"]) or pos["entry_spot"]
        iv = pos.get("entry_iv")
        if not iv:
            return round(pos["entry_ltp"], 1), "ENTRY"
        T = self._days_to_expiry(pos["index"]) / 365
        try:
            return round(self._bs_price(spot_now, pos["strike"], T, iv, pos["type"]), 1), "BS"
        except:
            return round(pos["entry_ltp"], 1), "ENTRY"

    def _build_status_message(self):
        nifty = self.get_spot("NIFTY")
        bnifty = self.get_spot("BANKNIFTY")
        elapsed = (datetime.now() - self.start_time).total_seconds() / 60
        remaining = max(0, (self.end_time - datetime.now()).total_seconds() / 60)

        now_str = datetime.now().strftime('%H:%M:%S')
        lines = [f"**📊 Monitor Update #{self.update_count}** @ {now_str}"]
        lines.append(f"⏱️ {elapsed:.0f}min elapsed / {remaining:.0f}min remaining")
        lines.append(f"**NIFTY:** {nifty or 'N/A'} | **BANKNIFTY:** {bnifty or 'N/A'}")

        # Momentum info
        n_ticks = self.nifty_ticks[-20:]
        if len(n_ticks) >= 5:
            moves = [v for _, v in n_ticks]
            trend = "📈" if moves[-1] > moves[0] else "📉" if moves[-1] < moves[0] else "➡"
            lines.append(f"20-tick trend: {trend} ({moves[0]:.0f}→{moves[-1]:.0f})")
        lines.append("")

        if self.pt.positions:
            lines.append(f"**Open Positions ({len(self.pt.positions)}):**")
            for pos in self.pt.positions:
                est_ltp, src = self._est_option_ltp(pos)
                pnl = round((est_ltp - pos["entry_ltp"]) * LOT_SIZES.get(pos["index"], 65), 0)
                pnl_str = f"P&L ₹{pnl:+,.0f}"
                sl_pct = round((pos["sl"] / pos["entry_ltp"] - 1) * 100, 1) if pos["entry_ltp"] else 0
                expiry = pos.get("expiry", "")
                lines.append(
                    f"  **{pos['strike']}{pos['type']}** {pos['index']} {expiry} "
                    f"entry ₹{pos['entry_ltp']:.0f} | WS ₹{est_ltp:.0f} "
                    f"| SL ₹{pos['sl']:.0f} ({sl_pct:+.0f}%) "
                    f"| TGT ₹{pos['target']:.0f} | {pnl_str}"
                )
        else:
            lines.append("**No open positions**")

        # GPU sentiment
        if self.gpu_sentiment:
            s = self.gpu_sentiment
            gpu_parts = []
            for k, v in s.items():
                emoji = "🟢" if "rsi" in k and v and v > 50 else "🔴" if "rsi" in k and v and v < 50 else "➡"
                gpu_parts.append(f"{k.replace('_',' ').title()} {emoji}{v}")
            if gpu_parts:
                lines.append(f"**GPU:** {' | '.join(gpu_parts)}")
        # GPU option chain (show ATM strike + IV)
        if self.gpu_chain:
            c = self.gpu_chain
            mid = len(c['strikes']) // 2
            atm_s = c['strikes'][mid]
            atm_ce = c['ce'][mid]
            atm_pe = c['pe'][mid]
            lines.append(f"**BN Chain:** {atm_s}CE ₹{atm_ce:.0f} | {atm_s}PE ₹{atm_pe:.0f} | IV {c['iv']:.0%}")
        lines.append("")
        lines.append(f"🔄 Next check in ~{CHECK_INTERVAL//60} min")
        return "\n".join(lines)

    def run(self):
        self.running = True
        self.start_time = datetime.now()
        # Run until 15:00 IST (no entries before 9:30 or after 14:25)
        eod = self.start_time.replace(hour=15, minute=0, second=0, microsecond=0)
        if self.start_time >= eod:
            print(f"[MON] Already past 15:00 ({self.start_time.strftime('%H:%M:%S')}) — shutting down")
            return
        self.end_time = eod
        self.update_count = 0

        actual_hours = (self.end_time - self.start_time).total_seconds() / 3600
        print(f"[MON] Starting real-time monitor ({actual_hours:.1f}h until EOD, interval={CHECK_INTERVAL}s)")
        print(f"[MON] End time: {self.end_time.strftime('%H:%M:%S')}")

        # Build tick history with moderate polling
        print("[MON] Building initial tick history...")
        for _ in range(10):
            self.refresh_spots()
            time.sleep(2)

        nifty = self.get_spot("NIFTY")
        bnifty = self.get_spot("BANKNIFTY")
        print(f"[MON] Spot: NIFTY={nifty} BANKNIFTY={bnifty}")

        if not nifty:
            print("[MON] WARN: No NIFTY spot — waiting...")
            for _ in range(20):
                time.sleep(2)
                self.refresh_spots()
                nifty = self.get_spot("NIFTY")
                if nifty:
                    break

        # Send start notification
        dur = (self.end_time - self.start_time).total_seconds() / 60
        msg = (
            f"**🚀 Real-Time Monitor Started (EOD)** @ {datetime.now().strftime('%H:%M:%S')}\n"
            f"NIFTY: {nifty:.0f}" + (f" | BANKNIFTY: {bnifty:.0f}" if bnifty else "") + "\n"
            f"Duration: {dur:.0f}min (until {self.end_time.strftime('%H:%M:%S')})\n"
            f"Strategies: Trend Confluence + GPU Pattern/MACD + Spot Momentum\n"
            f"Data source: Angel One API + GPU (NVIDIA 920MX)"
        )
        self._send_discord(msg)

        # Main loop (single-threaded — no background thread to avoid Session race)
        while self.running:
            now = datetime.now()
            if now >= self.end_time:
                print("[MON] Time expired")
                break

            try:
                self._check_cycle()
            except Exception as e:
                import traceback
                print(f"[MON] Check cycle error: {e}", flush=True)
                traceback.print_exc()
            self.update_count += 1

            sleep_secs = min(CHECK_INTERVAL, max(1, (self.end_time - now).total_seconds()))
            print(f"[MON] Sleeping {sleep_secs:.0f}s until next check...", flush=True)
            try:
                for _ in range(int(sleep_secs // 30)):
                    if not self.running:
                        break
                    time.sleep(30)
            except Exception:
                pass

        self._shutdown()

    def _check_positions(self):
        """Check open positions with real WS LTP (BS fallback)."""
        now = datetime.now()
        force_exit = now.hour >= 15 and now.minute >= 0
        if force_exit:
            print(f"[MON] 🔴 EOD close @ {now.strftime('%H:%M:%S')} — closing {len(self.pt.positions)} positions", flush=True)
            self.pt.running = False
            for pos in self.pt.positions[:]:
                est_ltp, _ = self._est_option_ltp(pos)
                spot_now = self.get_spot(pos["index"]) or pos["entry_spot"]
                pnl = round((est_ltp - pos["entry_ltp"]) * LOT_SIZES.get(pos["index"], 65), 0)
                pos["exit_ltp"] = est_ltp
                pos["exit_spot"] = spot_now
                pos["exit_reason"] = "EOD_1500"
                pos["pnl"] = pnl
                pos["held_minutes"] = (now - datetime.fromisoformat(pos["timestamp"])).total_seconds() / 60
                self.pt._save_trade(pos)
                self.pt.trade_log.append(pos)
                self.pt.positions.remove(pos)
                emoji = "✅" if pnl > 0 else "❌"
                print(f"[MON] {emoji} EOD EXIT (15:00): {pos['strike']}{pos['type']} @ ₹{est_ltp:.0f} (P&L ₹{pnl:+,.0f})", flush=True)
            return

        for pos in self.pt.positions[:]:
            spot_now = self.get_spot(pos["index"]) or pos["entry_spot"]
            est_ltp, _ = self._est_option_ltp(pos)

            # Trail SL
            trail = self.pt._trail_sl(pos, est_ltp)
            if trail == "target":
                pos["exit_ltp"] = est_ltp
                pos["exit_spot"] = spot_now
                pos["exit_reason"] = "TARGET_HIT"
                pos["pnl"] = round((est_ltp - pos["entry_ltp"]) * LOT_SIZES.get(pos["index"], 65), 0)
                pos["held_minutes"] = (datetime.now() - datetime.fromisoformat(pos["timestamp"])).total_seconds() / 60
                self.pt._save_trade(pos)
                self.pt.trade_log.append(pos)
                self.pt.positions.remove(pos)
                print(f"[MON] ✅ TARGET HIT: {pos['strike']}{pos['type']} @ est ₹{est_ltp:.0f} (P&L ₹{pos['pnl']:+,.0f})", flush=True)
                continue
            if est_ltp <= pos["sl"]:
                pos["exit_ltp"] = est_ltp
                pos["exit_spot"] = spot_now
                pos["exit_reason"] = "SL_HIT"
                pos["pnl"] = round((est_ltp - pos["entry_ltp"]) * LOT_SIZES.get(pos["index"], 65), 0)
                pos["held_minutes"] = (datetime.now() - datetime.fromisoformat(pos["timestamp"])).total_seconds() / 60
                self.pt._save_trade(pos)
                self.pt.trade_log.append(pos)
                self.pt.positions.remove(pos)
                print(f"[MON] ❌ SL HIT: {pos['strike']}{pos['type']} @ est ₹{est_ltp:.0f} (P&L ₹{pos['pnl']:+,.0f})", flush=True)

    def _check_cycle(self):
        nifty = self.get_spot("NIFTY")
        bnifty = self.get_spot("BANKNIFTY")
        self.refresh_spots()
        nifty = self.get_spot("NIFTY")
        bnifty = self.get_spot("BANKNIFTY")
        print(f"\n[MON] === Check #{self.update_count} @ {datetime.now().strftime('%H:%M:%S')} ===", flush=True)
        print(f"[MON] NIFTY={nifty} BANKNIFTY={bnifty}", flush=True)

        # 0. GPU sentiment + chain pricing every cycle (~450MB VRAM)
        self._gpu_refresh_sentiment()
        if self.gpu_sentiment:
            s = self.gpu_sentiment
            parts = []
            if 'nifty_rsi' in s:
                parts.append(f"N_RSI={s['nifty_rsi']}")
            if 'banknifty_rsi' in s:
                parts.append(f"BN_RSI={s['banknifty_rsi']}")
            if 'nifty_macd_hist' in s:
                parts.append(f"N_MACDh={s['nifty_macd_hist']}")
            if 'banknifty_macd_hist' in s:
                parts.append(f"BN_MACDh={s['banknifty_macd_hist']}")
            if parts:
                print(f"[GPU] Sentiment: {' | '.join(parts)}", flush=True)

        # 1. Check existing positions with trailing SL
        self._check_positions()

        # 2. Evaluate all strategies (including GPU-accelerated)
        signals = self._evaluate_all_strategies()
        print(f"[MON] Signals: {len(signals)}")
        for s in signals:
            p = s.get('patterns', '')
            p_str = f" patterns={p}" if p else ""
            m = f" macd_h={s.get('hist','')}" if 'hist' in s else ""
            print(f"  {s['strategy']}: {s['signal']} ({s['confidence']}){p_str}{m}")

        print(f"[MON] Step 3: entering trades ({len(signals)} signals)...", flush=True)
        now = datetime.now()
        if now.hour < 9 or (now.hour == 9 and now.minute < 30):
            print(f"[MON] Before 9:30 — skipping all entries", flush=True)
            return
        if now.hour >= 14 and now.minute >= 25:
            print(f"[MON] After 14:25 — skipping all entries", flush=True)
            return

        # Track daily P&L for monitoring (no hard caps)
        try:
            db_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "papertrades.db")
            conn = sqlite3.connect(db_path)
            today = datetime.now().strftime("%Y-%m-%d")
            closed = conn.execute(
                "SELECT pnl FROM trades WHERE date(timestamp) = ? AND exit_ltp IS NOT NULL", (today,)
            ).fetchall()
            conn.close()
            daily_pnl = sum(r[0] for r in closed if r[0] is not None)
            self._daily_pnl = daily_pnl
        except Exception:
            pass

        MIN_AGREE = 2

        # Group signals by index and direction
        by_index = defaultdict(lambda: {"BUY_CE": [], "BUY_PE": []})
        for sig in signals:
            by_index[sig["index"]][sig["signal"]].append(sig)

        # Vote per index — require MIN_AGREE signals agreeing on same direction
        candidates = []
        for idx, votes in by_index.items():
            ce_votes, pe_votes = votes["BUY_CE"], votes["BUY_PE"]
            ce_count, pe_count = len(ce_votes), len(pe_votes)

            if ce_count >= MIN_AGREE and ce_count > pe_count:
                conf_score = sum({"HIGH": 3, "MEDIUM": 2, "LOW": 1}.get(s.get("confidence", "LOW"), 1) for s in ce_votes)
                candidates.append((idx, "BUY_CE", ce_count, conf_score, ce_votes))
            if pe_count >= MIN_AGREE and pe_count > ce_count:
                conf_score = sum({"HIGH": 3, "MEDIUM": 2, "LOW": 1}.get(s.get("confidence", "LOW"), 1) for s in pe_votes)
                candidates.append((idx, "BUY_PE", pe_count, conf_score, pe_votes))

            print(f"[MON] Vote tally for {idx}: BUY_CE={ce_count}, BUY_PE={pe_count}", flush=True)
            for s in ce_votes + pe_votes:
                print(f"  {s['strategy']} → {s['signal']} ({s.get('confidence','?')})", flush=True)

        if not candidates:
            print("[MON] No signal has ≥2 agreement — skipping entry", flush=True)
        else:
            candidates.sort(key=lambda x: (x[2], x[3]), reverse=True)
            for idx, sig_type, count, _, agreeing_signals in candidates:
                if self._has_open_position_for(idx, sig_type):
                    print(f"[MON] Already in {idx} {sig_type}, skipping candidate", flush=True)
                    continue
                pos = self._enter_trade_estimate(idx, sig_type, agreeing_signals[0]["spot"], agreeing_signals[0])
                if pos:
                    self._daily_entry_count += 1
                    agree_str = " | ".join(s["strategy"] for s in agreeing_signals)
                    emoji = "🟢" if sig_type == "BUY_CE" else "🔴"
                    expiry = self._expiry_str(idx)
                    self._send_discord(
                        f"{emoji} **VOTE ({count}/{len(signals)}) — {idx} {sig_type}** @ {datetime.now().strftime('%H:%M:%S')}\n"
                        f"Agreeing: {agree_str}\n"
                        f"Buy **{pos['strike']}{pos['type']}** ({idx} {expiry}) @ ₹{pos['entry_ltp']:.0f}\n"
                        f"Spot: {agreeing_signals[0]['spot']:.0f}\n"
                        f"SL: ₹{pos['sl']:.0f} | Target: ₹{pos['target']:.0f} | "
                        f"Lot: {LOT_SIZES.get(idx, 65)}"
                    )
                else:
                    print(f"[MON] Failed to enter {idx} {sig_type}, trying next candidate", flush=True)

        print(f"[MON] Step 4: sending status update...", flush=True)
        if self.pt.positions or self.update_count % 2 == 0:
            status = self._build_status_message()
            self._send_discord(status)
        print(f"[MON] Check cycle complete", flush=True)

    def _shutdown(self):
        print("[MON] Shutting down...")

        if self.pt.positions:
            for pos in self.pt.positions[:]:
                spot_now = self.get_spot(pos["index"]) or pos["entry_spot"]
                exit_ltp, _ = self._est_option_ltp(pos)
                pos["exit_ltp"] = exit_ltp
                pos["exit_spot"] = spot_now
                pos["exit_reason"] = "MONITOR_END"
                pnl = (exit_ltp - pos["entry_ltp"]) * LOT_SIZES.get(pos["index"], 65)
                pos["pnl"] = round(pnl, 0)
                if pos.get("timestamp"):
                    pos["held_minutes"] = (datetime.now() - datetime.fromisoformat(pos["timestamp"])).total_seconds() / 60
                self.pt._save_trade(pos)
                self.pt.trade_log.append(pos)
            self.pt.positions.clear()

        elapsed = (datetime.now() - self.start_time).total_seconds() / 60
        nifty = self.get_spot("NIFTY")
        bnifty = self.get_spot("BANKNIFTY")

        total_pnl = sum(float(p.get("pnl", 0) or 0) for p in self.pt.trade_log)
        wins = sum(1 for p in self.pt.trade_log if p.get("pnl", 0) and p["pnl"] > 0)
        losses = sum(1 for p in self.pt.trade_log if p.get("pnl", 0) and p["pnl"] < 0)

        msg = (
            f"**🏁 Monitor Session Complete** @ {datetime.now().strftime('%H:%M:%S')}\n"
            f"Duration: {elapsed:.0f} min | Checks: {self.update_count}\n"
            f"Trades: {len(self.pt.trade_log)} ({wins}W/{losses}L)\n"
            f"P&L: ₹{total_pnl:+,.0f}\n"
            f"NIFTY: {nifty or 'N/A'} | BANKNIFTY: {bnifty or 'N/A'}"
        )
        self._send_discord(msg)
        self.running = False
        print(f"[MON] {msg}")


def _main():
    import argparse
    parser = argparse.ArgumentParser(description="Real-Time Market Monitor (Angel One only)")
    parser.add_argument("--webhook", default=os.environ.get("DISCORD_WEBHOOK", ""))
    parser.add_argument("--hours", type=int, default=MONITOR_HOURS)
    parser.add_argument("--interval", type=int, default=CHECK_INTERVAL)
    args = parser.parse_args()

    h = args.hours
    ci = args.interval

    print(f"[MON] Starting {h}h monitor with {ci}s interval (Angel One only)", flush=True)
    monitor = RealTimeMonitor(webhook_url=args.webhook)
    monitor.run()


if __name__ == "__main__":
    try:
        _main()
    except Exception as e:
        import traceback
        print(f"[MON] FATAL: {e}", flush=True)
        traceback.print_exc()
        sys.stdout.flush()
