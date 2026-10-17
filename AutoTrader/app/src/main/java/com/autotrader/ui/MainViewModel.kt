package com.autotrader.ui

import android.app.Application
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import com.autotrader.broker.*
import com.autotrader.data.db.AppDatabase
import com.autotrader.data.preferences.PreferencesManager
import com.autotrader.data.repository.TradeDirection
import com.autotrader.data.repository.TradeRepository
import com.autotrader.engine.*
import kotlinx.coroutines.*
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import java.text.SimpleDateFormat
import java.util.*

data class AppState(
    val isConfigured: Boolean = false,
    val lotSize: Int = 65,
    val capital: Double = 50000.0,
    val script: String = "NIFTY",
    val brokerType: String = "PAPER",
    val maxTrades: Int = 3,
    val dailyProfitCapPct: Double = 5.0,
    val stPeriod: Int = 10,
    val stMultiplier: Double = 3.0,
    val candleZonePct: Double = 0.5,

    // Dashboard
    val isRunning: Boolean = false,
    val currentLTP: Double = 0.0,
    val currentVWAP: Double = 0.0,
    val currentEMA9: Double = 0.0,
    val currentEMA27: Double = 0.0,
    val currentRSI: Double = 0.0,
    val currentRSIMA: Double = 0.0,
    val currentST: String = "",
    val currentCandle: String = "",
    val todayPnl: Double = 0.0,
    val tradesToday: Int = 0,
    val winsToday: Int = 0,
    val lossesToday: Int = 0,
    val dailyCapReached: Boolean = false,
    val hasOpenTrade: Boolean = false,
    val openTradeDirection: String = "",
    val openTradeEntry: Double = 0.0,
    val openTradePnl: Double = 0.0,
    val openTradeSL: Double = 0.0,
    val openTradeTarget: Double = 0.0,
    val openTradeProgress: Float = 0f,
    val signalLog: List<String> = emptyList(),
    val lastSignal: String = "",
    val lastExitReason: String = "",

    // Backtest
    val backtestResult: BacktestResult? = null,
    val isBacktesting: Boolean = false,
    val backtestProgress: String = "",

    // Broker Credentials
    val angelApiKey: String = "",
    val angelClientId: String = "",
    val angelPassword: String = "",
    val angelTotp: String = "",
    val zerodhaApiKey: String = "",
    val zerodhaAccessToken: String = "",
    val zerodhaUserId: String = "",

    // Errors
    val error: String? = null
)

class MainViewModel(application: Application) : AndroidViewModel(application) {

    private val prefs = PreferencesManager(application)
    private val db = AppDatabase.getInstance(application)
    private val repo = TradeRepository(db)

    private val _state = MutableStateFlow(AppState())
    val state: StateFlow<AppState> = _state.asStateFlow()

    private var broker: Broker = PaperBroker()
    private var riskManager: RiskManager = RiskManager(TradingConfig())
    private var tradingJob: Job? = null
    private var candlesCache = mutableListOf<Candle>()
    private var indicatorsCache: IndicatorValues? = null

    private val sdf = SimpleDateFormat("HH:mm:ss", Locale.getDefault())

    companion object {
        private const val MARKET_OPEN_HOUR = 9
        private const val MARKET_OPEN_MIN = 15
        private const val WARMUP_MINUTES = 5
        private const val MARKET_CLOSE_HOUR = 15
        private const val MARKET_CLOSE_MIN = 15
    }

    init {
        loadSavedConfig()
    }

    private fun loadSavedConfig() {
        _state.value = _state.value.copy(
            lotSize = prefs.lotSize,
            capital = prefs.capital,
            script = prefs.script,
            brokerType = prefs.brokerType,
            maxTrades = prefs.maxTradesPerDay,
            dailyProfitCapPct = prefs.dailyProfitCapPct,
            stPeriod = prefs.superTrendPeriod,
            stMultiplier = prefs.superTrendMultiplier,
            candleZonePct = prefs.candleZonePct,
            angelApiKey = prefs.angelApiKey,
            angelClientId = prefs.angelClientId,
            angelPassword = prefs.angelPassword,
            angelTotp = prefs.angelTotp,
            zerodhaApiKey = prefs.zerodhaApiKey,
            zerodhaAccessToken = prefs.zerodhaAccessToken,
            zerodhaUserId = prefs.zerodhaUserId,
            isConfigured = true
        )
    }

