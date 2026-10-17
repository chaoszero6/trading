package com.autotrader.broker

import com.autotrader.engine.Candle

data class BrokerConfig(
    val apiKey: String = "",
    val clientId: String = "",
    val password: String = "",
    val totp: String = "",
    val accessToken: String = "",
    val userId: String = ""
)

data class OrderResult(
    val success: Boolean,
    val orderId: String? = null,
    val message: String = ""
)

data class Position(
    val symbol: String = "",
    val quantity: Int = 0,
    val buyPrice: Double = 0.0,
    val ltp: Double = 0.0,
    val pnl: Double = 0.0
)

data class Funds(
    val availableCash: Double = 0.0,
    var usedMargin: Double = 0.0
)

interface Broker {
    val name: String
    suspend fun connect(config: BrokerConfig): Result<Boolean>
    suspend fun isConnected(): Boolean
    suspend fun disconnect()
    suspend fun getLTP(symbol: String): Result<Double>
    suspend fun getCandles(
        symbol: String,
        interval: String,
        fromDate: String = "",
        toDate: String = ""
    ): Result<List<Candle>>
    suspend fun placeOrder(
        symbol: String,
        quantity: Int,
        side: String, // BUY or SELL
        price: Double,
        orderType: String = "MARKET"
    ): OrderResult
    suspend fun getPositions(): Result<List<Position>>
    suspend fun getFunds(): Result<Funds>
}
