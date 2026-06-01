"""
LearningAgent — Trading knowledge base.
Stores suggestions + outcomes in SQLite, analyzes success/failure patterns,
and extracts lessons for continuous improvement.
"""

import sys, os, json
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import sqlite3
from datetime import datetime, timedelta
from pathlib import Path


DB_PATH = Path(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))) / "data" / "learning.db"


class LearningAgent:
    def __init__(self, db_path=None):
        self.name = "LearningAgent"
        self.db_path = db_path or DB_PATH
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS suggestions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    user_request TEXT,
                    index_name TEXT NOT NULL,
                    strike INTEGER NOT NULL,
                    option_type TEXT NOT NULL,
                    entry_premium REAL,
                    stop_loss REAL,
                    target REAL,
                    capital_allocated REAL,
                    max_loss REAL,
                    reasoning TEXT,
                    agents_used TEXT,
                    confidence TEXT,
                    market_context TEXT,
                    actual_pnl REAL,
                    exit_reason TEXT,
                    exit_price REAL,
                    highest_price REAL,
                    lowest_price REAL,
                    held_duration_hours REAL,
                    lessons_learned TEXT,
                    outcome_recorded_at TEXT
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS lessons (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    suggestion_id INTEGER,
                    lesson TEXT NOT NULL,
                    category TEXT,
                    severity TEXT,
                    created_at TEXT DEFAULT (datetime('now')),
                    applied_in_future INTEGER DEFAULT 0,
                    FOREIGN KEY (suggestion_id) REFERENCES suggestions(id)
                )
            """)
            conn.commit()

    def record_suggestion(self, data):
        with sqlite3.connect(self.db_path) as conn:
            cur = conn.execute("""
                INSERT INTO suggestions (
                    timestamp, user_request, index_name, strike, option_type,
                    entry_premium, stop_loss, target, capital_allocated,
                    max_loss, reasoning, agents_used, confidence, market_context
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                data.get("timestamp", datetime.now().isoformat()),
                data.get("user_request", ""),
                data.get("index", "NIFTY"),
                data.get("strike", 0),
                data.get("type", "CE"),
                data.get("entry_premium", 0),
                data.get("stop_loss", 0),
                data.get("target", 0),
                data.get("capital_allocated", 0),
                data.get("max_loss", 0),
                data.get("reasoning", ""),
                json.dumps(data.get("agents_used", [])),
                data.get("confidence", "medium"),
                json.dumps(data.get("market_context", {}))
            ))
            return cur.lastrowid

    def record_outcome(self, suggestion_id, outcome):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                UPDATE suggestions SET
                    actual_pnl = ?,
                    exit_reason = ?,
                    exit_price = ?,
                    highest_price = ?,
                    lowest_price = ?,
                    held_duration_hours = ?,
                    lessons_learned = ?,
                    outcome_recorded_at = datetime('now')
                WHERE id = ?
            """, (
                outcome.get("actual_pnl"),
                outcome.get("exit_reason", ""),
                outcome.get("exit_price"),
                outcome.get("highest_price_reached"),
                outcome.get("lowest_price_reached"),
                outcome.get("held_duration_hours"),
                outcome.get("lessons_learned", ""),
                suggestion_id
            ))

    def sync_from_papertrades(self):
        """Pull completed trades from papertrades.db into learning.db."""
        pt_db = Path(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))) / "data" / "papertrades.db"
        if not pt_db.exists():
            return
        try:
            import sqlite3 as _sql
            pt_conn = _sql.connect(str(pt_db))
            trades = pt_conn.execute("""
                SELECT timestamp, index_name, strike, option_type, entry_ltp, sl, target,
                       pnl, exit_reason, exit_ltp, held_minutes, entry_signal, rsi, vwap_diff
                FROM trades WHERE exit_ltp IS NOT NULL
                ORDER BY timestamp
            """).fetchall()
            pt_conn.close()
        except Exception:
            return

        with sqlite3.connect(self.db_path) as conn:
            for t in trades:
                ts, idx, strike, optype, entry, sl, tgt, pnl, reason, exit_ltp, mins, sig, rsi, vwap = t
                # Check if already synced by matching timestamp+index+strike+type
                exists = conn.execute(
                    "SELECT id FROM suggestions WHERE timestamp = ? AND index_name = ? AND strike = ? AND option_type = ?",
                    (ts, idx, strike, optype)
                ).fetchone()
                if exists:
                    # Update outcome if not already recorded
                    conn.execute(
                        "UPDATE suggestions SET actual_pnl = ?, exit_reason = ?, exit_price = ?, held_duration_hours = ?, outcome_recorded_at = datetime('now') WHERE id = ? AND outcome_recorded_at IS NULL",
                        (pnl, reason, exit_ltp, mins, exists[0])
                    )
                else:
                    conn.execute("""
                        INSERT INTO suggestions (timestamp, index_name, strike, option_type, entry_premium, stop_loss, target, actual_pnl, exit_reason, exit_price, held_duration_hours, confidence, outcome_recorded_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
                    """, (ts, idx, strike, optype, entry, sl, tgt, pnl, reason, exit_ltp, mins, "medium"))
            conn.commit()

    def get_statistics(self, index=None, days=30, option_type=None):
        self.sync_from_papertrades()
        with sqlite3.connect(self.db_path) as conn:
            q = """SELECT id, timestamp, index_name, strike, option_type, entry_premium,
                          stop_loss, target, capital_allocated, max_loss, reasoning,
                          agents_used, confidence, market_context,
                          actual_pnl, exit_reason, exit_price, highest_price,
                          lowest_price, held_duration_hours, lessons_learned, outcome_recorded_at
                   FROM suggestions WHERE outcome_recorded_at IS NOT NULL"""
            params = []
            if index:
                q += " AND index_name = ?"
                params.append(index)
            if days:
                cutoff = (datetime.now() - timedelta(days=days)).isoformat()
                q += " AND timestamp >= ?"
                params.append(cutoff)
            if option_type:
                q += " AND option_type = ?"
                params.append(option_type)

            rows = conn.execute(q, params).fetchall()

            total = len(rows)
            if total == 0:
                return {"total": 0, "message": "No completed trades found"}

            # column indices from explicit SELECT (0-based)
            IDX_ACTUAL_PNL = 14
            IDX_EXIT_REASON = 15

            won = sum(1 for r in rows if r[IDX_ACTUAL_PNL] and r[IDX_ACTUAL_PNL] > 0)
            lost = total - won
            pnl_values = [r[IDX_ACTUAL_PNL] for r in rows if r[IDX_ACTUAL_PNL] is not None]

            by_reason = {}
            for r in rows:
                reason = r[IDX_EXIT_REASON] or "unknown"
                by_reason.setdefault(reason, {"count": 0, "total_pnl": 0})
                by_reason[reason]["count"] += 1
                if r[IDX_ACTUAL_PNL]:
                    by_reason[reason]["total_pnl"] += r[IDX_ACTUAL_PNL]

            return {
                "total": total,
                "won": won,
                "lost": lost,
                "win_rate": round(won / total, 2) if total > 0 else 0,
                "avg_profit": round(sum(p for p in pnl_values if p > 0) / max(won, 1), 0) if won > 0 else 0,
                "avg_loss": round(abs(sum(p for p in pnl_values if p < 0)) / max(lost, 1), 0) if lost > 0 else 0,
                "total_pnl": round(sum(pnl_values), 0),
                "by_exit_reason": by_reason,
            }

    def analyze_recent_failures(self, lookback_days=30):
        with sqlite3.connect(self.db_path) as conn:
            cutoff = (datetime.now() - timedelta(days=lookback_days)).isoformat()
            rows = conn.execute("""
                SELECT id, timestamp, index_name, strike, option_type, entry_premium,
                       stop_loss, target, max_loss, actual_pnl, exit_reason,
                       lessons_learned, market_context, reasoning
                FROM suggestions
                WHERE outcome_recorded_at IS NOT NULL
                  AND (actual_pnl IS NULL OR actual_pnl <= 0)
                  AND timestamp >= ?
                ORDER BY timestamp DESC
            """, (cutoff,)).fetchall()

            if not rows:
                return {"total_failures": 0, "patterns": [], "message": "No recent failures"}

            patterns = []
            sl_hits = 0
            wrong_dir = 0
            for r in rows:
                reason = r[10] or ""
                if "stop_loss" in reason.lower() or "sl" in reason.lower():
                    sl_hits += 1
                if r[9] is not None and r[9] < 0 and r[8]:
                    loss_pct = abs(r[9]) / r[8] * 100
                    pattern = "excessive_loss" if loss_pct > 100 else "normal_loss"
                    patterns.append({"id": r[0], "loss_pct": round(loss_pct), "reason": reason})

            failures = []
            for r in rows[:10]:
                ctx = {}
                try:
                    ctx = json.loads(r[12]) if r[12] else {}
                except: pass
                failures.append({
                    "id": r[0], "date": r[1], "index": r[2],
                    "strike": r[3], "type": r[4],
                    "entry": r[5], "sl": r[6], "target": r[7],
                    "pnl": r[9], "exit_reason": r[10],
                    "lessons": r[11],
                    "market_context": ctx
                })

            return {
                "total_failures": len(rows),
                "sl_hit_count": sl_hits,
                "sl_hit_pct": round(sl_hits / len(rows) * 100) if rows else 0,
                "patterns": patterns[:5],
                "failures": failures,
                "recommendation": self._recommend(sl_hits, len(rows))
            }

    def get_lessons(self, market_regime=None, index=None):
        self.sync_from_papertrades()
        with sqlite3.connect(self.db_path) as conn:
            q = "SELECT lesson, category, severity, created_at FROM lessons ORDER BY created_at DESC LIMIT 20"
            rows = conn.execute(q).fetchall()

            lessons = []
            for r in rows:
                lessons.append({"lesson": r[0], "category": r[1], "severity": r[2], "date": r[3]})

            # Also check recent failures for auto-generated lessons
            failures = self.analyze_recent_failures(lookback_days=30)

            return {
                "recorded_lessons": lessons,
                "recent_failure_patterns": failures,
                "total_recorded": len(lessons),
            }

    def add_lesson(self, suggestion_id, lesson, category="general", severity="medium"):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                INSERT INTO lessons (suggestion_id, lesson, category, severity)
                VALUES (?, ?, ?, ?)
            """, (suggestion_id, lesson, category, severity))

    def _recommend(self, sl_hits, total):
        if total == 0:
            return "No data yet"
        sl_rate = sl_hits / total
        if sl_rate > 0.6:
            return "SLs are too tight. Widen by 20-30% or use ATR-based SL."
        elif sl_rate > 0.4:
            return "SLs could be slightly wider. Consider adding 10-15% buffer."
        else:
            return "SL discipline looks good. Keep it up."


if __name__ == "__main__":
    la = LearningAgent()
    print("Statistics:", la.get_statistics(days=30))
    print("Failures:", la.analyze_recent_failures())
    print("Lessons:", len(la.get_lessons()["recorded_lessons"]))
