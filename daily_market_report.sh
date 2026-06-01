#!/usr/bin/env bash
# ===========================================================
# Daily Market Report — runs every 5 min 9-11:30am, and
# end-of-day accuracy report at 5pm IST.
# ===========================================================
set -euo pipefail

VENV=/tmp/trading_venv
PROJECT=/root/trading
LOG=/var/log/trading-daily.log

export PATH="$VENV/bin:$PATH"
export TZ=Asia/Kolkata

cd "$PROJECT"

if [ -f .env ]; then
    set -a
    source .env
    set +a
fi

if [ -z "${DISCORD_WEBHOOK:-}" ]; then
    echo "[$(date)] ERROR: DISCORD_WEBHOOK not set" >> "$LOG"
    exit 1
fi

HOUR=$(date +%H)
MODE="regular"
DESCRIPTION=""

if [ "$HOUR" = "17" ]; then
    MODE="eod"
    DESCRIPTION="End-of-Day Accuracy Report"
elif [ "$HOUR" = "08" ]; then
    DESCRIPTION="Pre-Market Briefing"
else
    DESCRIPTION="Live Market Update"
fi

echo "[$(date)] Mode=$MODE $DESCRIPTION" >> "$LOG"

python discord_notifier.py \
    --webhook "$DISCORD_WEBHOOK" \
    --mode "$MODE" \
    --capital 500000 \
    >> "$LOG" 2>&1

echo "[$(date)] Done." >> "$LOG"
