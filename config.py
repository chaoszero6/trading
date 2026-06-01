import os
from datetime import datetime, timedelta

ANGEL_CONFIG = {
    "api_key": os.environ.get("ANGEL_API_KEY", ""),
    "client_id": os.environ.get("ANGEL_CLIENT_ID", ""),
    "password": os.environ.get("ANGEL_PASSWORD", ""),
    "totp_token": os.environ.get("ANGEL_TOTP_TOKEN", ""),
}

NSE_SYMBOL_MAP = {
    "NIFTY 50": {"exchange": "NSE", "symbol": "NIFTY", "token": "26000"},
    "BANK NIFTY": {"exchange": "NSE", "symbol": "BANKNIFTY", "token": "26009"},
    "SENSEX": {"exchange": "BSE", "symbol": "SENSEX", "token": ""},
    "FINNIFTY": {"exchange": "NSE", "symbol": "FINNIFTY", "token": "26037"},
    "MIDCPNIFTY": {"exchange": "NSE", "symbol": "MIDCPNIFTY", "token": "26029"},
}

NIFTY50_CONSTITUENTS = {
    "HDFCBANK": {"name": "HDFC Bank Ltd", "weight": 13.01, "sector": "banking"},
    "ICICIBANK": {"name": "ICICI Bank Ltd", "weight": 8.84, "sector": "banking"},
    "RELIANCE": {"name": "Reliance Industries Ltd", "weight": 8.12, "sector": "crude_oil"},
    "INFY": {"name": "Infosys Ltd", "weight": 5.41, "sector": "it"},
    "BHARTIARTL": {"name": "Bharti Airtel Ltd", "weight": 4.34, "sector": "telecom"},
    "LT": {"name": "Larsen & Toubro Ltd", "weight": 3.85, "sector": "infrastructure"},
    "ITC": {"name": "ITC Ltd", "weight": 3.57, "sector": "fmcg"},
    "TCS": {"name": "TCS Ltd", "weight": 3.50, "sector": "it"},
    "AXISBANK": {"name": "Axis Bank Ltd", "weight": 2.94, "sector": "banking"},
    "KOTAKBANK": {"name": "Kotak Mahindra Bank Ltd", "weight": 2.93, "sector": "banking"},
    "SBIN": {"name": "State Bank of India", "weight": 2.78, "sector": "banking"},
    "M&M": {"name": "Mahindra & Mahindra Ltd", "weight": 2.27, "sector": "auto"},
    "BAJFINANCE": {"name": "Bajaj Finance Ltd", "weight": 2.21, "sector": "banking"},
    "HINDUNILVR": {"name": "Hindustan Unilever Ltd", "weight": 1.87, "sector": "fmcg"},
    "SUNPHARMA": {"name": "Sun Pharma Ltd", "weight": 1.75, "sector": "pharma"},
    "HCLTECH": {"name": "HCL Technologies Ltd", "weight": 1.62, "sector": "it"},
    "NTPC": {"name": "NTPC Ltd", "weight": 1.60, "sector": "power"},
    "MARUTI": {"name": "Maruti Suzuki India Ltd", "weight": 1.44, "sector": "auto"},
    "TATAMOTORS": {"name": "Tata Motors Ltd", "weight": 1.31, "sector": "auto"},
    "POWERGRID": {"name": "Power Grid Corp Ltd", "weight": 1.25, "sector": "power"},
    "TATASTEEL": {"name": "Tata Steel Ltd", "weight": 1.20, "sector": "metal"},
    "BAJAJFINSV": {"name": "Bajaj Finserv Ltd", "weight": 1.02, "sector": "banking"},
    "BEL": {"name": "Bharat Electronics Ltd", "weight": 1.01, "sector": "defence"},
    "ASIANPAINT": {"name": "Asian Paints Ltd", "weight": 0.99, "sector": "fmcg"},
    "JSWSTEEL": {"name": "JSW Steel Ltd", "weight": 0.94, "sector": "metal"},
    "GRASIM": {"name": "Grasim Industries Ltd", "weight": 0.94, "sector": "metal"},
    "HINDALCO": {"name": "Hindalco Industries Ltd", "weight": 0.94, "sector": "metal"},
    "SHRIRAMFIN": {"name": "Shriram Finance Ltd", "weight": 0.89, "sector": "banking"},
    "ONGC": {"name": "ONGC Ltd", "weight": 0.88, "sector": "crude_oil"},
    "COALINDIA": {"name": "Coal India Ltd", "weight": 0.84, "sector": "metal"},
    "ADANIPORTS": {"name": "Adani Ports & SEZ Ltd", "weight": 0.83, "sector": "infrastructure"},
    "BAJAJ-AUTO": {"name": "Bajaj Auto Ltd", "weight": 0.83, "sector": "auto"},
    "CIPLA": {"name": "Cipla Ltd", "weight": 0.78, "sector": "pharma"},
    "NESTLEIND": {"name": "Nestle India Ltd", "weight": 0.75, "sector": "fmcg"},
    "EICHERMOT": {"name": "Eicher Motors Ltd", "weight": 0.69, "sector": "auto"},
    "JIOFIN": {"name": "Jio Financial Services Ltd", "weight": 0.69, "sector": "banking"},
    "HDFCLIFE": {"name": "HDFC Life Insurance Ltd", "weight": 0.68, "sector": "banking"},
    "SBILIFE": {"name": "SBI Life Insurance Ltd", "weight": 0.65, "sector": "banking"},
    "DRREDDY": {"name": "Dr Reddys Laboratories Ltd", "weight": 0.66, "sector": "pharma"},
    "APOLLOHOSP": {"name": "Apollo Hospitals Ltd", "weight": 0.61, "sector": "pharma"},
    "TATACONSUM": {"name": "Tata Consumer Products Ltd", "weight": 0.59, "sector": "fmcg"},
    "ADANIENT": {"name": "Adani Enterprises Ltd", "weight": 0.58, "sector": "infrastructure"},
    "BRITANNIA": {"name": "Britannia Industries Ltd", "weight": 0.55, "sector": "fmcg"},
    "HEROMOTOCO": {"name": "Hero Motocorp Ltd", "weight": 0.46, "sector": "auto"},
    "INDUSINDBK": {"name": "IndusInd Bank Ltd", "weight": 0.42, "sector": "banking"},
    "TITAN": {"name": "Titan Company Ltd", "weight": 1.26, "sector": "fmcg"},
    "ULTRACEMCO": {"name": "UltraTech Cement Ltd", "weight": 1.22, "sector": "cement"},
    "WIPRO": {"name": "Wipro Ltd", "weight": 0.80, "sector": "it"},
    "TRENT": {"name": "Trent Ltd", "weight": 1.47, "sector": "fmcg"},
    "TECHM": {"name": "Tech Mahindra Ltd", "weight": 1.01, "sector": "it"},
}