    fun updateLotSize(v: Int) { _state.value = _state.value.copy(lotSize = v); prefs.lotSize = v }
    fun updateCapital(v: Double) { _state.value = _state.value.copy(capital = v); prefs.capital = v }
    fun updateScript(v: String) { _state.value = _state.value.copy(script = v); prefs.script = v }
    fun updateBroker(v: String) { _state.value = _state.value.copy(brokerType = v); prefs.brokerType = v }
    fun updateMaxTrades(v: Int) { _state.value = _state.value.copy(maxTrades = v); prefs.maxTradesPerDay = v }
    fun updateProfitCap(v: Double) { _state.value = _state.value.copy(dailyProfitCapPct = v); prefs.dailyProfitCapPct = v }
    fun updateSTPeriod(v: Int) { _state.value = _state.value.copy(stPeriod = v); prefs.superTrendPeriod = v }
    fun updateSTMultiplier(v: Double) { _state.value = _state.value.copy(stMultiplier = v); prefs.superTrendMultiplier = v }
    fun updateCandleZone(v: Double) { _state.value = _state.value.copy(candleZonePct = v); prefs.candleZonePct = v }

    fun updateAngelCreds(apiKey: String, clientId: String, password: String, totp: String) {
        prefs.angelApiKey = apiKey; prefs.angelClientId = clientId
        prefs.angelPassword = password; prefs.angelTotp = totp
        _state.value = _state.value.copy(angelApiKey = apiKey, angelClientId = clientId, angelPassword = password, angelTotp = totp)
    }
    fun updateZerodhaCreds(apiKey: String, accessToken: String, userId: String) {
        prefs.zerodhaApiKey = apiKey; prefs.zerodhaAccessToken = accessToken; prefs.zerodhaUserId = userId
        _state.value = _state.value.copy(zerodhaApiKey = apiKey, zerodhaAccessToken = accessToken, zerodhaUserId = userId)
    }

    fun clearError() { _state.value = _state.value.copy(error = null) }

    fun startTrading() {
        val s = _state.value
        val config = TradingConfig(
            lotSize = s.lotSize,
            capital = s.capital,
            script = s.script,
            brokerType = s.brokerType,
            maxTradesPerDay = s.maxTrades,
            dailyProfitCapPct = s.dailyProfitCapPct,
            targetProfitPct = 3.0
        )
        riskManager = RiskManager(config)
        val brokerConfig = BrokerConfig(
            apiKey = s.angelApiKey,
            clientId = s.angelClientId,
            password = s.angelPassword,
            totp = s.angelTotp,
            accessToken = s.zerodhaAccessToken,
            userId = s.zerodhaUserId
        )
        broker = BrokerFactory.create(s.brokerType)
        _state.value = s.copy(isRunning = true, signalLog = emptyList())

        tradingJob = viewModelScope.launch(Dispatchers.IO) {
            try {
                broker.connect(brokerConfig)
                while (isActive && _state.value.isRunning) {
                    runTradingCycle()
                    delay(60_000L)
                }
            } catch (e: Exception) {
                _state.value = _state.value.copy(isRunning = false, error = e.message)
            }
        }
    }

    fun stopTrading() {
        tradingJob?.cancel()
        _state.value = _state.value.copy(isRunning = false)
        viewModelScope.launch {
            broker.disconnect()
        }
    }

