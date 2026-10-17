"""
AutoTrader Web — FastAPI Server
"""
from __future__ import annotations
import json
import asyncio
import time
import uuid
from dataclasses import dataclass, field, asdict
from typing import Optional
from datetime import datetime, timedelta
from pathlib import Path

from fastapi import FastAPI, Request, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse

from engine import (
    TradingConfig, TradeRecord, TradeDirection, Candle, IndicatorValues,
    compute_all, fetch_candles, get_ltp, run_backtest,
    StrategyEngine, RiskManager, fetch_pcr, get_pcr_bias,
)
from db import init_db, save_session, delete_session_db, load_all_sessions, save_trade, get_trades as db_get_trades

# ─── Session ──────────────────────────────────────────────────

@dataclass
class Session:
    id: str
    name: str
    created_at: float
    config: TradingConfig
    risk_mgr: RiskManager
    trading_active: bool = False
    trading_task: Optional[asyncio.Task] = None
    signal_log: list = field(default_factory=list)
    last_signal: str = ""
    candle_cache: list = field(default_factory=list)
    indicator_cache: Optional[IndicatorValues] = None
    morning_pcr: Optional[float] = None
    morning_pcr_day: Optional[int] = None
    ws_clients: list = field(default_factory=list)
    ws_push_task: Optional[asyncio.Task] = None

    def add_signal(self, msg: str):
        ts = datetime.now().strftime("%H:%M:%S")
        entry = f"{ts} {msg}"
        self.signal_log.append(entry)
        if len(self.signal_log) > 100:
            self.signal_log = self.signal_log[-100:]
        self.last_signal = entry

    def set_morning_pcr(self, val: Optional[float]):
        today = datetime.now().timetuple().tm_yday
        if self.morning_pcr_day != today:
            self.morning_pcr = val
            self.morning_pcr_day = today

    def get_morning_pcr(self) -> Optional[float]:
        today = datetime.now().timetuple().tm_yday
        if self.morning_pcr_day != today:
            return None
        return self.morning_pcr

class SessionManager:
    def __init__(self):
        self._sessions: dict[str, Session] = {}

    def load_from_db(self):
        for row in load_all_sessions():
            cfg_dict = row["config"]
            cfg = TradingConfig(**{k: v for k, v in cfg_dict.items() if hasattr(TradingConfig, k)})
            sess = Session(id=row["id"], name=row["name"], created_at=row["created_at"], config=cfg, risk_mgr=RiskManager(cfg))
            self._sessions[row["id"]] = sess

    def create(self, name: str) -> Session:
        sid = uuid.uuid4().hex[:12]
        cfg = TradingConfig()
        sess = Session(id=sid, name=name, created_at=time.time(), config=cfg, risk_mgr=RiskManager(cfg))
        self._sessions[sid] = sess
        self._persist(sess)
        return sess

    def _persist(self, s: Session):
        cfg_dict = asdict(s.config)
        save_session(s.id, s.name, json.dumps(cfg_dict), s.created_at)

    def get(self, sid: str) -> Optional[Session]:
        return self._sessions.get(sid)

    def delete(self, sid: str):
        sess = self._sessions.pop(sid, None)
        if sess and sess.trading_task:
            sess.trading_active = False
            sess.trading_task.cancel()
        delete_session_db(sid)

    def list(self) -> list[dict]:
        return [{
            "id": s.id, "name": s.name,
            "created_at": datetime.fromtimestamp(s.created_at).strftime("%Y-%m-%d %H:%M"),
            "active": s.trading_active,
        } for s in self._sessions.values()]

    def save_config(self, s: Session):
        self._persist(s)

    def save_closed_trade(self, s: Session, trade: TradeRecord):
        save_trade(
            session_id=s.id,
            direction=trade.direction.value,
            entry_price=trade.entryPrice,
            exit_price=trade.exitPrice or 0,
            stop_loss=trade.stopLoss,
            target=trade.target,
            quantity=trade.quantity,
            pnl=trade.pnl or 0,
            exit_reason=trade.exitReason or "",
            signals_met=trade.signalsMet,
            total_signals=trade.totalSignals,
            entry_time=trade.timestamp,
            exit_time=int(time.time()),
        )

    def get_trades(self, sid: str) -> list[dict]:
        return db_get_trades(sid)

