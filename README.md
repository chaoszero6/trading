# Trading Bot — Multi-Agent Indian Markets System

GPU-accelerated trading analysis and paper trading system for NIFTY, BANKNIFTY, and constituents. Uses Angel One SmartAPI for market data and yfinance for backtesting.

## Features

- **Multi-Agent Pipeline** — News analysis, technical indicators, candlestick patterns, options OI/Greeks, risk management
- **GPU Acceleration** — CUDA (Numba) kernels for parallel candlestick pattern detection (doji, engulfing, hammer), RSI, MACD across all 60+ symbols in a single pass
- **Paper Trading** — WebSocket LTP-based paper trading with auto-entry, trailing SL, target hit, and EOD close
- **Discord Bot** — Commands for market status, trade suggestions, paper trading control, P&L tracking
- **Daily Directional Bias** — GPU-powered next-day direction prediction (76% backtested accuracy)
- **Learning Agent** — SQLite-backed trade journal that auto-syncs from paper trades and tracks win rates, patterns, lessons
- **Real-Time Monitor** — 1-min monitoring loop for automated entry/exit during market hours
- **AutoTrader Android App** — Kotlin/Jetpack Compose app with multi-broker support (Angel One, Dhan, ICICI Direct, Upstox, Zerodha, paper), backtesting, and Room DB trade history
- **Web Dashboard** — FastAPI + WebSocket UI for live trading control and P&L
- **Holiday Gate** — Fail-safe NSE holiday calendar guard for all scheduled jobs (skips trading on holidays)

## Commands

| Command | Description |
|---------|-------------|
| `!ping` | Health check |
| `!summary` / `!plan` | Full multi-agent market analysis |
| `!status` | Market status + suggestions |
| `!daily` | Next-day directional bias (NIFTY & BANKNIFTY) |
| `!suggest` | Real-time option LTPs for key strikes |
| `!vwap` | VWAP heat map |
| `!oi` | Open Interest analysis |
| `!news` | Latest market news + sentiment |
| `!ltp <symbol> <strike> <type>` | Option LTP via WebSocket |
| `!eod` | End-of-day accuracy report + next-day prediction |
| `!recommend <amount> <strategy>` | Full analysis + trade suggestion |
| `!papertrade` / `!pt` | Paper trading controls |
| `!pnl` | P&L statement from today's paper trades |

## Architecture

```
discord_bot.py          — Discord entry point, command handlers
agents/
  prediction_agent.py   — GPU daily/5-min/15-min directional prediction + backtesting
  trader_manager.py     — Orchestrator: gathers all agent data
  trader_agent.py       — Strategy generation
  news_agent.py         — News fetch + sentiment analysis
  risk_manager.py       — Position sizing, capital checks
  trading_expert.py     — Options OI/PCR analysis, strike suggestions
  paper_trader.py       — WebSocket LTP paper trading engine
  realtime_monitor.py   — 1-min auto-trading loop
  learning_agent.py     — Trade journal, win rate, lessons
  python_expert.py      — Quantitative analysis helper
  ai_watcher.py         — Process health monitoring
core/
  gpu_candlestick.py    — CUDA kernels: doji, engulfing, hammer detection
  gpu_signals.py        — CUDA kernels: batch RSI, MACD, Bollinger Bands
  gpu_options.py        — CUDA Black-Scholes options pricing
  angel_bridge.py       — Angel One SmartAPI REST + WebSocket client
  market_data.py        — Market data aggregator
  technical_indicators.py  — CPU fallback indicators
data/
  papertrades.db        — Paper trade records
  learning.db           — Learning agent journal (auto-synced)
  predictions.db        — Prediction backtest results
AutoTrader/              — Android app (Kotlin/Compose, multi-broker, backtesting)
autotrader_web/          — FastAPI web dashboard + trading engine
scripts/
  holiday_gate.py        — Importable holiday gate (should_run_trading, guard_or_exit)
  holiday_guard.sh       — Sourceable bash guard for scheduled jobs
  holidays/              — NSE market calendar data + cache
  gate_detail.py         — TIME-EXIT GATE blocked-candidate analysis
  parse_monitor_log.py   — Post-market monitor log analysis
```

## Setup

```bash
# Install dependencies
pip install -r requirements.txt

# Configure environment
cp .env.example .env
# Edit .env with your API keys (Angel One, Discord)

# Start Discord bot
python3 discord_bot.py

# Start auto-monitor
python3 agents/realtime_monitor.py

# Run backtest
python3 agents/prediction_agent.py            # all modes (15m, daily, volume)
python3 agents/prediction_agent.py daily      # daily only
python3 agents/prediction_agent.py live       # live prediction from Angel One

# Post-market analysis
python3 scripts/parse_monitor_log.py           # monitor log summary + trade events
python3 scripts/gate_detail.py                 # blocked-candidate RSI analysis

# Web dashboard
cd autotrader_web && python3 main.py
```

## Backtest Results (Daily Directional Bias)

| Mode | Accuracy | High-Conf Accuracy |
|------|----------|--------------------|
| 5-min | 8.8% | 9.8% |
| 15-min | 16.8% | 7.3% |
| **Daily** | **68.4%** | **76.4%** |
| 5-min+Volume | 12.3% | 4.4% |

Daily mode across 57 symbols over ~227 trading days: 13,507 predictions, 9,239 correct (68.4%), with 76.4% accuracy on high-confidence predictions.

## Requirements

- Python 3.10+
- CUDA-capable GPU (NVIDIA with compute capability 5.0+)
- Angel One trading account (SmartAPI)
- Discord bot token & channel ID
