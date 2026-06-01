"""
TraderManager — Orchestrator tool that gathers ALL real-time market data,
runs all analysis modules, and returns structured data for the AI agent
to reason over and produce a final trade suggestion.
"""

import sys, os, json
from datetime import datetime, timedelta
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    import pandas as pd
    _ = pd.DataFrame
except (ImportError, AttributeError):
    import sys
    for k in list(sys.modules):
        if 'pandas' in k:
            del sys.modules[k]
    import pandas as pd
import yfinance as yf
import numpy as np


class TraderManager:
    """Collects real-time data from all sources for AI agent consumption."""

    def __init__(self):
        self.name = "TraderManager"
        self.data = {}

    def gather_all(self, capital=50000, risk_tolerance="moderate", preferred_index="NIFTY"):
        print(f"\n{'='*60}")
        print(f"  TRADER MANAGER — Gathering Real-Time Market Data")
        print(f"{'='*60}\n")

        self.data = {
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "user_params": {
                "capital": capital,
                "risk_tolerance": risk_tolerance,
                "preferred_index": preferred_index,
            }
        }

        self._gather_index_prices()
        self._gather_news_sentiment()
        self._gather_vwap_analysis()
        self._gather_gpu_candlestick()
        self._gather_option_chain_oi()
        self._gather_technical_indicators()
        self._gather_trading_expert()
        self._gather_risk_assessment()
        self._gather_lessons()

        self._print_summary()
        return self.data

    def _gather_index_prices(self):
        print("[1/8] Index prices...")
        from core.market_data import get_nifty_realtime, get_banknifty_realtime, get_market_summary
        nifty = get_nifty_realtime()
        bnifty = get_banknifty_realtime()
        ms = get_market_summary()
        self.data["nifty"] = nifty
        self.data["banknifty"] = bnifty
        self.data["indices"] = ms
        print(f"  NIFTY: {nifty} | BANKNIFTY: {bnifty}")

    def _gather_news_sentiment(self):
        print("[2/8] News sentiment...")
        try:
            from agents.news_agent import MarketNewsAgent
            na = MarketNewsAgent()
            articles = na.fetch_news(max_articles=25)
            analyzed = []
            for a in articles:
                impact = na.assess_indian_market_impact(a)
                analyzed.append({**a, "impact": impact})
            analyzed.sort(key=lambda x: -abs(x["impact"]["impact_score"]))
            ns = na.get_summary(analyzed)
            self.data["news"] = {
                "summary": ns,
                "top_stories": [{"title": a["title"], "impact": a["impact"]["impact_score"],
                                 "sentiment": a["impact"]["sentiment"]["label"],
                                 "sectors": a["impact"]["sectors_impacted"]}
                                for a in analyzed[:5]]
            }
            print(f"  Outlook: {ns['market_outlook']} | Sentiment: {ns['overall_sentiment']}")
        except Exception as e:
            print(f"  News error: {e}")
            self.data["news"] = {
                "summary": {"overall_sentiment": "neutral", "bullish_sectors": [],
                            "bearish_sectors": [], "top_stories": [],
                            "market_outlook": "NEUTRAL/SIDEWAYS"},
                "top_stories": []
            }

    def _gather_vwap_analysis(self):
        print("[3/8] VWAP analysis...")
        try:
            ndf = yf.download("^NSEI", period="1mo", interval="1d", progress=False)
            bdf = yf.download("^NSEBANK", period="1mo", interval="1d", progress=False)

            def calc_vwap(df):
                if df.empty: return None, None, None
                h = df["High"].values.ravel()
                l = df["Low"].values.ravel()
                c = df["Close"].values.ravel()
                v = df["Volume"].values.ravel()
                typ = (h + l + c) / 3
                vw = (typ * v).sum() / v.sum() if v.sum() > 0 else c[-1]
                curr = float(c[-1])
                diff = ((curr - vw) / vw) * 100
                return curr, vw, diff

            n_curr, n_vwap, n_diff = calc_vwap(ndf)
            b_curr, b_vwap, b_diff = calc_vwap(bdf)

            self.data["vwap"] = {
                "nifty": {"price": n_curr, "vwap": n_vwap, "diff_pct": round(n_diff, 2)},
                "banknifty": {"price": b_curr, "vwap": b_vwap, "diff_pct": round(b_diff, 2)},
            }
            print(f"  NIFTY: {n_curr:.0f} vs VWAP {n_vwap:.0f} ({n_diff:+.2f}%)")
        except Exception as e:
            print(f"  VWAP error: {e}")

    def _gather_gpu_candlestick(self):
        print("[4/8] GPU candlestick patterns...")
        try:
            from core.gpu_candlestick import predict_next
            banks = ["HDFCBANK","ICICIBANK","SBIN","AXISBANK","KOTAKBANK",
                     "INDUSINDBK","BANKBARODA","PNB","CANBK","FEDERALBNK",
                     "IDFCFIRSTB","AUBANK","YESBANK","UNIONBANK"]

            # Nifty
            nf = yf.download("^NSEI", period="2mo", interval="1d", progress=False)
            nifty_result = predict_next(nf, "NIFTY") if not nf.empty else None

            # Bank Nifty
            bf = yf.download("^NSEBANK", period="2mo", interval="1d", progress=False)
            bnifty_result = predict_next(bf, "BANKNIFTY") if not bf.empty else None

            # Individual bank stocks
            buys, sells = [], []
            for sym in banks:
                try:
                    df = yf.download(f"{sym}.NS", period="2mo", interval="1d", progress=False)
                    if not df.empty:
                        r = predict_next(df, sym)
                        if r["direction"] == "BUY": buys.append(r)
                        elif r["direction"] == "SELL": sells.append(r)
                except Exception:
                    continue
            buys.sort(key=lambda x: -x["score"])
            sells.sort(key=lambda x: -x["score"])

            self.data["candlestick"] = {
                "nifty": nifty_result,
                "banknifty": bnifty_result,
                "top_buys": buys[:5],
                "top_sells": sells[:3],
                "total_buy_signals": len(buys),
                "total_sell_signals": len(sells),
            }
            print(f"  NIFTY: {nifty_result['direction'] if nifty_result else 'N/A'} | "
                  f"BANKNIFTY: {bnifty_result['direction'] if bnifty_result else 'N/A'} | "
                  f"Stocks: {len(buys)} BUY / {len(sells)} SELL")
        except Exception as e:
            print(f"  GPU error: {e}")

    def _gather_option_chain_oi(self):
        print("[5/8] Option chain & OI...")
        try:
            from agents.trading_expert import TradingExpert
            te = TradingExpert()
            nifty = self.data.get("nifty") or 23500

            expiry, calls, puts = te.get_option_chain_data("^NSEI")
            oi = te.analyze_oi(calls, puts, nifty)
            expiry_date = datetime.strptime(expiry, "%Y-%m-%d") if expiry else datetime.now() + timedelta(days=7)
            greeks = te.compute_iv_and_greeks(calls, puts, nifty, expiry_date)

            self.data["option_chain"] = {
                "expiry": expiry,
                "oi_analysis": oi,
                "greeks": greeks,
                "nifty_atm": oi.get("atm"),
                "resistance": oi.get("resistance"),
                "support": oi.get("support"),
                "pcr": oi.get("pcr"),
            }
            print(f"  Expiry: {expiry} | PCR: {oi.get('pcr', 'N/A')} | "
                  f"Max Call OI: {oi.get('max_call_oi_strike', 'N/A')} | "
                  f"Max Put OI: {oi.get('max_put_oi_strike', 'N/A')}")
        except Exception as e:
            print(f"  OI error: {e}")

    def _gather_technical_indicators(self):
        print("[6/8] Technical indicators...")
        try:
            from core.gpu_signals import batch_rsi, batch_macd, generate_signals
            from core.technical_indicators import support_resistance, atr, bollinger_bands

            nf = yf.download("^NSEI", period="1mo", interval="1d", progress=False)
            bf = yf.download("^NSEBANK", period="1mo", interval="1d", progress=False)

            def compute(df, name):
                if df.empty: return {}
                close = df["Close"].values.ravel()
                close_s = df["Close"].squeeze()
                rsi_vals = batch_rsi(close, 14)
                macd_l, sig_l, hist = batch_macd(close, 12, 26, 9)
                sr = support_resistance(close_s)
                atr_val = atr(df)
                upper, mid, lower = bollinger_bands(close_s)
                return {
                    "name": name,
                    "price": float(close[-1]),
                    "rsi": float(rsi_vals[-1]),
                    "rsi_trend": "rising" if rsi_vals[-1] > rsi_vals[-3] else "falling" if rsi_vals[-1] < rsi_vals[-3] else "flat",
                    "macd_histogram": float(hist[-1]),
                    "macd_crossover": "bullish" if hist[-1] > 0 and hist[-2] <= 0 else ("bearish" if hist[-1] < 0 and hist[-2] >= 0 else "no_cross"),
                    "support": sr.get("support"),
                    "resistance": sr.get("resistance"),
                    "atr": float(atr_val.iloc[-1]) if not atr_val.empty else None,
                    "bb_upper": float(upper.iloc[-1]),
                    "bb_lower": float(lower.iloc[-1]),
                }

            nifty_tech = compute(nf, "NIFTY")
            bnifty_tech = compute(bf, "BANKNIFTY")
            self.data["technicals"] = {"nifty": nifty_tech, "banknifty": bnifty_tech}
            print(f"  NIFTY RSI: {nifty_tech.get('rsi', 'N/A')} | MACD: {nifty_tech.get('macd_crossover', 'N/A')}")
        except Exception as e:
            print(f"  Technicals error: {e}")

    def _gather_trading_expert(self):
        print("[7/8] Trading expert suggestions...")
        try:
            from agents.trading_expert import TradingExpert
            te = TradingExpert()
            ns = self.data.get("news", {}).get("summary", {})
            nifty = self.data.get("nifty")
            bnifty = self.data.get("banknifty")
            params = self.data["user_params"]

            result = te.suggest(
                capital=params["capital"],
                nifty=nifty,
                banknifty=bnifty,
                news_summary=ns,
                risk_tolerance=params["risk_tolerance"],
                preferred_index=params["preferred_index"],
            )
            self.data["trading_expert"] = result
            s = result["suggestions"][0] if result["suggestions"] else {}
            print(f"  {s.get('index','')} {s.get('strike','')}{s.get('type','')} | "
                  f"Entry: {s.get('entry_premium')} | SL: {s.get('stop_loss')} | "
                  f"Target: {s.get('target')} | Confidence: {s.get('confidence')}")
        except Exception as e:
            print(f"  Trading expert error: {e}")

    def _gather_risk_assessment(self):
        print("[8/8] Risk assessment & lessons...")
        from agents.risk_manager import RiskManager
        risk = RiskManager()

        suggestions = self.data.get("trading_expert", {}).get("suggestions", [])
        capital = self.data["user_params"]["capital"]

        if suggestions:
            s = suggestions[0]
            trade = {
                "type": "option_buy",
                "instrument": s.get("index", "NIFTY"),
                "strategy": f"long_{s.get('type', 'CE').lower()}",
                "action": "BUY",
                "entry": {"strike": s.get("strike"), "premium": s.get("entry_premium"),
                          "spot": self.data.get("nifty")},
                "stop_loss": s.get("stop_loss"),
                "confidence": s.get("confidence", "medium").lower(),
            }
            assessment = risk.assess_trade_risk(trade, capital)
            self.data["risk"] = {k: v for k, v in assessment.items() if k != "trade"}
        else:
            self.data["risk"] = {"risk_level": "unknown", "warnings": ["No trade to assess"]}

        print(f"  Risk level: {self.data['risk'].get('risk_level', 'N/A')}")

    def _gather_lessons(self):
        try:
            from agents.learning_agent import LearningAgent
            la = LearningAgent()
            lessons = la.get_lessons()
            stats = la.get_statistics(days=30)
            self.data["learning"] = {
                "past_30d_stats": stats,
                "recent_lessons": lessons["recorded_lessons"][:5],
                "failure_patterns": lessons.get("recent_failure_patterns", {}),
            }
        except Exception:
            self.data["learning"] = {"past_30d_stats": {"total": 0, "message": "Learning DB not yet populated"}}

    def _print_summary(self):
        print(f"\n{'='*60}")
        print(f"  Data gathered. Ready for AI analysis.")
        print(f"{'='*60}")

    def to_json(self, indent=2):
        class CustomEncoder(json.JSONEncoder):
            def default(self, obj):
                try:
                    if isinstance(obj, (np.integer,)): return int(obj)
                    if isinstance(obj, (np.floating,)): return float(obj)
                    if isinstance(obj, (np.ndarray,)): return obj.tolist()
                    return str(obj)
                except: return str(obj)
        return json.dumps(self.data, indent=indent, cls=CustomEncoder, default=str)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--capital", type=int, default=50000)
    parser.add_argument("--risk", choices=["conservative","moderate","aggressive"], default="moderate")
    parser.add_argument("--index", choices=["NIFTY","BANKNIFTY","auto"], default="NIFTY")
    parser.add_argument("--webhook", default=os.environ.get("DISCORD_WEBHOOK", ""))
    args = parser.parse_args()

    tm = TraderManager()
    data = tm.gather_all(args.capital, args.risk, args.index)
    print(tm.to_json())

    if args.webhook:
        import requests
        summary = data.get("trading_expert", {}).get("suggestions", [{}])[0]
        embed = {
            "title": "📊 TraderManager — Complete Market Data",
            "color": 0x5865F2,
            "description": (
                f"**NIFTY:** {data.get('nifty', 'N/A'):.0f} | **BANKNIFTY:** {data.get('banknifty', 'N/A'):.0f}\n"
                f"**News:** {data.get('news',{}).get('summary',{}).get('market_outlook','N/A')}\n"
                f"**VWAP:** {data.get('vwap',{}).get('nifty',{}).get('diff_pct','N/A')}%\n"
                f"**GPU:** {data.get('candlestick',{}).get('nifty',{}).get('direction','N/A')}\n"
                f"**PCR:** {data.get('option_chain',{}).get('pcr','N/A')}\n"
                f"**Trade:** {summary.get('strike','')}{summary.get('type','')} "
                f"@ ₹{summary.get('entry_premium','')} "
                f"SL ₹{summary.get('stop_loss','')} "
                f"TGT ₹{summary.get('target','')}\n"
                f"**Risk:** {data.get('risk',{}).get('risk_level','N/A')}"
            ),
            "footer": {"text": f"TraderManager • {data.get('timestamp')}"}
        }
        requests.post(args.webhook, json={"embeds": [embed]}, timeout=10)
        print("[✓] Sent to Discord")
