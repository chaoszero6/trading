package com.autotrader.data.db

import androidx.room.Entity
import androidx.room.PrimaryKey

@Entity(tableName = "trades")
data class TradeEntity(
    @PrimaryKey(autoGenerate = true)
    val id: Long = 0,
    val timestamp: Long = System.currentTimeMillis(),
    val script: String = "",
    val direction: String = "", // CE or PE
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
