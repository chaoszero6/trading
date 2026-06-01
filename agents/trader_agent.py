import numpy as np
from datetime import datetime, timedelta
from core.market_data import get_market_summary
from core.technical_indicators import get_signal, support_resistance, atr


class TraderAgent:
    def __init__(self):
        self.name = "TraderAgent"
        self.role = ("Options & Futures Strategist | Algo Trading Requirements Specialist | "
                     "Risk-Guided Trade Suggestions")
        self.risk_profile = {
            "conservative": {"max_risk_pct": 2, "opt_strategies": ["covered_call", "cash_sec_put",
                             "credit_spread"], "leverage": 1},
            "moderate": {"max_risk_pct": 5, "opt_strategies": ["vertical_spread", "iron_condor",
                         "calendar_spread"], "leverage": 2},
            "aggressive": {"max_risk_pct": 10, "opt_strategies": ["naked_call", "naked_put",
                           "straddle", "strangle"], "leverage": 3},
        }

    def define_algo_requirements(self, news_summary, market_summary):
        print(f"\n{'='*60}")
        print(f"  AGENT: {self.name}")
        print(f"  ROLE: {self.role}")
        print(f"{'='*60}")

        print("\n[TRADER] Analyzing market conditions & defining algo trading requirements...\n")

        outlook = news_summary.get("market_outlook", "NEUTRAL")
        bullish = news_summary.get("bullish_sectors", [])
        bearish = news_summary.get("bearish_sectors", [])
        nifty_data = market_summary.get("indian_indices", {}).get("NIFTY 50", {})

        requirements = {
            "market_regime": outlook,
            "data_frequency": "5min",
            "instruments": ["NIFTY_OPTIONS", "BANKNIFTY_OPTIONS", "STOCK_FUTURES"],
            "bullish_sectors": bullish,
            "bearish_sectors": bearish,
            "nifty_level": nifty_data.get("price", "N/A"),
            "indicators_needed": ["RSI(14)", "MACD(12,26,9)", "Bollinger Bands(20,2)",
                                  "ATR(14)", "Support/Resistance", "Option Greeks",
                                  "IV Percentile", "PCR"],
            "entry_rules": [],
            "exit_rules": [],
            "risk_rules": [],
        }

        if outlook == "BULLISH":
            requirements["entry_rules"] = [
                "RSI > 40 and RSI rising",
                "MACD bullish crossover or above signal line",
                "Price above 20 EMA",
                "Bullish sector stocks showing relative strength",
            ]
            requirements["strategies_to_consider"] = [
                "BUY NIFTY CALL OPTIONS (ATM or slightly OTM)",
                "BULL CALL SPREAD (delta 0.3-0.5)",
                "LONG STOCK FUTURES in bullish sectors",
                "PUT WRITING for credit",
            ]
        elif outlook == "BEARISH":
            requirements["entry_rules"] = [
                "RSI < 60 and RSI falling",
                "MACD bearish crossover or below signal line",
                "Price below 20 EMA",
                "Bearish sector stocks showing relative weakness",
            ]
            requirements["strategies_to_consider"] = [
                "BUY NIFTY PUT OPTIONS (ATM or slightly OTM)",
                "BEAR PUT SPREAD (delta -0.3 to -0.5)",
                "SHORT STOCK FUTURES in bearish sectors",
                "CALL WRITING for credit",
            ]
        else:
            requirements["entry_rules"] = [
                "Range-bound strategy: Sell OTM Call + Sell OTM Put (Iron Butterfly)",
                "Short straddle/strangle on high IV stocks",
                "Mean reversion using Bollinger Bands",
            ]
            requirements["strategies_to_consider"] = [
                "IRON CONDOR on indices",
                "SHORT STRADDLE if IV > 30%",
                "CALENDAR SPREAD for theta decay",
                "BUTTERFLY for defined risk",
            ]

        requirements["exit_rules"] = [
            "Target profit: 15-25% for options, 5-8% for futures",
            "Stop loss: 1.5x ATR from entry for futures",
            "Options: Exit if delta changes by > 0.20",
            "Time stop: Close all positions 30 min before market close",
            "Max hold time: 3 trading days for options",
        ]

        requirements["risk_rules"] = [
            "Max 5% of capital per position",
            "Portfolio beta-weighted delta < 1000",
            "Max 3 concurrent positions in same sector",
            "Reduce position size by 50% if VIX > 25",
            "No trading in first 15 min and last 15 min",
            "Weekly max drawdown limit: 8%",
        ]

        print("[REQUIREMENTS] Algo Trading System Requirements:\n")
        print(f"  Market Regime   : {requirements['market_regime']}")
        print(f"  Nifty Level     : {requirements['nifty_level']}")
        print(f"  Bullish Sectors : {', '.join(bullish) if bullish else 'None identified'}")
        print(f"  Bearish Sectors : {', '.join(bearish) if bearish else 'None identified'}")
        print(f"\n  Suggested Strategies:")
        for s in requirements["strategies_to_consider"]:
            print(f"    > {s}")
        print(f"\n  Indicators Required: {', '.join(requirements['indicators_needed'])}")

        return requirements

    def evaluate_trade_ideas(self, news_summary, market_summary):
        print(f"\n[TRADER] Generating risk-weighted trade suggestions...\n")

        nifty = market_summary.get("indian_indices", {}).get("NIFTY 50", {})
        nifty_price = nifty.get("price", 19500)
        sentiment = news_summary.get("overall_sentiment", "neutral")
        nifty_change = nifty.get("change_pct", 0)

        suggestions = {"conservative": [], "moderate": [], "aggressive": []}

        outlook = news_summary.get("market_outlook", "NEUTRAL")
        bullish_sectors = news_summary.get("bullish_sectors", [])
        bearish_sectors = news_summary.get("bearish_sectors", [])

        atm_strike = round(nifty_price / 50) * 50

        if outlook == "BULLISH":
            suggestions["conservative"] = [
                {"type": "OPTION", "instrument": "NIFTY", "strategy": "Bull Call Spread",
                 "action": "BUY 18400 CE + SELL 18800 CE",
                 "entry": f"Net debit ~120-150 pts when Nifty at {nifty_price:.0f}",
                 "max_risk": "Limited to premium paid (~120-150 pts)",
                 "max_profit": "Capped at spread width - premium (~250-280 pts)",
                 "suitability": "Low risk, defined loss, theta positive",
                 "confidence": "HIGH" if sentiment == "positive" else "MEDIUM"},
            ]
            suggestions["moderate"] = [
                {"type": "FUTURES", "instrument": "NIFTY", "strategy": "Long Futures",
                 "action": "BUY 1 lot NIFTY Futures",
                 "entry": f"Entry at {nifty_price:.0f} or above on confirmation",
                 "stop_loss": f"{nifty_price:.0f} - 1.5*ATR",
                 "target": f"{nifty_price:.0f} + 2*ATR",
                 "suitability": "Moderate risk, direct delta exposure",
                 "confidence": "MEDIUM"},
            ]
            suggestions["aggressive"] = [
                {"type": "OPTION", "instrument": "NIFTY", "strategy": "Long Call",
                 "action": f"BUY {atm_strike} CE",
                 "entry": f"When IV < 20% and RSI > 50, premium ~100-150",
                 "max_risk": "Full premium",
                 "max_profit": "Unlimited",
                 "suitability": "High risk, use only in strong uptrend with <2% capital",
                 "confidence": "MEDIUM"},
            ]
        elif outlook == "BEARISH":
            suggestions["conservative"] = [
                {"type": "OPTION", "instrument": "NIFTY", "strategy": "Bear Put Spread",
                 "action": "BUY 19200 PE + SELL 18800 PE",
                 "entry": f"Net debit ~120-150 pts when Nifty at {nifty_price:.0f}",
                 "max_risk": "Limited to premium paid",
                 "max_profit": "Capped at spread width - premium",
                 "suitability": "Low risk hedge or directional bearish",
                 "confidence": "HIGH" if sentiment == "negative" else "MEDIUM"},
            ]
            suggestions["moderate"] = [
                {"type": "FUTURES", "instrument": "BANKNIFTY", "strategy": "Short Futures",
                 "action": "SELL 1 lot BANKNIFTY Futures",
                 "entry": "On breakdown below support",
                 "suitability": "Moderate risk, trends well in banking",
                 "confidence": "MEDIUM"},
            ]
            suggestions["aggressive"] = [
                {"type": "OPTION", "instrument": "NIFTY", "strategy": "Long Put",
                 "action": f"BUY {atm_strike} PE",
                 "entry": f"When IV < 22%, premium ~100-150",
                 "max_risk": "Full premium",
                 "suitability": "High risk, use as hedge or directional",
                 "confidence": "MEDIUM"},
            ]
        else:
            suggestions["conservative"] = [
                {"type": "OPTION", "instrument": "NIFTY", "strategy": "Iron Condor",
                 "action": "SELL OTM CE + SELL OTM PE + BUY further OTM wings",
                 "entry": f"When IV > 25%, centered around {nifty_price:.0f}",
                 "max_risk": "Limited to wing width",
                 "suitability": "Low risk range-bound strategy, theta positive",
                 "confidence": "HIGH"},
            ]
            suggestions["moderate"] = [
                {"type": "OPTION", "instrument": "NIFTY", "strategy": "Short Straddle",
                 "action": f"SELL {atm_strike} CE + SELL {atm_strike} PE",
                 "entry": "When IV > 30%, collect high premium",
                 "max_risk": "Unlimited on one side (use with stop loss)",
                 "suitability": "Moderate risk, requires active management",
                 "confidence": "MEDIUM"},
            ]
            suggestions["aggressive"] = [
                {"type": "OPTION", "instrument": "STOCK", "strategy": "Earnings Play",
                 "action": "BUY ATM Straddle before earnings in bullish/bearish sector stocks",
                 "entry": "2 days before earnings, expect IV expansion",
                 "suitability": "High risk, binary event driven",
                 "confidence": "LOW"},
            ]

        for risk_level, trades in suggestions.items():
            print(f"\n  [{risk_level.upper()} RISK TRADES]")
            print(f"  {'='*50}")
            for t in trades:
                print(f"    Strategy   : {t['strategy']}")
                print(f"    Action     : {t['action']}")
                print(f"    Entry      : {t['entry']}")
                if "stop_loss" in t:
                    print(f"    Stop Loss  : {t['stop_loss']}")
                if "target" in t:
                    print(f"    Target     : {t['target']}")
                if "max_risk" in t:
                    print(f"    Max Risk   : {t['max_risk']}")
                print(f"    Suitability: {t['suitability']}")
                print(f"    Confidence : {t['confidence']}")
                print()

        return suggestions

    def run(self, news_summary, market_summary):
        reqs = self.define_algo_requirements(news_summary, market_summary)
        trades = self.evaluate_trade_ideas(news_summary, market_summary)
        return {"requirements": reqs, "trade_suggestions": trades}
