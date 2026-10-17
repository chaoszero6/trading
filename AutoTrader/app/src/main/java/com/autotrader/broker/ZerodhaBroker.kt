package com.autotrader.broker

import com.autotrader.engine.Candle

class ZerodhaBroker : Broker {
    override val name = "Zerodha"
    override suspend fun connect(config: BrokerConfig): Result<Boolean> {
        return Result.success(true)
    }
    override suspend fun isConnected(): Boolean = true
    override suspend fun disconnect() {}
    override suspend fun getLTP(symbol: String): Result<Double> = Result.failure(NotImplementedError("Zerodha live trading coming in next update"))
    override suspend fun getCandles(symbol: String, interval: String, fromDate: String, toDate: String): Result<List<Candle>> = Result.failure(NotImplementedError("Zerodha live trading coming in next update"))
    override suspend fun placeOrder(symbol: String, quantity: Int, side: String, price: Double, orderType: String): OrderResult = OrderResult(success = false, message = "Zerodha live trading coming in next update")
    override suspend fun getPositions(): Result<List<Position>> = Result.success(emptyList())
    override suspend fun getFunds(): Result<Funds> = Result.success(Funds())
}
