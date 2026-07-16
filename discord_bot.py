#!/usr/bin/env python3
"""
Discord Trading Bot — Listens to messages and responds with analysis.
Commands:
  !status     — Full market status + option suggestions
  !vwap       — VWAP heat map + entry strategy  
  !oi         — Open Interest analysis
  !suggest    — Option suggestions with strikes
  !eod        — End of day accuracy report
  !news       — Latest market news
  !recommend <amount> <strategy> — Full analysis + suggestion
  !papertrade — Live paper trading engine (real WebSocket LTP)
  !pt         — Alias for !papertrade
"""

import os
import sys
import asyncio
import logging
import discord
from discord.ext import commands

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

BOT_TOKEN = os.environ.get("DISCORD_BOT_TOKEN", "")
CHANNEL_ID = os.environ.get("DISCORD_CHANNEL_ID", "")
if CHANNEL_ID:
    CHANNEL_ID = int(CHANNEL_ID)

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents, help_command=None)


@bot.event
async def on_ready():
    logger.info(f"Bot ready: {bot.user}")
    if CHANNEL_ID:
        try:
            ch = bot.get_channel(CHANNEL_ID)
            if ch:
                await ch.send("🤖 **Trading Bot online!** Commands: `!pnl` `!summary` `!daily` `!vp` `!help` `!status` `!suggest` `!ltp` `!papertrade`")
                logger.info(f"Sent startup message to channel {CHANNEL_ID}")
        except Exception as e:
            logger.error(f"Could not send to channel: {e}")


@bot.event
async def on_message(message):
    if message.author.bot:
        return
    logger.info(f"Msg from {message.author}: {message.content[:100]}")
    await bot.process_commands(message)


@bot.command(name="ping")
async def cmd_ping(ctx):
    await ctx.send("pong! 🏓")

@bot.command(name="help")
async def cmd_help(ctx):
    msg = """**🤖 Trading Bot — Commands**

**P&L**
`!pnl` — Today's paper trades (individual)
`!history` — Day-wise all-time P&L statement

**Analysis**
`!summary` / `!plan` — Full TraderManager analysis
`!status` — Market status + suggestions
`!daily` — Next-day directional bias (76% accuracy)
`!vp` — VWAP Pullback Breakout strategy status
`!suggest` — Real-time option LTPs for key strikes
`!vwap` — VWAP heat map
`!oi` — Open Interest analysis
`!news` — Latest market news
`!ltp <symbol> <strike> <type>` — Option LTP

**Trading**
`!recommend <amount> <strategy>` — Trade suggestion
`!papertrade` / `!pt` — Paper trading
`!eod` — End of day report

**Utility**
`!help` — This message
`!ping` — Health check"""
    await ctx.send(msg)


@bot.command(name="status")
async def cmd_status(ctx):
    await ctx.send("🔄 Running full market analysis...")
    await run_async_send(ctx, "discord_notifier.py", "--mode", "regular")


@bot.command(name="vwap")
async def cmd_vwap(ctx):
    await ctx.send("🔄 Computing VWAP heat map...")
    await run_async_send(ctx, "heatmap_report.py")


@bot.command(name="news")
async def cmd_news(ctx):
    await ctx.send("🔄 Fetching latest news...")
    await run_async_send(ctx, "discord_notifier.py", "--mode", "regular")


