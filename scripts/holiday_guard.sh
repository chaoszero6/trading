#!/bin/bash
# =============================================================================
# Shared market-holiday gate for every scheduled trading job.
#
# Source this at the top of any script that must not run on a non-trading day:
#     . /root/trading/scripts/holiday_guard.sh
#     holiday_guard || exit 0
#
# Exit status: 0 = trading day, proceed.  1 = not a trading day, skip.
#              (2 = calendar error; treated as skip because we fail safe.)
#
# Fail-safe policy: if the NSE holiday calendar can't be resolved (API down AND
# no usable cache AND no complete local list), this returns 1 (skip) — a missed
# paper-trading day costs nothing, trading on a holiday corrupts the record.
#
# Manual override for ad-hoc closures (comma separated, optional reason after :):
#     EXTRA_TRADING_HOLIDAYS="2026-09-15:Local holiday"
# To force a run on a holiday, set TRADING_HOLIDAY_OVERRIDE=1.
# =============================================================================

HOLIDAY_GUARD_DIR="/root/trading/scripts/holidays"
HOLIDAY_GUARD_LOG="${HOLIDAY_GUARD_LOG:-/root/trading/logs/holiday_guard.log}"

holiday_guard() {
    local python_bin="python3"
    [ -x /tmp/trading_venv/bin/python ] && python_bin="/tmp/trading_venv/bin/python"

    if [ -n "${TRADING_HOLIDAY_OVERRIDE:-}" ]; then
        _holiday_guard_log "OVERRIDE: TRADING_HOLIDAY_OVERRIDE set, proceeding on $(date +%F)"
        return 0
    fi

    local out rc
    out="$("$python_bin" "$HOLIDAY_GUARD_DIR/market_calendar.py" --no-fail-safe 2>&1)"
    rc=$?

    if [ "$rc" -eq 0 ]; then
        # Log only what matters: holiday/weekend/fail-safe already logged below.
        if printf '%s' "$out" | grep -q '^RUN '; then
            case "${TRADING_HOLIDAY_VERBOSE:-}" in
                1|true|yes) _holiday_guard_log "$(printf '%s' "$out" | head -1)";;
            esac
        fi
        return 0
    fi

    _holiday_guard_log "$(printf '%s' "$out" | tr '\n' ' ' | sed 's/  */ /g')"
    if [ "$rc" -eq 2 ]; then
        _holiday_guard_log "WARN: calendar check errored (rc=2) — SKIPPING to stay safe"
    fi
    return 1
}

_holiday_guard_log() {
    mkdir -p "$(dirname "$HOLIDAY_GUARD_LOG")" 2>/dev/null
    echo "[$(date '+%F %T %Z')] $*" >> "$HOLIDAY_GUARD_LOG" 2>/dev/null
}
