"""
AutoTrader Engine
Technical Indicators, Strategy Engine, Risk Manager
"""
import math
import re
from dataclasses import dataclass, field
from typing import Optional
from enum import Enum
from datetime import datetime, timedelta
import requests
from bs4 import BeautifulSoup
import numpy as np
import pandas as pd
import yfinance as yf

# ─── Data Types ───────────────────────────────────────────────

@dataclass
class Candle:
    timestamp: int = 0
    open: float = 0.0
    high: float = 0.0
    low: float = 0.0
    close: float = 0.0
    volume: int = 0

class SuperTrendSignal(Enum):
    GREEN = "GREEN"
    RED = "RED"

class TradeDirection(Enum):
    CE = "CE"
    PE = "PE"

@dataclass
class IndicatorValues:
    emas: dict = field(default_factory=dict)  # period -> list
    rsi14: list = field(default_factory=list)
    rsiMa20: list = field(default_factory=list)
    vwap: list = field(default_factory=list)
    superTrend: list = field(default_factory=list)
    atr14: list = field(default_factory=list)

    @property
    def ema9(self): return self.emas.get(9, [])
    @property
    def ema27(self): return self.emas.get(27, [])

@dataclass
class TradingConfig:
    lotSize: int = 65
    capital: float = 50000.0
    script: str = "NIFTY"
    brokerType: str = "Paper Trade"
    maxTradesPerDay: int = 3
    dailyProfitCapPct: float = 5.0
    targetProfitPct: float = 3.0
    stPeriod: int = 10
    stMultiplier: float = 3.0
    candleZonePct: float = 0.5
    rsiCe: float = 55.0
    rsiPe: float = 45.0
    emaCe1: int = 9
    emaCe2: int = 27
    emaPe1: int = 9
    emaPe2: int = 27
    pcrBullish: float = 1.2
    pcrBearish: float = 0.8

@dataclass
class TradeRecord:
    timestamp: int = 0
    script: str = ""
    direction: TradeDirection = TradeDirection.CE
    entryPrice: float = 0.0
    exitPrice: Optional[float] = None
    stopLoss: float = 0.0
    target: float = 0.0
    quantity: int = 0
    pnl: Optional[float] = None
    exitReason: Optional[str] = None
    signalsMet: int = 0
    totalSignals: int = 0

@dataclass
class EntrySignal:
    direction: TradeDirection = TradeDirection.CE
    signalsMet: int = 0
    totalSignals: int = 5
    details: dict = field(default_factory=dict)
    entryPrice: float = 0.0
    stopLoss: float = 0.0
    target: float = 0.0
    reason: str = ""

@dataclass
class ExitSignal:
    shouldExit: bool = False
    reason: str = ""

@dataclass
class BacktestResult:
    totalTrades: int = 0
    wins: int = 0
    losses: int = 0
    winRate: float = 0.0
    netPnl: float = 0.0
    maxDrawdown: float = 0.0
    avgWin: float = 0.0
    avgLoss: float = 0.0
    sharpeRatio: float = 0.0
    maxConsecutiveLosses: int = 0
    totalReturnPct: float = 0.0
    trades: list = field(default_factory=list)

# ─── Technical Indicators ─────────────────────────────────────

def ema(values: list, period: int) -> list:
    if len(values) < period:
        return [0.0] * len(values)
    result = []
    multiplier = 2.0 / (period + 1)
    ema_val = sum(values[:period]) / period
    for i, v in enumerate(values):
        if i < period - 1:
            result.append(0.0)
        elif i == period - 1:
            result.append(ema_val)
        else:
            ema_val = (v - ema_val) * multiplier + ema_val
            result.append(ema_val)
    return result

def sma(values: list, period: int) -> list:
    if len(values) < period:
        return [0.0] * len(values)
    result = []
    for i in range(len(values)):
        if i < period - 1:
            result.append(0.0)
        else:
            result.append(sum(values[i - period + 1:i + 1]) / period)
    return result

def rsi(values: list, period: int = 14) -> list:
    if len(values) < period + 1:
        return [50.0] * len(values)
    gains, losses = [], []
    for i in range(1, len(values)):
        diff = values[i] - values[i - 1]
        gains.append(max(diff, 0))
        losses.append(max(-diff, 0))

    result = [50.0] * period
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    rs = avg_gain / avg_loss if avg_loss != 0 else 100.0
    result.append(100.0 - 100.0 / (1.0 + rs))

    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
        rs = avg_gain / avg_loss if avg_loss != 0 else 100.0
        result.append(100.0 - 100.0 / (1.0 + rs))

    return result[:len(values)]

