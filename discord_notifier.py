"""
Discord Webhook Notifier
Sends formatted market analysis & trade suggestions to a Discord channel.
Tracks predictions and reports accuracy on subsequent runs.
End-of-day accuracy report with GPU-accelerated batch analysis.
"""

import os
import json
import requests
from datetime import datetime, date
from pathlib import Path

HISTORY_FILE = Path(__file__).parent / "predictions_history.json"


def load_history():
    if HISTORY_FILE.exists():
        try:
            return json.loads(HISTORY_FILE.read_text())
        except Exception:
            return {"runs": []}
    return {"runs": []}


def save_run(entry):
    history = load_history()
    history.setdefault("runs", []).append(entry)
    if len(history["runs"]) > 100:
        history["runs"] = history["runs"][-100:]
    HISTORY_FILE.write_text(json.dumps(history, indent=2))


def check_predictions(current_nifty, current_bnifty):
    import sqlite3
    db_path = Path(__file__).parent / "data" / "learning.db"
    if not db_path.exists():
        return None, None
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    today = date.today().isoformat()
    cur.execute("""
        SELECT id, timestamp, index_name, strike, option_type, entry_premium,
               stop_loss, target, actual_pnl, exit_reason
        FROM suggestions WHERE timestamp LIKE ? ORDER BY id
    """, (f"{today}%",))
    rows = cur.fetchall()
    conn.close()
    if not rows:
        return None, None

    lines = []
    for r in rows:
        sid, ts, idx, strike, optype, entry, sl, tgt, pnl, reason = r
        sym = "✅" if pnl and pnl > 0 else "❌" if pnl and pnl < 0 else "⏳"
        status = reason or "MONITORING"
        strike_s = str(strike).replace(".0","").replace("0.0","")
        lines.append(f"{sym} #{sid} {idx} {strike_s}{optype}: {status}")
        if pnl is not None:
            lines.append(f"   P&L: ₹{pnl:+,.0f}")

    return "📊 **Today's Trades**", "\n".join(lines)


def eod_accuracy_report():
    """End-of-day report with real P&L from Angel One WebSocket LTP + next-day prediction."""
    import sys, sqlite3, json
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from core.market_data import get_market_summary
    from core.angel_bridge import AngelOneBridge

    db_path = Path(__file__).parent / "data" / "learning.db"
    if not db_path.exists():
        return None, "No learning database found"

    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    today = date.today().isoformat()
    cur.execute("""SELECT id, timestamp, index_name, strike, option_type,
        entry_premium, stop_loss, target, actual_pnl, exit_reason, exit_price,
        lessons_learned FROM suggestions WHERE timestamp LIKE ? ORDER BY id""",
        (f"{today}%",))
    rows = cur.fetchall()
    conn.close()

    ms = get_market_summary()
    close_nifty = ms.get("indian_indices", {}).get("NIFTY 50", {}).get("price", 0)
    close_bnifty = ms.get("indian_indices", {}).get("BANK NIFTY", {}).get("price", 0)

    # Daily prediction for next session
    next_day_pred = ""
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from agents.prediction_agent import predict_daily_live, print_daily_predictions
        pred_results = predict_daily_live()
        pred_text = print_daily_predictions(pred_results)
        if pred_text:
            next_day_pred = f"\n🔮 **Next Session Prediction:**\n{pred_text}\n"
    except Exception as e:
        next_day_pred = f"\n⚠️ Next-day prediction unavailable: {str(e)[:50]}\n"

    lines = []
    lines.append(f"📊 **EOD Report — {today}**")
    lines.append(f"📈 NIFTY: {close_nifty:.0f} | BANKNIFTY: {close_bnifty:.0f}")

    if rows:
        wins = sum(1 for r in rows if r[8] and r[8] > 0)
        losses = sum(1 for r in rows if r[8] and r[8] < 0)
        total_pnl = sum(r[8] for r in rows if r[8])

        lines.append("")
        for r in rows:
            sid, ts, idx, strike, optype, entry, sl, tgt, pnl, reason, exit_price, lessons = r
            sym = "✅" if pnl and pnl > 0 else "❌"
            strike_str = str(strike).replace("0.0","").replace(".0","") if strike else "?"
            lines.append(f"{sym} #{sid} {idx} {strike_str}{optype}")
            if pnl is not None:
                lines.append(f"   Entry ₹{entry:.0f} → Exit ₹{exit_price:.0f} | P&L ₹{pnl:+,.0f}")
            else:
                lines.append(f"   Entry ₹{entry:.0f} → Pending")
            if lessons:
                lines.append(f"   ⚠️ {lessons[:80]}")

        lines.append("")
        lines.append(f"🏆 **{wins}W / {losses}L** | P&L: ₹{total_pnl:+,.0f} | Win%: {wins/len(rows)*100:.0f}%")
    else:
        lines.append("\n📭 No trades today.")

    if next_day_pred:
        lines.append(next_day_pred)

    prediction_text = "\n".join(lines)
    return prediction_text, ""


