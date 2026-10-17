import sqlite3
import os
import requests
from datetime import datetime, timezone, timedelta

DISCORD_WEBHOOK = os.getenv("DISCORD_WEBHOOK", "")
DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "papertrades.db")
IST = timezone(timedelta(hours=5, minutes=30))

LOT_SIZES = {"NIFTY": 65, "BANKNIFTY": 30}


def get_today_summary():
    today = datetime.now(IST).strftime("%Y-%m-%d")
    try:
        conn = sqlite3.connect(DB_PATH)
        rows = conn.execute(
            "SELECT * FROM trades WHERE date(timestamp) = ? ORDER BY id", (today,)
        ).fetchall()
        conn.close()
    except Exception:
        return None, "No DB found."

    if not rows:
        return None, "No trades today."

    cols = ["id","timestamp","index_name","strike","option_type","entry_ltp","entry_spot",
            "sl","target","exit_ltp","exit_spot","exit_reason","pnl","held_minutes",
            "entry_signal","rsi","vwap_diff","expiry"]

    groups = {}
    for r in rows:
        d = dict(zip(cols, r))
        key = (d["timestamp"], d["strike"], d["option_type"])
        if key not in groups:
            groups[key] = {"open": None, "closed": None}
        if d["exit_ltp"] is not None and d["exit_reason"] is not None:
            groups[key]["closed"] = d
        elif d["exit_ltp"] is None:
            groups[key]["open"] = d

    closed = []
    open_positions = []
    for key, g in groups.items():
        if g["closed"] is not None:
            closed.append(g["closed"])
        elif g["open"] is not None:
            open_positions.append(g["open"])

    total_pnl = sum(d["pnl"] for d in closed if d["pnl"] is not None)
    wins = sum(1 for d in closed if d["pnl"] is not None and d["pnl"] > 0)
    losses = sum(1 for d in closed if d["pnl"] is not None and d["pnl"] < 0)

    return {
        "closed": closed,
        "open": open_positions,
        "total_pnl": total_pnl,
        "wins": wins,
        "losses": losses,
    }, None


def format_message(data, spot_nifty=None, spot_bn=None):
    now = datetime.now(IST)
    time_str = now.strftime("%H:%M")
    date_str = now.strftime("%d %b %Y (%a)")

    lines = [f"📊 **Hourly P&L Report — {date_str}**\n"]

    if spot_nifty:
        lines.append(f"NIFTY: {spot_nifty:.0f} | BANKNIFTY: {spot_bn:.0f}" if spot_bn else f"NIFTY: {spot_nifty:.0f}")
        lines.append("")

    pnl = data["total_pnl"]
    emoji = "🟢" if pnl > 0 else "🔴" if pnl < 0 else "⚪"
    lines.append(f"{emoji} **P&L: ₹{pnl:+,.0f}** ({data['wins']}W/{data['losses']}L)")

    if data["closed"]:
        lines.append("")
        lines.append("**Closed Trades:**")
        for d in data["closed"]:
            p = d["pnl"] or 0
            sym = "✅" if p > 0 else "❌"
            entry_t = d["timestamp"][11:16] if d["timestamp"] else "?"
            lines.append(f"{sym} {entry_t} {d['strike']}{d['option_type']} ₹{d['entry_ltp']:.0f}→₹{d['exit_ltp']:.0f} ({d['exit_reason']}) P&L ₹{p:+,.0f}")

    if data["open"]:
        lines.append("")
        lines.append("**Open Positions:**")
        for d in data["open"]:
            lines.append(f"⏳ {d['strike']}{d['option_type']} @ ₹{d['entry_ltp']:.0f}")

    lines.append("")
    lines.append(f"_{time_str} IST_")

    return "\n".join(lines)


def get_spot():
    try:
        from agents.paper_trader import PaperTrader
        pt = PaperTrader()
        n = pt.get_spot("NIFTY")
        b = pt.get_spot("BANKNIFTY")
        return n, b
    except:
        return None, None


def send_discord(message):
    if not DISCORD_WEBHOOK:
        return False
    try:
        r = requests.post(DISCORD_WEBHOOK, json={"content": message[:1900]}, timeout=10)
        return r.status_code == 204
    except:
        return False


def main():
    data, err = get_today_summary()
    if err:
        msg = f"📊 **Hourly P&L Report**\n\n{err}\n\n_{datetime.now(IST).strftime('%H:%M')} IST_"
    else:
        spot_nifty, spot_bn = get_spot()
        msg = format_message(data, spot_nifty, spot_bn)

    ok = send_discord(msg)
    if ok:
        print(f"[HR] Sent hourly report ({len(data.get('closed',[]))} closed, {len(data.get('open',[]))} open)")
    else:
        print(f"[HR] Failed to send")


if __name__ == "__main__":
    main()
