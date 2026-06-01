#!/bin/bash
export PATH=/usr/local/bin:/usr/bin:/bin
cd /root/trading || exit 1

if [ -f .env ]; then
    set -a; source .env; set +a
fi

python3 -u agents/hourly_report.py >> logs/hourly_report.log 2>&1
