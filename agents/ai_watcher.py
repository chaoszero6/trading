"""
AI Watcher — companion to realtime_monitor.
Periodically analyzes market state from monitor data and pushes
trend analysis + health checks to Discord every 5 min.
"""
import sys, os, json, time, sqlite3, subprocess, re
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

dotenv_path = Path(__file__).parent.parent / ".env"
if dotenv_path.exists():
    with open(dotenv_path) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())

DISCORD_WEBHOOK = os.environ.get("DISCORD_WEBHOOK", "")
LOG_DIR = Path(__file__).parent.parent / "logs"
MONITOR_LOG = LOG_DIR / "realtime_monitor.log"
DB_PATH = Path(__file__).parent.parent / "data" / "papertrades.db"

def tail_log(lines=15):
    if not MONITOR_LOG.exists():
        return "(no log)"
    content = MONITOR_LOG.read_text().strip().split("\n")
    return "\n".join(content[-lines:])

def check_monitor_alive():
    r = subprocess.run(["screen", "-ls"], capture_output=True, text=True, timeout=5)
    return "trading_" in r.stdout

def get_latest_trade():
    if not DB_PATH.exists():
        return None
    try:
        import sqlite3
        with sqlite3.connect(DB_PATH) as conn:
            row = conn.execute(
                "SELECT * FROM trades ORDER BY id DESC LIMIT 1"
            ).fetchone()
            if row:
                cols = [d[1] for d in conn.execute("PRAGMA table_info(trades)").fetchall()]
                return dict(zip(cols, row))
    except Exception:
        pass
    return None

def analyze_trend(log_text):
    lines = log_text.split("\n")
    trends = {"nifty": None, "banknifty": None, "gpu": {}, "signals": []}
    for line in lines:
        m = re.search(r"NIFTY=([\d.]+).*?BANKNIFTY=([\d.]+)", line)
        if m:
            trends["nifty"] = m.group(1)
            trends["banknifty"] = m.group(2)
        m = re.search(r"GPU.*Sentiment.*?(N_RSI=.*)", line)
        if m:
            trends["gpu"]["line"] = m.group(1)
        m = re.search(r"(TREND_CONFLUENCE|SPOT_MOMENTUM|GPU_PATTERN|GPU_MACD):\s*(BUY_CE|BUY_PE)\s*\((\w+)\)", line)
        if m:
            trends["signals"].append(f"{m.group(1)}: {m.group(2)} ({m.group(3)})")
    return trends

def send_discord(msg):
    if not DISCORD_WEBHOOK:
        return
    import requests
    try:
        resp = requests.post(DISCORD_WEBHOOK, json={"content": str(msg)[:1900]}, timeout=10)
        return resp.status_code == 204
    except Exception:
        return False

def build_report(trends, alive, trade):
    now = datetime.now().strftime("%H:%M:%S")
    lines = [f"**🤖 AI Watcher — {now}**"]
    lines.append(f"Monitor: {'✅ Alive' if alive else '❌ DEAD'}")
    if trends["nifty"]:
        lines.append(f"Spots: NIFTY {trends['nifty']} | BANKNIFTY {trends['banknifty']}")
    if trends["signals"]:
        lines.append(f"Signals ({len(trends['signals'])}):")
        for s in trends["signals"][-3:]:
            lines.append(f"  • {s}")
    else:
        lines.append("Signals: none")
    if trends["gpu"].get("line"):
        lines.append(f"GPU: {trends['gpu']['line']}")
    if trade and trade.get("exit_reason") is None:
        lines.append(f"Open: {trade['strike']}{trade['option_type']} @ ₹{trade['entry_ltp']:.0f} "
                     f"SL=₹{trade.get('sl',0):.0f}")
    if trade and trade.get("exit_reason"):
        pnl = trade.get("pnl", 0)
        emoji = "✅" if pnl and pnl > 0 else "❌"
        lines.append(f"Last exit: {emoji} {trade['strike']}{trade['option_type']} "
                     f"P&L ₹{float(pnl or 0):+,.0f} ({trade.get('exit_reason','?')})")
    return "\n".join(lines)

if __name__ == "__main__":
    print(f"[WATCHER] AI Watcher started at {datetime.now().isoformat()}")
    cycle = 0
    while True:
        now = datetime.now()
        if now.hour >= 15 and now.minute > 30:
            print(f"[WATCHER] Market closed ({now.hour}:{now.minute:02d}) — exiting")
            sys.exit(0)
        try:
            cycle += 1
            log_text = tail_log(20)
            trends = analyze_trend(log_text)
            alive = check_monitor_alive()
            trade = get_latest_trade()
            report = build_report(trends, alive, trade)
            if cycle > 1:
                send_discord(report)
            print(f"[WATCHER] Cycle {cycle}: analysis sent", flush=True)
        except Exception as e:
            print(f"[WATCHER] Error: {e}", flush=True)
        if not check_monitor_alive():
            print("[WATCHER] Monitor DEAD — will alert on next cycle", flush=True)
        time.sleep(300)
