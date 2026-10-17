package com.autotrader.ui.screens

import androidx.compose.foundation.*
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.autotrader.ui.MainViewModel
import com.autotrader.ui.theme.*
import java.text.DecimalFormat

@Composable
fun DashboardScreen(
    viewModel: MainViewModel,
    onBack: () -> Unit
) {
    val state = viewModel.state.collectAsState()
    val s = state.value
    val df = remember { DecimalFormat("#,##0.00") }
    val dfPct = remember { DecimalFormat("+0.00%;-0.00%") }

    Column(
        modifier = Modifier
            .fillMaxSize()
            .background(BgDark)
            .verticalScroll(rememberScrollState())
            .padding(12.dp)
    ) {
        // Header
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically
        ) {
            Text("📊 DASHBOARD", color = AccentBlue, fontSize = 18.sp, fontWeight = FontWeight.Bold)
            Button(
                onClick = {
                    viewModel.stopTrading()
                    onBack()
                },
                colors = ButtonDefaults.buttonColors(containerColor = AccentRed),
                contentPadding = PaddingValues(horizontal = 12.dp, vertical = 4.dp)
            ) {
                Text("STOP", color = Color.White, fontSize = 12.sp)
            }
        }
        Spacer(Modifier.height(8.dp))

        // Capital + P&L row
        Row(modifier = Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            StatCard("Capital", "₹${df.format(s.capital)}", AccentBlue, Modifier.weight(1f))
            StatCard("Today P&L",
                "₹${df.format(s.todayPnl)}",
                if (s.todayPnl >= 0) AccentGreen else AccentRed,
                Modifier.weight(1f))
            val winRate = if (s.tradesToday > 0) "${s.winsToday * 100 / s.tradesToday}%" else "-"
            StatCard("Win Rate", winRate, AccentYellow, Modifier.weight(1f))
        }

        Spacer(Modifier.height(4.dp))
        // Status
        val statusColor = if (s.isRunning) AccentGreen else AccentRed
        Row(
            modifier = Modifier.fillMaxWidth().background(BgCard, RoundedCornerShape(8.dp)).padding(8.dp),
            horizontalArrangement = Arrangement.SpaceBetween
        ) {
            Text("${s.script} | ${s.brokerType}", color = TextSecondary, fontSize = 12.sp)
            Row(verticalAlignment = Alignment.CenterVertically) {
                Box(Modifier.size(8.dp).background(statusColor, RoundedCornerShape(4.dp)))
                Spacer(Modifier.width(4.dp))
                Text(if (s.isRunning) "RUNNING" else "STOPPED", color = statusColor, fontSize = 12.sp, fontWeight = FontWeight.Bold)
            }
            Text("Trades: ${s.tradesToday}/${s.maxTrades}", color = TextSecondary, fontSize = 12.sp)
        }

        if (s.dailyCapReached) {
            Spacer(Modifier.height(4.dp))
            Text("✅ Daily profit cap (${s.dailyProfitCapPct}%) reached — no more trades today",
                color = AccentGreen, fontSize = 11.sp, fontWeight = FontWeight.Bold)
        }

        Spacer(Modifier.height(8.dp))

        // Active Position
        if (s.hasOpenTrade) {
            Card(
                modifier = Modifier.fillMaxWidth(),
                colors = CardDefaults.cardColors(containerColor = BgCard)
            ) {
                Column(Modifier.padding(12.dp)) {
                    val dirColor = if (s.openTradeDirection == "CE") AccentGreen else AccentRed
                    Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                        Text("ACTIVE POSITION", color = AccentBlue, fontSize = 14.sp, fontWeight = FontWeight.Bold)
                        Text(s.openTradeDirection, color = dirColor, fontSize = 16.sp, fontWeight = FontWeight.Bold)
                    }
                    Spacer(Modifier.height(4.dp))
                    Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                        Text("Entry: ₹${df.format(s.openTradeEntry)}", color = TextPrimary, fontSize = 13.sp)
                        val pnlColor = if (s.openTradePnl >= 0) AccentGreen else AccentRed
                        Text("P&L: ₹${df.format(s.openTradePnl)}", color = pnlColor, fontSize = 13.sp, fontWeight = FontWeight.Bold)
                    }
                    Spacer(Modifier.height(4.dp))
                    // Progress bar
                    val progressColor = if (s.openTradeProgress >= 1f) AccentGreen else AccentBlue
                    @Suppress("DEPRECATION")
                    LinearProgressIndicator(
                        progress = s.openTradeProgress.coerceIn(0f, 1f),
                        modifier = Modifier.fillMaxWidth().height(6.dp),
                        color = progressColor,
                        trackColor = TextSecondary.copy(alpha = 0.3f)
                    )
                    Spacer(Modifier.height(4.dp))
                    Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                        Text("SL: ₹${df.format(s.openTradeSL)}", color = AccentRed, fontSize = 11.sp)
                        Text("Target: ₹${df.format(s.openTradeTarget)}", color = AccentGreen, fontSize = 11.sp)
                    }
                }
            }
        } else {
            Card(
                modifier = Modifier.fillMaxWidth(),
                colors = CardDefaults.cardColors(containerColor = BgCard)
            ) {
                Text("No open position", color = TextSecondary, fontSize = 13.sp,
                    modifier = Modifier.padding(12.dp), textAlign = TextAlign.Center)
            }
        }

        Spacer(Modifier.height(8.dp))

        // Market Data
        Card(
            modifier = Modifier.fillMaxWidth(),
            colors = CardDefaults.cardColors(containerColor = BgCard)
        ) {
            Column(Modifier.padding(12.dp)) {
                Text("MARKET DATA", color = AccentBlue, fontSize = 14.sp, fontWeight = FontWeight.Bold)
                Spacer(Modifier.height(6.dp))
                Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                    Text("LTP:", color = TextSecondary, fontSize = 12.sp)
                    Text("₹${df.format(s.currentLTP)}", color = TextPrimary, fontSize = 12.sp, fontWeight = FontWeight.Bold)
                }
                Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                    Text("VWAP:", color = TextSecondary, fontSize = 12.sp)
                    Text("₹${df.format(s.currentVWAP)}", color = TextPrimary, fontSize = 12.sp)
                }
                Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                    Text("EMA9:", color = TextSecondary, fontSize = 12.sp)
                    Text("₹${df.format(s.currentEMA9)}", color = TextPrimary, fontSize = 12.sp)
                }
                Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                    Text("EMA27:", color = TextSecondary, fontSize = 12.sp)
                    Text("₹${df.format(s.currentEMA27)}", color = TextPrimary, fontSize = 12.sp)
                }
                Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                    Text("RSI(14):", color = TextSecondary, fontSize = 12.sp)
                    val rsiColor = when {
                        s.currentRSI > 55 -> AccentGreen
                        s.currentRSI < 45 -> AccentRed
                        else -> AccentYellow
                    }
                    Text(df.format(s.currentRSI), color = rsiColor, fontSize = 12.sp, fontWeight = FontWeight.Bold)
                }
                Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                    Text("RSI MA(20):", color = TextSecondary, fontSize = 12.sp)
                    Text(df.format(s.currentRSIMA), color = TextPrimary, fontSize = 12.sp)
                }
                Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                    Text("SuperTrend:", color = TextSecondary, fontSize = 12.sp)
                    val stColor = if (s.currentST == "GREEN") StGreen else StRed
                    Text(s.currentST.ifEmpty { "-" }, color = stColor, fontSize = 12.sp, fontWeight = FontWeight.Bold)
                }
                if (s.currentCandle.isNotEmpty()) {
                    Spacer(Modifier.height(4.dp))
                    Text("Candle: ${s.currentCandle}", color = TextSecondary, fontSize = 11.sp)
                }
            }
        }

        Spacer(Modifier.height(8.dp))

        // Signal Log
        Card(
            modifier = Modifier.fillMaxWidth().heightIn(max = 250.dp),
            colors = CardDefaults.cardColors(containerColor = BgCard)
        ) {
            Column(Modifier.padding(12.dp)) {
                Text("SIGNAL LOG", color = AccentBlue, fontSize = 14.sp, fontWeight = FontWeight.Bold)
                Spacer(Modifier.height(4.dp))
                if (s.signalLog.isEmpty()) {
                    Text("No signals yet", color = TextSecondary, fontSize = 12.sp)
                } else {
                    Column(
                        modifier = Modifier.verticalScroll(rememberScrollState())
                    ) {
                        s.signalLog.forEach { signal ->
                            Text(
                                signal,
                                color = when {
                                    signal.contains("ENTRY") -> AccentGreen
                                    signal.contains("CLOSED") -> AccentYellow
                                    signal.contains("Error") -> AccentRed
                                    else -> TextSecondary
                                },
                                fontSize = 11.sp,
                                modifier = Modifier.padding(vertical = 1.dp)
                            )
                        }
                    }
                }
            }
        }

        Spacer(Modifier.height(8.dp))

        // Start/Stop Button
        Button(
            onClick = {
                if (s.isRunning) viewModel.stopTrading()
                else viewModel.startTrading()
            },
            modifier = Modifier.fillMaxWidth().height(48.dp),
            colors = ButtonDefaults.buttonColors(
                containerColor = if (s.isRunning) AccentRed else AccentGreen
            )
        ) {
            Text(
                if (s.isRunning) "⏹ STOP ALGO" else "▶ START ALGO",
                color = Color.White,
                fontWeight = FontWeight.Bold
            )
        }

        if (s.error != null) {
            Spacer(Modifier.height(4.dp))
            Text("Error: ${s.error}", color = AccentRed, fontSize = 11.sp)
        }
    }
}

@Composable
private fun StatCard(label: String, value: String, valueColor: Color, modifier: Modifier = Modifier) {
    Card(
        modifier = modifier,
        colors = CardDefaults.cardColors(containerColor = BgCard)
    ) {
        Column(
            modifier = Modifier.padding(8.dp),
            horizontalAlignment = Alignment.CenterHorizontally
        ) {
            Text(label, color = TextSecondary, fontSize = 10.sp)
            Spacer(Modifier.height(2.dp))
            Text(value, color = valueColor, fontSize = 14.sp, fontWeight = FontWeight.Bold)
        }
    }
}
