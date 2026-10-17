package com.autotrader.engine

import com.autotrader.data.repository.TradeDirection
import org.junit.Assert.*
import org.junit.Test

class RiskManagerTest {

    @Test
    fun `canTakeTrade returns true initially`() {
        val config = TradingConfig(capital = 50000.0, maxTradesPerDay = 3, dailyProfitCapPct = 5.0)
        val rm = RiskManager(config)
        assertTrue(rm.canTakeTrade())
    }

    @Test
    fun `canTakeTrade returns false when max trades reached`() {
        val config = TradingConfig(capital = 50000.0, maxTradesPerDay = 1)
        val rm = RiskManager(config)
        rm.registerEntry(TradeRecord(direction = TradeDirection.CE, entryPrice = 100.0, quantity = 1))
        rm.registerExit(103.0, "Target hit")
        assertFalse(rm.canTakeTrade())
    }

    @Test
    fun `canTakeTrade returns false when daily cap hit`() {
        val config = TradingConfig(capital = 1000.0, maxTradesPerDay = 10, dailyProfitCapPct = 5.0)
        val rm = RiskManager(config)
        rm.registerEntry(TradeRecord(direction = TradeDirection.CE, entryPrice = 100.0, quantity = 1))
        rm.registerExit(160.0, "Target hit")
        val pnl = rm.currentDailyPnl()
        val cap = rm.dailyProfitCap
        assertTrue("P&L $pnl >= cap $cap", pnl >= cap)
        assertFalse("Should not allow trade after cap hit", rm.canTakeTrade())
    }

    @Test
    fun `canTakeTrade returns false when trade is open`() {
        val config = TradingConfig(capital = 50000.0, maxTradesPerDay = 3)
        val rm = RiskManager(config)
        rm.registerEntry(TradeRecord(direction = TradeDirection.CE, entryPrice = 100.0, quantity = 1))
        assertFalse(rm.canTakeTrade())
    }

    @Test
    fun `registerExit sets pnl correctly for CE`() {
        val config = TradingConfig(capital = 10000.0)
        val rm = RiskManager(config)
        val trade = TradeRecord(direction = TradeDirection.CE, entryPrice = 100.0, quantity = 10)
        rm.registerEntry(trade)
        val closed = rm.registerExit(105.0, "Target hit")
        assertEquals(50.0, closed.pnl ?: 0.0, 0.01)
        assertEquals("Target hit", closed.exitReason)
    }

    @Test
    fun `registerExit sets pnl correctly for PE`() {
        val config = TradingConfig(capital = 10000.0)
        val rm = RiskManager(config)
        val trade = TradeRecord(direction = TradeDirection.PE, entryPrice = 100.0, quantity = 10)
        rm.registerEntry(trade)
        val closed = rm.registerExit(95.0, "Target hit")
        assertEquals(50.0, closed.pnl ?: 0.0, 0.01)
    }

    @Test
    fun `registerExit gives negative pnl for losing trade`() {
        val config = TradingConfig(capital = 10000.0)
        val rm = RiskManager(config)
        val trade = TradeRecord(direction = TradeDirection.CE, entryPrice = 100.0, quantity = 10)
        rm.registerEntry(trade)
        val closed = rm.registerExit(90.0, "Stop loss")
        assertEquals(-100.0, closed.pnl ?: 0.0, 0.01)
    }

    @Test
    fun `currentDailyPnl tracks cumulative pnl`() {
        val config = TradingConfig(capital = 10000.0)
        val rm = RiskManager(config)
        rm.registerEntry(TradeRecord(direction = TradeDirection.CE, entryPrice = 100.0, quantity = 10))
        rm.registerExit(103.0, "Target")
        rm.registerEntry(TradeRecord(direction = TradeDirection.CE, entryPrice = 100.0, quantity = 10))
        rm.registerExit(98.0, "SL")
        assertEquals(10.0, rm.currentDailyPnl(), 0.01)
    }

    @Test
    fun `resetDay clears all trades`() {
        val config = TradingConfig(capital = 50000.0)
        val rm = RiskManager(config)
        rm.registerEntry(TradeRecord(direction = TradeDirection.CE, entryPrice = 100.0, quantity = 1))
        rm.registerExit(103.0, "Target")
        rm.resetDay()
        assertEquals(0, rm.tradesCount())
        assertEquals(0.0, rm.currentDailyPnl(), 0.01)
    }

    @Test
    fun `hasOpenTrade is true after entry`() {
        val config = TradingConfig()
        val rm = RiskManager(config)
        assertFalse(rm.hasOpenTrade())
        rm.registerEntry(TradeRecord(direction = TradeDirection.CE, entryPrice = 100.0, quantity = 1))
        assertTrue(rm.hasOpenTrade())
        rm.registerExit(103.0, "Target")
        assertFalse(rm.hasOpenTrade())
    }

    @Test
    fun `isDailyCapHit returns true when pnl exceeds cap`() {
        val config = TradingConfig(capital = 1000.0, dailyProfitCapPct = 5.0)
        val rm = RiskManager(config)
        rm.registerEntry(TradeRecord(direction = TradeDirection.CE, entryPrice = 100.0, quantity = 50))
        rm.registerExit(102.0, "Target")
        assertTrue(rm.isDailyCapHit())
    }

    @Test
    fun `isMaxTradeReached returns true at limit`() {
        val config = TradingConfig(maxTradesPerDay = 2)
        val rm = RiskManager(config)
        rm.registerEntry(TradeRecord(direction = TradeDirection.CE, entryPrice = 100.0, quantity = 1))
        rm.registerExit(103.0, "T1")
        rm.registerEntry(TradeRecord(direction = TradeDirection.CE, entryPrice = 100.0, quantity = 1))
        rm.registerExit(103.0, "T2")
        assertTrue(rm.isMaxTradeReached())
    }

    @Test
    fun `dailyProfitCap is calculated correctly`() {
        val config = TradingConfig(capital = 50000.0, dailyProfitCapPct = 5.0)
        val rm = RiskManager(config)
        assertEquals(2500.0, rm.dailyProfitCap, 0.01)
    }
}
