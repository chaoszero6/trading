#!/bin/bash
export PATH=/usr/local/bin:/usr/bin:/bin
cd /root/trading || exit 1

if [ -f .env ]; then
    set -a; source .env; set +a
fi

LOG_DIR="/root/trading/logs"
mkdir -p "$LOG_DIR"

rm -f "$LOG_DIR/realtime_monitor.log" /root/trading/data/papertrades.db 2>/dev/null

# Kill old sessions
screen -ls 2>/dev/null | grep -q trading_ && screen -X -S "$(screen -ls | grep trading_ | awk '{print $1}' | head -1)" quit 2>/dev/null
screen -ls 2>/dev/null | grep -q watchdog_ && screen -X -S "$(screen -ls | grep watchdog_ | awk '{print $1}' | head -1)" quit 2>/dev/null
screen -ls 2>/dev/null | grep -q discbot_ && screen -X -S "$(screen -ls | grep discbot_ | awk '{print $1}' | head -1)" quit 2>/dev/null

# Start monitor + watchdog + AI watcher + Discord bot
screen -dmS trading_$(date +%H%M) bash -c "cd /root/trading && python3 -u agents/realtime_monitor.py > $LOG_DIR/realtime_monitor.log 2>&1"
screen -dmS watchdog_$(date +%H%M) bash -c "cd /root/trading && bash watchdog.sh"
screen -dmS aiwatch_$(date +%H%M) bash -c "cd /root/trading && python3 -u agents/ai_watcher.py > $LOG_DIR/ai_watcher.log 2>&1"
screen -dmS discbot_$(date +%H%M) bash -c "cd /root/trading && python3 -u discord_bot.py > $LOG_DIR/discord_bot.log 2>&1"

echo "$(date): Monitor + watchdog + AI watcher + Discord bot started" >> "$LOG_DIR/monitor_scheduler.log"
