package com.autotrader.ui.screens

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.autotrader.ui.MainViewModel
import com.autotrader.ui.theme.*

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun SetupScreen(
    viewModel: MainViewModel,
    onStartTrading: () -> Unit,
    onOpenBacktest: () -> Unit
) {
    val state = viewModel.state.collectAsState()
    val s = state.value
    var showAngelCreds by remember { mutableStateOf(false) }
    var showZerodhaCreds by remember { mutableStateOf(false) }

    val brokers = listOf("Angel One", "Zerodha", "ICICI Direct", "Dhan", "Upstox", "Paper Trade")
    var brokerExpanded by remember { mutableStateOf(false) }

    val isLiveBroker = s.brokerType !in listOf("PAPER", "PAPER TRADE")

    Card(
        modifier = Modifier.fillMaxSize().padding(16.dp).verticalScroll(rememberScrollState()),
        colors = CardDefaults.cardColors(containerColor = BgCard)
    ) {
        Column(modifier = Modifier.padding(16.dp)) {
            Text("⚙️ DAILY CONFIGURATION", color = AccentBlue, fontSize = 20.sp, fontWeight = FontWeight.Bold)
            Spacer(Modifier.height(16.dp))

            // Lot Size
            OutlinedTextField(
                value = s.lotSize.toString(),
                onValueChange = { it.toIntOrNull()?.let { v -> viewModel.updateLotSize(v) } },
                label = { Text("Lot Size", color = TextSecondary) },
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number),
                modifier = Modifier.fillMaxWidth(),
                colors = OutlinedTextFieldDefaults.colors(
                    focusedBorderColor = AccentBlue, unfocusedBorderColor = TextSecondary,
                    focusedTextColor = TextPrimary, unfocusedTextColor = TextPrimary
                )
            )
            Spacer(Modifier.height(8.dp))

            // Capital
            OutlinedTextField(
                value = s.capital.toInt().toString(),
                onValueChange = { it.toDoubleOrNull()?.let { v -> viewModel.updateCapital(v) } },
                label = { Text("Capital (₹)", color = TextSecondary) },
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number),
                modifier = Modifier.fillMaxWidth(),
                colors = OutlinedTextFieldDefaults.colors(
                    focusedBorderColor = AccentBlue, unfocusedBorderColor = TextSecondary,
                    focusedTextColor = TextPrimary, unfocusedTextColor = TextPrimary
                )
            )
            Spacer(Modifier.height(8.dp))

            // Script
            OutlinedTextField(
                value = s.script,
                onValueChange = { viewModel.updateScript(it.uppercase()) },
                label = { Text("Script (e.g. NIFTY, BANKNIFTY)", color = TextSecondary) },
                modifier = Modifier.fillMaxWidth(),
                colors = OutlinedTextFieldDefaults.colors(
                    focusedBorderColor = AccentBlue, unfocusedBorderColor = TextSecondary,
                    focusedTextColor = TextPrimary, unfocusedTextColor = TextPrimary
                )
            )
            Spacer(Modifier.height(8.dp))

            // Broker Dropdown
            ExposedDropdownMenuBox(
                expanded = brokerExpanded,
                onExpandedChange = { brokerExpanded = it }
            ) {
                OutlinedTextField(
                    value = s.brokerType,
                    onValueChange = {},
                    readOnly = true,
                    label = { Text("Broker", color = TextSecondary) },
                    trailingIcon = { ExposedDropdownMenuDefaults.TrailingIcon(expanded = brokerExpanded) },
                    modifier = Modifier.fillMaxWidth().menuAnchor(),
                    colors = OutlinedTextFieldDefaults.colors(
                        focusedBorderColor = AccentBlue, unfocusedBorderColor = TextSecondary,
                        focusedTextColor = TextPrimary, unfocusedTextColor = TextPrimary
                    )
                )
                ExposedDropdownMenu(
                    expanded = brokerExpanded,
                    onDismissRequest = { brokerExpanded = false }
                ) {
                    brokers.forEach { b ->
                        DropdownMenuItem(
                            text = { Text(b) },
                            onClick = {
                                viewModel.updateBroker(b)
                                brokerExpanded = false
                                showAngelCreds = b == "Angel One"
                                showZerodhaCreds = b == "Zerodha"
                            }
                        )
                    }
                }
            }
            Spacer(Modifier.height(8.dp))

            // Broker Credentials (conditional)
            if (showAngelCreds || s.brokerType == "Angel One") {
                Text("🔐 Angel One Credentials", color = AccentGreen, fontSize = 14.sp, fontWeight = FontWeight.Bold)
                Spacer(Modifier.height(4.dp))
                OutlinedTextField(value = s.angelApiKey, onValueChange = { viewModel.updateAngelCreds(it, s.angelClientId, s.angelPassword, s.angelTotp) },
                    label = { Text("API Key") }, modifier = Modifier.fillMaxWidth(),
                    colors = fieldColors())
                OutlinedTextField(value = s.angelClientId, onValueChange = { viewModel.updateAngelCreds(s.angelApiKey, it, s.angelPassword, s.angelTotp) },
                    label = { Text("Client ID") }, modifier = Modifier.fillMaxWidth(), colors = fieldColors())
                OutlinedTextField(value = s.angelPassword, onValueChange = { viewModel.updateAngelCreds(s.angelApiKey, s.angelClientId, it, s.angelTotp) },
                    label = { Text("Password") }, modifier = Modifier.fillMaxWidth(), colors = fieldColors())
                OutlinedTextField(value = s.angelTotp, onValueChange = { viewModel.updateAngelCreds(s.angelApiKey, s.angelClientId, s.angelPassword, it) },
                    label = { Text("TOTP Secret") }, modifier = Modifier.fillMaxWidth(), colors = fieldColors())
                Spacer(Modifier.height(8.dp))
            }

            if (showZerodhaCreds || s.brokerType == "Zerodha") {
                Text("🔐 Zerodha Credentials", color = AccentGreen, fontSize = 14.sp, fontWeight = FontWeight.Bold)
                Spacer(Modifier.height(4.dp))
                OutlinedTextField(value = s.zerodhaApiKey, onValueChange = { viewModel.updateZerodhaCreds(it, s.zerodhaAccessToken, s.zerodhaUserId) },
                    label = { Text("API Key") }, modifier = Modifier.fillMaxWidth(), colors = fieldColors())
                OutlinedTextField(value = s.zerodhaAccessToken, onValueChange = { viewModel.updateZerodhaCreds(s.zerodhaApiKey, it, s.zerodhaUserId) },
                    label = { Text("Access Token") }, modifier = Modifier.fillMaxWidth(), colors = fieldColors())
                OutlinedTextField(value = s.zerodhaUserId, onValueChange = { viewModel.updateZerodhaCreds(s.zerodhaApiKey, s.zerodhaAccessToken, it) },
                    label = { Text("User ID") }, modifier = Modifier.fillMaxWidth(), colors = fieldColors())
                Spacer(Modifier.height(8.dp))
            }

            // Max Trades
            OutlinedTextField(
                value = s.maxTrades.toString(),
                onValueChange = { it.toIntOrNull()?.let { v -> viewModel.updateMaxTrades(v.coerceIn(1, 10)) } },
                label = { Text("Max Trades/Day", color = TextSecondary) },
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number),
                modifier = Modifier.fillMaxWidth(), colors = fieldColors()
            )
            Spacer(Modifier.height(8.dp))

            // Daily Profit Cap
            OutlinedTextField(
                value = s.dailyProfitCapPct.toString(),
                onValueChange = { it.toDoubleOrNull()?.let { v -> viewModel.updateProfitCap(v.coerceIn(1.0, 100.0)) } },
                label = { Text("Daily Profit Cap (%)", color = TextSecondary) },
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Decimal),
                modifier = Modifier.fillMaxWidth(), colors = fieldColors()
            )
            Spacer(Modifier.height(8.dp))

            // SuperTrend parameters
            Text("📐 SuperTrend Settings", color = AccentYellow, fontSize = 14.sp, fontWeight = FontWeight.Bold)
            Spacer(Modifier.height(4.dp))
            Row(modifier = Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                OutlinedTextField(
                    value = s.stPeriod.toString(),
                    onValueChange = { it.toIntOrNull()?.let { v -> viewModel.updateSTPeriod(v) } },
                    label = { Text("ATR Period", color = TextSecondary) },
                    keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number),
                    modifier = Modifier.weight(1f), colors = fieldColors()
                )
                OutlinedTextField(
                    value = s.stMultiplier.toString(),
                    onValueChange = { it.toDoubleOrNull()?.let { v -> viewModel.updateSTMultiplier(v) } },
                    label = { Text("Multiplier", color = TextSecondary) },
                    keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Decimal),
                    modifier = Modifier.weight(1f), colors = fieldColors()
                )
            }
            Spacer(Modifier.height(8.dp))

            // Candle Zone
            OutlinedTextField(
                value = s.candleZonePct.toString(),
                onValueChange = { it.toDoubleOrNull()?.let { v -> viewModel.updateCandleZone(v) } },
                label = { Text("Candle Zone % from VWAP", color = TextSecondary) },
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Decimal),
                modifier = Modifier.fillMaxWidth(), colors = fieldColors()
            )

            Spacer(Modifier.height(24.dp))

            // Action Buttons
            Button(
                onClick = {
                    viewModel.startTrading()
                    onStartTrading()
                },
                modifier = Modifier.fillMaxWidth().height(48.dp),
                colors = ButtonDefaults.buttonColors(containerColor = AccentGreen)
            ) {
                Text("▶ START TRADING", color = Color.Black, fontWeight = FontWeight.Bold)
            }
            Spacer(Modifier.height(8.dp))
            OutlinedButton(
                onClick = onOpenBacktest,
                modifier = Modifier.fillMaxWidth().height(48.dp),
                colors = ButtonDefaults.outlinedButtonColors(contentColor = AccentBlue)
            ) {
                Text("📊 BACKTEST")
            }

            // Error
            if (s.error != null) {
                Spacer(Modifier.height(8.dp))
                Text(s.error, color = AccentRed, fontSize = 12.sp)
            }
        }
    }
}

@Composable
private fun fieldColors() = OutlinedTextFieldDefaults.colors(
    focusedBorderColor = AccentBlue, unfocusedBorderColor = TextSecondary,
    focusedTextColor = TextPrimary, unfocusedTextColor = TextPrimary,
    cursorColor = AccentBlue
)