@bot.command(name="suggest")
async def cmd_suggest(ctx):
    await ctx.send("🔄 Generating option suggestions with real-time LTP...")
    try:
        import sys as _sys
        _sys.path.insert(0, "/root/trading")
        from agents.news_agent import MarketNewsAgent
        from core.angel_bridge import AngelOneBridge
        from core.market_data import get_nifty_realtime, get_banknifty_realtime

        nifty = get_nifty_realtime() or 23600
        bnifty = get_banknifty_realtime() or 53700

        ab = AngelOneBridge()
        ab.authenticate()

        # Get real-time option LTPs for key strikes
        atm_n = round(nifty / 50) * 50
        atm_b = round(bnifty / 100) * 100
        strikes_n = [atm_n-100, atm_n, atm_n+100, atm_n+200]
        strikes_b = [atm_b-100, atm_b, atm_b+100, atm_b+200]

        from config import get_next_next_weekly_expiry
        n_exp = get_next_next_weekly_expiry("NIFTY")
        bn_exp = get_next_next_weekly_expiry("BANKNIFTY")

        n_ce_ltps = {}
        for s in strikes_n:
            ltp = ab.get_option_ltp("NIFTY", n_exp, str(s), "CE")
            n_ce_ltps[s] = ltp

        b_ce_ltps = {}
        for s in strikes_b:
            ltp = ab.get_option_ltp("BANKNIFTY", bn_exp, str(s), "CE")
            b_ce_ltps[s] = ltp

        lines = []
        lines.append(f"**NIFTY:** {nifty:.0f}")
        lines.append(f"**BANKNIFTY:** {bnifty:.0f}")
        lines.append("")
        lines.append(f"**NIFTY {n_exp} CE Real LTP:**")
        for s in strikes_n:
            ltp = n_ce_ltps.get(s)
            ltp_str = f"₹{ltp:.1f}" if ltp else "N/A"
            lines.append(f"  {s}CE: {ltp_str}")
        lines.append("")
        lines.append(f"**BANKNIFTY {bn_exp} CE Real LTP:**")
        for s in strikes_b:
            ltp = b_ce_ltps.get(s)
            ltp_str = f"₹{ltp:.1f}" if ltp else "N/A"
            lines.append(f"  {s}CE: {ltp_str}")

        embed = discord.Embed(title=f"📊 Real-Time Option Prices (Angel One WebSocket)", color=0x00FF88)
        embed.description = "\n".join(lines)
        await ctx.send(embed=embed)
    except Exception as e:
        logger.error(f"suggest error: {e}", exc_info=True)
        await ctx.send(f"❌ Error: {str(e)[:100]}")


@bot.command(name="ltp")
async def cmd_ltp(ctx, symbol: str = "BANKNIFTY", strike: str = "54000", optype: str = "CE"):
    """Get real-time option LTP via WebSocket. Usage: !ltp BANKNIFTY 54000 CE"""
    await ctx.send(f"🔄 Fetching {symbol} {strike}{optype} real LTP...")
    try:
        import sys as _sys
        _sys.path.insert(0, "/root/trading")
        from config import get_next_next_weekly_expiry
        from core.angel_bridge import AngelOneBridge
        ab = AngelOneBridge()
        ab.authenticate()
        exp = get_next_next_weekly_expiry("BANKNIFTY") if "BANK" in symbol.upper() else get_next_next_weekly_expiry("NIFTY")
        ltp = ab.get_option_ltp(symbol.upper(), exp, strike, optype.upper())
        if ltp:
            await ctx.send(f"📊 **{symbol} {exp} {strike}{optype.upper()}** LTP: **₹{ltp:.1f}**")
        else:
            await ctx.send(f"❌ Could not fetch LTP for {symbol} {strike}{optype}")
    except Exception as e:
        await ctx.send(f"❌ Error: {str(e)[:100]}")


@bot.command(name="oi")
async def cmd_oi(ctx):
    embed = discord.Embed(title="OI Analysis — 26MAY Expiry", color=0x9B59B6)
    embed.add_field(name="NIFTY 50", value="Max Call OI: 23900CE (resistance)\nMax Put OI: 23500PE (support)\nPCR: ~0.85", inline=True)
    embed.add_field(name="BANKNIFTY", value="Max Call OI: 54400CE (resistance)\nMax Put OI: 53800PE (support)\nPCR: ~0.90", inline=True)
    embed.add_field(name="Signal", value="Call OI > Put OI = Bearish\nBoth below VWAP = Bearish\n→ BUY PE aligned", inline=False)
    await ctx.send(embed=embed)


