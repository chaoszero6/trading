#!/usr/bin/env python3
"""Detail the 20 TIME-EXIT GATE blocked candidates + RSI context."""
import re

log = open('/root/trading/logs/realtime_monitor.log').read().splitlines()

checks = []
cur = None
for i, line in enumerate(log):
    m = re.match(r'\[MON\] === Check #(\d+) @ (\d+:\d+):', line)
    if m:
        if cur:
            checks.append(cur)
        cur = {'num': int(m.group(1)), 'time': m.group(2), 'signals': [], 'gate': None, 'rsi_line': None, 'spot': None}
        continue
    if cur is None:
        continue
    if line.startswith('[MON] NIFTY='):
        mm = re.match(r'\[MON\] NIFTY=([\d.]+)', line)
        if mm:
            cur['spot'] = float(mm.group(1))
    elif line.startswith('[MON] Signals:'):
        cur['sig_count'] = int(line.split(':')[1])
    elif re.match(r'\s+(TREND_CONFLUENCE|GPU_MACD|SPOT_MOMENTUM): (BUY_CE|BUY_PE)', line):
        cur['signals'].append(line.strip())
    elif 'skipping all entries' in line and '13:00' in line:
        cur['gate'] = True
    elif line.startswith('[MON] RSI_GUARD:'):
        cur['rsi_line'] = line.replace('[MON] ', '').strip()
if cur:
    checks.append(cur)

print("=== All 20 TIME-EXIT GATE blocked would-be candidates ===")
n = 0
for c in checks:
    if not c['gate']:
        continue
    ce = sum(1 for s in c['signals'] if 'BUY_CE' in s)
    pe = sum(1 for s in c['signals'] if 'BUY_PE' in s)
    if ce >= 2 or pe >= 2:
        n += 1
        direction = 'CE' if ce >= 2 else 'PE'
        sigs = '; '.join(c['signals'])
        rsi = c['rsi_line'] or ''
        print(f"#{c['num']:>3} @ {c['time']} NIFTY={c['spot']} -> {direction} | {sigs} | {rsi}")

print(f"\nTotal: {n}")

print("\n=== RSI guard status between 12:00-13:30 (GPU sentiment) ===")
for c in checks:
    if c['time'] >= '12:00' and c['time'] <= '13:30' and c['num'] % 5 == 0:
        print(f"#{c['num']:>3} @ {c['time']} NIFTY={c['spot']} | {c['rsi_line']}")

print("\n=== 13:00-13:05 window full detail ===")
for c in checks:
    if '13:0' in c['time'][:4]:
        ce = sum(1 for s in c['signals'] if 'BUY_CE' in s)
        pe = sum(1 for s in c['signals'] if 'BUY_PE' in s)
        tag = 'CANDIDATE' if (ce >= 2 or pe >= 2) else 'no-candidate'
        print(f"#{c['num']:>3} @ {c['time']} sigs={c['sig_count'] if 'sig_count' in c else '?'} {tag} | {c['rsi_line']}")
