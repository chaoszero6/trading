package com.autotrader.ui.theme

import androidx.compose.material3.*
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color

val BgDark = Color(0xFF1A1A2E)
val BgCard = Color(0xFF16213E)
val AccentGreen = Color(0xFF00FF88)
val AccentRed = Color(0xFFFF4444)
val AccentBlue = Color(0xFF0F9BFF)
val AccentYellow = Color(0xFFFFD700)
val TextPrimary = Color.White
val TextSecondary = Color(0xFFB0B0B0)
val StGreen = Color(0xFF00C853)
val StRed = Color(0xFFFF1744)

private val DarkColorScheme = darkColorScheme(
    primary = AccentBlue,
    secondary = AccentGreen,
    tertiary = AccentYellow,
    background = BgDark,
    surface = BgCard,
    onPrimary = Color.White,
    onSecondary = Color.Black,
    onTertiary = Color.Black,
    onBackground = TextPrimary,
    onSurface = TextPrimary,
    error = AccentRed,
    onError = Color.White
)

@Composable
fun AutoTraderTheme(content: @Composable () -> Unit) {
    MaterialTheme(
        colorScheme = DarkColorScheme,
        typography = Typography(),
        content = content
    )
}
