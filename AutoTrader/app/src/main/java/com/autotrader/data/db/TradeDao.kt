package com.autotrader.data.db

import androidx.room.Dao
import androidx.room.Insert
import androidx.room.Query
import androidx.room.Update

@Dao
interface TradeDao {
    @Insert
    suspend fun insert(trade: TradeEntity): Long

    @Update
    suspend fun update(trade: TradeEntity)

    @Query("SELECT * FROM trades WHERE id = :id")
    suspend fun getById(id: Long): TradeEntity?

    @Query("SELECT * FROM trades ORDER BY timestamp DESC")
    suspend fun getAll(): List<TradeEntity>

    @Query("SELECT * FROM trades WHERE timestamp >= :startOfDay ORDER BY timestamp")
    suspend fun getTodayTrades(startOfDay: Long): List<TradeEntity>

    @Query("SELECT * FROM trades WHERE timestamp >= :startOfDay AND exitPrice IS NULL LIMIT 1")
    suspend fun getOpenTrade(startOfDay: Long): TradeEntity?

    @Query("SELECT * FROM trades WHERE timestamp >= :startTime AND timestamp <= :endTime ORDER BY timestamp")
    suspend fun getTradesInRange(startTime: Long, endTime: Long): List<TradeEntity>

    @Query("DELETE FROM trades")
    suspend fun deleteAll()
}
