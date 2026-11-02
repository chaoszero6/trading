#!/usr/bin/env python3
"""Verify the 6% profit target is disabled and the trailing SL still works.

Extracts the real _trail_sl function from the deployed paper_trader.py via AST
(no network / no broker auth) and exercises it against the deployed constants.
"""
import ast, sys, os

SRC = "/root/trading/agents/paper_trader.py"
src = open(SRC).read()
tree = ast.parse(src)

fn = None
consts = {}
for node in tree.body:
    if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name):
        n = node.targets[0].id
        if n in ("TARGET_ENABLED", "TARGET_PCT"):
            consts[n] = ast.literal_eval(node.value)
    if isinstance(node, ast.ClassDef):
        for sub in node.body:
            if isinstance(sub, ast.FunctionDef) and sub.name == "_trail_sl":
                fn = sub

assert fn is not None, "_trail_sl not found"
assert consts, "TARGET_ENABLED / TARGET_PCT not found in module scope"

mod: dict = {"print": lambda *a, **k: None}
mod.update(consts)
exec(compile(ast.Module(body=[fn], type_ignores=[]), SRC, "exec"), mod)
trail = mod["_trail_sl"]

checks = []


def chk(name, cond, detail=""):
    checks.append((name, bool(cond), detail))


# 1. constants
chk("TARGET_ENABLED is False", consts.get("TARGET_ENABLED") is False, f"={consts.get('TARGET_ENABLED')}")
chk("TARGET_PCT preserved as 1.06", abs(consts.get("TARGET_PCT", 0) - 1.06) < 1e-9, f"={consts.get('TARGET_PCT')}")

# 2. no 'target' return at any peak, up to +100%
entry = 100.0
got = [(p, trail(mod, {"entry_ltp": entry, "peak_ltp": entry, "sl": 90.0}, entry * p))
       for p in (1.02, 1.05, 1.06, 1.07, 1.20, 1.50, 2.00)]
chk("never returns 'target' at +6%", all(r != "target" for _, r in got),
    str([(p, r) for p, r in got]))

# 3. trail does NOT arm below +3%
pos = {"entry_ltp": 100.0, "peak_ltp": 100.0, "sl": 90.0}
trail(mod, pos, 102.9)
chk("trail dormant at +2.9%", pos["sl"] == 90.0 and not pos.get("trail_activated"), f"sl={pos['sl']}")

# 4. trail arms above +3% and ratchets up
pos = {"entry_ltp": 100.0, "peak_ltp": 100.0, "sl": 90.0}
trail(mod, pos, 103.5)
sl_at_35 = pos["sl"]
chk("trail arms at +3.5%", sl_at_35 > 90.0 and pos.get("trail_activated"), f"sl={sl_at_35}")
chk("sl locks 70% of gain at +3.5%", abs(sl_at_35 - 102.45) < 0.15, f"sl={sl_at_35} expected ~102.45")

# 5. keeps ratcheting as the winner runs (this is the behaviour the target was blocking)
pos = {"entry_ltp": 100.0, "peak_ltp": 100.0, "sl": 90.0}
for ltp in (103.5, 106.0, 110.0, 120.0):
    trail(mod, pos, ltp)
chk("winner allowed to run to +20%", pos["peak_ltp"] == 120.0 and pos["sl"] > 113.0,
    f"peak={pos['peak_ltp']} sl={pos['sl']} (locks 70% of +20%)")

# 6. sl never decreases
pos = {"entry_ltp": 100.0, "peak_ltp": 100.0, "sl": 90.0}
seq = []
for ltp in (103.5, 108.0, 105.0, 104.0):
    trail(mod, pos, ltp)
    seq.append(pos["sl"])
chk("trailing SL is monotonic", all(b >= a for a, b in zip(seq, seq[1:])), str(seq))

# 7. restoring the switch brings the target back
#    (the exec'd function reads TARGET_ENABLED from its own globals dict, so flip it in place)
mod["TARGET_ENABLED"] = True
restored = trail(mod, {"entry_ltp": 100.0, "peak_ltp": 100.0, "sl": 90.0}, 106.5)
mod["TARGET_ENABLED"] = False
chk("TARGET_ENABLED=True restores 6% target", restored == "target", f"returned {restored!r}")

bad = [c for c in checks if not c[1]]
for name, ok, detail in checks:
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f"  ({detail})" if detail else ""))
print(f"\n{len(checks) - len(bad)}/{len(checks)} passed")
sys.exit(1 if bad else 0)