BANKNIFTY_CONSTITUENTS = {
    "HDFCBANK": {"name": "HDFC Bank Ltd", "weight": 25.64},
    "SBIN": {"name": "State Bank of India", "weight": 20.06},
    "ICICIBANK": {"name": "ICICI Bank Ltd", "weight": 19.33},
    "AXISBANK": {"name": "Axis Bank Ltd", "weight": 8.41},
    "KOTAKBANK": {"name": "Kotak Mahindra Bank Ltd", "weight": 8.07},
    "BANKBARODA": {"name": "Bank of Baroda", "weight": 2.91},
    "UNIONBANK": {"name": "Union Bank of India", "weight": 2.70},
    "PNB": {"name": "Punjab National Bank", "weight": 2.63},
    "CANBK": {"name": "Canara Bank", "weight": 2.60},
    "AUBANK": {"name": "AU Small Finance Bank", "weight": 1.68},
    "FEDERALBNK": {"name": "Federal Bank Ltd", "weight": 1.56},
    "YESBANK": {"name": "Yes Bank Ltd", "weight": 1.53},
    "IDFCFIRSTB": {"name": "IDFC First Bank Ltd", "weight": 1.31},
}

NIFTY50_TOP_10 = sorted(NIFTY50_CONSTITUENTS.items(), key=lambda x: -x[1]["weight"])[:10]

