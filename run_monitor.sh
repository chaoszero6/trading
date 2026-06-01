#!/bin/bash
source /root/trading/.env 2>/dev/null || export $(grep -v "^#" /root/trading/.env | xargs)
cd /root/trading
exec python3 -u -c "
import sys, traceback, os
sys.path.insert(0, os.getcwd())

# Force load .env
from pathlib import Path
for line in Path('.env').read_text().strip().split('\n'):
    if line and not line.startswith('#') and '=' in line:
        k, v = line.split('=', 1)
        os.environ[k.strip()] = v.strip()

from agents.realtime_monitor import RealTimeMonitor
print('[WRAPPER] Starting monitor...', flush=True)
try:
    m = RealTimeMonitor()
    print('[WRAPPER] Monitor initialized, calling run()...', flush=True)
    m.run()
except Exception as e:
    print(f'[WRAPPER] FATAL: {e}', flush=True)
    traceback.print_exc()
" >> /root/trading/logs/realtime_monitor.log 2>&1
