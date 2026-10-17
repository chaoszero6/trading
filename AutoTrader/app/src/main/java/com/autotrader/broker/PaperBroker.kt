package com.autotrader.broker

import com.autotrader.engine.Candle
import com.autotrader.engine.TechnicalIndicators
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import org.json.JSONArray
import org.json.JSONObject
import java.net.URL


class PaperBroker : Broker {
    override val name = "Paper Trade"
    private var _connected = false
    private var _capital = 500000.0
    private val positions = mutableListOf<Position>()

    companion object {
        private val YF_SYMBOL_MAP = mapOf(
            "NIFTY" to "^NSEI",
            "BANKNIFTY" to "^NSEBANK",
            "SENSEX" to "^BSESN",
            "FINNIFTY" to "NIFTY_FIN_SERV.NS",
            "MIDCPNIFTY" to "^NSEMDCP50"
        )
        private fun yfSymbol(symbol: String): String {
            val s = symbol.trim().uppercase()
            return YF_SYMBOL_MAP[s] ?: "${s}.NS"
        }
    }

    override suspend fun connect(config: BrokerConfig): Result<Boolean> {
        _capital = config.clientId.toDoubleOrNull() ?: 500000.0
        _connected = true
        return Result.success(true)
    }

    override suspend fun isConnected(): Boolean = _connected

    override suspend fun disconnect() {
        _connected = false
    }

    override suspend fun getLTP(symbol: String): Result<Double> = withContext(Dispatchers.IO) {
        try {
            val url = URL("https://query1.finance.yahoo.com/v8/finance/chart/${yfSymbol(symbol)}?interval=1m&range=1d")
            val conn = url.openConnection()
            conn.setRequestProperty("User-Agent", "Mozilla/5.0")
            val text = conn.getInputStream().bufferedReader().readText()
            val json = JSONObject(text)
            val result = json.getJSONObject("chart").getJSONArray("result").getJSONObject(0)
            val meta = result.getJSONObject("meta")
            val ltp = meta.getDouble("regularMarketPrice")
            Result.success(ltp)
        } catch (e: Exception) {
            Result.failure(e)
        }
    }

    override suspend fun getCandles(
        symbol: String,
        interval: String,
        fromDate: String,
        toDate: String
    ): Result<List<Candle>> = withContext(Dispatchers.IO) {
        try {
            val yahooInterval = when (interval) {
                "1m" -> "1m"
                "5m" -> "5m"
                "15m" -> "15m"
                "60m" -> "60m"
                "1d" -> "1d"
                else -> "5m"
            }
            val yahooRange = when (interval) {
                "1m" -> "7d"
                "5m" -> "1mo"
                "15m" -> "1mo"
                "60m" -> "3mo"
                "1d" -> "1y"
                else -> "1mo"
            }
            val url = URL("https://query1.finance.yahoo.com/v8/finance/chart/${yfSymbol(symbol)}?interval=${yahooInterval}&range=${yahooRange}")
            val conn = url.openConnection()
            conn.setRequestProperty("User-Agent", "Mozilla/5.0")
            val text = conn.getInputStream().bufferedReader().readText()
            val json = JSONObject(text)
            val result = json.getJSONObject("chart").getJSONArray("result").getJSONObject(0)
            val timestamps = result.getJSONArray("timestamp")
            val quotes = result.getJSONObject("indicators").getJSONArray("quote").getJSONObject(0)
            val opens = quotes.getJSONArray("open")
            val highs = quotes.getJSONArray("high")
            val lows = quotes.getJSONArray("low")
            val closes = quotes.getJSONArray("close")
            val volumes = quotes.getJSONArray("volume")

            val candles = mutableListOf<Candle>()
            for (i in 0 until timestamps.length()) {
                if (!opens.isNull(i) && !closes.isNull(i)) {
                    candles.add(Candle(
                        timestamp = timestamps.getLong(i) * 1000,
                        open = opens.getDouble(i),
                        high = highs.getDouble(i),
                        low = lows.getDouble(i),
                        close = closes.getDouble(i),
                        volume = volumes.getLong(i)
                    ))
                }
            }
            Result.success(candles)
        } catch (e: Exception) {
            Result.failure(e)
        }
    }

    override suspend fun placeOrder(
        symbol: String,
        quantity: Int,
        side: String,
        price: Double,
        orderType: String
    ): OrderResult {
        if (side == "BUY") {
            positions.add(Position(symbol = symbol, quantity = quantity, buyPrice = price, ltp = price))
        } else {
            positions.removeAll { it.symbol == symbol }
        }
        return OrderResult(success = true, orderId = "PAPER_${System.currentTimeMillis()}")
    }

    override suspend fun getPositions(): Result<List<Position>> {
        return Result.success(positions.toList())
    }

    override suspend fun getFunds(): Result<Funds> {
        return Result.success(Funds(availableCash = _capital))
    }
}
