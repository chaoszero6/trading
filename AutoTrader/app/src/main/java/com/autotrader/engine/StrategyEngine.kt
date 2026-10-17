package com.autotrader.engine

import com.autotrader.data.repository.TradeDirection
import kotlin.math.abs

data class EntrySignal(
    val direction: TradeDirection,
    val signalsMet: Int,
    val totalSignals: Int,
    val details: Map<String, Boolean>,
    val entryPrice: Double,
    val stopLoss: Double,
    val target: Double,
    val reason: String
)

data class ExitSignal(
    val shouldExit: Boolean,
    val reason: String
)

object StrategyEngine {

    private const val VWAP_NEAR_PCT = 0.2
    private const val CANDLE_ZONE_PCT = 0.5
    private const val TARGET_PROFIT_PCT = 3.0

    fun evaluateEntry(
        candles: List<Candle>,
        ind: IndicatorValues,
        currentIndex: Int,
        timestamp: Long,
        checkPattern: Boolean = true
    ): EntrySignal? {
        if (candles.size < 28 || currentIndex < 1) return null

        val current = candles[currentIndex]
        val close = current.close
        val ema9 = ind.ema9[currentIndex]
        val ema27 = ind.ema27[currentIndex]
        val rsi14 = ind.rsi14[currentIndex]
        val vwap = ind.vwap[currentIndex]
        val st = ind.superTrend[currentIndex]

        if (ema9 == 0.0 || ema27 == 0.0 || vwap == 0.0) return null

        if (abs(close - vwap) / vwap * 100 <= VWAP_NEAR_PCT) return null

        val ceSignals = evaluateCeSignals(current, ind, currentIndex, checkPattern)
        val peSignals = evaluatePeSignals(current, ind, currentIndex, checkPattern)

        val totalPossible = 5
        val minSignals = 3

        val ceMet = ceSignals.values.count { it }
        val peMet = peSignals.values.count { it }

        val slPct = when {
            st == SuperTrendSignal.GREEN -> {
                val atrVal = ind.atr14[currentIndex]
                if (atrVal > 0) atrVal * 1.5 / close else 0.02
            }
            else -> 0.02
        }

        if (ceMet >= minSignals && ceSignals["ema9_gt_ema27"] == true && ceSignals["rsi_gt_55"] == true) {
            val sl = close * (1.0 - slPct)
            val target = close * (1.0 + TARGET_PROFIT_PCT / 100.0)
            val metList = ceSignals.filter { it.value }.keys.joinToString(", ")
            return EntrySignal(
                direction = TradeDirection.CE,
                signalsMet = ceMet,
                totalSignals = totalPossible,
                details = ceSignals,
                entryPrice = close,
                stopLoss = sl,
                target = target,
                reason = "CE entry: $ceMet/$totalPossible signals ($metList)"
            )
        }

        if (peMet >= minSignals && peSignals["ema9_lt_ema27"] == true && peSignals["rsi_lt_45"] == true) {
            val sl = close * (1.0 + slPct)
            val target = close * (1.0 - TARGET_PROFIT_PCT / 100.0)
            val metList = peSignals.filter { it.value }.keys.joinToString(", ")
            return EntrySignal(
                direction = TradeDirection.PE,
                signalsMet = peMet,
                totalSignals = totalPossible,
                details = peSignals,
                entryPrice = close,
                stopLoss = sl,
                target = target,
                reason = "PE entry: $peMet/$totalPossible signals ($metList)"
            )
        }

        return null
    }

