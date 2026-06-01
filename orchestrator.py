"""
TRADING MULTI-AGENT SYSTEM ORCHESTRATOR
Coordinates: MarketNewsAgent -> TraderAgent -> RiskManager -> PythonExpert
"""

import os
import sys
import logging
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from agents.news_agent import MarketNewsAgent
from agents.trader_agent import TraderAgent
from agents.risk_manager import RiskManager
from agents.python_expert import PythonExpert
from core.market_data import get_market_summary, get_nifty_realtime

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


class TradingOrchestrator:
    def __init__(self):
        self.agents = {
            "news": MarketNewsAgent(),
            "trader": TraderAgent(),
            "risk": RiskManager(),
            "dev": PythonExpert(),
        }
        self.workflow = []

    def show_header(self):
        print("\n" + "█" * 60)
        print("  TRADING MULTI-AGENT SYSTEM")
        print("  Coordinated Agents for Indian Markets Analysis & Execution")
        print("█" * 60)

    def run_pipeline(self, capital=500000, generate_bot=True):
        self.show_header()

        # Step 1: News Analysis
        print("\n" + "─" * 60)
        print("  STEP 1/4: MARKET NEWS ANALYSIS")
        print("  Agent: MarketNewsAgent")
        print("─" * 60)
        analyzed_news = self.agents["news"].run_analysis()
        news_summary = self.agents["news"].get_summary(analyzed_news)
        self.workflow.append(("news_analysis", news_summary))

        # Step 2: Market Data Snapshot
        print("\n" + "─" * 60)
        print("  STEP 2/4: MARKET DATA SNAPSHOT")
        print("─" * 60)
        market_summary = get_market_summary()
        nifty_price = get_nifty_realtime()
        print(f"\n  [MARKET DATA]")
        if nifty_price:
            print(f"    NIFTY 50 Live : {nifty_price:.2f}")
        for name, data in market_summary.get("indian_indices", {}).items():
            print(f"    {name:<15} : {data.get('price', 'N/A')}")
        for name, data in market_summary.get("global_indices", {}).items():
            chg = data.get("change_pct", 0)
            arrow = "↑" if chg > 0 else "↓" if chg < 0 else "→"
            print(f"    {name:<15} : {data.get('price', 'N/A'):>10}  "
                  f"{arrow} {chg:+.2f}%")
        print()
        self.workflow.append(("market_data", market_summary))

        # Step 3: Trader Analysis & Strategy
        print("─" * 60)
        print("  STEP 3/4: TRADER STRATEGY & RISK ASSESSMENT")
        print("  Agent: TraderAgent + RiskManager")
        print("─" * 60)
        trade_output = self.agents["trader"].run(news_summary, market_summary)
        risk_assessment = self.agents["risk"].run(
            trade_output["trade_suggestions"], capital)
        self.workflow.append(("strategy", trade_output))
        self.workflow.append(("risk", risk_assessment))

        # Step 4: Generate Algo Bot
        if generate_bot:
            print("─" * 60)
            print("  STEP 4/4: ALGO BOT GENERATION")
            print("  Agent: PythonExpert")
            print("─" * 60)
            bot_file = self.agents["dev"].run(trade_output["requirements"])
            self.workflow.append(("algo_bot", bot_file))

        # Final Summary
        self._print_summary(news_summary, market_summary, trade_output,
                            risk_assessment, capital)

    def _print_summary(self, news_summary, market_summary, trade_output,
                        risk_assessment, capital):
        nifty_p = market_summary.get("indian_indices", {}).get("NIFTY 50", {}).get("price", "N/A")
        outlook = news_summary.get("market_outlook", "NEUTRAL")

        print("\n" + "█" * 60)
        print("  FINAL EXECUTIVE SUMMARY")
        print("█" * 60)
        print(f"  Market Outlook     : {outlook}")
        print(f"  NIFTY 50           : {nifty_p}")
        print(f"  Overall Sentiment  : {news_summary.get('overall_sentiment', 'neutral').upper()}")
        print(f"  Bullish Sectors    : {', '.join(news_summary.get('bullish_sectors', [])) or 'None'}")
        print(f"  Bearish Sectors    : {', '.join(news_summary.get('bearish_sectors', [])) or 'None'}")
        print(f"  Capital            : ₹{capital:,}")
        print()

        print("  RISK-WEIGHTED TRADE SUGGESTIONS")
        print(f"  {'='*50}")
        for risk_lvl, trades in trade_output.get("trade_suggestions", {}).items():
            for t in trades:
                ra = risk_assessment.get(risk_lvl, [{}])[0].get("risk_assessment", {})
                print(f"  [{risk_lvl.upper():<12}] {t['strategy']:<20}"
                      f" | Confidence: {t.get('confidence', 'N/A'):<6}"
                      f" | Risk: {ra.get('risk_level', 'N/A')}")
                print(f"  {'':16} Action: {t.get('action', 'N/A')}")
                print(f"  {'':16} Entry:  {t.get('entry', 'N/A')[:60]}")
                print(f"  {'':16} Rec Qty: {ra.get('recommended_qty', 'N/A')} lot(s)"
                      f" | Max Loss: ₹{ra.get('max_loss', 0):,.0f}")
                if ra.get("warnings"):
                    for w in ra["warnings"]:
                        print(f"  {'':16} ⚠ {w}")
                print()
        print("=" * 60)
        print("  Next Step: Configure Angel One API credentials in .env")
        print("  Then run: python algo_trading_bot.py")
        print("=" * 60)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Trading Multi-Agent System")
    parser.add_argument("--capital", type=int, default=500000,
                        help="Capital in INR (default: 500000)")
    parser.add_argument("--no-bot", action="store_true",
                        help="Skip algo bot generation")
    parser.add_argument("--realtime", action="store_true",
                        help="Start real-time monitoring after analysis")
    args = parser.parse_args()

    orch = TradingOrchestrator()
    orch.run_pipeline(capital=args.capital, generate_bot=not args.no_bot)
