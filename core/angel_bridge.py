import json
import time
import logging
from datetime import datetime, timedelta
from typing import Optional

import pandas as pd
import pyotp
import requests

from config import ANGEL_CONFIG, NSE_SYMBOL_MAP, FUTURES_SYMBOLS, get_next_next_weekly_expiry

logger = logging.getLogger(__name__)

SMARTAPI_BASE = "https://apiconnect.angelone.in"
RESTFUL_URL = f"{SMARTAPI_BASE}/rest/secure/angelbroking"


class AngelOneBridge:
    def __init__(self):
        self.api_key = ANGEL_CONFIG["api_key"]
        self.client_id = ANGEL_CONFIG["client_id"]
        self.password = ANGEL_CONFIG["password"]
        self.totp_token = ANGEL_CONFIG["totp_token"]
        self.auth_token = None
        self.refresh_token = None
        self.feed_token = None
        self.session = requests.Session()
        self.session.headers.update({
            "Content-Type": "application/json",
            "Accept": "application/json",
            "X-UserType": "USER",
            "X-SourceID": "WEB",
            "X-ClientLocalIP": "127.0.0.1",
            "X-ClientPublicIP": "127.0.0.1",
            "X-MACAddress": "00:00:00:00:00:00",
            "X-PrivateKey": self.api_key,
        })
        self._authenticated = False
        self._rest_blocked = False

    def authenticate(self) -> bool:
        if not all([self.api_key, self.client_id, self.password, self.totp_token]):
            logger.warning("Angel One credentials not fully set. "
                           "Set ANGEL_API_KEY, ANGEL_CLIENT_ID, ANGEL_PASSWORD, ANGEL_TOTP_TOKEN")
            return False

        try:
            totp_code = pyotp.TOTP(self.totp_token).now()
            logger.info(f"Generated TOTP from secret key")
            payload = {
                "clientcode": self.client_id,
                "password": self.password,
                "totp": totp_code,
            }
            resp = self.session.post(
                f"{SMARTAPI_BASE}/rest/auth/angelbroking/user/v1/loginByPassword",
                json=payload,
                timeout=15,
            )
            data = resp.json()
            if data.get("status"):
                self.auth_token = data["data"]["jwtToken"]
                self.refresh_token = data["data"]["refreshToken"]
                self.feed_token = data["data"]["feedToken"]
                self.session.headers.update({
                    "Authorization": f"Bearer {self.auth_token}"
                })
                self._authenticated = True
                logger.info("Angel One authenticated successfully")
                return True
            else:
                logger.error(f"Angel One auth failed: {data.get('message')}")
                return False
        except Exception as e:
            logger.error(f"Angel One auth error: {e}")
            return False

    def _ensure_auth(self):
        if not self._authenticated:
            self.authenticate()

    def get_ltp(self, exchange: str, symbol: str, token: str = "") -> Optional[float]:
        self._ensure_auth()
        try:
            payload = {
                "exchange": exchange,
                "tradingsymbol": symbol,
                "symboltoken": token,
            }
            resp = self.session.post(
                f"{SMARTAPI_BASE}/rest/secure/angelbroking/order/v1/getLtpData",
                json=payload,
                timeout=10,
            )
            if "Request Rejected" in resp.text:
                logger.warning(f"WAF blocked LTP for {symbol} — falling back to yfinance")
                return None
            data = resp.json()
            if data.get("status") and data.get("data"):
                return float(data["data"].get("ltp", 0))
            return None
        except Exception as e:
            logger.debug(f"LTP error {symbol}: {e}")
            return None

    def search_scrip(self, exchange: str, query: str) -> Optional[list]:
        self._ensure_auth()
        try:
            resp = self.session.post(
                f"{SMARTAPI_BASE}/rest/secure/angelbroking/order/v1/searchScrip",
                json={"exchange": exchange, "searchscrip": query},
                timeout=10,
            )
            if resp.status_code == 200 and resp.text.strip():
                data = resp.json()
                if data.get("status") and data.get("data"):
                    return data["data"]
            return None
        except Exception:
            return None

    def get_candle_data(self, exchange: str, symbol: str, interval: str = "FIVE_MINUTE",
                         from_date: str = "", to_date: str = "") -> Optional[pd.DataFrame]:
        self._ensure_auth()
        try:
            if not to_date:
                to_date = datetime.now().strftime("%Y-%m-%d %H:%M")
            if not from_date:
                from_date = (datetime.now() - timedelta(days=5)).strftime("%Y-%m-%d %H:%M")

            payload = {
                "exchange": exchange,
                "tradingsymbol": symbol,
                "symboltoken": "",
                "interval": interval,
                "fromdate": from_date,
                "todate": to_date,
            }
            resp = self.session.post(
                f"{SMARTAPI_BASE}/rest/secure/angelbroking/historical/v1/getCandleData",
                json=payload,
                timeout=15,
            )
            data = resp.json()
            if data.get("status") and data.get("data"):
                records = data["data"]
                rows = []
                for rec in records:
                    rows.append({
                        "timestamp": rec[0],
                        "open": float(rec[1]),
                        "high": float(rec[2]),
                        "low": float(rec[3]),
                        "close": float(rec[4]),
                        "volume": int(rec[5]),
                    })
                df = pd.DataFrame(rows)
                df["timestamp"] = pd.to_datetime(df["timestamp"])
                df.set_index("timestamp", inplace=True)
                return df
            return None
        except Exception as e:
            logger.error(f"Candle data error {symbol}: {e}")
            return None

    def get_option_chain(self, exchange: str, symbol: str, expiry: str = "",
                          strike: str = "") -> Optional[dict]:
        self._ensure_auth()
        try:
            payload = {
                "exchange": exchange,
                "symboltoken": "",
                "tradingsymbol": symbol,
                "expiry": expiry,
                "strike": strike,
            }
            resp = self.session.post(
                f"{RESTFUL_URL}/v1/optionchain",
                json=payload,
                timeout=15,
            )
            if "Request Rejected" in resp.text:
                logger.warning(f"Option chain endpoint WAF blocked, falling back to optionGreek")
                return None
            data = resp.json()
            return data.get("data") if data.get("status") else None
        except Exception as e:
            logger.error(f"Option chain error {symbol}: {e}")
            return None

    def get_option_greeks(self, name: str, expirydate: str,
                           strike: str = "", optiontype: str = "") -> Optional[list]:
        self._ensure_auth()
        try:
            payload = {"name": name, "expirydate": expirydate}
            if strike:
                payload["strike"] = strike
            if optiontype:
                payload["optiontype"] = optiontype
            resp = self.session.post(
                f"{SMARTAPI_BASE}/rest/secure/angelbroking/marketData/v1/optionGreek",
                json=payload,
                timeout=10,
            )
            if resp.status_code == 200:
                data = resp.json()
                if data.get("status") and data.get("data"):
                    return data["data"]
            return None
        except Exception as e:
            logger.error(f"Option Greeks error {name}: {e}")
            return None

    def get_nifty_option_greeks(self, expirydate: str = "") -> Optional[list]:
        if not expirydate:
            expirydate = get_next_next_weekly_expiry("NIFTY")
            # convert DDMMMYY → DDMMMYYYY
            import re
            m = re.match(r'(\d+)([A-Z]+)(\d+)', expirydate)
            if m:
                expirydate = f"{m.group(1)}{m.group(2)}20{m.group(3)}"
        return self.get_option_greeks("NIFTY", expirydate)

    def get_banknifty_option_greeks(self, expirydate: str = "") -> Optional[list]:
        if not expirydate:
            expirydate = get_next_next_weekly_expiry("BANKNIFTY")
            import re
            m = re.match(r'(\d+)([A-Z]+)(\d+)', expirydate)
            if m:
                expirydate = f"{m.group(1)}{m.group(2)}20{m.group(3)}"
        return self.get_option_greeks("BANKNIFTY", expirydate)

    def get_nifty_ltp(self) -> Optional[float]:
        info = NSE_SYMBOL_MAP.get("NIFTY 50")
        if not info:
            return None
        return self.get_ltp(info["exchange"], info["symbol"], info["token"])

    def get_banknifty_ltp(self) -> Optional[float]:
        info = NSE_SYMBOL_MAP.get("BANK NIFTY")
        if not info:
            return None
        return self.get_ltp(info["exchange"], info["symbol"], info["token"])

    def get_nifty_candles(self, interval: str = "5",
                           days: int = 5) -> Optional[pd.DataFrame]:
        info = NSE_SYMBOL_MAP.get("NIFTY 50")
        if not info:
            return None
        to_date = datetime.now().strftime("%Y-%m-%d %H:%M")
        from_date = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d %H:%M")
        return self.get_candle_data(info["exchange"], info["symbol"],
                                     interval, from_date, to_date)

    def get_stock_future_ltp(self, symbol: str) -> Optional[float]:
        info = FUTURES_SYMBOLS.get(symbol)
        if not info:
            return None
        tradingsymbol = f"{symbol.upper()}-EQ"
        return self.get_ltp(info["exchange"], tradingsymbol, info["token"])

    def place_order(self, symbol: str, qty: int, side: str, price: float,
                     variety: str = "NORMAL", product: str = "DELIVERY",
                     exchange: str = "NSE", order_type: str = "LIMIT") -> dict:
        self._ensure_auth()
        try:
            payload = {
                "variety": variety,
                "tradingsymbol": symbol,
                "symboltoken": FUTURES_SYMBOLS.get(symbol, {}).get("token", ""),
                "transactiontype": side.upper(),
                "exchange": exchange,
                "ordertype": order_type,
                "producttype": product,
                "duration": "DAY",
                "price": str(price),
                "quantity": str(qty),
            }
            resp = self.session.post(
                f"{RESTFUL_URL}/v1/placeOrder",
                json=payload,
                timeout=10,
            )
            data = resp.json()
            if data.get("status"):
                logger.info(f"Order placed: {side} {qty} {symbol} @ {price}")
                return {"success": True, "order_id": data["data"].get("orderid", "")}
            return {"success": False, "error": data.get("message", "")}
        except Exception as e:
            logger.error(f"Order placement error: {e}")
            return {"success": False, "error": str(e)}


    def get_funds(self) -> Optional[dict]:
        """Get account balance / RMS funds."""
        self._ensure_auth()
        try:
            resp = self.session.post(
                f"{RESTFUL_URL}/user/v1/getRMS",
                json={},
                timeout=10,
            )
            data = resp.json()
            if data.get("status") and data.get("data"):
                return data["data"]
            return None
        except Exception as e:
            logger.error(f"Funds error: {e}")
            return None

    def get_option_ltp(self, symbol: str, expiry: str, strike: str, optype: str) -> Optional[float]:
        """Get real-time LTP for a specific option via WebSocket (one-shot)."""
        import threading, time
        from SmartApi.smartWebSocketV2 import SmartWebSocketV2

        tradingsymbol = f"{symbol}{expiry}{strike}{optype}"
        try:
            tokens = self.search_scrip("NFO", tradingsymbol)
            if not tokens:
                logger.warning(f"Option token not found for {tradingsymbol}")
                return None
            token = tokens[0]["symboltoken"]
        except Exception as e:
            logger.warning(f"Search scrip error for {tradingsymbol}: {e}")
            return None

        result = {"ltp": None, "done": False}

        def on_data(wsapp, data):
            result["ltp"] = data.get("last_traded_price", 0) / 100
            result["done"] = True

        def on_error(wsapp, error):
            result["done"] = True

        def on_close(wsapp):
            result["done"] = True

        sws = SmartWebSocketV2(
            auth_token=self.auth_token,
            api_key=self.api_key,
            client_code=self.client_id,
            feed_token=self.feed_token,
        )
        sws.on_data = on_data
        sws.on_error = on_error
        sws.on_close = on_close

        t = threading.Thread(target=sws.connect, daemon=True)
        t.start()
        time.sleep(1.5)
        try:
            sws.subscribe(correlation_id="optltp01", mode=1,
                          token_list=[{"exchangeType": 2, "tokens": [token]}])
        except Exception:
            pass

        for _ in range(30):
            if result["done"] and result["ltp"] is not None:
                break
            time.sleep(0.1)

        try:
            sws.close_connection()
        except Exception:
            pass
        return result["ltp"]


_singleton = None


def get_angel_bridge() -> AngelOneBridge:
    global _singleton
    if _singleton is None:
        _singleton = AngelOneBridge()
    return _singleton