    private fun evaluateCeSignals(
        current: Candle,
        ind: IndicatorValues,
        idx: Int,
        checkPattern: Boolean
    ): Map<String, Boolean> {
        val close = current.close
        val vwap = ind.vwap[idx]
        val ema9 = ind.ema9[idx]
        val ema27 = ind.ema27[idx]
        val rsi14 = ind.rsi14[idx]
        val st = ind.superTrend[idx]
        val candles = emptyList<Candle>()

        return mapOf(
            "price_above_vwap" to (close > vwap),
            "ema9_gt_ema27" to (ema9 > ema27),
            "st_green" to (st == SuperTrendSignal.GREEN),
            "rsi_gt_55" to (rsi14 > 55),
            "bullish_candle" to if (checkPattern) {
                TechnicalIndicators.isBullishEngulfing(listOf(), 0) ||
                        TechnicalIndicators.isHammer(listOf(), 0)
            } else false
        )
    }

    private fun evaluatePeSignals(
        current: Candle,
        ind: IndicatorValues,
        idx: Int,
        checkPattern: Boolean
    ): Map<String, Boolean> {
        val close = current.close
        val vwap = ind.vwap[idx]
        val ema9 = ind.ema9[idx]
        val ema27 = ind.ema27[idx]
        val rsi14 = ind.rsi14[idx]
        val st = ind.superTrend[idx]

        return mapOf(
            "price_below_vwap" to (close < vwap),
            "ema9_lt_ema27" to (ema9 < ema27),
            "st_red" to (st == SuperTrendSignal.RED),
            "rsi_lt_45" to (rsi14 < 45),
            "bearish_candle" to false
        )
    }

    fun evaluateExit(
        direction: TradeDirection,
        candles: List<Candle>,
        ind: IndicatorValues,
        currentIndex: Int,
        hourlyCandles: List<Candle>? = null,
        hourlyInd: IndicatorValues? = null,
        hourlyIndex: Int = -1
    ): ExitSignal {
        if (currentIndex < 1) return ExitSignal(false, "")

        val rsi14 = ind.rsi14[currentIndex]
        val rsiMa = ind.rsiMa20[currentIndex]
        var hourlyExit = false

        if (hourlyCandles != null && hourlyInd != null && hourlyIndex >= 1) {
            val hourlyClose = hourlyCandles[hourlyIndex].close
            val hourlyOpen = hourlyCandles[hourlyIndex].open
            hourlyExit = when (direction) {
                TradeDirection.CE -> hourlyClose < hourlyOpen
                TradeDirection.PE -> hourlyClose > hourlyOpen
            }
        }

        return when (direction) {
            TradeDirection.CE -> {
                if (rsi14 < rsiMa || hourlyExit) {
                    val reasons = mutableListOf<String>()
                    if (rsi14 < rsiMa) reasons.add("RSI($rsi14) < RSI MA($rsiMa)")
                    if (hourlyExit) reasons.add("Hourly bearish candle")
                    ExitSignal(true, reasons.joinToString(" | "))
                } else ExitSignal(false, "")
            }
            TradeDirection.PE -> {
                if (rsi14 > rsiMa || hourlyExit) {
                    val reasons = mutableListOf<String>()
                    if (rsi14 > rsiMa) reasons.add("RSI($rsi14) > RSI MA($rsiMa)")
                    if (hourlyExit) reasons.add("Hourly bullish candle")
                    ExitSignal(true, reasons.joinToString(" | "))
                } else ExitSignal(false, "")
            }
        }
    }

    fun evaluateExitAtTarget(
        entryPrice: Double,
        currentPrice: Double,
        direction: TradeDirection
    ): Boolean {
        return when (direction) {
            TradeDirection.CE -> (currentPrice - entryPrice) / entryPrice * 100 >= TARGET_PROFIT_PCT
            TradeDirection.PE -> (entryPrice - currentPrice) / entryPrice * 100 >= TARGET_PROFIT_PCT
        }
    }

    fun evaluateExitAtStop(
        entryPrice: Double,
        stopLoss: Double,
        currentPrice: Double,
        direction: TradeDirection
    ): Boolean {
        return when (direction) {
            TradeDirection.CE -> currentPrice <= stopLoss
            TradeDirection.PE -> currentPrice >= stopLoss
        }
    }
}