def vwap(candles: list) -> list:
    if not candles:
        return []
    total_vol = sum(c.volume for c in candles)
    if total_vol == 0:
        # equal-weight VWAP = SMA of typical price (no volume data)
        tps = [(c.high + c.low + c.close) / 3.0 for c in candles]
        cum, n = 0.0, 0
        result = []
        for tp in tps:
            n += 1
            cum += tp
            result.append(cum / n)
        return result
    cum_pv, cum_vol = 0.0, 0
    result = []
    for c in candles:
        tp = (c.high + c.low + c.close) / 3.0
        cum_pv += tp * c.volume
        cum_vol += c.volume
        result.append(cum_pv / cum_vol)
    return result

def atr(candles: list, period: int = 14) -> list:
    if len(candles) < 2:
        return [0.0] * len(candles)
    trs = []
    for i in range(1, len(candles)):
        hl = candles[i].high - candles[i].low
        hc = abs(candles[i].high - candles[i - 1].close)
        lc = abs(candles[i].low - candles[i - 1].close)
        trs.append(max(hl, hc, lc))

    result = [0.0] * period
    first_atr = sum(trs[:period]) / period
    result.append(first_atr)
    for i in range(period, len(trs)):
        first_atr = (first_atr * (period - 1) + trs[i]) / period
        result.append(first_atr)
    while len(result) < len(candles):
        result.append(0.0)
    return result[:len(candles)]

@dataclass
class SuperTrendResult:
    trend: list = field(default_factory=list)
    bands: list = field(default_factory=list)

def super_trend(candles: list, atr_period: int = 10, multiplier: float = 3.0) -> SuperTrendResult:
    atr_vals = atr(candles, atr_period)
    trend, bands = [], []
    prev_upper = prev_lower = 0.0
    prev_trend = SuperTrendSignal.GREEN

    for i, c in enumerate(candles):
        hl_avg = (c.high + c.low) / 2.0
        if i < atr_period:
            trend.append(SuperTrendSignal.GREEN)
            bands.append(0.0)
            continue

        upper_band = hl_avg + multiplier * atr_vals[i]
        lower_band = hl_avg - multiplier * atr_vals[i]

        new_upper = upper_band if (upper_band < prev_upper or candles[i - 1].close > prev_upper) else prev_upper
        new_lower = lower_band
        final_upper = new_upper
        final_lower = new_lower if (lower_band > prev_lower or candles[i - 1].close < prev_lower) else prev_lower

        current_trend = SuperTrendSignal.RED if c.close <= final_upper else SuperTrendSignal.GREEN
        band = final_upper if current_trend == SuperTrendSignal.RED else final_lower
        trend.append(current_trend)
        bands.append(band)
        prev_upper, prev_lower = final_upper, final_lower
        prev_trend = current_trend

    return SuperTrendResult(trend=trend, bands=bands)

def is_bullish_engulfing(candles: list, idx: int) -> bool:
    if idx < 1:
        return False
    p, c = candles[idx - 1], candles[idx]
    return (p.close < p.open and c.close > c.open and
            c.close > p.close and c.open < p.open)

def is_bearish_engulfing(candles: list, idx: int) -> bool:
    if idx < 1:
        return False
    p, c = candles[idx - 1], candles[idx]
    return (p.close > p.open and c.close < c.open and
            c.close < p.close and c.open > p.open)

def is_hammer(candles: list, idx: int) -> bool:
    if idx < 0 or idx >= len(candles):
        return False
    c = candles[idx]
    body = abs(c.close - c.open)
    if body == 0:
        return False
    lower_wick = min(c.close, c.open) - c.low
    upper_wick = c.high - max(c.close, c.open)
    return (lower_wick >= 2 * body and upper_wick <= body * 0.3 and c.close > c.open)

def is_shooting_star(candles: list, idx: int) -> bool:
    if idx < 0 or idx >= len(candles):
        return False
    c = candles[idx]
    body = abs(c.close - c.open)
    if body == 0:
        return False
    lower_wick = min(c.close, c.open) - c.low
    upper_wick = c.high - max(c.close, c.open)
    return (upper_wick >= 2 * body and lower_wick <= body * 0.3 and c.close < c.open)