sessions = SessionManager()
init_db()
sessions.load_from_db()

# ─── WebSocket Broadcast ──────────────────────────────────────

def build_status_dict(s: Session) -> dict:
    open_tr = s.risk_mgr.open_trade
    trades = s.risk_mgr.trades_today
    wins = sum(1 for t in trades if t.pnl and t.pnl > 0)
    losses = sum(1 for t in trades if t.pnl and t.pnl < 0)
    ind = s.indicator_cache
    ltp = s.candle_cache[-1].close if s.candle_cache else 0
    market = {}
    if ind and s.candle_cache:
        last = len(s.candle_cache) - 1
        market = {
            "ltp": round(ltp, 2),
            "vwap": round(ind.vwap[last], 2) if len(ind.vwap) > last else 0,
            "ema9": round(ind.ema9[last], 2) if len(ind.ema9) > last else 0,
            "ema27": round(ind.ema27[last], 2) if len(ind.ema27) > last else 0,
            "rsi14": round(ind.rsi14[last], 2) if len(ind.rsi14) > last else 50,
            "rsiMa": round(ind.rsiMa20[last], 2) if len(ind.rsiMa20) > last else 50,
            "st": ind.superTrend[last].value if len(ind.superTrend) > last else "",
        }
    pcr_data = fetch_pcr(s.config.script)
    if s.get_morning_pcr() is None and pcr_data and pcr_data.get("pcr"):
        s.set_morning_pcr(pcr_data["pcr"])
    pcr_val = (pcr_data or {}).get("pcr")
    return {
        "active": s.trading_active,
        "canTrade": s.risk_mgr.can_take_trade(),
        "config": {
            "lotSize": s.config.lotSize,
            "capital": s.config.capital,
            "script": s.config.script,
            "dailyProfitCapPct": s.config.dailyProfitCapPct,
            "maxTradesPerDay": s.config.maxTradesPerDay,
            "pcrBullish": s.config.pcrBullish,
            "pcrBearish": s.config.pcrBearish,
        },
        "todayPnl": round(s.risk_mgr.current_pnl(), 2),
        "tradesToday": s.risk_mgr.trades_count(),
        "winsToday": wins,
        "lossesToday": losses,
        "dailyCapHit": s.risk_mgr.is_daily_cap_hit(),
        "maxTradeReached": s.risk_mgr.is_max_trade_reached(),
        "pcr": pcr_data,
        "morningPcr": s.get_morning_pcr(),
        "pcrBias": get_pcr_bias(pcr_val, s.config),
        "openTrade": {
            "direction": open_tr.direction.value,
            "entryPrice": open_tr.entryPrice,
            "stopLoss": open_tr.stopLoss,
            "target": open_tr.target,
            "quantity": open_tr.quantity,
            "signalsMet": open_tr.signalsMet,
            "totalSignals": open_tr.totalSignals,
        } if open_tr else None,
        "market": market,
        "signalLog": s.signal_log[-20:],
        "lastSignal": s.last_signal or "",
    }

async def broadcast(s: Session, data: dict):
    dead = []
    for ws in s.ws_clients:
        try:
            await ws.send_json(data)
        except:
            dead.append(ws)
    for ws in dead:
        if ws in s.ws_clients:
            s.ws_clients.remove(ws)

async def push_status_loop(s: Session):
    while s.ws_clients:
        await asyncio.sleep(3)
        if not s.ws_clients:
            break
        try:
            status = build_status_dict(s)
            await broadcast(s, {"type": "status", "data": status})
        except:
            pass

# ─── App ──────────────────────────────────────────────────────

app = FastAPI(title="AutoTrader")

