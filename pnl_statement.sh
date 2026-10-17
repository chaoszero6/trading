#!/bin/bash
DIR="$(cd "$(dirname "$0")" && pwd)"
source "$DIR/.env"
export DISCORD_WEBHOOK
python3 << 'PYEOF'
import sqlite3, os, requests
from datetime import datetime, timezone, timedelta

IST = timezone(timedelta(hours=5, minutes=30))
today = datetime.now(IST).strftime('%Y-%m-%d')
db = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "papertrades.db")
db = os.path.join(os.environ.get('DIR', '/root/trading'), 'data', 'papertrades.db')

try:
    conn = sqlite3.connect(db)
    conn.execute("ALTER TABLE trades ADD COLUMN exit_timestamp TEXT")
except Exception:
    pass
try:
    rows = conn.execute('''
        SELECT id, timestamp, index_name, strike, option_type,
               entry_ltp, exit_ltp, exit_reason, pnl, exit_timestamp
        FROM trades WHERE date(timestamp) = ? ORDER BY id
    ''', (today,)).fetchall()
    conn.close()
except Exception as e:
    print(f'DB error: {e}')
    exit(1)

cols = ['id','ts','idx','strike','type','entry','exit_ltp','reason','pnl','exit_ts']
by_trade = {}
for r in rows:
    d = dict(zip(cols, r))
    key = (d['ts'], d['strike'], d['type'])
    if key not in by_trade:
        by_trade[key] = {}
    if d['exit_ltp'] is not None:
        by_trade[key]['exit'] = d
    else:
        by_trade[key]['entry'] = d

closed, opened = [], []
for k, v in by_trade.items():
    if 'exit' in v:
        closed.append(v['exit'])
    else:
        opened.append(v['entry'])

total_pnl = sum(d['pnl'] for d in closed)
wins = sum(1 for d in closed if d['pnl'] > 0)
losses = sum(1 for d in closed if d['pnl'] < 0)

lines = [f'**📊 P&L Statement — {datetime.now(IST).strftime("%d %b %Y (%a)")}**']
lines.append(f'Closed: {len(closed)} | {"🟢" if total_pnl>=0 else "🔴"} **₹{total_pnl:+,.0f}** ({wins}W/{losses}L)')
if closed:
    lines.append('')
    for d in sorted(closed, key=lambda x: x['ts']):
        bt = d['ts'][11:16]
        st = d['exit_ts'][11:16] if d.get('exit_ts') else bt
        em = '✅' if d['pnl'] > 0 else '❌'
        lines.append(f'{em} {d["idx"]} {d["strike"]}{d["type"]} B {bt} @ ₹{d["entry"]:.0f} | S {st} @ ₹{d["exit_ltp"]:.0f} ({d["reason"]}) P&L ₹{d["pnl"]:+,.0f}')
if opened:
    lines.append('')
    for d in opened:
        bt = d['ts'][11:16]
        lines.append(f'⏳ {d["idx"]} {d["strike"]}{d["type"]} B {bt} @ ₹{d["entry"]:.0f} (OPEN)')

wh = os.environ.get('DISCORD_WEBHOOK', '')
if wh:
    r = requests.post(wh, json={'content': '\n'.join(lines)[:1900]}, timeout=10)
    print('Sent' if r.status_code == 204 else f'FAIL {r.status_code}')
else:
    print('\n'.join(lines))
PYEOF