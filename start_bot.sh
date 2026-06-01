#!/bin/bash
source /tmp/trading_venv/bin/activate
export $(grep -v "^#" /root/trading/.env | xargs)
cd /root/trading
nohup python discord_bot.py > /var/log/trading-bot.log 2>&1 &
echo "BOT_PID=$!"
