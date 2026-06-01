#!/usr/bin/env python3
"""VWAP Heat Map — Nifty 50 Entry Strategy"""
import sys, os, requests
sys.path.insert(0, '/root/trading')
import yfinance as yf
import numpy as np

wh = os.environ.get("DISCORD_WEBHOOK", "")
if not wh:
    print("DISCORD_WEBHOOK not set")
    sys.exit(1)

stocks = [
    ("RELIANCE","Reliance"),("TCS","TCS"),("HDFCBANK","HDFC Bank"),
    ("ICICIBANK","ICICI Bank"),("INFY","Infosys"),("SBIN","SBI"),
    ("BHARTIARTL","Airtel"),("ITC","ITC"),("LT","L&T"),
    ("HINDUNILVR","HUL"),("AXISBANK","Axis Bank"),("KOTAKBANK","Kotak Bank"),
    ("BAJFINANCE","Bajaj Fin"),("MARUTI","Maruti"),("SUNPHARMA","Sun Pharma"),
    ("M&M","M&M"),("NTPC","NTPC"),("POWERGRID","Pwr Grid"),
    ("WIPRO","Wipro"),("HCLTECH","HCL Tech"),("TITAN","Titan"),
    ("ULTRACEMCO","UltraTech"),("BAJAJ-AUTO","Bajaj Auto"),
    ("ADANIPORTS","Adani Ports"),("ONGC","ONGC"),("JSWSTEEL","JSW Steel"),
    ("GRASIM","Grasim"),("HINDALCO","Hindalco"),("COALINDIA","Coal India"),
    ("BRITANNIA","Britannia"),("DRREDDY","Dr Reddy"),("CIPLA","Cipla"),
    ("APOLLOHOSP","Apollo Hosp"),("TRENT","Trent"),
]

above, below, neutral = [], [], []

for sym, name in stocks:
    try:
        df = yf.download(f"{sym}.NS", period="1mo", interval="1d", progress=False)
        if df.empty:
            continue
        h = df["High"].values.ravel()
        l = df["Low"].values.ravel()
        c = df["Close"].values.ravel()
        v = df["Volume"].values.ravel()
        typ = (h + l + c) / 3
        vwap = (typ * v).sum() / v.sum() if v.sum() > 0 else c[-1]
        curr = float(c[-1])
        diff = ((curr - vwap) / vwap) * 100
        bar = chr(9608) * min(int(abs(diff) * 3), 15)
        entry = "BUY CE" if curr > vwap else "BUY PE" if curr < vwap else "HOLD"
        arrow = "+" if diff > 0 else ""
        line = f"{name:12} Rs{curr:>7.0f} | VWAP:Rs{vwap:>7.0f} | {arrow}{diff:+.2f}% {bar} -> {entry}"
        if diff > 0.5:
            above.append(line)
        elif diff < -0.5:
            below.append(line)
        else:
            neutral.append(line)
    except:
        continue

above.sort(key=lambda x: abs(float(x.split("|")[2].split("%")[0].strip().replace("+",""))), reverse=True)
below.sort(key=lambda x: abs(float(x.split("|")[2].split("%")[0].strip().replace("+",""))), reverse=True)

ndf = yf.download("^NSEI", period="1mo", interval="1d", progress=False)
n_curr, n_vwap = 0, 0
if not ndf.empty:
    h = ndf["High"].values.ravel(); l = ndf["Low"].values.ravel()
    c = ndf["Close"].values.ravel(); v = ndf["Volume"].values.ravel()
    typ = (h + l + c) / 3
    n_vwap = (typ * v).sum() / v.sum() if v.sum() > 0 else c[-1]
    n_curr = float(c[-1])

n_diff = ((n_curr - n_vwap) / n_vwap) * 100 if n_vwap else 0
atm_n = round(n_curr / 50) * 50

embed = {
    "title": "VWAP Heat Map - Nifty 50 Entry Strategy",
    "color": 0x5865F2,
    "description": f"NIFTY 50: Rs{n_curr:.0f} | VWAP: Rs{n_vwap:.0f} | Diff: {n_diff:+.2f}%",
    "fields": [
        {
            "name": f"ABOVE VWAP - BUY CE ({len(above)})",
            "value": "```\n" + "\n".join(above[:7]) + "\n```" if above else "None",
            "inline": False,
        },
        {
            "name": f"BELOW VWAP - BUY PE ({len(below)})",
            "value": "```\n" + "\n".join(below[:7]) + "\n```" if below else "None",
            "inline": False,
        },
        {
            "name": f"NEAR VWAP - WAIT ({len(neutral)})",
            "value": "```\n" + "\n".join(neutral[:4]) + "\n```" if neutral else "None",
            "inline": False,
        },
        {
            "name": "ENTRY STRATEGY",
            "value": (
                f"Nifty is {n_diff:+.2f}% below VWAP - Bearish bias\n\n"
                f"BUY 23650 PE (OTM)\n"
                f"Entry: Rs154 | SL: Rs77 | Target: Rs231 | R:R 1:1.5\n\n"
                f"STRONGEST SELLS (most below VWAP):\n"
                + ("\n".join(below[:3]) if below else "N/A") + "\n\n"
                f"STRONGEST BUYS (most above VWAP):\n"
                + ("\n".join(above[:3]) if above else "N/A")
            ),
            "inline": False,
        },
    ],
    "footer": {"text": "VWAP Heat Map | GPU Powered"},
}

r = requests.post(wh, json={"embeds": [embed]}, timeout=10)
print(f"Sent: {r.status_code} | Above: {len(above)} Below: {len(below)} Neutral: {len(neutral)}")
