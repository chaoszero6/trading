package com.autotrader.data.preferences

import android.content.Context
import android.content.SharedPreferences
import androidx.security.crypto.EncryptedSharedPreferences
import androidx.security.crypto.MasterKey

class PreferencesManager(context: Context) {

    private val masterKey = MasterKey.Builder(context)
        .setKeyScheme(MasterKey.KeyScheme.AES256_GCM)
        .build()

    private val securePrefs: SharedPreferences = EncryptedSharedPreferences.create(
        context,
        "autotrader_secure",
        masterKey,
        EncryptedSharedPreferences.PrefKeyEncryptionScheme.AES256_SIV,
        EncryptedSharedPreferences.PrefValueEncryptionScheme.AES256_GCM
    )

    private val prefs: SharedPreferences =
        context.getSharedPreferences("autotrader_config", Context.MODE_PRIVATE)

    // --- Secure Credentials ---
    var angelApiKey: String
        get() = securePrefs.getString("angel_api_key", "") ?: ""
        set(v) = securePrefs.edit().putString("angel_api_key", v).apply()

    var angelClientId: String
        get() = securePrefs.getString("angel_client_id", "") ?: ""
        set(v) = securePrefs.edit().putString("angel_client_id", v).apply()

    var angelPassword: String
        get() = securePrefs.getString("angel_password", "") ?: ""
        set(v) = securePrefs.edit().putString("angel_password", v).apply()

    var angelTotp: String
        get() = securePrefs.getString("angel_totp", "") ?: ""
        set(v) = securePrefs.edit().putString("angel_totp", v).apply()

    var zerodhaApiKey: String
        get() = securePrefs.getString("zerodha_api_key", "") ?: ""
        set(v) = securePrefs.edit().putString("zerodha_api_key", v).apply()

    var zerodhaAccessToken: String
        get() = securePrefs.getString("zerodha_access_token", "") ?: ""
        set(v) = securePrefs.edit().putString("zerodha_access_token", v).apply()

    var zerodhaUserId: String
        get() = securePrefs.getString("zerodha_user_id", "") ?: ""
        set(v) = securePrefs.edit().putString("zerodha_user_id", v).apply()

    // --- Daily Config ---
    var lotSize: Int
        get() = prefs.getInt("lot_size", 65)
        set(v) = prefs.edit().putInt("lot_size", v).apply()

    var capital: Double
        get() = prefs.getFloat("capital", 50000f).toDouble()
        set(v) = prefs.edit().putFloat("capital", v.toFloat()).apply()

    var script: String
        get() = prefs.getString("script", "NIFTY") ?: "NIFTY"
        set(v) = prefs.edit().putString("script", v).apply()

    var brokerType: String
        get() = prefs.getString("broker_type", "PAPER") ?: "PAPER"
        set(v) = prefs.edit().putString("broker_type", v).apply()

    var maxTradesPerDay: Int
        get() = prefs.getInt("max_trades_per_day", 3)
        set(v) = prefs.edit().putInt("max_trades_per_day", v).apply()

    var dailyProfitCapPct: Double
        get() = prefs.getFloat("daily_profit_cap_pct", 5f).toDouble()
        set(v) = prefs.edit().putFloat("daily_profit_cap_pct", v.toFloat()).apply()

    var superTrendPeriod: Int
        get() = prefs.getInt("st_period", 10)
        set(v) = prefs.edit().putInt("st_period", v).apply()

    var superTrendMultiplier: Double
        get() = prefs.getFloat("st_multiplier", 3f).toDouble()
        set(v) = prefs.edit().putFloat("st_multiplier", v.toFloat()).apply()

    var candleZonePct: Double
        get() = prefs.getFloat("candle_zone_pct", 0.5f).toDouble()
        set(v) = prefs.edit().putFloat("candle_zone_pct", v.toFloat()).apply()
}