def compute_all(candles: list, config: Optional[TradingConfig] = None) -> IndicatorValues:
    closes = [c.close for c in candles]
    periods = set()
    if config:
        periods.update([config.emaCe1, config.emaCe2, config.emaPe1, config.emaPe2])
    if not periods:
        periods = {9, 27}
    emas = {}
    for p in sorted(periods):
        emas[p] = ema(closes, p)
    return IndicatorValues(
        emas=emas,
        rsi14=rsi(closes, 14),
        rsiMa20=sma(rsi(closes, 14), 20),
        vwap=vwap(candles),
        superTrend=super_trend(candles).trend,
        atr14=atr(candles, 14)
    )

# ─── Strategy Engine ──────────────────────────────────────────

class StrategyEngine:
    @staticmethod
    def evaluate_entry(candles: list, ind: IndicatorValues, idx: int,
                       config: Optional[TradingConfig] = None,
                       check_pattern: bool = True,
                       pcr_bias: str = "NEUTRAL") -> Optional[EntrySignal]:
        if len(candles) < 28 or idx < 1:
            return None

        cfg = config or TradingConfig()
        ce_e1 = cfg.emaCe1
        ce_e2 = cfg.emaCe2
        pe_e1 = cfg.emaPe1
        pe_e2 = cfg.emaPe2

        cur = candles[idx]
        close = cur.close
        vw = ind.vwap[idx] if len(ind.vwap) > idx else 0
        eCe1 = ind.emas.get(ce_e1, [])[idx] if len(ind.emas.get(ce_e1, [])) > idx else 0
        eCe2 = ind.emas.get(ce_e2, [])[idx] if len(ind.emas.get(ce_e2, [])) > idx else 0
        ePe1 = ind.emas.get(pe_e1, [])[idx] if len(ind.emas.get(pe_e1, [])) > idx else 0
        ePe2 = ind.emas.get(pe_e2, [])[idx] if len(ind.emas.get(pe_e2, [])) > idx else 0
        r14 = ind.rsi14[idx] if len(ind.rsi14) > idx else 50
        st = ind.superTrend[idx] if len(ind.superTrend) > idx else SuperTrendSignal.GREEN
        at = ind.atr14[idx] if len(ind.atr14) > idx else 0

        if eCe1 == 0 or eCe2 == 0 or ePe1 == 0 or ePe2 == 0 or vw == 0:
            return None

        # Skip if near VWAP
        if abs(close - vw) / vw * 100 <= cfg.candleZonePct:
            return None

        ce_sigs = {
            "price_above_vwap": close > vw,
            "ema_ce": eCe1 > eCe2,
            "st_green": st == SuperTrendSignal.GREEN,
            f"rsi_gt_{cfg.rsiCe:.0f}": r14 > cfg.rsiCe,
            "pcr_bullish": pcr_bias == "CE",
        }
        pe_sigs = {
            "price_below_vwap": close < vw,
            "ema_pe": ePe1 < ePe2,
            "st_red": st == SuperTrendSignal.RED,
            f"rsi_lt_{cfg.rsiPe:.0f}": r14 < cfg.rsiPe,
            "pcr_bearish": pcr_bias == "PE",
        }

        # Add pattern check
        if check_pattern and idx >= 1:
            ce_sigs["bullish_candle"] = is_hammer(candles, idx) or is_bullish_engulfing(candles, idx)
            pe_sigs["bearish_candle"] = is_shooting_star(candles, idx) or is_bearish_engulfing(candles, idx)
        else:
            ce_sigs["bullish_candle"] = False
            pe_sigs["bearish_candle"] = False

        # Filter by PCR bias: skip opposite-direction signals
        total = 6  # 5 original + 1 PCR bias signal
        min_sig = 3
        sl_pct = at * 1.5 / close if at > 0 else 0.02

        if pcr_bias != "PE":
            ce_met = sum(1 for v in ce_sigs.values() if v)
            if ce_met >= min_sig and ce_sigs.get("ema_ce", False) and any(k.startswith("rsi_gt") for k in ce_sigs if ce_sigs[k]):
                sl = close * (1.0 - sl_pct)
                target = close * (1.0 + cfg.targetProfitPct / 100.0)
                met_list = ", ".join(k for k, v in ce_sigs.items() if v)
                return EntrySignal(
                    direction=TradeDirection.CE, signalsMet=ce_met, totalSignals=total,
                    details=ce_sigs, entryPrice=close, stopLoss=sl, target=target,
                    reason=f"CE entry: {ce_met}/{total} ({met_list})"
                )

        if pcr_bias != "CE":
            pe_met = sum(1 for v in pe_sigs.values() if v)
            if pe_met >= min_sig and pe_sigs.get("ema_pe", False) and any(k.startswith("rsi_lt") for k in pe_sigs if pe_sigs[k]):
                sl = close * (1.0 + sl_pct)
                target = close * (1.0 - cfg.targetProfitPct / 100.0)
                met_list = ", ".join(k for k, v in pe_sigs.items() if v)
                return EntrySignal(
                    direction=TradeDirection.PE, signalsMet=pe_met, totalSignals=total,
                    details=pe_sigs, entryPrice=close, stopLoss=sl, target=target,
                    reason=f"PE entry: {pe_met}/{total} ({met_list})"
                )

        return None

    @staticmethod
    def evaluate_exit(direction: TradeDirection, candles: list, ind: IndicatorValues,
                      idx: int) -> ExitSignal:
        if idx < 1:
            return ExitSignal(False, "")
        r14 = ind.rsi14[idx] if len(ind.rsi14) > idx else 50
        rma = ind.rsiMa20[idx] if len(ind.rsiMa20) > idx else 50

        if direction == TradeDirection.CE and r14 < rma:
            return ExitSignal(True, f"RSI({r14:.1f}) < RSI MA({rma:.1f})")
        if direction == TradeDirection.PE and r14 > rma:
            return ExitSignal(True, f"RSI({r14:.1f}) > RSI MA({rma:.1f})")

        # Hourly check
        if len(candles) >= idx + 1:
            c = candles[idx]
            if direction == TradeDirection.CE and c.close < c.open:
                return ExitSignal(True, "Hourly bearish candle")
            if direction == TradeDirection.PE and c.close > c.open:
                return ExitSignal(True, "Hourly bullish candle")

        return ExitSignal(False, "")

    @staticmethod
    def at_target(entry: float, current: float, direction: TradeDirection,
                  config: Optional[TradingConfig] = None) -> bool:
        cfg = config or TradingConfig()
        pct = (current - entry) / entry * 100
        return pct >= cfg.targetProfitPct if direction == TradeDirection.CE else -pct >= cfg.targetProfitPct

    @staticmethod
    def at_stop(entry: float, sl: float, current: float, direction: TradeDirection) -> bool:
        return current <= sl if direction == TradeDirection.CE else current >= sl