# ─── Routes: Frontend ────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def index():
    html = Path(__file__).parent / "templates" / "index.html"
    return HTMLResponse(html.read_text())

# ─── Routes: Sessions ─────────────────────────────────────────

@app.get("/api/sessions")
async def list_sessions():
    return sessions.list()

@app.post("/api/sessions")
async def create_session(req: Request):
    data = await req.json()
    name = data.get("name", "Untitled").strip() or "Untitled"
    sess = sessions.create(name)
    return {"id": sess.id, "name": sess.name, "created_at": sess.created_at}

@app.delete("/api/sessions/{session_id}")
async def delete_session(session_id: str):
    sessions.delete(session_id)
    return {"status": "ok"}

# ─── Routes: Config ───────────────────────────────────────────

def _get_session(session_id: str) -> Session:
    s = sessions.get(session_id)
    if not s:
        raise HTTPException(404, "Session not found")
    return s

@app.get("/api/sessions/{session_id}/config")
async def get_config(session_id: str):
    s = _get_session(session_id)
    cfg = s.config
    return {
        "lotSize": cfg.lotSize,
        "capital": cfg.capital,
        "script": cfg.script,
        "brokerType": cfg.brokerType,
        "maxTradesPerDay": cfg.maxTradesPerDay,
        "dailyProfitCapPct": cfg.dailyProfitCapPct,
        "targetProfitPct": cfg.targetProfitPct,
        "stPeriod": cfg.stPeriod,
        "stMultiplier": cfg.stMultiplier,
        "candleZonePct": cfg.candleZonePct,
        "rsiCe": cfg.rsiCe,
        "rsiPe": cfg.rsiPe,
        "emaCe1": cfg.emaCe1,
        "emaCe2": cfg.emaCe2,
        "emaPe1": cfg.emaPe1,
        "emaPe2": cfg.emaPe2,
        "pcrBullish": cfg.pcrBullish,
        "pcrBearish": cfg.pcrBearish,
    }

@app.post("/api/sessions/{session_id}/config")
async def save_config(session_id: str, req: Request):
    s = _get_session(session_id)
    data = await req.json()
    cfg = s.config
    s.config = TradingConfig(
        lotSize=int(data.get("lotSize", cfg.lotSize)),
        capital=float(data.get("capital", cfg.capital)),
        script=data.get("script", cfg.script).upper(),
        brokerType=data.get("brokerType", cfg.brokerType),
        maxTradesPerDay=int(data.get("maxTradesPerDay", cfg.maxTradesPerDay)),
        dailyProfitCapPct=float(data.get("dailyProfitCapPct", cfg.dailyProfitCapPct)),
        targetProfitPct=float(data.get("targetProfitPct", cfg.targetProfitPct)),
        stPeriod=int(data.get("stPeriod", cfg.stPeriod)),
        stMultiplier=float(data.get("stMultiplier", cfg.stMultiplier)),
        candleZonePct=float(data.get("candleZonePct", cfg.candleZonePct)),
        rsiCe=float(data.get("rsiCe", cfg.rsiCe)),
        rsiPe=float(data.get("rsiPe", cfg.rsiPe)),
        emaCe1=int(data.get("emaCe1", cfg.emaCe1)),
        emaCe2=int(data.get("emaCe2", cfg.emaCe2)),
        emaPe1=int(data.get("emaPe1", cfg.emaPe1)),
        emaPe2=int(data.get("emaPe2", cfg.emaPe2)),
        pcrBullish=float(data.get("pcrBullish", cfg.pcrBullish)),
        pcrBearish=float(data.get("pcrBearish", cfg.pcrBearish)),
    )
    s.risk_mgr = RiskManager(s.config)
    sessions.save_config(s)
    if s.ws_clients:
        asyncio.create_task(broadcast(s, {"type": "config", "data": build_status_dict(s)}))
    return {"status": "ok"}

# ─── Routes: Start / Stop ─────────────────────────────────────

