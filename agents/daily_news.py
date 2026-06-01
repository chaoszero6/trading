import feedparser
import requests
import json
import os
import re
from datetime import datetime, timezone, timedelta
import html

DISCORD_WEBHOOK = os.getenv("DISCORD_WEBHOOK", "")
IST = timezone(timedelta(hours=5, minutes=30))

RSS_FEEDS = [
    "https://news.google.com/rss/search?q=nifty+sensex+india+stock+market&hl=en-IN&gl=IN&ceid=IN:en",
    "https://news.google.com/rss/search?q=banknifty+crude+oil+rupee+market&hl=en-IN&gl=IN&ceid=IN:en",
    "https://news.google.com/rss/search?q=GIFT+Nifty+pre+market+today&hl=en-IN&gl=IN&ceid=IN:en",
    "https://feeds.feedburner.com/moneycontrol/market",
    "https://news.google.com/rss/search?q=reliance+hdfc+bank+icici+infosys+tcs+stock+news&hl=en-IN&gl=IN&ceid=IN:en",
    "https://news.google.com/rss/search?q=bharti+airtel+sbi+bajaj+finance+lt+itc+hul+axis+bank+stock&hl=en-IN&gl=IN&ceid=IN:en",
    "https://news.google.com/rss/search?q=kotak+indusind+pnb+baroda+canara+coal+ntpc+maruti+stock&hl=en-IN&gl=IN&ceid=IN:en",
]

BULLISH_WORDS = ["gains", "surge", "rally", "bullish", "positive", "higher", "green", "up",
                 "recover", "bounce", "breakout", "buy", "support", "strong", "rise", "jump"]
BEARISH_WORDS = ["falls", "decline", "losses", "bearish", "negative", "lower", "red", "down",
                 "crash", "selloff", "breakdown", "sell", "resistance", "weak", "drop", "slump"]

MARKET_KEYWORDS = {
    "crude oil": "🛢", "rupee": "💵", "iran": "🔥", "us-iran": "🔥",
    "war": "⚔️", "fed": "🏦", "fii": "📉", "dii": "📈",
    "gdp": "📊", "inflation": "📈", "rbi": "🏛",
    "nifty": "📊", "sensex": "📊", "banknifty": "🏦",
    "ipo": "🚀", "earning": "📋", "result": "📋",
    "china": "🐉", "metal": "⛏", "auto": "🚗",
    "pharma": "💊", "it ": "💻", "realty": "🏗",
    "gift nifty": "🎁", "pre-market": "🌅",
    "sbi": "🏦", "bajaj finance": "💳", "lt": "🏗",
    "hul": "🧴", "axis bank": "🏦", "kotak": "🏦",
    "indusind": "🏦", "maruti": "🚗", "ntpc": "⚡",
    "coal india": "⛏", "pnb": "🏦", "baroda": "🏦",
    "titan": "⌚", "adani": "🏗", "wipro": "💻",
    "larsen": "🏗", "l&t": "🏗",
    "tech mahindra": "💻", "sun pharma": "💊",
    "cipla": "💊", "hindalco": "⛏", "jsw": "⛏",
}

CATEGORIES = {
    "Geopolitical": ["iran", "war", "middle east", "russia", "china", "ukraine", "trump"],
    "Macro": ["crude oil", "rupee", "inflation", "gdp", "fed", "rbi", "bond yield"],
    "FII/DII": ["fii", "dii", "foreign", "institutional", "fpis"],
    "Corporate": ["reliance", "hdfc", "icici", "tcs", "infosys", "bharti", "itc",
                   "sbi", "bajaj", "axis", "kotak", "maruti", "ntpc", "adani",
                   "titan", "wipro", "hindalco", "sun pharma", "cipla",
                   "result", "earning", "ipo"],
    "Sector": ["metal", "auto", "pharma", "it ", "realty", "bank", "fmcg"],
}

NIFTY_LEVELS_RE = re.compile(r'(\d{2}[,.]?\d{3})')
BN_LEVELS_RE = re.compile(r'(\d{2}[,.]?\d{3})')


def _emoji_for(title):
    title_lower = title.lower()
    for kw, emoji in MARKET_KEYWORDS.items():
        if kw in title_lower:
            return emoji
    return "📰"


def _categorize(title):
    title_lower = title.lower()
    for cat, keywords in CATEGORIES.items():
        for kw in keywords:
            if kw in title_lower:
                return cat
    return "General"


def _sentiment(articles):
    bull, bear = 0, 0
    for a in articles:
        t = a["title"].lower()
        for w in BULLISH_WORDS:
            if w in t:
                bull += 1
                break
        for w in BEARISH_WORDS:
            if w in t:
                bear += 1
                break
    return bull, bear