# ─── Risk Manager ────────────────────────────────────────────

class RiskManager:
    def __init__(self, config: TradingConfig):
        self.config = config
        self.trades_today = []
        self.open_trade = None

    @property
    def daily_capital(self): return self.config.capital
    @property
    def daily_profit_cap(self): return self.config.capital * self.config.dailyProfitCapPct / 100.0
    @property
    def max_trades(self): return self.config.maxTradesPerDay

    def reset_day(self):
        self.trades_today.clear()
        self.open_trade = None

    def can_take_trade(self):
        if self.open_trade:
            return False
        if len(self.trades_today) >= self.max_trades:
            return False
        if self.current_pnl() >= self.daily_profit_cap:
            return False
        return True

    def register_entry(self, trade: TradeRecord):
        self.open_trade = trade

    def register_exit(self, exit_price: float, reason: str) -> Optional[TradeRecord]:
        if not self.open_trade:
            return None
        diff = exit_price - self.open_trade.entryPrice if self.open_trade.direction == TradeDirection.CE \
            else self.open_trade.entryPrice - exit_price
        pnl = diff * self.open_trade.quantity
        completed = TradeRecord(
            timestamp=self.open_trade.timestamp, script=self.open_trade.script,
            direction=self.open_trade.direction, entryPrice=self.open_trade.entryPrice,
            exitPrice=exit_price, stopLoss=self.open_trade.stopLoss, target=self.open_trade.target,
            quantity=self.open_trade.quantity, pnl=pnl, exitReason=reason,
            signalsMet=self.open_trade.signalsMet, totalSignals=self.open_trade.totalSignals,
        )
        self.trades_today.append(completed)
        self.open_trade = None
        return completed

    def current_pnl(self):
        return sum(t.pnl or 0 for t in self.trades_today)

    def is_daily_cap_hit(self):
        return self.current_pnl() >= self.daily_profit_cap

    def is_max_trade_reached(self):
        return len(self.trades_today) >= self.max_trades

    def trades_count(self):
        return len(self.trades_today)

