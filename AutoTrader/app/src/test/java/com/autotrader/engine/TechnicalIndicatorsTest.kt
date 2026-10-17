package com.autotrader.engine

import org.junit.Assert.*
import org.junit.Test

class TechnicalIndicatorsTest {

    @Test
    fun `ema returns correct values`() {
        val prices = listOf(100.0, 102.0, 104.0, 103.0, 105.0, 107.0, 106.0, 108.0, 110.0, 109.0)
        val ema9 = TechnicalIndicators.ema(prices, 9)
        assertEquals(prices.size, ema9.size)
        assertTrue(ema9[0] == 0.0)
        assertTrue(ema9[8] > 0)
        assertTrue(ema9.last() > 0)
    }

    @Test
    fun `ema with period larger than data returns zeros`() {
        val prices = listOf(1.0, 2.0, 3.0)
        val ema = TechnicalIndicators.ema(prices, 14)
        assertEquals(prices.size, ema.size)
        assertTrue(ema.all { it == 0.0 })
    }

    @Test
    fun `sma returns correct average`() {
        val prices = listOf(10.0, 20.0, 30.0, 40.0, 50.0)
        val sma3 = TechnicalIndicators.sma(prices, 3)
        assertEquals(prices.size, sma3.size)
        assertTrue(sma3[0] == 0.0)
        assertTrue(sma3[1] == 0.0)
        assertEquals(20.0, sma3[2], 0.001)
        assertEquals(30.0, sma3[3], 0.001)
        assertEquals(40.0, sma3[4], 0.001)
    }

    @Test
    fun `rsi is 50 for flat data`() {
        val prices = List(20) { 100.0 }
        val rsi = TechnicalIndicators.rsi(prices, 14)
        assertTrue(rsi.all { it > 0 })
    }

    @Test
    fun `rsi above 70 for strong uptrend`() {
        val prices = (0 until 30).map { 100.0 + it * 2.0 }
        val rsi = TechnicalIndicators.rsi(prices, 14)
        assertTrue(rsi.last() > 65)
    }

    @Test
    fun `rsi below 30 for strong downtrend`() {
        val prices = (0 until 30).map { 200.0 - it * 2.0 }
        val rsi = TechnicalIndicators.rsi(prices, 14)
        assertTrue(rsi.last() < 35)
    }

    @Test
    fun `vwap equals price for single candle`() {
        val candles = listOf(Candle(close = 100.0, high = 105.0, low = 95.0, volume = 1000L))
        val vwap = TechnicalIndicators.vwap(candles)
        assertEquals(1, vwap.size)
        assertEquals(100.0, vwap[0], 0.01)
    }

    @Test
    fun `vwap increases with higher price and volume`() {
        val candles = listOf(
            Candle(close = 100.0, high = 105.0, low = 95.0, volume = 1000L),
            Candle(close = 110.0, high = 115.0, low = 105.0, volume = 2000L)
        )
        val vwap = TechnicalIndicators.vwap(candles)
        assertEquals(2, vwap.size)
        assertTrue(vwap[1] > vwap[0])
    }

    @Test
    fun `atr returns zero for insufficient data`() {
        val candles = listOf(Candle(high = 100.0, low = 90.0, close = 95.0))
        val atr = TechnicalIndicators.atr(candles, 14)
        assertEquals(1, atr.size)
        assertEquals(0.0, atr[0], 0.01)
    }

    @Test
    fun `atr is positive with enough data`() {
        val candles = (0 until 20).map {
            Candle(high = 100.0 + it * 2.0, low = 90.0 + it * 2.0 - 5.0, close = 95.0 + it * 2.0, volume = 1000L)
        }
        val atr = TechnicalIndicators.atr(candles, 14)
        assertTrue(atr.size == candles.size)
        assertTrue(atr.last() > 0)
    }

    @Test
    fun `superTrend returns green first`() {
        val candles = (0 until 15).map {
            Candle(high = 105.0, low = 95.0, close = 100.0, open = 100.0, volume = 1000L)
        }
        val st = TechnicalIndicators.superTrend(candles, 10, 3.0)
        assertEquals(candles.size, st.trend.size)
    }

    @Test
    fun `superTrend turns red on sustained downtrend`() {
        val candles = (0 until 30).map {
            Candle(high = 100.0 - it * 2.0 + 5.0, low = 100.0 - it * 2.0 - 5.0, close = 100.0 - it * 2.0, volume = 1000L)
        }
        val st = TechnicalIndicators.superTrend(candles, 10, 3.0)
        val lastRed = st.trend.takeLast(5).any { it == SuperTrendSignal.RED }
        assertTrue("Expected RED trend in sustained downtrend", lastRed)
    }

    @Test
    fun `bullish engulfing detection`() {
        val candles = listOf(
            Candle(open = 110.0, close = 100.0, high = 112.0, low = 98.0, volume = 1000L),
            Candle(open = 95.0, close = 115.0, high = 118.0, low = 93.0, volume = 2000L)
        )
        assertTrue(TechnicalIndicators.isBullishEngulfing(candles, 1))
        assertFalse(TechnicalIndicators.isBullishEngulfing(candles, 0))
    }

    @Test
    fun `bearish engulfing detection`() {
        val candles = listOf(
            Candle(open = 100.0, close = 110.0, high = 112.0, low = 98.0, volume = 1000L),
            Candle(open = 115.0, close = 95.0, high = 118.0, low = 93.0, volume = 2000L)
        )
        assertTrue(TechnicalIndicators.isBearishEngulfing(candles, 1))
        assertFalse(TechnicalIndicators.isBearishEngulfing(candles, 0))
    }

    @Test
    fun `hammer detection`() {
        val candle = Candle(open = 100.0, close = 102.0, high = 102.5, low = 96.0, volume = 1000L)
        assertTrue(TechnicalIndicators.isHammer(listOf(candle), 0))
    }

    @Test
    fun `shooting star detection`() {
        val candle = Candle(open = 100.0, close = 98.0, high = 110.0, low = 97.8, volume = 1000L)
        assertTrue(TechnicalIndicators.isShootingStar(listOf(candle), 0))
    }

    @Test
    fun `computeAll returns all indicators`() {
        val candles = (0 until 50).map {
            Candle(high = 100.0 + it * 0.5, low = 99.0 + it * 0.5, close = 99.5 + it * 0.5, open = 100.0, volume = 1000L)
        }
        val ind = TechnicalIndicators.computeAll(candles)
        assertEquals(candles.size, ind.ema9.size)
        assertEquals(candles.size, ind.ema27.size)
        assertEquals(candles.size, ind.rsi14.size)
        assertEquals(candles.size, ind.rsiMa20.size)
        assertEquals(candles.size, ind.vwap.size)
        assertEquals(candles.size, ind.superTrend.size)
        assertEquals(candles.size, ind.atr14.size)
    }
}
