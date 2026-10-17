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
import com.autotrader.engine.BacktestResult
import com.autotrader.ui.MainViewModel
import com.autotrader.ui.theme.*
import java.text.DecimalFormat
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun BacktestScreen(
    viewModel: MainViewModel,
    onBack: () -> Unit
) {
    val state = viewModel.state.collectAsState()
    val s = state.value
    val df = remember { DecimalFormat("#,##0.00") }

    var startDate by remember { mutableStateOf("") }
    var endDate by remember { mutableStateOf("") }
    var startDateMs by remember { mutableStateOf<Long?>(null) }
    var endDateMs by remember { mutableStateOf<Long?>(null) }
    var showStartPicker by remember { mutableStateOf(false) }
    var showEndPicker by remember { mutableStateOf(false) }

    val dateFormat = remember { SimpleDateFormat("yyyy-MM-dd", Locale.US) }

    if (showStartPicker) {
        val dateState = rememberDatePickerState(initialSelectedDateMillis = startDateMs)
        DatePickerDialog(
            onDismissRequest = { showStartPicker = false },
            confirmButton = {
                TextButton(onClick = {
                    dateState.selectedDateMillis?.let { ms ->
                        startDateMs = ms
                        startDate = dateFormat.format(Date(ms))
                    }
                    showStartPicker = false
                }) { Text("OK", color = AccentGreen) }
            },
            dismissButton = {
                TextButton(onClick = { showStartPicker = false }) { Text("CANCEL", color = AccentRed) }
            }
        ) {
            DatePicker(state = dateState, colors = DatePickerDefaults.colors(containerColor = BgCard))
        }
    }

    if (showEndPicker) {
        val dateState = rememberDatePickerState(initialSelectedDateMillis = endDateMs)
        DatePickerDialog(
            onDismissRequest = { showEndPicker = false },
            confirmButton = {
                TextButton(onClick = {
                    dateState.selectedDateMillis?.let { ms ->
                        endDateMs = ms
                        endDate = dateFormat.format(Date(ms))
                    }
                    showEndPicker = false
                }) { Text("OK", color = AccentGreen) }
            },
            dismissButton = {
                TextButton(onClick = { showEndPicker = false }) { Text("CANCEL", color = AccentRed) }
            }
        ) {
            DatePicker(state = dateState, colors = DatePickerDefaults.colors(containerColor = BgCard))
        }
    }

    Column(
        modifier = Modifier
            .fillMaxSize()
            .background(BgDark)
            .verticalScroll(rememberScrollState())
            .padding(12.dp)
    ) {
        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween, verticalAlignment = Alignment.CenterVertically) {
            Text("📊 BACKTEST", color = AccentBlue, fontSize = 18.sp, fontWeight = FontWeight.Bold)
            Button(onClick = onBack, colors = ButtonDefaults.buttonColors(containerColor = AccentRed),
                contentPadding = PaddingValues(horizontal = 12.dp, vertical = 4.dp)) {
                Text("BACK", color = Color.White, fontSize = 12.sp)
            }
        }
        Spacer(Modifier.height(8.dp))

        // Date inputs
        Card(modifier = Modifier.fillMaxWidth(), colors = CardDefaults.cardColors(containerColor = BgCard)) {
            Column(Modifier.padding(12.dp)) {
                Text("Date Range (optional, leave blank for max data)", color = TextSecondary, fontSize = 12.sp)
                Spacer(Modifier.height(4.dp))
                Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    // Start date picker
                    Column(Modifier.weight(1f)) {
                        Text("Start Date", color = TextSecondary, fontSize = 11.sp)
                        Spacer(Modifier.height(2.dp))
                        Surface(
                            onClick = { showStartPicker = true },
                            modifier = Modifier.fillMaxWidth().height(48.dp),
                            shape = RoundedCornerShape(8.dp),
                            color = BgDark,
                            border = BorderStroke(1.dp, TextSecondary.copy(alpha = 0.5f))
                        ) {
                            Box(Modifier.fillMaxSize().padding(horizontal = 12.dp), contentAlignment = Alignment.CenterStart) {
                                Text(
                                    if (startDate.isEmpty()) "Select start date" else startDate,
                                    color = if (startDate.isEmpty()) TextSecondary else TextPrimary,
                                    fontSize = 13.sp
                                )
                            }
                        }
                    }
                    // End date picker
                    Column(Modifier.weight(1f)) {
                        Text("End Date", color = TextSecondary, fontSize = 11.sp)
                        Spacer(Modifier.height(2.dp))
                        Surface(
                            onClick = { showEndPicker = true },
                            modifier = Modifier.fillMaxWidth().height(48.dp),
                            shape = RoundedCornerShape(8.dp),
                            color = BgDark,
                            border = BorderStroke(1.dp, TextSecondary.copy(alpha = 0.5f))
                        ) {
                            Box(Modifier.fillMaxSize().padding(horizontal = 12.dp), contentAlignment = Alignment.CenterStart) {
                                Text(
                                    if (endDate.isEmpty()) "Select end date" else endDate,
                                    color = if (endDate.isEmpty()) TextSecondary else TextPrimary,
                                    fontSize = 13.sp
                                )
                            }
                        }
                    }
                }
                Spacer(Modifier.height(8.dp))

                val script = s.script
                Text("Script: $script | Capital: ₹${df.format(s.capital)} | Lot: ${s.lotSize}", color = TextSecondary, fontSize = 12.sp)

                Spacer(Modifier.height(8.dp))

                Button(
                    onClick = {
                        val range = if (startDate.isEmpty() && endDate.isEmpty()) "" to ""
                        else startDate to endDate
                        viewModel.startBacktest(range)
                    },
                    modifier = Modifier.fillMaxWidth().height(48.dp),
                    enabled = !s.isBacktesting,
                    colors = ButtonDefaults.buttonColors(containerColor = AccentBlue)
                ) {
                    Text(
                        if (s.isBacktesting) "RUNNING... ${s.backtestProgress}" else "▶ RUN BACKTEST",
                        color = Color.White, fontWeight = FontWeight.Bold
                    )
                }

                if (s.isBacktesting) {
                    Spacer(Modifier.height(4.dp))
                    LinearProgressIndicator(modifier = Modifier.fillMaxWidth(), color = AccentGreen, trackColor = TextSecondary.copy(alpha = 0.3f))
                }
            }
        }

        Spacer(Modifier.height(12.dp))

        // Results
        val result = s.backtestResult
        if (result != null) {
            Card(modifier = Modifier.fillMaxWidth(), colors = CardDefaults.cardColors(containerColor = BgCard)) {
                Column(Modifier.padding(12.dp)) {
                    Text("RESULTS", color = AccentGreen, fontSize = 16.sp, fontWeight = FontWeight.Bold)
                    Spacer(Modifier.height(8.dp))

                    ResultRow("Total Trades", "${result.totalTrades}", AccentBlue)
                    val winColor = if (result.winRate >= 50) AccentGreen else AccentRed
                    ResultRow("Win / Loss", "${result.wins}W / ${result.losses}L", AccentYellow)
                    ResultRow("Win Rate", "${"%.1f".format(result.winRate)}%", winColor)
                    val pnlColor = if (result.netPnl >= 0) AccentGreen else AccentRed
                    ResultRow("Net P&L", "₹${df.format(result.netPnl)}", pnlColor)
                    ResultRow("Total Return", "${"%.2f".format(result.totalReturnPct)}%", pnlColor)
                    ResultRow("Max Drawdown", "${"%.2f".format(result.maxDrawdown)}%", AccentRed)
                    ResultRow("Avg Win", "₹${df.format(result.avgWin)}", AccentGreen)
                    ResultRow("Avg Loss", "₹${df.format(result.avgLoss)}", AccentRed)
                    ResultRow("Sharpe Ratio", "${"%.2f".format(result.sharpeRatio)}", if (result.sharpeRatio >= 1) AccentGreen else AccentYellow)
                    ResultRow("Max Consecutive Losses", "${result.maxConsecutiveLosses}", AccentRed)

                    Spacer(Modifier.height(8.dp))

                    // Trade Log
                    if (result.trades.isNotEmpty()) {
                        Text("TRADE LOG", color = AccentBlue, fontSize = 14.sp, fontWeight = FontWeight.Bold)
                        Spacer(Modifier.height(4.dp))
                        Column(
                            modifier = Modifier.heightIn(max = 300.dp).verticalScroll(rememberScrollState())
                        ) {
                            result.trades.forEachIndexed { i, trade ->
                                val color = if (trade.pnl != null && trade.pnl > 0) AccentGreen else AccentRed
                                Card(
                                    modifier = Modifier.fillMaxWidth().padding(vertical = 2.dp),
                                    colors = CardDefaults.cardColors(containerColor = BgDark)
                                ) {
                                    Column(Modifier.padding(8.dp)) {
                                        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                                            Text("#${i + 1} ${trade.direction}", color = color, fontSize = 12.sp, fontWeight = FontWeight.Bold)
                                            Text("P&L: ₹${df.format(trade.pnl ?: 0.0)}", color = color, fontSize = 12.sp)
                                        }
                                        Text("Entry: ${"%.1f".format(trade.entryPrice)} → Exit: ${"%.1f".format(trade.exitPrice ?: 0.0)}",
                                            color = TextSecondary, fontSize = 11.sp)
                                        Text("Reason: ${trade.exitReason ?: "Open"}", color = TextSecondary, fontSize = 11.sp)
                                        Text("Sig: ${trade.signalsMet}/${trade.totalSignals} | RSI: ${"%.1f".format(trade.rsiAtEntry)}",
                                            color = TextSecondary, fontSize = 10.sp)
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }

        Spacer(Modifier.height(12.dp))
    }
}

@Composable
private fun ResultRow(label: String, value: String, valueColor: Color) {
    Row(Modifier.fillMaxWidth().padding(vertical = 2.dp), horizontalArrangement = Arrangement.SpaceBetween) {
        Text(label, color = TextSecondary, fontSize = 12.sp)
        Text(value, color = valueColor, fontSize = 12.sp, fontWeight = FontWeight.Bold)
    }
}

@Composable
private fun fieldColors() = OutlinedTextFieldDefaults.colors(
    focusedBorderColor = AccentBlue, unfocusedBorderColor = TextSecondary,
    focusedTextColor = TextPrimary, unfocusedTextColor = TextPrimary,
    cursorColor = AccentBlue
)
