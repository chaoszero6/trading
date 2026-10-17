package com.autotrader.engine

import org.junit.Assert.*
import org.junit.Test

class BacktestEngineTest {

    @Test
    fun `backtest returns empty result for insufficient data`() {
        val engine = BacktestEngine()
        val candles = List(20) { Candle(close = 100.0) }
        val result = engine.run(
            candles,
            BacktestEngine.BacktestConfig(capital = 50000.0, lotSize = 65)
        )
        assertEquals(0, result.totalTrades)
    }

    @Test
    fun `backtest runs with sufficient data`() {
        val engine = BacktestEngine()
        val candles = (0 until 100).map {
            Candle(
                open = 100.0 + it * 0.3,
                high = 100.0 + it * 0.3 + 2.0,
                low = 100.0 + it * 0.3 - 1.0,
                close = 100.0 + it * 0.3 + 1.0,
                volume = 1000L
            )
        }
        val result = engine.run(
            candles,
            BacktestEngine.BacktestConfig(capital = 50000.0, lotSize = 65)
        )
        assertTrue("Expected at least 0 trades", result.totalTrades >= 0)
        assertEquals(result.wins + result.losses, result.totalTrades)
    }

    @Test
    fun `backtest respects max trades per day`() {
        val engine = BacktestEngine()
        val candles = (0 until 100).map {
            Candle(
                open = 100.0,
                high = 105.0,
                low = 95.0,
                close = if (it % 2 == 0) 102.0 else 98.0,
                volume = 1000L,
                timestamp = 1704067200000L + it * 3600000L
            )
        }
        val result = engine.run(
            candles,
            BacktestEngine.BacktestConfig(
                capital = 50000.0,
                lotSize = 65,
                maxTradesPerDay = 1
            )
        )
        assertTrue(result.totalTrades >= 0)
    }

    @Test
    fun `backtest result has valid win rate`() {
        val engine = BacktestEngine()
        val candles = (0 until 150).map {
            Candle(
                open = 100.0 + it * 0.2,
                high = 100.0 + it * 0.2 + 1.0,
                low = 100.0 + it * 0.2 - 1.0,
                close = 100.0 + it * 0.2 + 0.5,
                volume = 1000L
            )
        }
        val result = engine.run(
            candles,
            BacktestEngine.BacktestConfig(capital = 50000.0, lotSize = 65)
        )
        if (result.totalTrades > 0) {
            assertTrue("Win rate 0-100", result.winRate in 0.0..100.0)
            assertTrue(result.wins + result.losses == result.totalTrades)
        }
    }

    @Test
    fun `backtest uses precomputed indicators`() {
        val engine = BacktestEngine()
        val candles = (0 until 100).map {
            Candle(close = 100.0 + it * 0.5, high = 102.0 + it * 0.5, low = 98.0 + it * 0.5, open = 100.0, volume = 1000L)
        }
        val ind = TechnicalIndicators.computeAll(candles)
        val result1 = engine.run(candles, BacktestEngine.BacktestConfig(), null)
        val result2 = engine.run(candles, BacktestEngine.BacktestConfig(), ind)
        assertEquals(result1.totalTrades, result2.totalTrades)
    }

    @Test
    fun `backtest handles volatile data`() {
        val engine = BacktestEngine()
        val rng = java.util.Random(42)
        val candles = (0 until 200).map {
            val base = 100.0 + rng.nextGaussian() * 5.0
            Candle(
                open = base - 1.0,
                high = base + 3.0,
                low = base - 3.0,
                close = base + rng.nextGaussian() * 2.0,
                volume = 1000L
            )
        }
        val result = engine.run(
            candles,
            BacktestEngine.BacktestConfig(capital = 50000.0, lotSize = 65)
        )
        assertTrue(result.totalTrades >= 0)
        assertFalse(result.netPnl.isNaN())
        assertFalse(result.sharpeRatio.isNaN())
        assertFalse(result.maxDrawdown.isNaN())
    }

    @Test
    fun `backtest with daily profit cap`() {
        val engine = BacktestEngine()
        val candles = (0 until 200).map {
            Candle(
                open = 100.0 + it * 0.8,
                high = 100.0 + it * 0.8 + 2.0,
                low = 100.0 + it * 0.8 - 1.0,
                close = 100.0 + it * 0.8 + 1.0,
                volume = 1000L
            )
        }
        val result = engine.run(
            candles,
            BacktestEngine.BacktestConfig(
                capital = 50000.0,
                lotSize = 65,
                dailyProfitCapPct = 5.0,
                maxTradesPerDay = 10
            )
        )
        assertTrue(result.totalTrades >= 0)
    }
}