# ─── Paper Broker (Yahoo Finance) ────────────────────────────

YF_SYMBOL_MAP = {
    "NIFTY": "^NSEI",
    "BANKNIFTY": "^NSEBANK",
    "SENSEX": "^BSESN",
    "FINNIFTY": "NIFTY_FIN_SERV.NS",
    "MIDCPNIFTY": "^NSEMDCP50",
}

def _yf_symbol(symbol: str) -> str:
    s = symbol.strip().upper()
    if s in YF_SYMBOL_MAP:
        return YF_SYMBOL_MAP[s]
    return f"{s}.NS"

def fetch_candles(symbol: str, interval: str = "5m", period: str = "1mo") -> list:
    """Fetch candles from Yahoo Finance."""
    try:
        ticker = yf.Ticker(_yf_symbol(symbol))
        df = ticker.history(period=period, interval=interval)
        if df.empty:
            return []
        candles = []
        for idx, row in df.iterrows():
            candles.append(Candle(
                timestamp=int(idx.timestamp()),
                open=float(row["Open"]), high=float(row["High"]),
                low=float(row["Low"]), close=float(row["Close"]),
                volume=int(row["Volume"])
            ))
        return candles
    except Exception:
        return []

def get_ltp(symbol: str) -> Optional[float]:
    """Get latest price."""
    try:
        ticker = yf.Ticker(_yf_symbol(symbol))
        df = ticker.history(period="1d", interval="1m")
        if not df.empty:
            return float(df["Close"].iloc[-1])
        return None
    except Exception:
        return None

# ─── PCR Bias ─────────────────────────────────────────────────

def get_pcr_bias(pcr_val: Optional[float], config: Optional[TradingConfig] = None) -> str:
    if pcr_val is None:
        return "NEUTRAL"
    cfg = config or TradingConfig()
    if pcr_val >= cfg.pcrBullish:
        return "CE"
    if pcr_val <= cfg.pcrBearish:
        return "PE"
    return "NEUTRAL"

# ─── Backtest Engine ─────────────────────────────────────────