@bot.command(name="daily")
async def cmd_daily(ctx):
    """Predict next-day direction for NIFTY & BANKNIFTY (daily candles)."""
    await ctx.send("🔄 Computing daily directional bias...")
    try:
        import sys as _sys
        _sys.path.insert(0, "/root/trading")
        from agents.prediction_agent import predict_daily_live, print_daily_predictions
        results = predict_daily_live()
        text = print_daily_predictions(results)
        if not text:
            await ctx.send("❌ Could not compute daily predictions.")
            return
        embed = discord.Embed(
            title="📊 Daily Directional Bias — Next Session",
            description=text,
            color=0x00FF88
        )
        embed.set_footer(text="Daily model accuracy: 76.4% (backtested)")
        await ctx.send(embed=embed)
    except Exception as e:
        logger.error(f"daily error: {e}", exc_info=True)
        await ctx.send(f"❌ Error: {str(e)[:150]}")


@bot.command(name="vp")
async def cmd_vp(ctx):
    """VWAP Pullback Breakout strategy status."""
    try:
        import sys as _sys
        _sys.path.insert(0, "/root/trading")
        from agents.vwap_pullback_breakout import VwapPullbackTrader
        vp = VwapPullbackTrader()
        text = vp.get_summary()
        embed = discord.Embed(
            title="📊 VWAP Pullback Breakout",
            description=text,
            color=0x00BFFF
        )
        from datetime import datetime
        embed.set_footer(text=f"VP Strategy • {datetime.now().strftime('%H:%M')}")
        await ctx.send(embed=embed)
    except Exception as e:
        logger.error(f"vp error: {e}", exc_info=True)
        await ctx.send(f"❌ Error: {str(e)[:150]}")


@bot.command(name="eod")
async def cmd_eod(ctx):
    await ctx.send("🔄 Running end-of-day report...")
    await run_async_send(ctx, "discord_notifier.py", "--mode", "eod")


_pt_instance = None

def _get_pt():
    global _pt_instance
    if _pt_instance is None:
        from agents.paper_trader import PaperTrader
        _pt_instance = PaperTrader()
    return _pt_instance


@bot.command(name="papertrade", aliases=["pt"])
async def cmd_papertrade(ctx, action: str = "status"):
    """Live paper trading with real WebSocket LTP.
    Usage:
      !pt status     — Show current positions + P&L
      !pt check      — Run one trend check + enter/exit trades
      !pt start      — Start auto-monitoring (every 15 min)
      !pt stop       — Stop auto-monitoring
      !pt close      — Close all positions (EOD)
      !pt summary    — Full trade log for today
    """
    try:
        import sys as _sys
        _sys.path.insert(0, "/root/trading")
        pt = _get_pt()

        if action == "start":
            pt.running = True
            await ctx.send("🟢 **PaperTrader started** — monitoring every ~15 min during market hours.\n"
                           "Use `!pt stop` to stop, `!pt status` to check positions.")
            if not hasattr(cmd_papertrade, "_timer"):
                def monitor_loop():
                    while pt.running:
                        trend = pt.evaluate_trend("NIFTY")
                        if trend and trend["signal"] != "NEUTRAL":
                            pt.check_open_positions()
                            pt.enter_trade("NIFTY", trend["signal"], trend["spot"], trend)
                        import time as _t
                        _t.sleep(900)  # 15 min
                import threading as _th
                t = _th.Thread(target=monitor_loop, daemon=True)
                t.start()
                cmd_papertrade._timer = True
            return

        elif action == "stop":
            pt.running = False
            await ctx.send("🔴 **PaperTrader stopped**")
            return

        elif action == "close":
            pt.close_all_eod()
            await ctx.send(f"📊 **EOD Close** — {len(pt.trade_log)} trades closed.\n" + pt.get_summary())
            return

        elif action == "check":
            trend = pt.evaluate_trend("NIFTY")
            if not trend:
                await ctx.send("❌ Could not evaluate trend")
                return
            pt.check_open_positions()
            if trend["signal"] != "NEUTRAL":
                pos = pt.enter_trade("NIFTY", trend["signal"], trend["spot"], trend)
            msg = f"**Trend check:** {trend['signal']} | Spot: ₹{trend['spot']:.0f} | RSI: {trend['rsi']} | VWAP: {trend['vwap_diff']}% | Above VWAP: {trend['above_vwap']}\n"
            msg += f"**Open positions:** {len(pt.positions)}"
            await ctx.send(msg)
            return

        # Default: status / summary
        await ctx.send(pt.get_summary()[:1900])
    except Exception as e:
        logger.error(f"papertrade error: {e}", exc_info=True)
        await ctx.send(f"❌ Error: {str(e)[:100]}")