@app.post("/api/sessions/{session_id}/start")
async def start_trading(session_id: str):
    s = _get_session(session_id)
    if s.trading_active:
        return {"status": "already_running"}
    s.trading_active = True
    s.signal_log = []
    s.risk_mgr.reset_day()
    s.trading_task = asyncio.create_task(trading_loop(s))
    if s.ws_clients:
        asyncio.create_task(broadcast(s, {"type": "status", "data": build_status_dict(s)}))
    return {"status": "started"}

@app.post("/api/sessions/{session_id}/stop")
async def stop_trading(session_id: str):
    s = _get_session(session_id)
    s.trading_active = False
    if s.trading_task:
        s.trading_task.cancel()
        s.trading_task = None
    if s.ws_clients:
        asyncio.create_task(broadcast(s, {"type": "status", "data": build_status_dict(s)}))
    return {"status": "stopped"}

# ─── Routes: Status ───────────────────────────────────────────

@app.get("/api/sessions/{session_id}/status")
async def get_status(session_id: str):
    s = _get_session(session_id)
    return build_status_dict(s)

# ─── Routes: WebSocket ────────────────────────────────────────

@app.websocket("/api/sessions/{session_id}/ws")
async def websocket_endpoint(websocket: WebSocket, session_id: str):
    s = _get_session(session_id)
    await websocket.accept()
    start_push = len(s.ws_clients) == 0
    s.ws_clients.append(websocket)
    try:
        await websocket.send_json({"type": "status", "data": build_status_dict(s)})
    except:
        s.ws_clients.remove(websocket)
        return
    if start_push:
        s.ws_push_task = asyncio.create_task(push_status_loop(s))
    try:
        while True:
            msg = await websocket.receive_text()
            if msg == "ping":
                try:
                    await websocket.send_text("pong")
                except:
                    break
    except WebSocketDisconnect:
        pass
    finally:
        if websocket in s.ws_clients:
            s.ws_clients.remove(websocket)

# ─── Routes: Backtest ─────────────────────────────────────────

@app.post("/api/sessions/{session_id}/backtest")
async def backtest(session_id: str, req: Request):
    s = _get_session(session_id)
    data = await req.json()
    bt_config = TradingConfig(
        lotSize=int(data.get("lotSize", s.config.lotSize)),
        capital=float(data.get("capital", s.config.capital)),
        script=data.get("script", s.config.script).upper(),
        maxTradesPerDay=int(data.get("maxTradesPerDay", s.config.maxTradesPerDay)),
        dailyProfitCapPct=float(data.get("dailyProfitCapPct", s.config.dailyProfitCapPct)),
        targetProfitPct=float(data.get("targetProfitPct", s.config.targetProfitPct)),
        stPeriod=int(data.get("stPeriod", s.config.stPeriod)),
        stMultiplier=float(data.get("stMultiplier", s.config.stMultiplier)),
        candleZonePct=float(data.get("candleZonePct", s.config.candleZonePct)),
        rsiCe=float(data.get("rsiCe", s.config.rsiCe)),
        rsiPe=float(data.get("rsiPe", s.config.rsiPe)),
        emaCe1=int(data.get("emaCe1", s.config.emaCe1)),
        emaCe2=int(data.get("emaCe2", s.config.emaCe2)),
        emaPe1=int(data.get("emaPe1", s.config.emaPe1)),
        emaPe2=int(data.get("emaPe2", s.config.emaPe2)),
        pcrBullish=float(data.get("pcrBullish", s.config.pcrBullish)),
        pcrBearish=float(data.get("pcrBearish", s.config.pcrBearish)),
    )
    script = bt_config.script

    candles = fetch_candles(script, interval="5m", period="1mo")
    if not candles:
        candles = fetch_candles(script, interval="60m", period="3mo")

    start_date = data.get("startDate", "")
    end_date = data.get("endDate", "")
    if start_date:
        try:
            sd = datetime.strptime(start_date, "%Y-%m-%d").timestamp()
            candles = [c for c in candles if c.timestamp >= sd]
        except:
            pass
    if end_date:
        try:
            ed = (datetime.strptime(end_date, "%Y-%m-%d") + timedelta(days=1)).timestamp()
            candles = [c for c in candles if c.timestamp < ed]
        except:
            pass

    if len(candles) < 50:
        return JSONResponse({"error": f"Insufficient data: {len(candles)} candles (need 50+)"}, status_code=400)

    result = run_backtest(candles, bt_config)
    return {
        "totalTrades": result.totalTrades,
        "wins": result.wins,
        "losses": result.losses,
        "winRate": result.winRate,
        "netPnl": result.netPnl,
        "maxDrawdown": result.maxDrawdown,
        "avgWin": result.avgWin,
        "avgLoss": result.avgLoss,
        "sharpeRatio": result.sharpeRatio,
        "maxConsecutiveLosses": result.maxConsecutiveLosses,
        "totalReturnPct": result.totalReturnPct,
        "trades": result.trades,
    }