def run_backtest(candles: list, config: TradingConfig) -> BacktestResult:
    if len(candles) < 50:
        return BacktestResult()

    ind = compute_all(candles, config)
    trades = []
    capital = config.capital
    peak_capital = capital
    max_dd = 0.0
    daily_trades = 0
    daily_pnl = 0.0
    last_day = -1
    consec_losses = 0
    max_cl = 0
    in_pos = False
    open_tr = None
    daily_cap = config.capital * config.dailyProfitCapPct / 100.0

    for i in range(50, len(candles)):
        c = candles[i]
        day = datetime.fromtimestamp(c.timestamp).timetuple().tm_yday

        if day != last_day:
            daily_trades = 0
            daily_pnl = 0.0
            last_day = day

        if in_pos and open_tr:
            exit_sig = StrategyEngine.evaluate_exit(open_tr.direction, candles, ind, i)
            at_tgt = StrategyEngine.at_target(open_tr.entryPrice, c.close, open_tr.direction, config)
            at_sl = StrategyEngine.at_stop(open_tr.entryPrice, open_tr.stopLoss, c.close, open_tr.direction)

            exit_price, exit_reason = None, None
            if at_tgt:
                exit_price, exit_reason = open_tr.target, "Target hit"
            elif at_sl:
                exit_price, exit_reason = open_tr.stopLoss, "Stop loss"
            elif exit_sig.shouldExit:
                exit_price, exit_reason = c.close, exit_sig.reason

            if exit_price is not None:
                diff = exit_price - open_tr.entryPrice if open_tr.direction == TradeDirection.CE \
                    else open_tr.entryPrice - exit_price
                pnl = diff * open_tr.quantity
                completed = TradeRecord(
                    timestamp=c.timestamp, script=config.script, direction=open_tr.direction,
                    entryPrice=open_tr.entryPrice, exitPrice=exit_price,
                    stopLoss=open_tr.stopLoss, target=open_tr.target, quantity=open_tr.quantity,
                    pnl=pnl, exitReason=exit_reason, signalsMet=open_tr.signalsMet,
                    totalSignals=open_tr.totalSignals,
                )
                trades.append(completed)
                capital += pnl
                daily_pnl += pnl
                daily_trades += 1
                consec_losses = 0 if pnl > 0 else consec_losses + 1
                max_cl = max(max_cl, consec_losses)
                in_pos = False
                open_tr = None

                if capital > peak_capital:
                    peak_capital = capital
                dd = (peak_capital - capital) / peak_capital * 100
                if dd > max_dd:
                    max_dd = dd
            continue

        if daily_trades >= config.maxTradesPerDay or daily_pnl >= daily_cap:
            continue

        entry = StrategyEngine.evaluate_entry(candles, ind, i, config=config, check_pattern=False)
        if entry:
            qty = config.lotSize  # 1 lot
            tr = TradeRecord(
                timestamp=c.timestamp, script=config.script, direction=entry.direction,
                entryPrice=entry.entryPrice, stopLoss=entry.stopLoss, target=entry.target,
                quantity=qty, signalsMet=entry.signalsMet, totalSignals=entry.totalSignals,
            )
            in_pos = True
            open_tr = tr

    wins = sum(1 for t in trades if t.pnl and t.pnl > 0)
    losses = sum(1 for t in trades if t.pnl and t.pnl < 0)
    total = len(trades)
    wr = wins / total * 100 if total > 0 else 0
    net = sum(t.pnl or 0 for t in trades)
    ret = net / config.capital * 100 if config.capital > 0 else 0
    avg_w = sum(t.pnl for t in trades if t.pnl and t.pnl > 0) / wins if wins > 0 else 0
    avg_l = sum(t.pnl for t in trades if t.pnl and t.pnl < 0) / losses if losses > 0 else 0

    returns_list = [t.pnl or 0 for t in trades]
    sharpe = 0.0
    if len(returns_list) > 1:
        mean_r = sum(returns_list) / len(returns_list)
        var_r = sum((r - mean_r) ** 2 for r in returns_list) / len(returns_list)
        std_r = math.sqrt(var_r) if var_r > 0 else 1
        sharpe = mean_r / std_r * math.sqrt(252) if std_r > 0 else 0

    trade_dicts = []
    for t in trades:
        ts = datetime.fromtimestamp(t.timestamp).strftime("%Y-%m-%d %H:%M") if t.timestamp else ""
        trade_dicts.append({
            "time": ts, "direction": t.direction.value, "entry": round(t.entryPrice, 2),
            "exit": round(t.exitPrice, 2) if t.exitPrice else None,
            "pnl": round(t.pnl, 2) if t.pnl else 0, "reason": t.exitReason or "",
            "signals": f"{t.signalsMet}/{t.totalSignals}"
        })

    return BacktestResult(
        totalTrades=total, wins=wins, losses=losses, winRate=round(wr, 1),
        netPnl=round(net, 2), maxDrawdown=round(max_dd, 2),
        avgWin=round(avg_w, 2), avgLoss=round(avg_l, 2),
        sharpeRatio=round(sharpe, 2), maxConsecutiveLosses=max_cl,
        totalReturnPct=round(ret, 2), trades=trade_dicts,
    )

# ─── PCR (Put-Call Ratio) ──────────────────────────────────────

def fetch_pcr(symbol: str = "NIFTY") -> Optional[dict]:
    """Fetch Put-Call Ratio from niftyinvest.com.

    Returns dict with pcr (total OI) and/or coi_pcr (change in OI),
    or None if unavailable.
    """
    try:
        r = requests.get(
            f"https://niftyinvest.com/put-call-ratio/{symbol.upper()}",
            headers={"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"},
            timeout=15
        )
        soup = BeautifulSoup(r.text, 'html.parser')
        data = {"source": "niftyinvest", "symbol": symbol.upper()}

        for div in soup.find_all('div', class_='col-3'):
            text = div.get_text(strip=True)
            m = re.match(r'^PCR(\d+\.?\d*)$', text)
            if m:
                data['pcr'] = float(m.group(1))
            m = re.match(r'^COI PCR(\d+\.?\d*)$', text)
            if m:
                data['coi_pcr'] = float(m.group(1))

        if 'pcr' in data or 'coi_pcr' in data:
            return data
        return None
    except Exception:
        return None
