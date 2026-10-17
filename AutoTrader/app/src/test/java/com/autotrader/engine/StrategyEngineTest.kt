package com.autotrader.engine

import com.autotrader.data.repository.TradeDirection
import org.junit.Assert.*
import org.junit.Test

class StrategyEngineTest {

    private fun generateBullishCandles(size: Int): List<Candle> {
        return (0 until size).map {
            Candle(
                open = 100.0 + it * 0.5,
                high = 100.0 + it * 0.5 + 2.0,
                low = 100.0 + it * 0.5 - 1.0,
                close = 100.0 + it * 0.5 + 1.0,
                volume = 1000L
            )
        }
    }

    private fun generateBearishCandles(size: Int): List<Candle> {
        return (0 until size).map {
            Candle(
                open = 200.0 - it * 0.5,
                high = 200.0 - it * 0.5 + 1.0,
                low = 200.0 - it * 0.5 - 2.0,
                close = 200.0 - it * 0.5 - 1.0,
                volume = 1000L
            )
        }
    }

    @Test
    fun `evaluateEntry returns null for insufficient data`() {
        val candles = List(10) { Candle(close = 100.0) }
        val ind = TechnicalIndicators.computeAll(candles)
        val result = StrategyEngine.evaluateEntry(candles, ind, 5, 0L)
        assertNull(result)
    }

    @Test
    fun `evaluateEntry returns null for early index`() {
        val candles = generateBullishCandles(30)
        val ind = TechnicalIndicators.computeAll(candles)
        val result = StrategyEngine.evaluateEntry(candles, ind, 0, 0L)
        assertNull(result)
    }

    @Test
    fun `evaluateExit returns false for early index`() {
        val candles = generateBullishCandles(30)
        val ind = TechnicalIndicators.computeAll(candles)
        val exit = StrategyEngine.evaluateExit(TradeDirection.CE, candles, ind, 0)
        assertFalse(exit.shouldExit)
    }

    @Test
    fun `evaluateExit returns proper reason`() {
        val candles = generateBearishCandles(50)
        val ind = TechnicalIndicators.computeAll(candles)
        val rsi14 = ind.rsi14.last()
        val rsiMa = ind.rsiMa20.last()
        if (rsi14 < rsiMa) {
            val exit = StrategyEngine.evaluateExit(TradeDirection.CE, candles, ind, candles.size - 1)
            if (exit.shouldExit) {
                assertTrue(exit.reason.isNotEmpty())
            }
        }
    }

    @Test
    fun `evaluateExitAtTarget returns true when target is met for CE`() {
        assertTrue(StrategyEngine.evaluateExitAtTarget(100.0, 103.0, TradeDirection.CE))
        assertFalse(StrategyEngine.evaluateExitAtTarget(100.0, 101.0, TradeDirection.CE))
    }

    @Test
    fun `evaluateExitAtTarget returns true when target is met for PE`() {
        assertTrue(StrategyEngine.evaluateExitAtTarget(100.0, 97.0, TradeDirection.PE))
        assertFalse(StrategyEngine.evaluateExitAtTarget(100.0, 99.0, TradeDirection.PE))
    }

    @Test
    fun `evaluateExitAtStop detects stop loss for CE`() {
        val sl = 95.0
        val entry = 100.0
        assertTrue(StrategyEngine.evaluateExitAtStop(entry, sl, 94.0, TradeDirection.CE))
        assertFalse(StrategyEngine.evaluateExitAtStop(entry, sl, 96.0, TradeDirection.CE))
    }

    @Test
    fun `evaluateExitAtStop detects stop loss for PE`() {
        val sl = 105.0
        val entry = 100.0
        assertTrue(StrategyEngine.evaluateExitAtStop(entry, sl, 106.0, TradeDirection.PE))
        assertFalse(StrategyEngine.evaluateExitAtStop(entry, sl, 104.0, TradeDirection.PE))
    }
}
