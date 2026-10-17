package com.autotrader.engine

import com.autotrader.data.repository.TradeDirection
import java.util.Date

data class TradingConfig(
    val lotSize: Int = 65,
    val capital: Double = 50000.0,
    val script: String = "NIFTY",
    val brokerType: String = "PAPER",
    val maxTradesPerDay: Int = 3,
    val dailyProfitCapPct: Double = 5.0,
    val targetProfitPct: Double = 3.0
)

data class TradeRecord(
    val id: Long = 0,
    val timestamp: Long = System.currentTimeMillis(),
    val script: String = "",
    val direction: TradeDirection = TradeDirection.CE,
    val entryPrice: Double = 0.0,
    val exitPrice: Double? = null,
    val stopLoss: Double = 0.0,
    val target: Double = 0.0,
    val quantity: Int = 0,
    val pnl: Double? = null,
    val exitReason: String? = null,
    val signalsMet: Int = 0,
    val totalSignals: Int = 0,
    val rsiAtEntry: Double = 0.0,
    val ema9AtEntry: Double = 0.0,
    val ema27AtEntry: Double = 0.0,
    val vwapAtEntry: Double = 0.0,
    val stAtEntry: String = ""
)

class RiskManager(private val config: TradingConfig) {

    private val tradesToday = mutableListOf<TradeRecord>()
    private var openTrade: TradeRecord? = null

    val dailyCapital: Double get() = config.capital
    val dailyProfitCap: Double get() = config.capital * config.dailyProfitCapPct / 100.0
    val maxTrades: Int get() = config.maxTradesPerDay

    fun resetDay() {
        tradesToday.clear()
        openTrade = null
    }

    fun canTakeTrade(): Boolean {
        if (openTrade != null) return false
        if (tradesToday.size >= maxTrades) return false
        if (currentDailyPnl() >= dailyProfitCap) return false
        return true
    }

    fun calculateQuantity(): Int {
        val pricePerLot = config.capital // whole capital in one trade
        return (pricePerLot / config.lotSize).toInt().coerceAtLeast(1) * config.lotSize
    }

    fun registerEntry(trade: TradeRecord) {
        openTrade = trade
    }

    fun registerExit(exitPrice: Double, reason: String): TradeRecord {
        val trade = openTrade ?: return TradeRecord()
        val pnl = calculatePnl(trade, exitPrice)
        val completed = trade.copy(
            exitPrice = exitPrice,
            pnl = pnl,
            exitReason = reason
        )
        tradesToday.add(completed)
        openTrade = null
        return completed
    }

    fun currentDailyPnl(): Double {
        return tradesToday.sumOf { it.pnl ?: 0.0 }
    }

    fun totalDailyPnl(): Double {
        val openPnl = if (openTrade != null) {
            openTrade!!.let { calculatePnl(it, it.entryPrice) }
        } else 0.0
        return currentDailyPnl() + openPnl
    }

    private fun calculatePnl(trade: TradeRecord, exitPrice: Double): Double {
        val diff = when (trade.direction) {
            TradeDirection.CE -> exitPrice - trade.entryPrice
            TradeDirection.PE -> trade.entryPrice - exitPrice
        }
        return diff * trade.quantity
    }

    fun hasOpenTrade(): Boolean = openTrade != null
    fun getOpenTrade(): TradeRecord? = openTrade
    fun getTradesToday(): List<TradeRecord> = tradesToday.toList()
    fun tradesCount(): Int = tradesToday.size

    fun isDailyCapHit(): Boolean {
        return currentDailyPnl() >= dailyProfitCap
    }

    fun isMaxTradeReached(): Boolean {
        return tradesToday.size >= maxTrades
    }
}
