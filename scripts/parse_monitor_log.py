#!/usr/bin/env python3
"""Parse /root/trading/logs/realtime_monitor.log for post-market analysis.

Read-only. Extracts checks, signals, gate blocks, entries, trailing-SL
activations, exits, and spot timeline. Prints summary counts + all trade
events. Expected on a normal day: 351 checks, 129 post-13:00 blocks,
20 would-be candidates, entries/trailing/target lines for each trade.

Usage: python3 scripts/parse_monitor_log.py   (run from /root/trading)
"""
import re
from collections import Counter

LOG_PATH = '/root/trading/logs/realtime_monitor.log'


def main():
    log = open(LOG_PATH).read().splitlines()

    checks = []
    cur = None
    for line in log:
        m = re.match(r'\[MON\] === Check #(\d+) @ (\d+:\d+):', line)
        if m:
            if cur:
                checks.append(cur)
            cur = {'num': int(m.group(1)), 'time': m.group(2), 'signals': []}
            continue
        if cur is None:
            continue
        if line.startswith('[MON] NIFTY='):
            mm = re.match(r'\[MON\] NIFTY=([\d.]+) BANKNIFTY=([\d.]+)', line)
            if mm:
                cur['spot'] = (float(mm.group(1)), float(mm.group(2)))
        elif line.startswith('[MON] Signals:'):
            cur['sig_count'] = int(line.split(':')[1])
        elif re.match(r'\s+(TREND_CONFLUENCE|GPU_MACD|SPOT_MOMENTUM): (BUY_CE|BUY_PE)', line):
            cur['signals'].append(line.strip())
        elif 'skipping all entries' in line:
            cur['gate'] = line.split('—')[0].replace('[MON]', '').strip()
        elif 'ENTRY:' in line:
            cur['entry'] = line.strip()
        elif 'TARGET HIT' in line or 'SL HIT' in line:
            cur['exit'] = line.strip()
        elif 'Trailing SL activated' in line:
            cur.setdefault('trailing', []).append(line.strip())
        elif 'RSI_GUARD:' in line and 'rejected' in line:
            cur.setdefault('rsi_reject', []).append(line.strip())
        elif 'DEAD' in line or 'TIME_FORCE' in line or 'EOD CLOSE' in line:
            cur.setdefault('exit2', []).append(line.strip())
    if cur:
        checks.append(cur)

    print(f"Total checks parsed: {len(checks)}")
    print(f"First: #{checks[0]['num']} @ {checks[0]['time']} | "
          f"Last: #{checks[-1]['num']} @ {checks[-1]['time']}")

    gated = [c for c in checks if 'gate' in c]
    pre930 = [c for c in gated if '9:30' in c['gate']]
    post13 = [c for c in gated if '13:00' in c['gate']]
    print(f"\nPre-9:30 blocks: {len(pre930)} | Post-13:00 blocks: {len(post13)}")
    if post13:
        print(f"First post-13:00 block: #{post13[0]['num']} @ {post13[0]['time']} "
              f"(spot NIFTY={post13[0].get('spot')})")

    def viable(c):
        ce = sum(1 for s in c['signals'] if 'BUY_CE' in s)
        pe = sum(1 for s in c['signals'] if 'BUY_PE' in s)
        return ce >= 2 or pe >= 2

    viable_blocks = [c for c in post13 if viable(c)]
    print(f"Post-13:00 checks with >=2 same-direction signals "
          f"(would-be candidates): {len(viable_blocks)}")
    dirs = Counter()
    for c in viable_blocks:
        ce = sum(1 for s in c['signals'] if 'BUY_CE' in s)
        pe = sum(1 for s in c['signals'] if 'BUY_PE' in s)
        dirs[('CE' if ce >= 2 else 'PE')] += 1
    print(f"Direction mix: {dict(dirs)}")

    print("\n--- All entries/exits/trailing/RSI-reject/dead events ---")
    for c in checks:
        for k in ('entry', 'exit'):
            if k in c:
                print(f"  #{c['num']} @ {c['time']}: {c[k]}")
        for t in c.get('trailing', []):
            print(f"  #{c['num']} @ {c['time']}: {t}")
        for t in c.get('rsi_reject', []):
            print(f"  #{c['num']} @ {c['time']}: {t}")
        for t in c.get('exit2', []):
            print(f"  #{c['num']} @ {c['time']}: {t}")

    print("\n--- Spot timeline (every 60 checks + key early checks) ---")
    for c in checks:
        if c['num'] % 60 == 0 or c['num'] in (1, 16, 17, 38, 39, 40):
            print(f"  #{c['num']} @ {c['time']}: NIFTY={c.get('spot')}")


if __name__ == '__main__':
    main()
