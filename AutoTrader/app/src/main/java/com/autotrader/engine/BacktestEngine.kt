package com.autotrader.engine

import com.autotrader.data.repository.TradeDirection

data class BacktestResult(
    val totalTrades: Int = 0,
    val wins: Int = 0,
    val losses: Int = 0,
    val winRate: Double = 0.0,
    val netPnl: Double = 0.0,
    val maxDrawdown: Double = 0.0,
    val avgWin: Double = 0.0,
    val avgLoss: Double = 0.0,
    val sharpeRatio: Double = 0.0,
    val maxConsecutiveLosses: Int = 0,
    val totalReturnPct: Double = 0.0,
    val trades: List<TradeRecord> = emptyList()
)

class BacktestEngine {

    data class BacktestConfig(
        val capital: Double = 50000.0,
        val lotSize: Int = 65,
        val script: String = "NIFTY",
        val maxTradesPerDay: Int = 3,
        val targetPct: Double = 3.0,
        val dailyProfitCapPct: Double = 5.0
    )

    fun run(
        candles: List<Candle>,
        config: BacktestConfig,
        ind: IndicatorValues? = null
    ): BacktestResult {
        if (candles.size < 50) return BacktestResult()

        val indicators = ind ?: TechnicalIndicators.computeAll(candles)
        val trades = mutableListOf<TradeRecord>()
        var capital = config.capital
        var peakCapital = capital
        var maxDrawdown = 0.0
        var dailyTrades = 0
        var dailyPnl = 0.0
        var lastTradeDay = -1
        var consecutiveLosses = 0
        var maxConsLosses = 0
        var inPosition = false
        var openTrade: TradeRecord? = null
        val dailyProfitCap = config.capital * config.dailyProfitCapPct / 100.0

        for (i in 50 until candles.size) {
            val candle = candles[i]
            val dayOfYear = java.util.Calendar.getInstance().apply {
                timeInMillis = candle.timestamp
            }.get(java.util.Calendar.DAY_OF_YEAR)

            if (dayOfYear != lastTradeDay) {
                dailyTrades = 0
                dailyPnl = 0.0
                lastTradeDay = dayOfYear
            }

            if (inPosition && openTrade != null) {
                val exit = StrategyEngine.evaluateExit(
                    direction = openTrade.direction,
                    candles = candles,
                    ind = indicators,
                    currentIndex = i
                )

                val atTarget = StrategyEngine.evaluateExitAtTarget(
                    openTrade.entryPrice, candle.close, openTrade.direction
                )
                val atStop = StrategyEngine.evaluateExitAtStop(
                    openTrade.entryPrice, openTrade.stopLoss, candle.close, openTrade.direction
                )

                var exitPrice: Double? = null
                var exitReason: String? = null

                if (atTarget) {
                    exitPrice = openTrade.target
                    exitReason = "Target hit"
                } else if (atStop) {
                    exitPrice = openTrade.stopLoss
                    exitReason = "Stop loss"
                } else if (exit.shouldExit) {
                    exitPrice = candle.close
                    exitReason = exit.reason
                }

                if (exitPrice != null) {
                    val diff = when (openTrade.direction) {
                        TradeDirection.CE -> exitPrice - openTrade.entryPrice
                        TradeDirection.PE -> openTrade.entryPrice - exitPrice
                    }
                    val pnl = diff * openTrade.quantity
                    val completed = openTrade.copy(
                        exitPrice = exitPrice,
                        pnl = pnl,
                        exitReason = exitReason
                    )
                    trades.add(completed)
                    capital += pnl
                    dailyPnl += pnl
                    dailyTrades++

                    if (pnl > 0) consecutiveLosses = 0
                    else {
                        consecutiveLosses++
                        maxConsLosses = maxOf(maxConsLosses, consecutiveLosses)
                    }

                    inPosition = false
                    openTrade = null

                    if (capital > peakCapital) peakCapital = capital
                    val dd = (peakCapital - capital) / peakCapital * 100
                    if (dd > maxDrawdown) maxDrawdown = dd
                }
                continue
            }

            if (dailyTrades >= config.maxTradesPerDay) continue
            if (dailyPnl >= dailyProfitCap) continue

            val entry = StrategyEngine.evaluateEntry(
                candles = candles,
                ind = indicators,
                currentIndex = i,
                timestamp = candle.timestamp,
                checkPattern = false
            )

            if (entry != null) {
                val quantity = config.lotSize
                val trade = TradeRecord(
                    timestamp = candle.timestamp,
                    script = config.script,
                    direction = entry.direction,
                    entryPrice = entry.entryPrice,
                    stopLoss = entry.stopLoss,
                    target = entry.target,
                    quantity = quantity,
                    signalsMet = entry.signalsMet,
                    totalSignals = entry.totalSignals,
                    rsiAtEntry = indicators.rsi14[i],
                    ema9AtEntry = indicators.ema9[i],
                    ema27AtEntry = indicators.ema27[i],
                    vwapAtEntry = indicators.vwap[i],
                    stAtEntry = if (i < indicators.superTrend.size) indicators.superTrend[i].name else ""
                )
                inPosition = true
                openTrade = trade
            }
        }

        val wins = trades.count { it.pnl != null && it.pnl > 0 }
        val losses = trades.count { it.pnl != null && it.pnl < 0 }
        val total = trades.size
        val winRate = if (total > 0) wins.toDouble() / total * 100 else 0.0
        val netPnl = trades.sumOf { it.pnl ?: 0.0 }
        val totalReturn = if (config.capital > 0) netPnl / config.capital * 100 else 0.0
        val avgWin = trades.filter { it.pnl != null && it.pnl > 0 }.let { if (it.isNotEmpty()) it.map { t -> t.pnl ?: 0.0 }.average() else 0.0 }
        val avgLoss = trades.filter { it.pnl != null && it.pnl < 0 }.let { if (it.isNotEmpty()) it.map { t -> t.pnl ?: 0.0 }.average() else 0.0 }

        val returns = trades.mapNotNull { it.pnl }.toList()
        val sharpe = if (returns.isNotEmpty() && returns.size > 1) {
            val mean = returns.average()
            val std = kotlin.math.sqrt(returns.map { (it - mean) * (it - mean) }.average())
            if (std > 0) mean / std * kotlin.math.sqrt(252.0) else 0.0
        } else 0.0

        return BacktestResult(
            totalTrades = total,
            wins = wins,
            losses = losses,
            winRate = winRate,
            netPnl = netPnl,
            maxDrawdown = maxDrawdown,
            avgWin = avgWin,
            avgLoss = avgLoss,
            sharpeRatio = sharpe,
            maxConsecutiveLosses = maxConsLosses,
            totalReturnPct = totalReturn,
            trades = trades
        )
    }
}
