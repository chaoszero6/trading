package com.autotrader.data.repository

import com.autotrader.data.db.AppDatabase
import com.autotrader.data.db.TradeEntity
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.flow
import java.util.Calendar

class TradeRepository(private val db: AppDatabase) {

    private val dao = db.tradeDao()

    suspend fun insertTrade(
        script: String,
        direction: TradeDirection,
        entryPrice: Double,
        stopLoss: Double,
        target: Double,
        quantity: Int,
        signalsMet: Int,
        totalSignals: Int,
        rsiAtEntry: Double,
        ema9AtEntry: Double,
        ema27AtEntry: Double,
        vwapAtEntry: Double,
        stAtEntry: String
    ): Long {
        return dao.insert(TradeEntity(
            script = script,
            direction = direction.name,
            entryPrice = entryPrice,
            stopLoss = stopLoss,
            target = target,
            quantity = quantity,
            signalsMet = signalsMet,
            totalSignals = totalSignals,
            rsiAtEntry = rsiAtEntry,
            ema9AtEntry = ema9AtEntry,
            ema27AtEntry = ema27AtEntry,
            vwapAtEntry = vwapAtEntry,
            stAtEntry = stAtEntry
        ))
    }

    suspend fun closeTrade(id: Long, exitPrice: Double, pnl: Double, reason: String) {
        val trade = dao.getById(id) ?: return
        dao.update(trade.copy(
            exitPrice = exitPrice,
            pnl = pnl,
            exitReason = reason
        ))
    }

    suspend fun getOpenTrade(): TradeEntity? {
        return dao.getOpenTrade(getStartOfToday())
    }

    suspend fun getTodayTrades(): List<TradeEntity> {
        return dao.getTodayTrades(getStartOfToday())
    }

    suspend fun getAllTrades(): List<TradeEntity> {
        return dao.getAll()
    }

    suspend fun getTradesInRange(startTime: Long, endTime: Long): List<TradeEntity> {
        return dao.getTradesInRange(startTime, endTime)
    }

    suspend fun deleteAll() {
        dao.deleteAll()
    }

    fun getTodayTradesFlow(): Flow<List<TradeEntity>> = flow {
        val trades = dao.getTodayTrades(getStartOfToday())
        emit(trades)
    }

    private fun getStartOfToday(): Long {
        val cal = Calendar.getInstance()
        cal.set(Calendar.HOUR_OF_DAY, 0)
        cal.set(Calendar.MINUTE, 0)
        cal.set(Calendar.SECOND, 0)
        cal.set(Calendar.MILLISECOND, 0)
        return cal.timeInMillis
    }
}
