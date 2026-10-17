package com.autotrader.broker

object BrokerFactory {
    fun create(type: String): Broker {
        return when (type.uppercase()) {
            "ANGEL" -> AngelOneBroker()
            "ANGEL ONE" -> AngelOneBroker()
            "ZERODHA" -> ZerodhaBroker()
            "ICICI" -> ICICIDirectBroker()
            "ICICI DIRECT" -> ICICIDirectBroker()
            "DHAN" -> DhanBroker()
            "UPSTOX" -> UpstoxBroker()
            "PAPER" -> PaperBroker()
            "PAPER TRADE" -> PaperBroker()
            else -> PaperBroker()
        }
    }
}
