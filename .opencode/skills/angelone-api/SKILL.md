---
name: angelone-api
description: >
  Angel One SmartAPI integration reference. Use when fetching any market data (LTP, option Greeks, PCR, OI, gainers/losers, historical candles) via Angel One REST API. 
  Includes all working endpoints, exact payload formats, WAF-related fallbacks, and Black-Scholes pricing using real IV from the API.
  NEVER use yfinance or BS approximations when Angel One API can provide the data.
---

# Angel One SmartAPI Reference

## Base URLs
- **Production:** `https://apiconnect.angelone.in`
- Auth: `/rest/auth/angelbroking/user/v1/loginByPassword`
- Secure: `/rest/secure/angelbroking`

## Required Headers (all requests)
```
Content-Type: application/json
Accept: application/json
X-UserType: USER
X-SourceID: WEB
X-ClientLocalIP: 127.0.0.1
X-ClientPublicIP: 127.0.0.1
X-MACAddress: 00:00:00:00:00:00
X-PrivateKey: {api_key}
Authorization: Bearer {jwt_token}  (after login)
```

## Authentication
```python
import pyotp
totp = pyotp.TOTP(totp_token).now()
POST {BASE}/rest/auth/angelbroking/user/v1/loginByPassword
Body: {"clientcode": client_id, "password": password, "totp": totp}
Response: {"status": true, "data": {"jwtToken": "...", "refreshToken": "...", "feedToken": "..."}}
```

## Working Endpoints

### 1. LTP Data ✅
**URL:** `POST {BASE}/rest/secure/angelbroking/order/v1/getLtpData`
**Body:** `{"exchange": "NSE", "tradingsymbol": "NIFTY", "symboltoken": "99926000"}`
**Response:** `{"data": {"ltp": 23645.15, "open": 23731.4, "high": 23839.3, "low": 23610.3, "close": 23689.6}}`

### 2. Scrip Search ✅
**URL:** `POST {BASE}/rest/secure/angelbroking/order/v1/searchScrip`
**Body:** `{"exchange": "NSE", "searchscrip": "BANKNIFTY"}`
**Response:** Returns matching tokens

### 3. Option Greeks ✅ (use instead of blocked optionchain)
**URL:** `POST {BASE}/rest/secure/angelbroking/marketData/v1/optionGreek`
**Body:** `{"name": "BANKNIFTY", "expirydate": "26MAY2026"}`
**Optional:** `"strike": "53900"`, `"optiontype": "CE"` (to filter)
**Response:** Array of `{name, expiry, strikePrice, optionType, delta, gamma, theta, vega, impliedVolatility, tradeVolume}`
**Notes:** 
- Weekly expiries: NIFTY=Thursday (e.g. `28MAY2026`), BANKNIFTY=Tuesday (e.g. `26MAY2026`)
- Monthly: `30JUN2026`
- Returns IV, Greeks, Volume — NOT LTP. Use BS with returned IV to compute premium.
- Returns ALL strikes when no filter specified (294+ options)
- Use this to get real IV for accurate BS pricing

### 4. Historical Candle Data ✅
**URL:** `POST {BASE}/rest/secure/angelbroking/historical/v1/getCandleData`
**Body:** `{"exchange": "NSE", "tradingsymbol": "NIFTY", "symboltoken": "99926000", "interval": "ONE_MINUTE", "fromdate": "2026-05-15 09:00", "todate": "2026-05-15 15:30"}`
**Intervals:** ONE_MINUTE, THREE_MINUTE, FIVE_MINUTE, TEN_MINUTE, FIFTEEN_MINUTE, THIRTY_MINUTE, ONE_HOUR, ONE_DAY

### 5. Market Quote ✅
**URL:** `POST {BASE}/rest/secure/angelbroking/market/v1/quote`
**Body:** `{"exchange": "NSE", "tradingsymbol": "BANKNIFTY", "symboltoken": ""}`

