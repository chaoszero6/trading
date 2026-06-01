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

    def suggest(self, capital=50000, nifty=None, banknifty=None, news_summary=None, risk_tolerance="moderate", preferred_index="NIFTY"):
        """Generate trade suggestions using Angel One real IV + Black-Scholes pricing."""
        result = {
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "capital": capital,
            "risk_tolerance": risk_tolerance,
            "lot_size": LOT_SIZES.get(preferred_index, 65),
            "suggestions": [],
        }

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
        iv = greeks.get("iv_call", 0.21) or 0.21

        sentiment = 0
        if news_summary:
            if news_summary.get("overall_sentiment") == "positive":
                sentiment = 1
            elif news_summary.get("overall_sentiment") == "negative":
                sentiment = -1

        direction_score = 0
        direction_score += 0.5 if sentiment > 0 else (-0.5 if sentiment < 0 else 0)
        direction_score += 0.5 if oi.get("pcr", 0.8) > 0.8 else (-0.3 if oi.get("pcr", 0.8) < 0.6 else 0)
        direction_score += 0.3 if spot > oi.get("support", spot - 100) else 0

        is_bullish = direction_score > 0
        atm = oi.get("atm", round(spot / 50) * 50)
        resistance = oi.get("resistance", atm + 200)
        support = oi.get("support", atm - 200)

        strike_dist = {"conservative": 100, "moderate": 200, "aggressive": 300}.get(risk_tolerance, 200)
        trade_type = "CE" if is_bullish else "PE"
        buy_strike = atm + strike_dist if is_bullish else atm - strike_dist

        premium = self._bs_price(spot, buy_strike, T, r, iv, trade_type)
        if premium == 0:
            premium = max(round(spot * 0.006), 50)

        sl_points = round(premium * 0.4)
        target_points = round(premium * 2.5)
        sl_price = round(premium - sl_points, 1)
        target_price = round(premium + target_points, 1)
        cost_per_lot = premium * lot_size
        r_to_r = round(target_points / sl_points, 1) if sl_points > 0 else 0
        max_lots = max(1, int(capital / cost_per_lot)) if cost_per_lot > 0 else 1
        qty = max_lots * lot_size
        total_risk = max_lots * lot_size * sl_points
        confidence = "HIGH" if abs(direction_score) > 0.8 else ("MEDIUM" if abs(direction_score) > 0.3 else "LOW")

        main_suggestion = {
            "index": preferred_index,
            "lot_size": lot_size,
            "strike": buy_strike,
            "type": trade_type,
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
            "confidence": confidence,
            "direction_score": round(direction_score, 2),
            "reasoning_summary": self._generate_reasoning(direction_score, oi, greeks, is_bullish, news_summary),
            "oi_support": support,
            "oi_resistance": resistance,
            "pcr": oi.get("pcr", "N/A"),
            "atm": atm,
        }

        result["suggestions"] = [main_suggestion]
        result["oi_analysis"] = oi
        result["greeks"] = greeks
        return result

    def _generate_reasoning(self, direction_score, oi, greeks, is_bullish, news_summary):
        parts = []
        supp = oi.get('support')
        res = oi.get('resistance')
        pcr = oi.get('pcr', 'N/A')
        if is_bullish:
            parts.append(f"Bullish bias (score {direction_score:+.2f})")
            parts.append(f"OI support at {supp if supp else 'N/A'}")
            parts.append(f"PCR at {pcr}")
        else:
            parts.append(f"Bearish bias (score {direction_score:+.2f})")
            parts.append(f"OI resistance at {res if res else 'N/A'}")
            parts.append(f"PCR at {pcr}")

        if greeks.get("iv_call"):
            parts.append(f"Call IV: {greeks['iv_call']:.1%}")
        if greeks.get("iv_put"):
            parts.append(f"Put IV: {greeks['iv_put']:.1%}")

        if news_summary:
            parts.append(f"Sentiment: {news_summary.get('overall_sentiment', 'neutral')}")

        return " | ".join(parts)


if __name__ == "__main__":
    expert = TradingExpert()
    result = expert.suggest(capital=50000)
    import json
    print(json.dumps(result, indent=2, default=str))
