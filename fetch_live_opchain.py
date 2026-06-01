import requests, json

s = requests.Session()
headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.nseindia.com/option-chain",
}
s.get("https://www.nseindia.com", headers=headers, timeout=10)

# Nifty option chain
r = s.get("https://www.nseindia.com/api/option-chain-indices?symbol=NIFTY", headers=headers, timeout=15)
data = r.json()
rec = data.get("records", {})

print("Expiry:", rec.get("expiryDates", [None])[0])
print("Underlying:", rec.get("underlyingValue"))
print("Lot Size (marketLot):", rec.get("marketLot"))

# Find specific strikes
strike_data = rec.get("data", [])
for item in strike_data:
    st = item.get("strikePrice")
    if st in [23700, 23800, 23900, 24000]:
        ce = item.get("CE", {})
        pe = item.get("PE", {})
        print(f"\n{st}: CE LTP={ce.get('lastPrice')} OI={ce.get('openInterest')} IV={ce.get('impliedVolatility')} Bid={ce.get('bidprice')} Ask={ce.get('askPrice')}")
        print(f"{st}: PE LTP={pe.get('lastPrice')} OI={pe.get('openInterest')} IV={pe.get('impliedVolatility')} Bid={pe.get('bidprice')} Ask={pe.get('askPrice')}")

print(f"\nTotal strike data items: {len(strike_data)}")
