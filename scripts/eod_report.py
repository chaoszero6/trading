"""
EOD Analysis — uses Angel One WebSocket for real option LTPs.
Records accurate P&L in learning.db with root cause analysis.
"""
import sys, os, sqlite3, json, math
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from datetime import datetime
from pathlib import Path
from core.angel_bridge import AngelOneBridge

DB_PATH = Path(__file__).parent.parent / "data" / "learning.db"
ab = AngelOneBridge()
ab.authenticate()

def get_option_ltp(symbol, expiry, strike, optype):
    """Get real LTP via WebSocket."""
    try:
        return ab.get_option_ltp(symbol, expiry, strike, optype)
    except Exception as e:
        return None

def build_tradingsymbol(index_name, strike, optype):
    """Build Angel One trading symbol from suggestion data."""
    from config import get_next_next_weekly_expiry
    if "BANKNIFTY" in index_name.upper():
        return "BANKNIFTY", get_next_next_weekly_expiry("BANKNIFTY")
    else:
        return "NIFTY", get_next_next_weekly_expiry("NIFTY")

conn = sqlite3.connect(DB_PATH)
cur = conn.cursor()
cur.execute("SELECT * FROM suggestions WHERE outcome_recorded_at IS NULL ORDER BY id")
rows = cur.fetchall()
cols = [d[0] for d in cur.description]

now = datetime.now().isoformat()
print("=" * 70)
print("  EOD ACCURACY REPORT — Angel One WebSocket LTP")
print("=" * 70)
print()

results = []
for row in rows:
    rec = dict(zip(cols, row))
    sid = rec["id"]
    ts = rec["timestamp"]
    idx = rec["index_name"]
    strike = rec["strike"]
    optype = rec["option_type"]
    entry_p = rec["entry_premium"]
    sl = rec["stop_loss"]
    tgt = rec["target"]
    cap = rec["capital_allocated"]
    context = json.loads(rec["market_context"]) if rec["market_context"] else {}

    # Parse strike
    try:
        strike_val = int(float(str(strike).replace(",","").split(" ")[0].replace("CE","").replace("PE","")))
    except:
        strike_val = 23800
    if strike_val == 0:
        strike_val = 23800

    is_ce = "CE" in str(optype).upper() or "CALL" in str(optype).upper()
    optype_str = "CE" if is_ce else "PE"

    sym, exp = build_tradingsymbol(idx, strike_val, optype_str)

    # Get real LTP from WebSocket
    ltp = get_option_ltp(sym, exp, str(strike_val), optype_str)

    if ltp is not None:
        pnl = ltp - entry_p
        lot_size = 65 if "BANK" not in idx.upper() else 30
        total_pnl = round(pnl * lot_size, 2)
        pnl_pct = (pnl / entry_p) * 100 if entry_p else 0
        tgt_hit = ltp >= (tgt or 999999)
        sl_hit = ltp <= (sl or 0)
        exit_reason = "TARGET_HIT" if tgt_hit else ("SL_HIT" if sl_hit else "EOD_CLOSE")

        # Root cause
        causes = []
        if sl_hit:
            causes.append(f"SL triggered (LTP ₹{ltp:.0f} <= SL ₹{sl})")
        if pnl_pct < -20:
            causes.append(f"Drawdown {pnl_pct:.0f}%")
        if is_ce and pnl < 0:
            causes.append(f"Market fell against CE position")

        winner = "WIN" if pnl > 0 else "LOSS" if pnl < 0 else "DRAW"

        cur.execute("""UPDATE suggestions SET actual_pnl=?, exit_reason=?, exit_price=?,
            highest_price=?, lowest_price=?, held_duration_hours=?, lessons_learned=?, outcome_recorded_at=?
            WHERE id=?""",
            (total_pnl, exit_reason, round(ltp, 2), round(ltp, 2), round(ltp, 2),
             6.0, "; ".join(causes[:2]) if causes else None, now, sid))

        sym_str = "✅" if total_pnl >= 0 else "❌"
        print(f"  #{sid}: {sym_str} ₹{total_pnl:>+8.0f} | {sym} {strike_val}{optype_str} entry=₹{entry_p:.0f} now=₹{ltp:.0f} | {causes[0] if causes else 'OK'}")
        results.append((sid, total_pnl, winner, causes))
    else:
        # WebSocket failed, mark as unknown
        cur.execute("""UPDATE suggestions SET exit_reason=?, lessons_learned=?, outcome_recorded_at=? WHERE id=?""",
            ("LTP_UNAVAILABLE", "WebSocket LTP fetch failed", now, sid))
        print(f"  #{sid}: ⚠️  LTP unavailable (WebSocket failed)")

conn.commit()

# Summary
wins = sum(1 for _, p, w, _ in results if w == "WIN")
losses = sum(1 for _, p, w, _ in results if w == "LOSS")
total_pnl = sum(p for _, p, _, _ in results)
print()
print("-" * 70)
print(f"  ACCURACY: {wins}/{len(results)} wins")
if losses > 0:
    print(f"  LOSSES: {losses}")
    print(f"  TOTAL P&L: ₹{total_pnl:+,.0f}")
    # Record lessons for losses
    for sid, pnl, winner, causes in results:
        if winner == "LOSS":
            cur.execute("INSERT INTO lessons (suggestion_id, lesson, category, severity) VALUES (?,?,?,?)",
                       (sid, "; ".join(causes[:2]) or f"Loss of ₹{pnl:.0f}", "direction_error", "high"))
    conn.commit()
    print("  Lessons recorded ✓")
else:
    print(f"  TOTAL P&L: ₹{total_pnl:+,.0f}")
    print("  ✅ No losses today")

conn.close()
print(f"  Results saved to learning.db ✓")
