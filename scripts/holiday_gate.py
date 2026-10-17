#!/usr/bin/env python3
"""Importable holiday gate for Python entry points under /root/trading.

    from holiday_gate import should_run_trading, guard_or_exit

    if not should_run_trading():
        sys.exit(0)          # or: guard_or_exit()
"""

import sys
from pathlib import Path

CALENDAR_DIR = Path("/root/trading/scripts/holidays")
if str(CALENDAR_DIR) not in sys.path:
    sys.path.insert(0, str(CALENDAR_DIR))

from market_calendar import (  # noqa: E402
    trading_day_status,
    should_run_trading,
    now_ist,
)


def guard_or_exit(verbose=True):
    """Exit 0 (silently skipping) unless today is a confirmed trading day."""
    status = trading_day_status()
    if not status["isTradingDay"]:
        if verbose:
            print(
                f"[holiday_gate] SKIP {status['date']}: {status['reason']} "
                f"(source: {status['source']})"
            )
        sys.exit(0)
    if verbose:
        print(f"[holiday_gate] RUN {status['date']}: {status['reason']}")
    return True


__all__ = [
    "trading_day_status",
    "should_run_trading",
    "guard_or_exit",
    "now_ist",
    "CALENDAR_DIR",
]

if __name__ == "__main__":
    guard_or_exit()