def send_discord_message(webhook_url, content, embeds=None):
    payload = {"content": content}
    if embeds:
        payload["embeds"] = embeds if isinstance(embeds, list) else [embeds]
    try:
        resp = requests.post(webhook_url, json=payload, timeout=10)
        resp.raise_for_status()
        return True
    except Exception as e:
        print(f"[!] Discord send failed: {e}")
        return False


def build_full_embed(news_summary, market_summary, trade_suggestions,
                     prediction_text=None):
    outlook = news_summary.get("market_outlook", "N/A")
    sentiment = news_summary.get("overall_sentiment", "neutral").upper()
    nifty_data = market_summary.get("indian_indices", {}).get("NIFTY 50", {})
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    color = 0x00ff88 if outlook == "BULLISH" else 0xff4444 if outlook == "BEARISH" else 0xffaa00
    embed = {
        "title": f"📊 Market Status — {outlook}",
        "color": color,
        "fields": [],
        "footer": {"text": f"Multi-Agent System • {timestamp}"},
    }

    desc_lines = []
    for name, data in market_summary.get("indian_indices", {}).items():
        p = data.get("price", "N/A")
        desc_lines.append(f"**{name}**: {p}")
    for name, data in market_summary.get("global_indices", {}).items():
        chg = data.get("change_pct", 0)
        arrow = "📈" if chg and chg > 0 else "📉" if chg and chg < 0 else "➡"
        desc_lines.append(f"{arrow} **{name}**: {data.get('price', 'N/A')} ({chg:+.2f}%)")
    embed["description"] = "\n".join(desc_lines) if desc_lines else "No data"

    bullish = news_summary.get("bullish_sectors", [])
    bearish = news_summary.get("bearish_sectors", [])
    embed["fields"].append({
        "name": "📰 Sentiment",
        "value": f"**Overall**: {sentiment}\n**Outlook**: {outlook}\n"
                 f"**Bullish**: {', '.join(bullish) if bullish else 'None'}\n"
                 f"**Bearish**: {', '.join(bearish) if bearish else 'None'}",
        "inline": False,
    })

    news_stories = news_summary.get("top_stories", [])
    if news_stories:
        story_text = "\n".join(f"• {s[:85]}" for s in news_stories[:5])
        embed["fields"].append({
            "name": "📰 Headlines",
            "value": story_text,
            "inline": False,
        })

    if prediction_text:
        embed["fields"].append({
            "name": prediction_text.split("\n")[0] if "\n" in prediction_text else "📊 Tracker",
            "value": prediction_text,
            "inline": False,
        })

    for risk_lvl in ["conservative", "moderate", "aggressive"]:
        trades = trade_suggestions.get(risk_lvl, [])
        if not trades:
            continue
        lines = []
        for t in trades:
            action = t.get("action", t.get("strategy", ""))
            confidence = t.get("confidence", "N/A")
            entry = t.get("entry", "")
            lines.append(f"**{action}** (Confidence: {confidence})")
            if entry:
                lines.append(f"  Entry: {entry[:60]}")
        emoji = {"conservative": "🟢", "moderate": "🟡", "aggressive": "🔴"}
        embed["fields"].append({
            "name": f"{emoji.get(risk_lvl, '⚪')} {risk_lvl.upper()}",
            "value": "\n".join(lines),
            "inline": False,
        })

    return embed


