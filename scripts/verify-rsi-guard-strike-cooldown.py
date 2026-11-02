#!/usr/bin/env python3
"""Ad-hoc verification for Fix 1 (RSI guard persistence) + Fix 5 (per-strike cooldown).

Imports the REAL deployed methods from /root/trading/agents/realtime_monitor.py and
exercises them with fixtures. No network, no broker, no monitor loop.
"""
import os
import sys
import time
import types

sys.path.insert(0, "/root/trading")
os.chdir("/root/trading")

# Pull the module without running __main__ / connecting to the broker.
src = open("agents/realtime_monitor.py").read()
mod = types.ModuleType("rtm_test")
mod.__dict__["__name__"] = "rtm_test"
mod.__dict__["__file__"] = os.path.abspath("agents/realtime_monitor.py")
exec(compile(src, "agents/realtime_monitor.py", "exec"), mod.__dict__)

R = mod.RealTimeMonitor
RSI_PERSIST = mod.RSI_PERSIST_CHECKS
COOLDOWN = mod.STRIKE_COOLDOWN_MINUTES

fails, checks = [], 0


def check(name, cond, detail=""):
    global checks
    checks += 1
    print(("  PASS  " if cond else "  FAIL  ") + name + (f"   [{detail}]" if detail else ""))
    if not cond:
        fails.append(name)


# Build an instance without __init__ (that authenticates to the broker).
m = R.__new__(R)
m._rsi_guard_state = {}
m._strike_cooldown = {}


print(f"\n=== FIX 1: RSI guard persistence (RSI_PERSIST_CHECKS={RSI_PERSIST}) ===")

# 1. One extreme tick blocks immediately (fail-safe direction).
m._rsi_guard_state = {}
b, why = m._rsi_guard_check("NIFTY", "BUY_CE", 72.0)
check("CE at RSI 72.0 blocks immediately", b is True, why)

# 2. The wobble case that motivated the fix: RSI 72.8 -> 69.4 in one check.
#    Old code let this through. New code must still block.
b, why = m._rsi_guard_check("NIFTY", "BUY_CE", 69.4)
check("CE at RSI 69.4 after 72.8 STILL blocked (wobble)", b is True, why)

# 3. After RSI_PERSIST_CHECKS consecutive clear checks it releases.
m._rsi_guard_state = {}                       # fresh guard for this sequence
m._rsi_guard_check("NIFTY", "BUY_CE", 72.0)   # arm it
blocked_ticks = []
for i in range(1, RSI_PERSIST + 1):
    b, why = m._rsi_guard_check("NIFTY", "BUY_CE", 68.0 - i * 0.1)
    blocked_ticks.append(b)
check(f"releases on clear tick #{RSI_PERSIST} exactly",
      blocked_ticks[-1] is False, f"progression={blocked_ticks}")
# Freshly armed: the first (RSI_PERSIST-1) clear ticks stay blocked, the
# RSI_PERSIST-th releases.
check(f"blocked for the first {RSI_PERSIST - 1} clear tick(s)",
      all(blocked_ticks[: RSI_PERSIST - 1]) and blocked_ticks[-1] is False,
      f"progression={blocked_ticks}")

# 4. Guard is clean afterwards (no sticky block).
b, _ = m._rsi_guard_check("NIFTY", "BUY_CE", 60.0)
check("no sticky block after release", b is False)

# 5. PE oversold side behaves the same.
m._rsi_guard_state = {}
b, why = m._rsi_guard_check("NIFTY", "BUY_PE", 33.0)
check("PE at RSI 33.0 blocks (oversold)", b is True, why)
b, why = m._rsi_guard_check("NIFTY", "BUY_PE", 36.0)
check("PE at RSI 36.0 still blocked (clearing)", b is True, why)

# 6. PE overbought guard.
m._rsi_guard_state = {}
b, why = m._rsi_guard_check("NIFTY", "BUY_PE", 76.0)
check("PE at RSI 76.0 blocks (avoid fade)", b is True, why)

# 7. A fresh extreme refreshes the counter (no release mid-extreme).
m._rsi_guard_state = {}
m._rsi_guard_check("NIFTY", "BUY_CE", 71.0)   # arm
m._rsi_guard_check("NIFTY", "BUY_CE", 69.0)   # 1 clear
b, _ = m._rsi_guard_check("NIFTY", "BUY_CE", 71.5)  # extreme again -> re-arm
check("re-arm on fresh extreme", b is True)
blocked = []
for _ in range(RSI_PERSIST - 1):
    b, _ = m._rsi_guard_check("NIFTY", "BUY_CE", 69.0)
    blocked.append(b)
check("re-release needs the full count again", all(blocked))

# 8. Non-extreme with no prior state is not blocked.
m._rsi_guard_state = {}
b, _ = m._rsi_guard_check("NIFTY", "BUY_CE", 55.0)
check("neutral RSI passes with no history", b is False)


print(f"\n=== FIX 5: per-strike cooldown (STRIKE_COOLDOWN_MINUTES={COOLDOWN}) ===")

m._strike_cooldown = {}
pos = {"index": "NIFTY", "strike": 22800, "type": "CE"}
m._start_strike_cooldown(pos)

b, left = m._strike_on_cooldown("NIFTY", 22800, "CE")
check("same strike+type blocked after exit", b is True, f"{left:.1f}m left")
check("remaining is ~full cooldown", abs(left - COOLDOWN) < 0.5, f"{left:.2f}m")

b, _ = m._strike_on_cooldown("NIFTY", 22800, "PE")
check("opposite type same strike NOT blocked", b is False)

b, _ = m._strike_on_cooldown("NIFTY", 22850, "CE")
check("different strike NOT blocked", b is False)

b, _ = m._strike_on_cooldown("BANKNIFTY", 22800, "CE")
check("different index NOT blocked", b is False)

# Simulate expiry of the cooldown.
m._strike_cooldown["NIFTY:22800:CE"] = time.time() - 1
b, _ = m._strike_on_cooldown("NIFTY", 22800, "CE")
check("cooldown expires and self-cleans", b is False and "NIFTY:22800:CE" not in m._strike_cooldown)

# Two different strikes can be blocked simultaneously.
m._strike_cooldown = {}
m._start_strike_cooldown({"index": "NIFTY", "strike": 22800, "type": "CE"})
m._start_strike_cooldown({"index": "NIFTY", "strike": 22900, "type": "PE"})
b1, _ = m._strike_on_cooldown("NIFTY", 22800, "CE")
b2, _ = m._strike_on_cooldown("NIFTY", 22900, "PE")
check("independent strikes tracked separately", b1 and b2)

# Guard against None pos (defensive).
m._start_strike_cooldown(None)
check("None position does not crash", True)

print(f"\n=== ATM strike helper consistency ===")
check("NIFTY 22837 -> 22850", R._atm_strike_for("NIFTY", 22837) == 22850)
check("NIFTY 22824 -> 22800", R._atm_strike_for("NIFTY", 22824) == 22800)
check("BANKNIFTY 54923 -> 54900", R._atm_strike_for("BANKNIFTY", 54923) == 54900)
check("None spot -> None", R._atm_strike_for("NIFTY", None) is None)

print("\n" + "=" * 60)
print(f"{checks - len(fails)}/{checks} checks passed")
if fails:
    print("FAILED: " + ", ".join(fails))
    sys.exit(1)
print("ALL GOOD")