# ─── Routes: PCR ─────────────────────────────────────────────

@app.get("/api/sessions/{session_id}/pcr")
async def pcr(session_id: str):
    s = _get_session(session_id)
    data = fetch_pcr(s.config.script)
    if s.get_morning_pcr() is None and data and data.get("pcr"):
        s.set_morning_pcr(data["pcr"])
    if data:
        return data
    return {"source": None, "symbol": s.config.script, "pcr": None, "coi_pcr": None}

@app.post("/api/sessions/{session_id}/pcr/reset-morning")
async def reset_morning_pcr(session_id: str):
    s = _get_session(session_id)
    s.morning_pcr = None
    s.morning_pcr_day = None
    return {"status": "ok"}

# ─── Routes: Compare ──────────────────────────────────────────

@app.post("/api/compare")
async def compare_sessions(req: Request):
    data = await req.json()
    session_ids = data.get("session_ids", [])
    results = []
    for sid in session_ids:
        s = sessions.get(sid)
        if not s:
            continue
        cfg = s.config
        trades = sessions.get_trades(sid)
        wins = sum(1 for t in trades if t.get("pnl", 0) > 0)
        losses = sum(1 for t in trades if t.get("pnl", 0) < 0)
        total_pnl = sum(t.get("pnl", 0) for t in trades)
        results.append({
            "id": s.id,
            "name": s.name,
            "created_at": datetime.fromtimestamp(s.created_at).strftime("%Y-%m-%d %H:%M"),
            "config": {
                "lotSize": cfg.lotSize, "capital": cfg.capital, "script": cfg.script,
                "brokerType": cfg.brokerType, "maxTradesPerDay": cfg.maxTradesPerDay,
                "dailyProfitCapPct": cfg.dailyProfitCapPct, "targetProfitPct": cfg.targetProfitPct,
                "stPeriod": cfg.stPeriod, "stMultiplier": cfg.stMultiplier,
                "candleZonePct": cfg.candleZonePct, "rsiCe": cfg.rsiCe, "rsiPe": cfg.rsiPe,
                "emaCe1": cfg.emaCe1, "emaCe2": cfg.emaCe2, "emaPe1": cfg.emaPe1, "emaPe2": cfg.emaPe2,
                "pcrBullish": cfg.pcrBullish, "pcrBearish": cfg.pcrBearish,
            },
            "stats": {
                "totalTrades": len(trades),
                "wins": wins, "losses": losses,
                "winRate": round(wins / (wins + losses) * 100, 1) if (wins + losses) > 0 else 0,
                "totalPnl": round(total_pnl, 2),
                "avgWin": round(sum(t["pnl"] for t in trades if t["pnl"] > 0) / wins, 2) if wins > 0 else 0,
                "avgLoss": round(sum(t["pnl"] for t in trades if t["pnl"] < 0) / losses, 2) if losses > 0 else 0,
                "maxConsecutiveLosses": _max_consecutive_losses(trades),
            },
        })
    return results