SECTORS_IMPACT = {
    "crude_oil": {"stocks": ["RELIANCE", "ONGC", "BPCL", "IOC"], "nifty_weight": 9.5},
    "it": {"stocks": ["TCS", "INFY", "WIPRO", "HCLTECH", "TECHM"], "nifty_weight": 12.3},
    "banking": {"stocks": ["HDFCBANK", "ICICIBANK", "SBIN", "KOTAKBANK", "AXISBANK", "INDUSINDBK"], "nifty_weight": 28.9},
    "pharma": {"stocks": ["SUNPHARMA", "DRREDDY", "CIPLA", "APOLLOHOSP"], "nifty_weight": 3.8},
    "auto": {"stocks": ["M&M", "MARUTI", "TATAMOTORS", "BAJAJ-AUTO", "EICHERMOT", "HEROMOTOCO"], "nifty_weight": 7.2},
    "metal": {"stocks": ["TATASTEEL", "HINDALCO", "JSWSTEEL", "COALINDIA", "GRASIM"], "nifty_weight": 4.8},
    "fmcg": {"stocks": ["HINDUNILVR", "ITC", "NESTLEIND", "BRITANNIA", "TATACONSUM", "TITAN", "TRENT"], "nifty_weight": 10.7},
    "power": {"stocks": ["NTPC", "POWERGRID"], "nifty_weight": 2.8},
}

FUTURES_SYMBOLS = {
    "NIFTY": {"exchange": "NSE", "token": "26000"},
    "BANKNIFTY": {"exchange": "NSE", "token": "26009"},
    "RELIANCE": {"exchange": "NSE", "token": "2885"},
    "TCS": {"exchange": "NSE", "token": "11536"},
    "HDFCBANK": {"exchange": "NSE", "token": "1333"},
    "ICICIBANK": {"exchange": "NSE", "token": "4963"},
    "SBIN": {"exchange": "NSE", "token": "3045"},
    "INFY": {"exchange": "NSE", "token": "1594"},
    "TATAMOTORS": {"exchange": "NSE", "token": "3456"},
    "LT": {"exchange": "NSE", "token": "3501"},
    "AXISBANK": {"exchange": "NSE", "token": "1232"},
    "KOTAKBANK": {"exchange": "NSE", "token": "4926"},
    "M&M": {"exchange": "NSE", "token": "20374"},
    "MARUTI": {"exchange": "NSE", "token": "5839"},
    "BHARTIARTL": {"exchange": "NSE", "token": "1660"},
    "HCLTECH": {"exchange": "NSE", "token": "7229"},
    "SUNPHARMA": {"exchange": "NSE", "token": "8623"},
    "HINDUNILVR": {"exchange": "NSE", "token": "1394"},
}

GLOBAL_INDICES = {
    "S&P 500": "^GSPC",
    "NASDAQ": "^IXIC",
    "DOW": "^DJI",
    "FTSE": "^FTSE",
    "NIKKEI": "^N225",
    "HSI": "^HSI",
    "DAX": "^GDAXI",
    "SHANGHAI": "000001.SS",
}

def get_next_next_weekly_expiry(index: str) -> str:
    """Return weekly expiry identifier in DDMMMYY format, skipping the current weekly.

    Angel One uses Tuesday as the expiry identifier for both indices.
    Current weekly = Tuesday of the current ISO week (Mon-Sun).
    For NIFTY: next-next Tuesday (+14d), for BN: next Tuesday (+7d).
    """
    today = datetime.now()
    this_monday = today - timedelta(days=today.weekday())
    this_tuesday = this_monday + timedelta(days=1)
    if index == "NIFTY":
        expiry = this_tuesday + timedelta(days=14)
    else:
        expiry = this_tuesday + timedelta(days=7)
    return expiry.strftime("%d%b%y").upper()

NEWS_RSS_FEEDS = [
    "https://www.economictimes.indiatimes.com/rssfeeds/13352319.cms",
    "https://www.moneycontrol.com/rss/business.xml",
    "https://www.livemint.com/rss/money",
    "https://feeds.content.dowjones.io/public/rss/mw_topstories",
    "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=100003114",
    "https://feeds.bloomberg.com/markets/news.rss",
]
