package com.autotrader.engine

import kotlin.math.abs
import kotlin.math.roundToInt

data class Candle(
    val timestamp: Long = 0L,
    val open: Double = 0.0,
    val high: Double = 0.0,
    val low: Double = 0.0,
    val close: Double = 0.0,
    val volume: Long = 0L
)

data class IndicatorValues(
    val ema9: List<Double> = emptyList(),
    val ema27: List<Double> = emptyList(),
    val rsi14: List<Double> = emptyList(),
    val rsiMa20: List<Double> = emptyList(),
    val vwap: List<Double> = emptyList(),
    val superTrend: List<SuperTrendSignal> = emptyList(),
    val atr14: List<Double> = emptyList()
)

enum class SuperTrendSignal { GREEN, RED }

object TechnicalIndicators {

    fun ema(values: List<Double>, period: Int): List<Double> {
        if (values.size < period) return values.map { 0.0 }
        val result = mutableListOf<Double>()
        val multiplier = 2.0 / (period + 1)
        var emaVal = values.take(period).average()
        for (i in values.indices) {
            if (i < period - 1) {
                result.add(0.0)
            } else if (i == period - 1) {
                result.add(emaVal)
            } else {
                emaVal = (values[i] - emaVal) * multiplier + emaVal
                result.add(emaVal)
            }
        }
        return result
    }

    fun sma(values: List<Double>, period: Int): List<Double> {
        if (values.size < period) return values.map { 0.0 }
        val result = mutableListOf<Double>()
        for (i in values.indices) {
            if (i < period - 1) {
                result.add(0.0)
            } else {
                result.add(values.subList(i - period + 1, i + 1).average())
            }
        }
        return result
    }

    fun rsi(values: List<Double>, period: Int = 14): List<Double> {
        if (values.size < period + 1) return values.map { 50.0 }
        val result = mutableListOf<Double>()
        val gains = mutableListOf<Double>()
        val losses = mutableListOf<Double>()
        for (i in 1 until values.size) {
            val diff = values[i] - values[i - 1]
            gains.add(if (diff > 0) diff else 0.0)
            losses.add(if (diff < 0) -diff else 0.0)
        }

        var avgGain = gains.take(period).average()
        var avgLoss = losses.take(period).average()

        result.add(50.0)

        for (i in 0 until period) {
            result.add(50.0)
        }

        val firstRs = if (avgLoss == 0.0) 100.0 else avgGain / avgLoss
        result.add(100.0 - (100.0 / (1.0 + firstRs)))

        for (i in period until gains.size) {
            avgGain = (avgGain * (period - 1) + gains[i]) / period
            avgLoss = (avgLoss * (period - 1) + losses[i]) / period
            val rs = if (avgLoss == 0.0) 100.0 else avgGain / avgLoss
            result.add(100.0 - (100.0 / (1.0 + rs)))
        }

        return result.take(values.size)
    }

    fun vwap(candles: List<Candle>): List<Double> {
        if (candles.isEmpty()) return emptyList()
        val totalVol = candles.sumOf { it.volume }
        if (totalVol == 0L) {
            // equal-weight VWAP = SMA of typical price
            val tps = candles.map { (it.high + it.low + it.close) / 3.0 }
            val result = mutableListOf<Double>()
            var cum = 0.0
            for (i in tps.indices) {
                cum += tps[i]
                result.add(cum / (i + 1))
            }
            return result
        }
        val typicalPrices = candles.map { (it.high + it.low + it.close) / 3.0 }
        val volumes = candles.map { it.volume.toDouble() }
        var cumPv = 0.0
        var cumVol = 0.0
        val result = mutableListOf<Double>()
        for (i in candles.indices) {
            cumPv += typicalPrices[i] * volumes[i]
            cumVol += volumes[i]
            result.add(if (cumVol > 0) cumPv / cumVol else 0.0)
        }
        return result
    }

    fun atr(candles: List<Candle>, period: Int = 14): List<Double> {
        if (candles.size < 2) return candles.map { 0.0 }
        val trueRanges = mutableListOf<Double>()
        for (i in 1 until candles.size) {
            val hl = candles[i].high - candles[i].low
            val hc = abs(candles[i].high - candles[i - 1].close)
            val lc = abs(candles[i].low - candles[i - 1].close)
            trueRanges.add(maxOf(hl, hc, lc))
        }
        val result = mutableListOf<Double>()
        var firstAtr = trueRanges.take(period).average()
        result.add(0.0)
        for (i in 0 until period - 1) result.add(0.0)
        result.add(firstAtr)
        for (i in period until trueRanges.size) {
            firstAtr = (firstAtr * (period - 1) + trueRanges[i]) / period
            result.add(firstAtr)
        }
        while (result.size < candles.size) result.add(0.0)
        return result
    }

