#!/usr/bin/env python3
"""
TRADING MULTI-AGENT SYSTEM
==========================
Agents:
  1. MarketNewsAgent   - Worldwide news → Indian market impact
  2. TraderAgent       - Options/futures strategist, defines algo requirements
  3. RiskManager       - Risk assessment & position sizing
  4. PythonExpert      - Generates Angel One SmartAPI algo trading bot

Usage:
  python main.py                           # Full pipeline
  python main.py --capital 1000000          # Set capital to ₹10L
  python main.py --no-bot                   # Skip bot generation
  python main.py --realtime                 # Live monitoring after analysis
  python main.py --help                     # All options
"""

from orchestrator import TradingOrchestrator
import sys


def print_usage():
    print(__doc__)


if __name__ == "__main__":
    if "--help" in sys.argv or "-h" in sys.argv:
        print_usage()
        sys.exit(0)

    import argparse
    parser = argparse.ArgumentParser(
        description="Trading Multi-Agent System",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python main.py
  python main.py --capital 1000000
  python main.py --realtime
  python main.py --no-bot
        """)
    parser.add_argument("--capital", type=int, default=500000)
    parser.add_argument("--no-bot", action="store_true")
    parser.add_argument("--realtime", action="store_true")
    args = parser.parse_args()

    orch = TradingOrchestrator()
    orch.run_pipeline(capital=args.capital, generate_bot=not args.no_bot)

    if args.realtime:
        print("\n[REALTIME] Starting live monitoring...")
        print("(Requires Angel One API credentials)\n")
        from core.angel_bridge import get_angel_bridge
        bridge = get_angel_bridge()
        if bridge.authenticate():
            print("Monitoring NIFTY 50... (Ctrl+C to stop)")
            try:
                while True:
                    ltp = bridge.get_nifty_ltp()
                    if ltp:
                        from datetime import datetime
                        print(f"  [{datetime.now().strftime('%H:%M:%S')}] "
                              f"NIFTY: {ltp:.2f}")
                    import time
                    time.sleep(30)
            except KeyboardInterrupt:
                print("\n[REALTIME] Stopped.")
        else:
            print("[!] Cannot authenticate with Angel One. Check your .env credentials.")