    private suspend fun runTradingCycle() {
        val s = _state.value
        try {
            val now = Calendar.getInstance()
            val hour = now.get(Calendar.HOUR_OF_DAY)
            val minute = now.get(Calendar.MINUTE)

            val marketOpenMs = Calendar.getInstance().apply {
                set(Calendar.HOUR_OF_DAY, MARKET_OPEN_HOUR)
                set(Calendar.MINUTE, MARKET_OPEN_MIN)
                set(Calendar.SECOND, 0)
            }.timeInMillis
            val warmupEndMs = marketOpenMs + WARMUP_MINUTES * 60_000L
            val marketCloseMs = Calendar.getInstance().apply {
                set(Calendar.HOUR_OF_DAY, MARKET_CLOSE_HOUR)
                set(Calendar.MINUTE, MARKET_CLOSE_MIN)
                set(Calendar.SECOND, 0)
            }.timeInMillis

            if (now.timeInMillis < marketOpenMs) {
                _state.value = s.copy(lastSignal = "Waiting for market open...")
                return
            }
            if (now.timeInMillis < warmupEndMs) {
                _state.value = s.copy(lastSignal = "Warmup period (first 5 min)...")
                return
            }
            if (now.timeInMillis >= marketCloseMs) {
                _state.value = s.copy(lastSignal = "Market closed", isRunning = false)
                return
            }

            val ltpResult = broker.getLTP(s.script)
            if (ltpResult.isFailure) {
                addSignal("LTP fetch failed: ${ltpResult.exceptionOrNull()?.message}")
                return
            }
            val ltp = ltpResult.getOrThrow()

            val candlesResult = broker.getCandles(s.script, "5m")
            if (candlesResult.isSuccess) {
                candlesCache = candlesResult.getOrThrow().toMutableList()
                indicatorsCache = TechnicalIndicators.computeAll(candlesCache)
            }

            val hourlyCandlesResult = broker.getCandles(s.script, "60m")
            var hourlyInd: IndicatorValues? = null
            var hourlyIdx = -1
            if (hourlyCandlesResult.isSuccess) {
                val hourlyData = hourlyCandlesResult.getOrThrow()
                hourlyInd = TechnicalIndicators.computeAll(hourlyData)
                hourlyIdx = hourlyData.size - 1
            }

            val ind = indicatorsCache
            if (ind != null && candlesCache.isNotEmpty()) {
                val lastIdx = candlesCache.size - 1
                val lastCandle = candlesCache[lastIdx]
                val ema9 = if (ind.ema9.size > lastIdx) ind.ema9[lastIdx] else 0.0
                val ema27 = if (ind.ema27.size > lastIdx) ind.ema27[lastIdx] else 0.0
                val rsi14 = if (ind.rsi14.size > lastIdx) ind.rsi14[lastIdx] else 50.0
                val rsiMa = if (ind.rsiMa20.size > lastIdx) ind.rsiMa20[lastIdx] else 50.0
                val vwap = if (ind.vwap.size > lastIdx) ind.vwap[lastIdx] else 0.0
                val st = if (ind.superTrend.size > lastIdx) ind.superTrend[lastIdx].name else ""

                _state.value = s.copy(
                    currentLTP = ltp,
                    currentVWAP = vwap,
                    currentEMA9 = ema9,
                    currentEMA27 = ema27,
                    currentRSI = rsi14,
                    currentRSIMA = rsiMa,
                    currentST = st,
                    currentCandle = formatCandle(lastCandle)
                )

                if (riskManager.hasOpenTrade()) {
                    val openTrade = riskManager.getOpenTrade()!!
                    val pnlDiff = when (openTrade.direction) {
                        TradeDirection.CE -> ltp - openTrade.entryPrice
                        TradeDirection.PE -> openTrade.entryPrice - ltp
                    }
                    val pnl = pnlDiff * openTrade.quantity
                    val progress = ((ltp - openTrade.entryPrice) / (openTrade.target - openTrade.entryPrice)).toFloat().coerceIn(0f, 1f)

                    _state.value = _state.value.copy(
                        hasOpenTrade = true,
                        openTradeDirection = openTrade.direction.name,
                        openTradeEntry = openTrade.entryPrice,
                        openTradePnl = pnl,
                        openTradeSL = openTrade.stopLoss,
                        openTradeTarget = openTrade.target,
                        openTradeProgress = progress,
                        todayPnl = riskManager.currentDailyPnl() + pnl
                    )

                    val exit = StrategyEngine.evaluateExit(
                        direction = openTrade.direction,
                        candles = candlesCache,
                        ind = ind,
                        currentIndex = lastIdx,
                        hourlyCandles = hourlyCandlesResult.getOrNull(),
                        hourlyInd = hourlyInd,
                        hourlyIndex = hourlyIdx
                    )

                    val atTarget = StrategyEngine.evaluateExitAtTarget(openTrade.entryPrice, ltp, openTrade.direction)
                    val atStop = StrategyEngine.evaluateExitAtStop(openTrade.entryPrice, openTrade.stopLoss, ltp, openTrade.direction)

                    var exitReason: String? = null
                    if (atTarget) exitReason = "Target hit"
                    else if (atStop) exitReason = "Stop loss"
                    else if (exit.shouldExit) exitReason = exit.reason

                    if (exitReason != null) {
                        val closed = riskManager.registerExit(ltp, exitReason)
                        addSignal("CLOSED ${openTrade.direction} @ $ltp | P&L: ${closed.pnl?.toInt()} | $exitReason")
                        val (w, l) = countWinsLosses()
                        _state.value = _state.value.copy(
                            hasOpenTrade = false,
                            tradesToday = riskManager.tradesCount(),
                            winsToday = w,
                            lossesToday = l,
                            dailyCapReached = riskManager.isDailyCapHit(),
                            todayPnl = riskManager.currentDailyPnl(),
                            lastExitReason = exitReason
                        )
                    }
                } else {
                    if (riskManager.canTakeTrade()) {
                        val entry = StrategyEngine.evaluateEntry(
                            candles = candlesCache, ind = ind, currentIndex = lastIdx, timestamp = lastCandle.timestamp
                        )
                        if (entry != null) {
                            val quantity = (s.capital / s.lotSize).toInt().coerceAtLeast(1) * s.lotSize
                            val trade = TradeRecord(
                                script = s.script,
                                direction = entry.direction,
                                entryPrice = entry.entryPrice,
                                stopLoss = entry.stopLoss,
                                target = entry.target,
                                quantity = quantity,
                                signalsMet = entry.signalsMet,
                                totalSignals = entry.totalSignals,
                                rsiAtEntry = rsi14,
                                ema9AtEntry = ema9,
                                ema27AtEntry = ema27,
                                vwapAtEntry = vwap,
                                stAtEntry = st
                            )
                            riskManager.registerEntry(trade)
                            addSignal("ENTRY ${entry.direction} @ ${entry.entryPrice} | Sig: ${entry.signalsMet}/${entry.totalSignals} | Qty: $quantity")
                            _state.value = _state.value.copy(
                                hasOpenTrade = true,
                                openTradeDirection = entry.direction.name,
                                openTradeEntry = entry.entryPrice,
                                openTradePnl = 0.0,
                                openTradeSL = entry.stopLoss,
                                openTradeTarget = entry.target,
                                openTradeProgress = 0f
                            )
                        } else {
                            _state.value = _state.value.copy(lastSignal = "No entry signal")
                        }
                    } else {
                        var reason = "Skipped: "
                        if (!riskManager.canTakeTrade()) {
                            if (riskManager.isMaxTradeReached()) reason += "Max trades (${s.maxTrades}) reached"
                            if (riskManager.isDailyCapHit()) reason += "Daily cap (${s.dailyProfitCapPct}%) hit"
                        }
                        _state.value = _state.value.copy(lastSignal = reason)
                    }
                }
            }
        } catch (e: Exception) {
            addSignal("Error: ${e.message}")
        }
    }