def _max_consecutive_losses(trades: list[dict]) -> int:
    streak = 0
    best = 0
    for t in trades:
        if t.get("pnl", 0) < 0:
            streak += 1
            best = max(best, streak)
        else:
            streak = 0
    return best

# ─── Trading Loop ─────────────────────────────────────────────

async def trading_loop(s: Session):
    while s.trading_active:
        try:
            now = datetime.now()
            market_open = now.replace(hour=9, minute=15, second=0)
            warmup_end = now.replace(hour=9, minute=20, second=0)
            market_close = now.replace(hour=15, minute=15, second=0)

            if now < market_open:
                s.add_signal("Waiting for market open...")
                await asyncio.sleep(60)
                continue
            if now < warmup_end:
                s.add_signal("Warmup period (first 5 min)...")
                await asyncio.sleep(30)
                continue
            if now >= market_close:
                s.add_signal("Market closed")
                s.trading_active = False
                break

            if s.get_morning_pcr() is None:
                pcr_data = fetch_pcr(s.config.script)
                if pcr_data and pcr_data.get("pcr"):
                    s.set_morning_pcr(pcr_data["pcr"])
                    s.add_signal(f"Morning PCR: {pcr_data['pcr']:.2f}")

            candles = fetch_candles(s.config.script, interval="5m", period="5d")
            if candles:
                s.candle_cache = candles
                s.indicator_cache = compute_all(candles, s.config)

            if s.risk_mgr.open_trade:
                ltp = get_ltp(s.config.script) or (s.candle_cache[-1].close if s.candle_cache else 0)
                if ltp and s.indicator_cache and len(s.candle_cache) > 1:
                    ot = s.risk_mgr.open_trade
                    exit_sig = StrategyEngine.evaluate_exit(ot.direction, s.candle_cache, s.indicator_cache, len(s.candle_cache) - 1)
                    at_tgt = StrategyEngine.at_target(ot.entryPrice, ltp, ot.direction, s.config)
                    at_sl = StrategyEngine.at_stop(ot.entryPrice, ot.stopLoss, ltp, ot.direction)

                    reason = None
                    if at_tgt: reason = "Target hit"
                    elif at_sl: reason = "Stop loss"
                    elif exit_sig.shouldExit: reason = exit_sig.reason

                    if reason:
                        closed = s.risk_mgr.register_exit(ltp, reason)
                        if closed:
                            s.add_signal(f"CLOSED {ot.direction.value} @ {ltp:.1f} | P&L: {closed.pnl:.0f} | {reason}")
                            sessions.save_closed_trade(s, closed)
            else:
                if s.risk_mgr.can_take_trade() and s.indicator_cache and len(s.candle_cache) > 1:
                    idx = len(s.candle_cache) - 1
                    pcr_bias = get_pcr_bias((fetch_pcr(s.config.script) or {}).get("pcr"), s.config)
                    entry = StrategyEngine.evaluate_entry(s.candle_cache, s.indicator_cache, idx, config=s.config, check_pattern=True, pcr_bias=pcr_bias)
                    if entry:
                        qty = s.config.lotSize
                        tr = TradeRecord(
                            timestamp=int(time.time()), script=s.config.script,
                            direction=entry.direction, entryPrice=entry.entryPrice,
                            stopLoss=entry.stopLoss, target=entry.target, quantity=qty,
                            signalsMet=entry.signalsMet, totalSignals=entry.totalSignals,
                        )
                        s.risk_mgr.register_entry(tr)
                        s.add_signal(f"ENTRY {entry.direction.value} @ {entry.entryPrice:.1f} | {entry.signalsMet}/{entry.totalSignals} signals")
                    else:
                        s.add_signal("No entry signal this cycle")

        except asyncio.CancelledError:
            break
        except Exception as e:
            s.add_signal(f"Error: {e}")

        await asyncio.sleep(60)

# ─── Main ─────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8050, reload=False)