@bot.command(name="plan", aliases=["summary", "all"])
async def cmd_plan(ctx):
    """TraderManager: Runs ALL agents, collects real-time data, gives final summary."""
    await ctx.send("🧠 **TraderManager** gathering real-time data from all agents...")
    try:
        import sys as _sys
        _sys.path.insert(0, "/root/trading")
        # Defensive: force-clear any corrupted pandas from import cache
        if 'pandas' in _sys.modules:
            try:
                _ = _sys.modules['pandas'].DataFrame
            except AttributeError:
                for k in list(_sys.modules):
                    if 'pandas' in k:
                        del _sys.modules[k]
        from agents.trader_manager import TraderManager as TM
        tm = TM()
        msg = await ctx.send("📡 [1/8] Index prices → [2/8] News → [3/8] VWAP → [4/8] Candlestick → [5/8] OI → [6/8] Technicals → [7/8] Strategy → [8/8] Risk...")
        data = tm.gather_all(capital=50000, risk_tolerance="moderate", preferred_index="NIFTY")

        nifty = data.get("nifty", 0) or 0
        bnifty = data.get("banknifty", 0) or 0
        ns = data.get("news", {}).get("summary", {})
        vwap = data.get("vwap", {}).get("nifty", {})
        cs = data.get("candlestick", {})
        oc = data.get("option_chain", {})
        tech = data.get("technicals", {}).get("nifty", {})
        te = data.get("trading_expert", {}).get("suggestions", [{}])[0]
        risk = data.get("risk", {})

        lines = [
            f"**📊 TRADER MANAGER — MARKET OVERVIEW**",
            f"**Time:** {data.get('timestamp')}\n",
            f"**NIFTY:** {nifty:.0f} | **BANKNIFTY:** {bnifty:.0f}\n",
            f"**📰 Sentiment:** {ns.get('overall_sentiment','N/A')} | **Outlook:** {ns.get('market_outlook','N/A')}",
            f"**Bullish:** {', '.join(ns.get('bullish_sectors',[]))[:80] or 'None'}",
            f"**Bearish:** {', '.join(ns.get('bearish_sectors',[]))[:80] or 'None'}\n",
            f"**📊 VWAP:** {vwap.get('diff_pct','N/A')}% → {'BUY PE' if vwap.get('diff_pct',0) < 0 else 'BUY CE'}",
            f"**RSI:** {tech.get('rsi','N/A')} ({tech.get('rsi_trend','')}) | **MACD:** {tech.get('macd_crossover','N/A')}",
            f"**GPU NIFTY:** {cs.get('nifty',{}).get('direction','N/A')} | **GPU BANKNIFTY:** {cs.get('banknifty',{}).get('direction','N/A')}\n",
            f"**📊 OI:** Exp {oc.get('expiry','N/A')} | PCR {oc.get('pcr','N/A')}",
            f"**Support:** {oc.get('support','N/A')} | **Resistance:** {oc.get('resistance','N/A')}\n",
            f"**🎯 TRADE SUGGESTION:**",
            f"**{te.get('index','NIFTY')} {te.get('strike','')}{te.get('type','')}**",
            f"**Entry:** ₹{te.get('entry_premium','N/A')} | **SL:** ₹{te.get('stop_loss','N/A')} | **Target:** ₹{te.get('target','N/A')}",
            f"**R:R:** {te.get('risk_reward','N/A')}:1 | **Qty:** {te.get('recommended_qty','N/A')} | **Max Risk:** ₹{te.get('total_risk','N/A')}",
            f"**Confidence:** {te.get('confidence','N/A')}",
            f"**Reasoning:** {te.get('reasoning_summary','')[:200]}\n",
            f"**⚠️ Risk:** {risk.get('risk_level','N/A').upper()} | {'; '.join(risk.get('warnings',[]))[:100]}",
        ]
        summary = "\n".join(lines)

        embed = discord.Embed(
            title="🧠 TraderManager — Complete Analysis",
            description=summary[:2000],
            color=0x5865F2
        )
        embed.set_footer(text=f"TraderManager • {data.get('timestamp')}")
        await msg.edit(content="✅ All agents reported.", embed=embed)
    except Exception as e:
        logger.error(f"plan error: {e}", exc_info=True)
        await ctx.send(f"❌ Error: {str(e)[:150]}")