    fun startBacktest(dateRange: Pair<String, String>) {
        _state.value = _state.value.copy(isBacktesting = true, backtestProgress = "Fetching historical data...")
        viewModelScope.launch(Dispatchers.IO) {
            try {
                val s = _state.value
                val broker = PaperBroker()
                broker.connect(BrokerConfig())

                var allCandles = mutableListOf<Candle>()
                if (dateRange.first.isNotEmpty() && dateRange.second.isNotEmpty()) {
                    val sdf = SimpleDateFormat("yyyy-MM-dd", Locale.US)
                    val startMs = sdf.parse(dateRange.first)?.time ?: 0L
                    val endMs = sdf.parse(dateRange.second)?.time ?: System.currentTimeMillis()
                    val endOfDay = endMs + 24 * 60 * 60 * 1000 - 1L
                    val diffDays = ((endMs - startMs) / (24 * 60 * 60 * 1000)).toInt().coerceIn(1, 365)

                    _state.value = _state.value.copy(backtestProgress = "Fetching $diffDays days of data...")
                    val result = broker.getCandles(s.script, "5m")
                    if (result.isSuccess) {
                        allCandles = result.getOrThrow()
                            .filter { it.timestamp in startMs..endOfDay }
                            .toMutableList()
                    }
                } else {
                    val result = broker.getCandles(s.script, "5m")
                    if (result.isSuccess) {
                        allCandles = result.getOrThrow().toMutableList()
                    }
                }

                if (allCandles.size < 50) {
                    _state.value = _state.value.copy(
                        isBacktesting = false,
                        error = "Insufficient data (${allCandles.size} candles). Need 50+."
                    )
                    return@launch
                }

                _state.value = _state.value.copy(backtestProgress = "Running backtest on ${allCandles.size} candles...")

                val engine = BacktestEngine()
                val result = engine.run(
                    candles = allCandles,
                    config = BacktestEngine.BacktestConfig(
                        capital = s.capital,
                        lotSize = s.lotSize,
                        script = s.script,
                        maxTradesPerDay = s.maxTrades,
                        dailyProfitCapPct = s.dailyProfitCapPct
                    )
                )

                _state.value = _state.value.copy(
                    isBacktesting = false,
                    backtestResult = result,
                    backtestProgress = "Done"
                )
            } catch (e: Exception) {
                _state.value = _state.value.copy(isBacktesting = false, error = e.message)
            }
        }
    }

    private fun addSignal(msg: String) {
        val ts = sdf.format(Date())
        val entry = "$ts $msg"
        val log = _state.value.signalLog.toMutableList()
        log.add(0, entry)
        if (log.size > 100) log.removeAt(log.size - 1)
        _state.value = _state.value.copy(signalLog = log, lastSignal = entry)
    }

    private fun countWinsLosses(): Pair<Int, Int> {
        val trades = riskManager.getTradesToday()
        val w = trades.count { it.pnl != null && it.pnl > 0 }
        val l = trades.count { it.pnl != null && it.pnl < 0 }
        return w to l
    }

    private fun formatCandle(c: Candle): String {
        return "O:${"%.1f".format(c.open)} H:${"%.1f".format(c.high)} L:${"%.1f".format(c.low)} C:${"%.1f".format(c.close)}"
    }
}