    data class SuperTrendResult(
        val trend: List<SuperTrendSignal>,
        val bands: List<Double>
    )

    fun superTrend(
        candles: List<Candle>,
        atrPeriod: Int = 10,
        multiplier: Double = 3.0
    ): SuperTrendResult {
        val atrVals = atr(candles, atrPeriod)
        val hlAvg = candles.map { (it.high + it.low) / 2.0 }
        val trend = mutableListOf<SuperTrendSignal>()
        val bands = mutableListOf<Double>()

        var prevUpper = 0.0
        var prevLower = 0.0
        var prevTrend = SuperTrendSignal.GREEN

        for (i in candles.indices) {
            val atrVal = atrVals[i]
            val close = candles[i].close
            val hlAvgVal = hlAvg[i]

            if (i < atrPeriod) {
                trend.add(SuperTrendSignal.GREEN)
                bands.add(0.0)
                continue
            }

            val upperBand = hlAvgVal + multiplier * atrVal
            val lowerBand = hlAvgVal - multiplier * atrVal

            val (newUpper, newLower) = if (upperBand < prevUpper || candles[i - 1].close > prevUpper) {
                upperBand to prevLower
            } else {
                prevUpper to lowerBand
            }

            val (finalUpper, finalLower) = if (lowerBand > prevLower || candles[i - 1].close < prevLower) {
                newUpper to lowerBand
            } else {
                newUpper to prevLower
            }

            val currentTrend = if (close <= finalUpper) {
                SuperTrendSignal.RED
            } else {
                SuperTrendSignal.GREEN
            }

            val band = if (currentTrend == SuperTrendSignal.RED) finalUpper else finalLower
            trend.add(currentTrend)
            bands.add(band)

            prevUpper = finalUpper
            prevLower = finalLower
            prevTrend = currentTrend
        }

        return SuperTrendResult(trend, bands)
    }

    fun isBullishEngulfing(candles: List<Candle>, index: Int): Boolean {
        if (index < 1) return false
        val prev = candles[index - 1]
        val curr = candles[index]
        return prev.close < prev.open &&
                curr.close > curr.open &&
                curr.close > prev.close &&
                curr.open < prev.open
    }

    fun isBearishEngulfing(candles: List<Candle>, index: Int): Boolean {
        if (index < 1) return false
        val prev = candles[index - 1]
        val curr = candles[index]
        return prev.close > prev.open &&
                curr.close < curr.open &&
                curr.close < prev.close &&
                curr.open > prev.open
    }

    fun isHammer(candles: List<Candle>, index: Int): Boolean {
        if (index < 0) return false
        val c = candles[index]
        val body = abs(c.close - c.open)
        val lowerWick = minOf(c.close, c.open) - c.low
        val upperWick = c.high - maxOf(c.close, c.open)
        return body > 0 &&
                lowerWick >= 2 * body &&
                upperWick <= body * 0.3 &&
                c.close > c.open
    }

    fun isShootingStar(candles: List<Candle>, index: Int): Boolean {
        if (index < 0) return false
        val c = candles[index]
        val body = abs(c.close - c.open)
        val lowerWick = minOf(c.close, c.open) - c.low
        val upperWick = c.high - maxOf(c.close, c.open)
        return body > 0 &&
                upperWick >= 2 * body &&
                lowerWick <= body * 0.3 &&
                c.close < c.open
    }

    fun isDoji(candles: List<Candle>, index: Int): Boolean {
        if (index < 0) return false
        val c = candles[index]
        val body = abs(c.close - c.open)
        val range = c.high - c.low
        return range > 0 && body / range <= 0.1
    }

    fun computeAll(candles: List<Candle>): IndicatorValues {
        val closes = candles.map { it.close }
        return IndicatorValues(
            ema9 = ema(closes, 9),
            ema27 = ema(closes, 27),
            rsi14 = rsi(closes, 14),
            rsiMa20 = sma(rsi(closes, 14), 20),
            vwap = vwap(candles),
            superTrend = superTrend(candles).trend,
            atr14 = atr(candles, 14)
        )
    }
}
