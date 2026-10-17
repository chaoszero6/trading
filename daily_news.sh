#!/bin/bash
export PATH=/usr/local/bin:/usr/bin:/bin
cd /root/trading || exit 1

# --- Holiday gate -----------------------------------------------------------
# Skip on weekends/NSE holidays; fail safe (skip) if the calendar is unavailable.
. /root/trading/scripts/holiday_guard.sh
if ! holiday_guard; then
    echo "$(date): SKIPPED — not a trading day" >> logs/daily_news.log
    exit 0
fi
# ---------------------------------------------------------------------------

if [ -f .env ]; then
    set -a; source .env; set +a
fi

python3 -u agents/daily_news.py >> logs/daily_news.log 2>&1
