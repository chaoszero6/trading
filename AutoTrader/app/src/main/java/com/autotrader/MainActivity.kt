package com.autotrader

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.lifecycle.viewmodel.compose.viewModel
import com.autotrader.ui.MainViewModel
import com.autotrader.ui.screens.BacktestScreen
import com.autotrader.ui.screens.DashboardScreen
import com.autotrader.ui.screens.SetupScreen
import com.autotrader.ui.theme.AutoTraderTheme
import com.autotrader.ui.theme.BgDark

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContent {
            AutoTraderTheme {
                Surface(
                    modifier = Modifier.fillMaxSize().background(BgDark),
                    color = BgDark
                ) {
                    AppContent()
                }
            }
        }
    }
}

enum class Screen { SETUP, DASHBOARD, BACKTEST }

@Composable
fun AppContent() {
    val viewModel: MainViewModel = viewModel()
    var currentScreen by remember { mutableStateOf(Screen.SETUP) }

    when (currentScreen) {
        Screen.SETUP -> SetupScreen(
            viewModel = viewModel,
            onStartTrading = { currentScreen = Screen.DASHBOARD },
            onOpenBacktest = { currentScreen = Screen.BACKTEST }
        )
        Screen.DASHBOARD -> DashboardScreen(
            viewModel = viewModel,
            onBack = { currentScreen = Screen.SETUP }
        )
        Screen.BACKTEST -> BacktestScreen(
            viewModel = viewModel,
            onBack = { currentScreen = Screen.SETUP }
        )
    }
}