def build_suggestion_records(trade_suggestions):
    records = []
    for risk_lvl, trades in trade_suggestions.items():
        for t in trades:
            a = t.get("action", "")
            records.append({
                "name": t.get("strategy", a),
                "direction": "bullish" if "call" in a.lower() or "ce" in a.lower() else
                             "bearish" if "put" in a.lower() or "pe" in a.lower() else "neutral",
                "entry": None,
                "stop_loss": None,
                "target": None,
                "strike": 0,
                "instrument": "NIFTY" if "NIFTY" in a.upper() else "BANKNIFTY",
            })
    return records


def run_and_notify(webhook_url, mode="regular", capital=500000):
    import sys
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

    if mode == "eod":
        print("[*] Running End-of-Day Accuracy Report...")
        pred_text, pnl_text = eod_accuracy_report()

        embed = {
            "title": "🏁 EOD Accuracy Report — GPU Powered",
            "color": 0x9B59B6,
            "fields": [],
            "footer": {"text": f"Multi-Agent System • {datetime.now().strftime('%Y-%m-%d %H:%M')}"},
        }
        if pred_text:
            lines = pred_text.split("\n")
            embed["fields"].append({
                "name": lines[0] if lines else "📊 Accuracy",
                "value": "\n".join(lines[1:]),
                "inline": False,
            })
        if pnl_text:
            embed["fields"].append({
                "name": "💰 Option P&L (GPU MC)",
                "value": pnl_text[:1024],
                "inline": False,
            })

        ok = send_discord_message(webhook_url, "@here 🏁 **Market Close — Accuracy Report**", embed)
        print(f"[{'✓' if ok else '✗'}] EOD report sent")
        return ok

    from agents.news_agent import MarketNewsAgent
    from agents.trader_agent import TraderAgent
    from agents.risk_manager import RiskManager
    from core.market_data import get_market_summary, get_nifty_realtime, get_banknifty_realtime

    print("[*] NewsAgent: Fetching & analyzing news...")
    news_agent = MarketNewsAgent()
    analyzed = news_agent.run_analysis()
    news_summary = news_agent.get_summary(analyzed)

    print("[*] MarketData: Snapshot...")
    market_summary = get_market_summary()

    nifty = get_nifty_realtime()
    bnifty = get_banknifty_realtime()
    if nifty is None:
        nifty = market_summary.get("indian_indices", {}).get("NIFTY 50", {}).get("price")
    if bnifty is None:
        bnifty = market_summary.get("indian_indices", {}).get("BANK NIFTY", {}).get("price")

    print("[*] TraderAgent: Generating strategies...")
    trader = TraderAgent()
    trade_output = trader.run(news_summary, market_summary)

    pred_title, pred_text = None, None
    if nifty and bnifty:
        pred_title, pred_text = check_predictions(nifty, bnifty)

    embed = build_full_embed(news_summary, market_summary,
                              trade_output["trade_suggestions"],
                              prediction_text=pred_text)

    content = "@here 📢 **Market Update**"
    ok = send_discord_message(webhook_url, content, embed)
    print(f"[{'✓' if ok else '✗'}] Discord notification sent")

    records = build_suggestion_records(trade_output["trade_suggestions"])
    save_run({
        "time": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "nifty": nifty,
        "banknifty": bnifty,
        "outlook": news_summary.get("market_outlook", ""),
        "sentiment": news_summary.get("overall_sentiment", ""),
        "suggestions": records,
    })

    return ok


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--webhook", default=os.environ.get("DISCORD_WEBHOOK", ""))
    parser.add_argument("--mode", default="regular", choices=["regular", "eod"])
    parser.add_argument("--capital", type=int, default=500000)
    args = parser.parse_args()

    if not args.webhook:
        print("[!] Pass --webhook or set DISCORD_WEBHOOK env var")
        sys.exit(1)

    run_and_notify(args.webhook, args.mode, args.capital)