def _extract_levels(articles):
    nifty_levels, bn_levels = [], []
    for a in articles:
        nums = [int(x.replace(",", "")) for x in NIFTY_LEVELS_RE.findall(a["title"]) if len(x.replace(",", "")) >= 4]
        for n in nums:
            if 23000 <= n <= 25000 and n not in nifty_levels:
                nifty_levels.append(n)
            if 50000 <= n <= 58000 and n not in bn_levels:
                bn_levels.append(n)
    nifty_levels.sort()
    bn_levels.sort()
    return nifty_levels[:4], bn_levels[:4]


def fetch_news(hours=36):
    cutoff = datetime.now(IST) - timedelta(hours=hours)
    seen = set()
    articles = []
    for feed_url in RSS_FEEDS:
        try:
            f = feedparser.parse(feed_url)
            for entry in f.entries[:15]:
                published = entry.get("published_parsed")
                if not published:
                    continue
                pub_dt = datetime(*published[:6], tzinfo=timezone.utc).astimezone(IST)
                if pub_dt < cutoff:
                    continue
                title = html.unescape(entry.get("title", "")).strip()
                if title in seen:
                    continue
                seen.add(title)
                articles.append({
                    "title": title,
                    "link": entry.get("link", ""),
                    "time": pub_dt,
                    "emoji": _emoji_for(title),
                    "category": _categorize(title),
                })
        except Exception:
            pass
    articles.sort(key=lambda x: x["time"], reverse=True)
    return articles


def format_discord(articles):
    if not articles:
        return "No recent market news found."

    date_str = datetime.now(IST).strftime("%d %b %Y (%a)")
    lines = [f"📊 **Market News — {date_str}**\n"]

    show = articles[:12]
    cat_order = ["Geopolitical", "Macro", "FII/DII", "Corporate", "Sector", "General"]
    categorized = {c: [] for c in cat_order}
    for a in show:
        categorized[a["category"]].append(a)

    first = True
    for cat in cat_order:
        items = categorized[cat]
        if not items:
            continue
        if not first:
            lines.append("")
        first = False
        for a in items:
            time_str = a["time"].strftime("%H:%M")
            lines.append(f"{a['emoji']} [{time_str}] {a['title']}")

    lines.append("")

    bull, bear = _sentiment(show)
    nifty_levels, bn_levels = _extract_levels(show)

    has_gift = any("gift" in a["title"].lower() for a in show)
    has_crude = any("crude" in a["title"].lower() for a in show)
    has_rupee = any("rupee" in a["title"].lower() for a in show)
    has_fii = any(a["category"] == "FII/DII" for a in show)

    lines.append("**📈 Prediction**")

    bias = "NEUTRAL"
    bias_emoji = "➡️"
    if bull > bear + 1:
        bias = "BULLISH"
        bias_emoji = "🟢"
    elif bear > bull + 1:
        bias = "BEARISH"
        bias_emoji = "🔴"

    factors = []
    if has_gift:
        factors.append("GIFT Nifty positive" if bias == "BULLISH" else "GIFT Nifty mixed")
    if has_crude:
        factors.append("Crude elevated → bearish for India")
    if has_rupee:
        factors.append("Rupee under pressure → FII outflow risk")
    if has_fii:
        factors.append("FII selling + DII buying offset")
    if nifty_levels:
        factors.append(f"NIFTY levels: {nifty_levels[0]}-{nifty_levels[-1]}")
    if bn_levels:
        factors.append(f"BN levels: {bn_levels[0]}-{bn_levels[-1]}")

    lines.append(f"{bias_emoji} **Bias: {bias}** (bullish={bull}, bearish={bear})")
    if factors:
        lines.append("┃ " + "\n┃ ".join(factors))

    if bias == "BULLISH":
        lines.append("📌 Likely gap-up open. Watch for sustained move above resistance.")
    elif bias == "BEARISH":
        lines.append("📌 Cautious open expected. Selling pressure at higher levels likely.")
    else:
        lines.append("📌 Range-bound session expected. Stock-specific action likely.")

    lines.append("")
    lines.append("_Sources: Google News, Moneycontrol_")

    return "\n".join(lines)


def send_discord(message):
    if not DISCORD_WEBHOOK:
        print("[DN] No webhook configured")
        return False
    payload = {"content": message}
    try:
        r = requests.post(DISCORD_WEBHOOK, json=payload, timeout=10)
        ok = r.status_code == 204
        if not ok:
            print(f"[DN] Discord returned {r.status_code}: {r.text[:200]}")
        return ok
    except Exception as e:
        print(f"[DN] Discord send error: {e}")
        return False


def main():
    articles = fetch_news(hours=36)
    msg = format_discord(articles)
    ok = send_discord(msg)
    if ok:
        print(f"[DN] Sent {len(articles)} news items to Discord")
    else:
        print(f"[DN] Failed to send to Discord")


if __name__ == "__main__":
    main()
