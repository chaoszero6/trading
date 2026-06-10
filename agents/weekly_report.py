#!/usr/bin/env python3
"""Weekly P&L report — sends to Discord webhook every Friday 5:00 PM IST."""
import sqlite3
import time
import os
import requests
from datetime import datetime, timezone, timedelta

DB_PATH = "/root/trading/data/papertrades.db"
IST = timezone(timedelta(hours=5, minutes=30))
CHECK_INTERVAL = 30
TARGET_HOUR = 17
TARGET_MIN = 0
TARGET_DAY = 4  # Monday=0, Friday=4

WEBHOOK_URL = None

def get_webhook():
    global WEBHOOK_URL
    if WEBHOOK_URL:
        return WEBHOOK_URL
    WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK", "")
    return WEBHOOK_URL

def get_weekly_pnl():
    """Get this week's P&L from trade_history (Mon-Fri)."""
    now = datetime.now(IST)
    monday = (now - timedelta(days=now.weekday())).strftime("%Y-%m-%d")
    with sqlite3.connect(DB_PATH) as conn:
        rows = conn.execute("""
            SELECT date(timestamp) as day,
                   count(*) as trades,
                   sum(CASE WHEN exit_reason='TARGET_HIT' THEN 1 ELSE 0 END) as wins,
                   sum(CASE WHEN exit_reason='STOP_LOSS' THEN 1 ELSE 0 END) as losses,
                   sum(CASE WHEN pnl IS NOT NULL THEN pnl ELSE 0 END) as pnl
            FROM trade_history
            WHERE date(timestamp) >= ?
            GROUP BY day ORDER BY day
        """, (monday,)).fetchall()
    return rows

def send_report(rows):
    total_t = sum(r[1] for r in rows)
    total_w = sum(r[2] for r in rows)
    total_l = sum(r[3] for r in rows)
    total_p = sum(r[4] for r in rows)

    lines = [f"**📊 Weekly P&L Report**"]
    for day, cnt, wins, losses, pnl in rows:
        emoji = "🟢" if pnl >= 0 else "🔴"
        lines.append(f"{emoji} **{day}** — {wins}W / {losses}L | P&L **₹{pnl:+,.0f}**")
    lines.append("")
    if total_t > 0:
        lines.append(f"**Week Total: {total_t} trades | {total_w}W / {total_l}L | P&L ₹{total_p:+,.0f} | Win%: {total_w/total_t*100:.0f}%**")
    else:
        lines.append("No completed trades this week.")

    wh = get_webhook()
    if wh:
        msg = "\n".join(lines)
        try:
            r = requests.post(wh, json={"content": msg[:1900]}, timeout=5)
            print(f"[Weekly] Sent: {r.status_code} — {datetime.now(IST).strftime('%d %b %Y %H:%M')}")
        except Exception as e:
            print(f"[Weekly] Error: {e}")
    else:
        print("[Weekly] No webhook configured")

def run_weekly():
    now = datetime.now(IST)
    print(f"[Weekly] Started at {now.strftime('%d %b %Y %H:%M:%S')}")
    last_sent_day = -1

    while True:
        now = datetime.now(IST)
        if now.weekday() == TARGET_DAY and now.hour == TARGET_HOUR and now.minute == TARGET_MIN and now.day != last_sent_day:
            rows = get_weekly_pnl()
            if rows:
                send_report(rows)
            else:
                print(f"[Weekly] No trades this week — {now.strftime('%d %b %Y')}")
            last_sent_day = now.day

        time.sleep(CHECK_INTERVAL)

if __name__ == "__main__":
    run_weekly()
