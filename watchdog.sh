#!/bin/bash
export PATH=/usr/local/bin:/usr/bin:/bin
cd /root/trading || exit 1

if [ -f .env ]; then
    set -a; source .env; set +a
fi

LOG_DIR="/root/trading/logs"
mkdir -p "$LOG_DIR"
WATCHDOG_LOG="$LOG_DIR/watchdog.log"
MONITOR_LOG="$LOG_DIR/realtime_monitor.log"

# --- Holiday gate -----------------------------------------------------------
# The watchdog restarts the monitor, so it must respect the calendar too —
# otherwise it happily resurrects a trading session on a holiday.
. /root/trading/scripts/holiday_guard.sh
if ! holiday_guard; then
    echo "$(date '+%H:%M:%S') Watchdog: not a trading day — exiting" >> "$WATCHDOG_LOG"
    exit 0
fi
# ---------------------------------------------------------------------------

log() {
    echo "[$(date '+%H:%M:%S')] $*" >> "$WATCHDOG_LOG"
    echo "[WATCHDOG] $*"
}

is_market_hours() {
    H=$(date +%H%M)
    # Only monitor 9:00 - 15:35 IST
    [ "$H" -ge 0900 ] && [ "$H" -le 1500 ]
}

restart_monitor() {
    log "Restarting monitor..."
    screen -ls 2>/dev/null | grep -q trading_ && screen -X -S "$(screen -ls | grep trading_ | awk '{print $1}' | head -1)" quit 2>/dev/null
    screen -dmS trading_$(date +%H%M) bash -c "cd /root/trading && python3 -u agents/realtime_monitor.py >> $MONITOR_LOG 2>&1"
    log "Monitor restarted in screen session"
}

# The Discord bot is started once by start_monitor.sh and, unlike the monitor,
# was never supervised: a transient DNS blip at login killed it for the whole
# day and `!pnl` / `!status` silently stopped answering. Keep it alive here.
restart_discbot() {
    log "Restarting Discord bot..."
    screen -ls 2>/dev/null | grep -q discbot_ && screen -X -S "$(screen -ls | grep discbot_ | awk '{print $1}' | head -1)" quit 2>/dev/null
    screen -dmS discbot_$(date +%H%M) bash -c "cd /root/trading && python3 -u discord_bot.py >> $LOG_DIR/discord_bot.log 2>&1"
    log "Discord bot restarted in screen session"
}

# Send Discord alert
discord_alert() {
    local msg="$1"
    if [ -n "$DISCORD_WEBHOOK" ]; then
        curl -s -X POST "$DISCORD_WEBHOOK" -H "Content-Type: application/json" \
            -d "{\"content\": \"🔧 **Watchdog:** $msg\"}" > /dev/null 2>&1
    fi
}

log "Watchdog started"

# Initial start
restart_monitor
discord_alert "Watchdog online — monitoring session"

# Adopt (or start) the Discord bot at watchdog startup.
if ! screen -ls 2>/dev/null | grep -q discbot_; then
    restart_discbot
    discord_alert "Discord bot was not running — started"
fi

LAST_HEARTBEAT=""
CONSECUTIVE_FAILS=0

while true; do
    if is_market_hours; then
        SCREEN_ALIVE=$(screen -ls 2>/dev/null | grep -c trading_)
        if [ "$SCREEN_ALIVE" -eq 0 ]; then
            # Normal EOD: monitor writes 'Session Complete' before exiting at 15:00.
            # Don't treat that as a crash — restarting would spawn a monitor that
            # immediately exits and trips the AI watcher into a false DEAD alert.
            if [ -f "$MONITOR_LOG" ] && tail -10 "$MONITOR_LOG" | grep -q "Session Complete"; then
                log "Monitor completed session normally at EOD — no restart"
                sleep 60
                continue
            fi
            CONSECUTIVE_FAILS=$((CONSECUTIVE_FAILS + 1))
            log "Monitor screen dead (fail #$CONSECUTIVE_FAILS)"
            if [ -f "$MONITOR_LOG" ]; then
                TAIL=$(tail -5 "$MONITOR_LOG")
                log "Last log lines: $TAIL"
            fi
            if [ "$CONSECUTIVE_FAILS" -le 3 ]; then
                restart_monitor
                discord_alert "Monitor crashed — restarted (attempt $CONSECUTIVE_FAILS/3)"
            else
                log "Too many failures — giving up until next cycle"
                discord_alert "Monitor crashed $CONSECUTIVE_FAILS times — waiting 5 min"
                sleep 300
                CONSECUTIVE_FAILS=0
            fi
        else
            CONSECUTIVE_FAILS=0
            # Discord bot liveness — it is a separate screen from the monitor.
            if ! screen -ls 2>/dev/null | grep -q discbot_; then
                log "Discord bot screen dead — restarting"
                restart_discbot
                discord_alert "Discord bot was down — restarted"
            fi
            # Check log heartbeat
            if [ -f "$MONITOR_LOG" ]; then
                LAST_MOD=$(stat -c %Y "$MONITOR_LOG" 2>/dev/null || echo 0)
                NOW=$(date +%s)
                AGE=$((NOW - LAST_MOD))
                if [ "$AGE" -gt 180 ] && [ -n "$LAST_HEARTBEAT" ]; then
                    log "Monitor log stale (${age}s) — may be stuck"
                    discord_alert "Monitor may be stuck (log unchanged ${age}s)"
                fi
                if [ "$AGE" -lt 120 ]; then
                    LAST_HEARTBEAT=$(date +%s)
                fi
            fi
        fi
    else
        log "Market closed — watchdog exiting"
        discord_alert "Watchdog shutting down for the day"
        exit 0
    fi
    sleep 60
done