### 6. Historical OI Data ✅
**URL:** `POST {BASE}/rest/secure/angelbroking/historical/v1/getOIData`

## BLOCKED Endpoints (WAF)
These return HTML "Request Rejected" — do NOT use:
- `POST .../v1/optionchain` ❌
- `POST .../marketData/v1/putCallRatio` ❌

## Symbol Tokens
```
NIFTY:  99926000
BANKNIFTY:  use searchScrip to find
```

## Option Expiry Dates (verified working)
- BANKNIFTY weekly: `26MAY2026` (Tuesdays)
- BANKNIFTY monthly: `30JUN2026`
- NIFTY weekly: `28MAY2026` (Thursdays)
- NIFTY monthly: `28MAY2026`

## WebSocket — Real-time Option LTP ✅
Provides LIVE market prices for specific option contracts (not blocked by WAF).

### WebSocket Endpoint
```
wss://smartapisocket.angelone.in/smart-stream
```

### Subscription Parameters
- **auth_token:** JWT token from login
- **api_key:** Your API key  
- **client_code:** Your client ID
- **feed_token:** From login response
- **mode:** 1=LTP, 2=QUOTE, 3=SNAP_QUOTE, 4=DEPTH
- **exchangeType:** 2=NSE_FO (for options)
- **tokens:** Instrument token from searchScrip

### Option Token Format (searchScrip in NFO segment)
```
NIFTY02JUN26{strike}{type}      e.g. NIFTY02JUN2623800CE
BANKNIFTY26MAY26{strike}{type}  e.g. BANKNIFTY26MAY2654000CE
```
**Expiry format:** DDMMMYY (e.g., 26MAY26, 02JUN26)
- NIFTY weekly: Tuesdays → `02JUN26`
- BANKNIFTY weekly: Tuesdays → `26MAY26`

### Usage in code
```python
from core.angel_bridge import AngelOneBridge
ab = AngelOneBridge()
ab.authenticate()
ltp = ab.get_option_ltp('BANKNIFTY', '26MAY26', '54000', 'CE')
# Returns ₹758.9 (real market price)
```

### Known Working Option Tokens (verified)
- `BANKNIFTY26MAY2654000CE` → token `67200`, LTP ₹758.9
- `NIFTY02JUN2623800CE` → token `57042`, LTP ₹313.7

## Black-Scholes Pricing with Real IV
When WebSocket is unavailable or IV/Greeks are needed, use BS with real IV from optionGreek:
```python
from scipy.stats import norm
def bs_price(S, K, T, r, sigma, optype='CE'):
    sigma = max(sigma, 0.05)
    if T <= 0 or sigma * math.sqrt(T) < 0.001:
        return max(0, S - K) if optype == 'CE' else max(0, K - S)
    d1 = (math.log(S/K) + (r + 0.5*sigma**2)*T) / (sigma*math.sqrt(T))
    d2 = d1 - sigma*math.sqrt(T)
    if optype == 'CE':
        return S*norm.cdf(d1) - K*math.exp(-r*T)*norm.cdf(d2)
    else:
        return K*math.exp(-r*T)*norm.cdf(-d2) - S*norm.cdf(-d1)
```

## Entry/Exit Strategy Parameters
When recommending options, use these defaults:
- **SL:** 60% of premium (risk management)
- **Target:** 2.5x premium (or nearest technical resistance)
- **Capital allocation:** max 1-2 lots within available capital
- **Lot sizes:** NIFTY=65, BANKNIFTY=30
- **Risk-free rate (r):** 0.065 (6.5%)

## Implementation in codebase
- `core/angel_bridge.py` — `AngelOneBridge` class with methods for all endpoints
- Use `get_option_greeks(name, expirydate, strike, optiontype)` for options data
- Use `get_ltp(exchange, symbol, token)` for live prices
- Use `get_candle_data(...)` for historical candles
