"""AutoTrader Database — SQLite persistence for sessions and trades"""
from __future__ import annotations
import sqlite3
import json
import os
import time

DB_PATH = os.path.join(os.path.dirname(__file__), "autotrader.db")

def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn

def init_db():
    conn = get_conn()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS sessions (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            config TEXT NOT NULL,
            created_at REAL NOT NULL,
            updated_at REAL NOT NULL
        );
        CREATE TABLE IF NOT EXISTS trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL,
            direction TEXT,
            entry_price REAL,
            exit_price REAL,
            stop_loss REAL,
            target REAL,
            quantity INTEGER,
            pnl REAL,
            exit_reason TEXT,
            signals_met INTEGER DEFAULT 0,
            total_signals INTEGER DEFAULT 0,
            entry_time INTEGER,
            exit_time INTEGER,
            FOREIGN KEY (session_id) REFERENCES sessions(id)
        );
        CREATE INDEX IF NOT EXISTS idx_trades_session ON trades(session_id);
    """)
    conn.commit()
    conn.close()

def save_session(sid: str, name: str, config_json: str, created_at: float):
    conn = get_conn()
    conn.execute(
        "INSERT OR REPLACE INTO sessions (id, name, config, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
        (sid, name, config_json, created_at, time.time())
    )
    conn.commit()
    conn.close()

def delete_session_db(sid: str):
    conn = get_conn()
    conn.execute("DELETE FROM trades WHERE session_id = ?", (sid,))
    conn.execute("DELETE FROM sessions WHERE id = ?", (sid,))
    conn.commit()
    conn.close()

def load_all_sessions():
    conn = get_conn()
    rows = conn.execute("SELECT id, name, config, created_at FROM sessions ORDER BY created_at").fetchall()
    conn.close()
    return [{"id": r["id"], "name": r["name"], "config": json.loads(r["config"]), "created_at": r["created_at"]} for r in rows]

def save_trade(session_id: str, direction: str, entry_price: float, exit_price: float,
               stop_loss: float, target: float, quantity: int, pnl: float,
               exit_reason: str, signals_met: int, total_signals: int,
               entry_time: int, exit_time: int):
    conn = get_conn()
    conn.execute(
        "INSERT INTO trades (session_id, direction, entry_price, exit_price, stop_loss, target, "
        "quantity, pnl, exit_reason, signals_met, total_signals, entry_time, exit_time) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (session_id, direction, entry_price, exit_price, stop_loss, target,
         quantity, pnl, exit_reason, signals_met, total_signals, entry_time, exit_time)
    )
    conn.commit()
    conn.close()

def get_trades(session_id: str) -> list[dict]:
    conn = get_conn()
    rows = conn.execute(
        "SELECT direction, entry_price, exit_price, pnl, exit_reason, signals_met, "
        "total_signals, entry_time, exit_time FROM trades WHERE session_id = ? ORDER BY entry_time",
        (session_id,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]