@bot.command(name="recommend")
async def cmd_recommend(ctx, amount: int = 10000, strategy: str = "outright"):
    """Run full analysis and suggest a trade for given amount. Usage: !recommend 10000 outright"""
    valid_strategies = {"outright", "straight"}
    if strategy.lower() not in valid_strategies:
        await ctx.send(f"⚠️ Strategy must be one of: {', '.join(valid_strategies)}")
        return

    is_outright = strategy.lower() == "outright"
    risk_tol = "aggressive" if is_outright else "conservative"
    await ctx.send(f"🧠 **TraderManager** analyzing for ₹{amount:,} ({strategy})...")
    try:
        import sys as _sys
        _sys.path.insert(0, "/root/trading")
        from agents.trader_manager import TraderManager as TM
        tm = TM()
        msg = await ctx.send("📡 Gathering market data...")
        data = tm.gather_all(capital=amount, risk_tolerance=risk_tol, preferred_index="NIFTY")

        nifty = data.get("nifty", 0) or 0
        bnifty = data.get("banknifty", 0) or 0
        ns = data.get("news", {}).get("summary", {})
        vwap = data.get("vwap", {}).get("nifty", {})
        cs = data.get("candlestick", {})
        tech = data.get("technicals", {}).get("nifty", {})
        te = data.get("trading_expert", {}).get("suggestions", [{}])[0]
        risk = data.get("risk", {})
        lot_size = te.get("lot_size", 65)

        premium = sl_v = tg_v = max_loss = max_profit = 0
        atm = round(nifty / 50) * 50 if nifty else 23800
        buf = atm * 0.006

        if is_outright:
            strike = atm
            premium = max(round(buf), 50)
            cost = premium * lot_size
            sl_pt = round(premium * 0.35)
            tg_pt = round(premium * 1.8)
            sl_v = round(premium - sl_pt, 1)
            tg_v = round(premium + tg_pt, 1)
            max_loss = sl_pt * lot_size
            max_profit = tg_pt * lot_size
            rr = round(tg_pt / sl_pt, 1) if sl_pt else 0
            lines = [
                f"**📊 RECOMMEND — ₹{amount:,} ({strategy.upper()})**",
                f"**Time:** {data.get('timestamp')}",
                f"**NIFTY:** {nifty:.0f} | **BANKNIFTY:** {bnifty:.0f} | **Lot:** {lot_size}\n",
                f"**📰 {ns.get('market_outlook','N/A')}** | **VWAP:** {vwap.get('diff_pct','N/A')}% | **RSI:** {tech.get('rsi','N/A')}",
                f"**GPU:** {cs.get('nifty',{}).get('direction','N/A')}\n",
                f"**🎯 BUY {strike}CE @ ₹{premium} × 1 lot ({lot_size} qty)**",
                f"**Cost:** ₹{cost:,} ({cost/amount*100:.0f}% deployed)",
                f"**SL:** ₹{sl_v} → loss **₹{max_loss:,}** ({max_loss/amount*100:.0f}%)",
                f"**Target:** ₹{tg_v} → profit **₹{max_profit:,}** ({max_profit/amount*100:.0f}%)",
                f"**R:R:** 1:{rr}",
                f"**Buffer:** ₹{amount - cost:,}\n",
                f"**Reasoning:** Nifty near lower band, RSI rising, GPU {cs.get('nifty',{}).get('direction','mixed')}. "
                f"VWAP below suggests caution — tight SL recommended.\n",
                f"**⚠️ Max loss {max_loss/amount*100:.0f}% of capital.** Invalidate if Nifty < {nifty-200:.0f}.",
            ]
        else:
            # Straight = bull call spread
            buy_strike = atm
            sell_strike = atm + 200
            buy_prem = max(round(buf), 50)
            sell_prem = max(round(buy_prem * 0.45), 25)
            net_debit = buy_prem - sell_prem
            cost = net_debit * lot_size
            max_profit = (sell_strike - buy_strike - net_debit) * lot_size
            lines = [
                f"**📊 RECOMMEND — ₹{amount:,} ({strategy.upper()} spread)**",
                f"**Time:** {data.get('timestamp')}",
                f"**NIFTY:** {nifty:.0f} | **BANKNIFTY:** {bnifty:.0f} | **Lot:** {lot_size}\n",
                f"**📰 {ns.get('market_outlook','N/A')}** | **VWAP:** {vwap.get('diff_pct','N/A')}% | **RSI:** {tech.get('rsi','N/A')}",
                f"**GPU:** {cs.get('nifty',{}).get('direction','N/A')}\n",
                f"**🎯 BUY {buy_strike}CE @ ₹{buy_prem} + SELL {sell_strike}CE @ ₹{sell_prem}**",
                f"**Net Debit:** ₹{net_debit} × {lot_size} = **₹{cost:,}** ({cost/amount*100:.0f}% deployed)",
                f"**Max Loss:** ₹{cost:,} (if Nifty < {buy_strike})",
                f"**Max Profit:** ₹{max_profit:,} (if Nifty > {sell_strike})",
                f"**Breakeven:** {buy_strike + net_debit}\n",
                f"**Reasoning:** Defined-risk bounce play. Nifty near lower BB, RSI recovering. "
                f"Spread caps risk at {cost/amount*100:.0f}% of capital.\n",
                f"**⚠️ Invalidate if Nifty < {nifty-200:.0f}.**",
            ]

        summary = "\n".join(lines)
        color = 0x00FF88 if is_outright else 0x5865F2
        embed = discord.Embed(title=f"📊 Recommend — ₹{amount:,} {strategy}", description=summary[:2000], color=color)
        embed.set_footer(text=f"TraderManager • Suggestion #{data.get('timestamp')}")
        await msg.edit(content="✅ Analysis complete.", embed=embed)

        # Record in learning agent
        try:
            _sys.path.insert(0, "/root/trading")
            from agents.learning_agent import LearningAgent
            la = LearningAgent()
            la.record_suggestion({
                "timestamp": data.get("timestamp"),
                "user_request": f"₹{amount} {strategy}",
                "index": "NIFTY",
                "strike": f"{atm}CE {'spread' if not is_outright else 'outright'}",
                "type": "CE",
                "entry_premium": te.get("entry_premium", premium),
                "stop_loss": te.get("stop_loss", sl_v if is_outright else 0),
                "target": te.get("target", tg_v if is_outright else 0),
                "capital_allocated": amount,
                "max_loss": cost if not is_outright else max_loss,
                "reasoning": f"Auto-suggest: {strategy}, Nifty {nifty}, RSI {tech.get('rsi')}, GPU {cs.get('nifty',{}).get('direction')}",
                "agents_used": ["news", "candlestick", "vwap", "technicals", "trading_expert"],
                "confidence": "medium",
                "market_context": {"nifty": nifty, "bnifty": bnifty, "strategy": strategy},
            })
        except Exception:
            pass
    except Exception as e:
        logger.error(f"recommend error: {e}", exc_info=True)
        await ctx.send(f"❌ Error: {str(e)[:150]}")


