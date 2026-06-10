"""
TradingExpert — Options trading strategist.
Uses Angel One SmartAPI optionGreek endpoint for real IV + yfinance for spot prices.
Recommends specific CE/PE strikes with entry, SL, target computed via Black-Scholes.
"""

import sys, os, math
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import datetime, timedelta
from scipy.stats import norm

from config import get_next_next_weekly_expiry

LOT_SIZES = {"NIFTY": 65, "BANKNIFTY": 30} 

def _bn_expiry_yyyy():
    exp = get_next_next_weekly_expiry("BANKNIFTY")
    import re
    m = re.match(r'(\d+)([A-Z]+)(\d+)', exp)
    return f"{m.group(1)}{m.group(2)}20{m.group(3)}" if m else exp

EXPIRIES = {"NIFTY": "", "BANKNIFTY": _bn_expiry_yyyy()}


class TradingExpert:
    def __init__(self):
        self.name = "TradingExpert"
        self._angel = None

    def _get_angel(self):
        if self._angel is None:
            from core.angel_bridge import AngelOneBridge
            self._angel = AngelOneBridge()
            self._angel.authenticate()
        return self._angel

    def get_option_chain_data(self, symbol="NIFTY"):
        """Fetch option Greeks + IV from Angel One API (BANKNIFTY only)."""
        if symbol != "BANKNIFTY":
            return None, [], []
        try:
            ab = self._get_angel()
            expiry = EXPIRIES.get("BANKNIFTY", "26MAY2026")
            data = ab.get_option_greeks("BANKNIFTY", expiry)
            if not data:
                return None, [], []
            calls = [d for d in data if d.get("optionType") == "CE"]
            puts = [d for d in data if d.get("optionType") == "PE"]
            return expiry, calls, puts
        except Exception:
            return None, [], []

    def analyze_oi(self, calls, puts, spot):
        """Analyze volume concentration from Angel One optionGreek data."""
        if not calls or not puts:
            return {}

        atm = round(spot / 50) * 50
        near_calls = [c for c in calls if abs(float(c["strikePrice"]) - atm) <= 300]
        near_puts = [p for p in puts if abs(float(p["strikePrice"]) - atm) <= 300]

        def by_vol(items):
            return sorted(items, key=lambda x: float(x.get("tradeVolume", 0)), reverse=True)

        top_calls = by_vol(near_calls)
        top_puts = by_vol(near_puts)

        total_call_vol = sum(float(c.get("tradeVolume", 0)) for c in calls)
        total_put_vol = sum(float(p.get("tradeVolume", 0)) for p in puts)
        pcr = round(total_put_vol / total_call_vol, 2) if total_call_vol > 0 else 0

        max_call = top_calls[0] if top_calls else {}
        max_put = top_puts[0] if top_puts else {}

        return {
            "max_call_oi_strike": float(max_call.get("strikePrice", 0)) if max_call else 0,
            "max_call_oi": int(float(max_call.get("tradeVolume", 0))),
            "max_put_oi_strike": float(max_put.get("strikePrice", 0)) if max_put else 0,
            "max_put_oi": int(float(max_put.get("tradeVolume", 0))),
            "pcr": pcr,
            "resistance": float(max_call.get("strikePrice", atm + 200)) if max_call else atm + 200,
            "support": float(max_put.get("strikePrice", atm - 200)) if max_put else atm - 200,
            "atm": atm,
            "top_call_oi_%": round(sum(float(c.get("tradeVolume", 0)) for c in near_calls) / total_call_vol * 100, 1) if total_call_vol > 0 else 0,
            "top_put_oi_%": round(sum(float(p.get("tradeVolume", 0)) for p in near_puts) / total_put_vol * 100, 1) if total_put_vol > 0 else 0,
        }

    def compute_iv_and_greeks(self, calls, puts, spot, expiry_date):
        """Get real IV from Angel One optionGreek data (BANKNIFTY only)."""
        atm = round(spot / 50) * 50
        # NIFTY: no optionGreek data available, return estimate
        if not calls or not puts:
            return {"atm": atm, "iv_call": 0.22, "iv_put": 0.22, "T_days": 11}
        # Use real IV from first available call/put
        iv_call = iv_put = 0.22
        for c in calls:
            iv = float(c.get("impliedVolatility", 0))
            if iv > 0:
                iv_call = iv / 100
                break
        for p in puts:
            iv = float(p.get("impliedVolatility", 0))
            if iv > 0:
                iv_put = iv / 100
                break
        return {"atm": atm, "iv_call": iv_call, "iv_put": iv_put, "T_days": 11}

    @staticmethod
    def _bs_price(S, K, T, r, sigma, optype='CE'):
        sigma = max(sigma, 0.05)
        if T <= 0 or sigma * math.sqrt(T) < 0.001:
            return max(0, S - K) if optype == 'CE' else max(0, K - S)
        d1 = (math.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * math.sqrt(T))
        d2 = d1 - sigma * math.sqrt(T)
        if optype == 'CE':
            return S * norm.cdf(d1) - K * math.exp(-r * T) * norm.cdf(d2)
        else:
            return K * math.exp(-r * T) * norm.cdf(-d2) - S * norm.cdf(-d1)

    # ── Price / momentum helpers ──────────────────────────────────────

    def _fetch_price_data(self, symbol):
        """Fetch 5-min candles for VWAP, momentum, and pullback analysis."""
        import yfinance as yf
        yf_sym = {"NIFTY": "^NSEI", "BANKNIFTY": "^NSEBANK"}.get(symbol, "^NSEI")
        try:
            df = yf.download(yf_sym, period="5d", interval="5m", progress=False)
            if df is None or df.empty:
                return None
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.droplevel(1)
            df.columns = [str(c).lower() for c in df.columns]
            if df.index.tz is not None:
                df.index = df.index.tz_convert("Asia/Kolkata")
            else:
                df.index = pd.to_datetime(df.index).tz_localize("UTC").tz_convert("Asia/Kolkata")
            df = df.between_time("09:15", "15:30")
            return df
        except Exception:
            return None

    def _vwap_structure_score(self, df):
        """Compute VWAP + market structure score.
        Returns (score, vwap, above_vwap, hhlh, lhll, details_str)."""
        if df is None or len(df) < 20:
            return 0, None, False, False, False, "Insufficient data"

        df = df.copy()
        df["tp"] = (df["high"] + df["low"] + df["close"]) / 3
        vol = df["volume"].values
        if vol.max() > 0:
            df["vwap"] = (df["tp"] * df["volume"]).cumsum() / df["volume"].cumsum()
        else:
            df["vwap"] = df["tp"].expanding().mean()
        df["vwap_diff"] = ((df["close"] - df["vwap"]) / df["vwap"]) * 100

        vwap = float(df["vwap"].iloc[-1])
        above_vwap = float(df["close"].iloc[-1]) > vwap

        # Find swing points for structure
        from agents.vwap_pullback_breakout import find_swing_points, check_hhlh, check_lhll
        swh, swl = find_swing_points(df)
        hhlh, _, _ = check_hhlh(swl, swh)
        lhll, _, _ = check_lhll(swl, swh)

        score = 0
        details = []
        if above_vwap and hhlh:
            score = 0.5
            details.append("VWAP uptrend (HHLH)")
        elif not above_vwap and lhll:
            score = -0.5
            details.append("VWAP downtrend (LHLL)")
        elif above_vwap:
            score = 0.2
            details.append("Above VWAP only")
        elif not above_vwap:
            score = -0.2
            details.append("Below VWAP only")
        else:
            details.append("No clear structure")

        return score, vwap, above_vwap, hhlh, lhll, " | ".join(details)

    def _momentum(self, df):
        """Compute momentum strength from price data.
        Returns (strength_label, rsi, atr_pct, vol_ratio, details_str)."""
        if df is None or len(df) < 20:
            return "neutral", 50, 0, 1, "No data"

        closes = df["close"].values
        highs = df["high"].values
        lows = df["low"].values
        vols = df["volume"].values

        # RSI(14)
        deltas = np.diff(closes)
        gains = np.where(deltas > 0, deltas, 0)
        losses = np.where(deltas < 0, -deltas, 0)
        avg_gain = np.mean(gains[-14:]) if len(gains) >= 14 else np.mean(gains)
        avg_loss = np.mean(losses[-14:]) if len(losses) >= 14 else np.mean(losses)
        rsi = 50
        if avg_loss > 0:
            rs = avg_gain / avg_loss
            rsi = 100 - (100 / (1 + rs))

        # ATR %
        true_ranges = []
        for j in range(1, min(15, len(df))):
            tr = max(highs[-j] - lows[-j], abs(highs[-j] - closes[-j - 1]), abs(lows[-j] - closes[-j - 1]))
            true_ranges.append(tr)
        atr = np.mean(true_ranges) if true_ranges else 0
        atr_pct = atr / closes[-1] * 100 if closes[-1] > 0 else 0

        # Volume ratio
        avg_vol = np.mean(vols[-20:]) if len(vols) >= 20 else np.mean(vols)
        vol_ratio = float(vols[-1] / avg_vol) if avg_vol > 0 else 1

        # Candle strength
        last = df.iloc[-1]
        candle_range = last["high"] - last["low"]
        body = abs(last["close"] - last["open"])
        body_pct = body / candle_range if candle_range > 0 else 0.5

        # Combined momentum assessment
        details = [f"RSI {rsi:.0f}", f"ATR {atr_pct:.2f}%", f"Vol {vol_ratio:.1f}x", f"Body {body_pct:.0%}"]

        if rsi > 65 and vol_ratio > 1.2 and body_pct > 0.6:
            return "strong_bullish", rsi, atr_pct, vol_ratio, " | ".join(details)
        elif rsi < 35 and vol_ratio > 1.2 and body_pct > 0.6:
            return "strong_bearish", rsi, atr_pct, vol_ratio, " | ".join(details)
        elif rsi > 55:
            return "mild_bullish", rsi, atr_pct, vol_ratio, " | ".join(details)
        elif rsi < 45:
            return "mild_bearish", rsi, atr_pct, vol_ratio, " | ".join(details)
        else:
            return "neutral", rsi, atr_pct, vol_ratio, " | ".join(details)

    def _detect_pullback(self, df, direction):
        """Detect pullback/retracement in price action.
        direction: 'bullish' (looking for pullback in uptrend) or 'bearish' (retrace in downtrend).
        Returns (is_pullback, pullback_price, description)."""
        if df is None or len(df) < 10:
            return False, None, "Insufficient data"

        closes = df["close"].values
        highs = df["high"].values
        lows = df["low"].values

        if direction == "bullish":
            # Look for 2+ down candles after a rise
            down_count = 0
            pullback_low = None
            for j in range(min(8, len(df) - 1), 0, -1):
                if closes[-j] < closes[-j - 1]:
                    down_count += 1
                    if pullback_low is None or lows[-j] < pullback_low:
                        pullback_low = lows[-j]
                else:
                    if down_count >= 2:
                        # Found pullback — check if last candle reversed up
                        last_bullish = closes[-1] > closes[-2]
                        if last_bullish:
                            return True, pullback_low, f"Pullback to {pullback_low:.0f}, reversing up"
                        return True, pullback_low, f"Pullback to {pullback_low:.0f}, awaiting reversal"
                    return False, None, "No pullback"
            return False, None, "No pullback"

        else:  # bearish
            # Look for 2+ up candles after a fall
            up_count = 0
            retrace_high = None
            for j in range(min(8, len(df) - 1), 0, -1):
                if closes[-j] > closes[-j - 1]:
                    up_count += 1
                    if retrace_high is None or highs[-j] > retrace_high:
                        retrace_high = highs[-j]
                else:
                    if up_count >= 2:
                        last_bearish = closes[-1] < closes[-2]
                        if last_bearish:
                            return True, retrace_high, f"Retrace to {retrace_high:.0f}, reversing down"
                        return True, retrace_high, f"Retrace to {retrace_high:.0f}, awaiting reversal"
                    return False, None, "No retracement"
            return False, None, "No retracement"

    # ── Contract scoring ──────────────────────────────────────────────

    def _score_contract(self, spot, strike, optype, T, r, iv, direction, momentum_label, balance):
        """Score an option contract 0-100 for suitability."""
        premium = self._bs_price(spot, strike, T, r, iv, optype)
        if premium <= 0:
            return 0, premium, "Zero premium"

        interval = 50 if strike % 50 == 0 else 100
        atm = round(spot / interval) * interval
        otm_distance = abs(strike - atm) / interval

        # Affordability: premium * lot size ≤ 10% of capital
        lot_size = 65 if strike < 50000 else 30  # NIFTY vs BANKNIFTY approx
        cost = premium * lot_size
        affordable = cost <= balance * 0.10

        delta_est = 0.5 - otm_distance * 0.15 if optype == "CE" else -(0.5 - otm_distance * 0.15)
        if optype == "PE":
            delta_est = -(0.5 - otm_distance * 0.15)

        score = 30  # base

        # Affordability weight (soft penalty — 1 lot minimum trade)
        if affordable:
            score += 15
        elif cost > balance:
            score -= 10  # genuinely can't afford even 1 lot
        else:
            score += 0  # can afford 1 lot but tight

        # OTM distance fit with momentum
        bullish = optype == "CE"
        if momentum_label == "strong_bullish" and bullish:
            score += max(0, 15 - otm_distance * 5)  # strong bull → prefer OTM for leverage
            score += 15
        elif momentum_label == "mild_bullish" and bullish:
            score += max(0, 10 - otm_distance * 8)  # prefer nearer strikes
        elif momentum_label == "strong_bearish" and not bullish:
            score += max(0, 15 - otm_distance * 5)
            score += 15
        elif momentum_label == "mild_bearish" and not bullish:
            score += max(0, 10 - otm_distance * 8)
        elif momentum_label == "neutral":
            score += 0  # no momentum penalty or bonus
        else:
            score -= 10  # mismatched direction

        # Premium reasonability
        premium_pct = premium / spot * 100
        if 0.2 <= premium_pct <= 2.0:
            score += 10
        elif premium_pct > 5.0:
            score -= 5  # too expensive

        # ATM bonus (best liquidity)
        if otm_distance == 0:
            score += 10
        elif otm_distance <= 1:
            score += 5

        confidence = round(min(max(score, 0), 100))
        return confidence, round(premium, 1), None

    # ── Main suggest ──────────────────────────────────────────────────

    def suggest(self, capital=50000, nifty=None, banknifty=None, news_summary=None, risk_tolerance="moderate", preferred_index="NIFTY"):
        """Generate trade suggestions using full strategy: combined direction, 10-contract scan, momentum strike selection, pullback entry."""
        import pandas as pd

        result = {
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "capital": capital,
            "risk_tolerance": risk_tolerance,
            "lot_size": LOT_SIZES.get(preferred_index, 65),
            "suggestions": [],
        }

        # ── Spot price ──
        if preferred_index == "BANKNIFTY":
            from core.market_data import get_banknifty_realtime
            spot = (banknifty or get_banknifty_realtime()) or 53700
        else:
            if nifty is None:
                from core.market_data import get_nifty_realtime
                nifty = get_nifty_realtime()
            spot = nifty or 23500

        lot_size = LOT_SIZES.get(preferred_index, 65)
        api_symbol = "NIFTY" if preferred_index == "NIFTY" else "BANKNIFTY"
        expiry, calls, puts = self.get_option_chain_data(api_symbol)
        oi = self.analyze_oi(calls, puts, spot)
        greeks = self.compute_iv_and_greeks(calls, puts, spot, None)
        iv = greeks.get("iv_call", 0.21) or 0.21

        T = 11 / 365
        r = 0.065

        # ── News sentiment ──
        sentiment = 0
        if news_summary:
            if news_summary.get("overall_sentiment") == "positive":
                sentiment = 1
            elif news_summary.get("overall_sentiment") == "negative":
                sentiment = -1

        # ── Price data for VWAP + momentum + pullback ──
        price_df = self._fetch_price_data(preferred_index)

        # VWAP structure score
        vwap_score, vwap, above_vwap, hhlh, lhll, vwap_detail = self._vwap_structure_score(price_df)

        # Momentum
        momentum_label, rsi, atr_pct, vol_ratio, momentum_detail = self._momentum(price_df)

        # ── Combined direction score ──
        direction_score = 0
        direction_score += 0.5 if sentiment > 0 else (-0.5 if sentiment < 0 else 0)
        pcr = oi.get("pcr", 1.0)
        direction_score += 0.5 if pcr > 0.8 else (-0.2 if pcr > 0.6 else -0.5)
        direction_score += 0.3 if spot > oi.get("support", spot - 200) else -0.3
        direction_score += vwap_score  # ±0.5 from VWAP structure

        is_bullish = direction_score > 0
        interval = 50 if preferred_index == "NIFTY" else 100
        atm = round(spot / interval) * interval
        resistance = oi.get("resistance", atm + 200)
        support = oi.get("support", atm - 200)

        # ── Pullback detection ──
        pullback_dir = "bullish" if is_bullish else "bearish"
        in_pullback, pullback_price, pullback_detail = self._detect_pullback(price_df, pullback_dir)

        # ── 10-contract scan: ATM-2 to ATM+2 for both CE and PE ──
        strikes = [atm - 2 * interval, atm - interval, atm, atm + interval, atm + 2 * interval]
        scored = []
        for strike in strikes:
            for optype in ["CE", "PE"]:
                # Only score contracts matching our direction
                if is_bullish and optype != "CE":
                    continue
                if not is_bullish and optype != "PE":
                    continue
                conf, prem, err = self._score_contract(spot, strike, optype, T, r, iv, is_bullish, momentum_label, capital)
                if err:
                    continue
                scored.append((conf, strike, optype, prem))

        scored.sort(key=lambda x: -x[0])

        # ── Build suggestion ──
        if scored:
            best_conf, best_strike, best_type, best_prem = scored[0]
            alternative = scored[1] if len(scored) > 1 else None
        else:
            # Fallback: use ATM
            best_strike = atm
            best_type = "CE" if is_bullish else "PE"
            best_prem = self._bs_price(spot, best_strike, T, r, iv, best_type)
            if best_prem <= 0:
                best_prem = max(round(spot * 0.006), 50)
            best_prem = round(best_prem, 1)
            best_conf = 50

        premium = best_prem if best_prem > 0 else max(round(spot * 0.006), 50)
        sl_points = round(premium * 0.4)
        target_points = round(premium * 2.5)
        sl_price = round(premium - sl_points, 1)
        target_price = round(premium + target_points, 1)
        cost_per_lot = premium * lot_size
        r_to_r = round(target_points / sl_points, 1) if sl_points > 0 else 0
        max_lots = max(1, int(capital / cost_per_lot)) if cost_per_lot > 0 else 1
        qty = max_lots * lot_size
        total_risk = max_lots * lot_size * sl_points

        if best_conf >= 70:
            confidence_label = "HIGH"
        elif best_conf >= 40:
            confidence_label = "MEDIUM"
        else:
            confidence_label = "LOW"

        # Entry trigger description
        if in_pullback:
            entry_trigger = f"Enter on pullback: {pullback_detail}. Wait for candle to resume in direction."
        else:
            entry_trigger = f"No pullback yet. {pullback_detail}. Wait for retrace."

        otm_distance = (best_strike - atm) / interval
        otm_label = "ITM" if otm_distance < 0 else ("ATM" if otm_distance == 0 else "OTM")

        main_suggestion = {
            "index": preferred_index,
            "lot_size": lot_size,
            "strike": best_strike,
            "type": best_type,
            "entry_premium": round(premium),
            "cost_per_lot": round(cost_per_lot),
            "stop_loss": sl_price,
            "sl_points": sl_points,
            "target": target_price,
            "target_points": target_points,
            "max_loss_per_share": sl_points,
            "recommended_lots": max_lots,
            "recommended_qty": qty,
            "total_risk": round(total_risk),
            "risk_reward": r_to_r,
            "confidence": confidence_label,
            "direction_score": round(direction_score, 2),
            "reasoning_summary": self._generate_reasoning(
                direction_score, oi, greeks, is_bullish, news_summary,
                momentum_label, vwap_detail, in_pullback, pullback_detail,
                best_strike, best_type, otm_label, atm,
            ),
            "oi_support": support,
            "oi_resistance": resistance,
            "pcr": oi.get("pcr", "N/A"),
            "atm": atm,
            "vwap": round(vwap, 1) if vwap else None,
            "above_vwap": above_vwap,
            "hhlh": hhlh,
            "lhll": lhll,
            "momentum": momentum_label,
            "rsi": round(rsi, 1),
            "atr_pct": round(atr_pct, 3),
            "volume_ratio": round(vol_ratio, 1),
            "in_pullback": in_pullback,
            "entry_trigger": entry_trigger,
            "scanned_contracts": [
                {"strike": s, "type": t, "score": c, "premium": p}
                for c, s, t, p in scored[:6]
            ],
        }

        result["suggestions"] = [main_suggestion]
        result["oi_analysis"] = oi
        result["greeks"] = greeks
        return result

    def _generate_reasoning(self, direction_score, oi, greeks, is_bullish, news_summary,
                           momentum=None, vwap_detail=None, in_pullback=None, pullback_detail=None,
                           strike=None, optype=None, otm_label=None, atm=None):
        parts = []
        supp = oi.get('support')
        res = oi.get('resistance')
        pcr = oi.get('pcr', 'N/A')
        direction = "BULLISH" if is_bullish else "BEARISH"
        parts.append(f"{direction} (score {direction_score:+.2f})")

        if vwap_detail:
            parts.append(vwap_detail)
        if momentum:
            parts.append(f"Momentum: {momentum}")

        parts.append(f"OI support {supp if supp else 'N/A'} | PCR {pcr}")

        if strike and optype:
            otm_str = otm_label or ""
            parts.append(f"Pick: {strike}{optype} ({otm_str})")

        if in_pullback:
            parts.append(f"Pullback: {pullback_detail}")
        elif pullback_detail and "No" not in pullback_detail:
            parts.append(f"Pullback: {pullback_detail}")

        if greeks.get("iv_call"):
            parts.append(f"Call IV: {greeks['iv_call']:.1%} | Put IV: {greeks.get('iv_put', 0):.1%}")
        if news_summary:
            parts.append(f"News: {news_summary.get('overall_sentiment', 'neutral')}")

        return " | ".join(parts)


if __name__ == "__main__":
    expert = TradingExpert()
    result = expert.suggest(capital=50000)
    import json
    print(json.dumps(result, indent=2, default=str))