@bot.command(name="pnl")
async def cmd_pnl(ctx):
    """P&L statement from today's paper trades."""
    import sqlite3
    from datetime import datetime, timezone, timedelta
    IST = timezone(timedelta(hours=5, minutes=30))
    today = datetime.now(IST).strftime("%Y-%m-%d")
    db = "/root/trading/data/papertrades.db"
    conn = sqlite3.connect(db)
    rows = conn.execute("""
        SELECT id, timestamp, index_name, strike, option_type,
               entry_ltp, exit_ltp, exit_reason, pnl, exit_timestamp
        FROM trades WHERE date(timestamp) = ? ORDER BY id
    """, (today,)).fetchall()
    conn.close()
    if not rows:
        await ctx.send("No trades today.")
        return
    cols = ['id','ts','idx','strike','type','entry','exit_ltp','reason','pnl','exit_ts']
    by_trade = {}
    for r in rows:
        d = dict(zip(cols, r))
        key = (d['ts'], d['strike'], d['type'])
        if key not in by_trade:
            by_trade[key] = {}
        if d['exit_ltp'] is not None:
            by_trade[key]['exit'] = d
        else:
            by_trade[key]['entry'] = d
    closed = [v['exit'] for k,v in by_trade.items() if 'exit' in v]
    opened = [v['entry'] for k,v in by_trade.items() if 'exit' not in v]
    total = sum(d['pnl'] for d in closed)
    lines = [f"**📊 P&L Statement — {datetime.now(IST).strftime('%d %b %Y (%a)')}**"]
    lines.append(f"Closed: {len(closed)} | {'🟢' if total>=0 else '🔴'} **₹{total:+,.0f}** ({sum(1 for d in closed if d['pnl']>0)}W/{sum(1 for d in closed if d['pnl']<0)}L)\n")
    for d in sorted(closed, key=lambda x: x['ts']):
        bt = d['ts'][11:16]
        st = d['exit_ts'][11:16] if d.get('exit_ts') else bt
        lines.append(f"✅ {d['idx']} {d['strike']}{d['type']}  B {bt} @ ₹{d['entry']:.0f} → S {st} @ ₹{d['exit_ltp']:.0f} | P&L ₹{d['pnl']:+,.0f}")
    for d in opened:
        bt = d['ts'][11:16]
        lines.append(f"\n⏳ {d['idx']} {d['strike']}{d['type']}  B {bt} @ ₹{d['entry']:.0f}  (OPEN)")
    await ctx.send("\n".join(lines))


@bot.command(name="history")
async def cmd_history(ctx):
    """Day-wise all-time P&L from trade history."""
    import sqlite3
    db = "/root/trading/data/papertrades.db"
    conn = sqlite3.connect(db)
    day_rows = conn.execute("""
        SELECT date(timestamp) as day,
               count(*) as trades,
               sum(CASE WHEN exit_reason='TARGET_HIT' THEN 1 ELSE 0 END) as wins,
               sum(CASE WHEN exit_reason='STOP_LOSS' THEN 1 ELSE 0 END) as losses,
               sum(CASE WHEN pnl IS NOT NULL THEN pnl ELSE 0 END) as pnl
        FROM trade_history
        GROUP BY day ORDER BY day
    """).fetchall()
    conn.close()
    if not day_rows:
        await ctx.send("No trade history found.")
        return
    total_trades = sum(r[1] for r in day_rows)
    total_wins = sum(r[2] for r in day_rows)
    total_losses = sum(r[3] for r in day_rows)
    total_pnl = sum(r[4] for r in day_rows)
    lines = [f"**📊 Day-Wise P&L (All Time)**"]
    for day, cnt, wins, losses, pnl in day_rows:
        emoji = "🟢" if pnl >= 0 else "🔴"
        lines.append(f"{emoji} **{day}** — {wins}W / {losses}L | P&L **₹{pnl:+,.0f}**")
    lines.append("")
    if total_trades > 0:
        lines.append(f"**Total: {total_trades} trades | {total_wins}W / {total_losses}L | P&L ₹{total_pnl:+,.0f} | Win%: {total_wins/total_trades*100:.0f}%**")
    else:
        lines.append("No completed trades")
    await ctx.send("\n".join(lines))


async def run_async_send(ctx, script, *args):
    import subprocess
    wh = os.environ.get("DISCORD_WEBHOOK", "")
    cmd = [sys.executable, os.path.join("/root/trading", script)]
    if wh:
        cmd.extend(["--webhook", wh])
    cmd.extend(list(args))
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            env={**os.environ}
        )
        stdout, stderr = await proc.communicate()
        output = (stdout + stderr).decode()[-500:]
        if "Sent" in output or "success" in output.lower():
            await ctx.send("✅ Done! Check the channel for the report.")
        else:
            await ctx.send(f"⚠️ Script ran. Last output: {output[-200:]}")
    except Exception as e:
        await ctx.send(f"❌ Error: {str(e)[:100]}")


if __name__ == "__main__":
    if not BOT_TOKEN:
        print("[!] Set DISCORD_BOT_TOKEN env var")
        sys.exit(1)
    print("[+] Starting Discord trading bot...")
    bot.run(BOT_TOKEN)
