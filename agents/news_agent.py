import feedparser
import re
import requests
from datetime import datetime, timedelta
from textblob import TextBlob
from config import NEWS_RSS_FEEDS, SECTORS_IMPACT, NIFTY50_CONSTITUENTS, BANKNIFTY_CONSTITUENTS


class MarketNewsAgent:
    def __init__(self):
        self.name = "MarketNewsAgent"
        self.role = "Worldwide Market News Analyst | Indian Market Impact Specialist"
        self.news_cache = []
        self.sector_keywords = {
            "crude_oil": ["crude", "oil", "opec", "petroleum", "brent", "wti"],
            "it": ["tech", "software", "it services", "digital", "cloud", "ai",
                   "semiconductor", "outsourcing"],
            "banking": ["bank", "rbi", "repo rate", "interest rate", "lending",
                        "npas", "credit", "monetary policy"],
            "pharma": ["pharma", "drug", "fda", "vaccine", "clinical trial",
                       "generic", "biotech"],
            "auto": ["auto", "automobile", "ev", "electric vehicle", "sales",
                     "dealership", "manufacturing"],
            "metal": ["metal", "steel", "aluminium", "copper", "mining",
                      "commodity", "china demand"],
            "fmcg": ["fmcg", "consumer", "retail", "demand", "spending",
                     "inflation", "disposable", "fMCG"],
        }
        self.impact_keywords = {
            "positive": ["surge", "rally", "bullish", "growth", "expansion",
                         "profit", "upgrade", "positive", "gain", "boom",
                         "strong demand", "outperform"],
            "negative": ["crash", "decline", "bearish", "recession", "inflation",
                         "slowdown", "downgrade", "sell-off", "volatile",
                         "loss", "weak demand", "sanctions", "tariff"],
            "neutral": ["mixed", "steady", "stable", "flat", "consolidation",
                        "unchanged", "neutral", "hold"],
        }

    def fetch_news(self, max_articles=25):
        all_entries = []
        for feed_url in NEWS_RSS_FEEDS:
            try:
                feed = feedparser.parse(feed_url)
                for entry in feed.entries[:10]:
                    title = entry.get("title", "")
                    summary = entry.get("summary", entry.get("description", ""))
                    published = entry.get("published", datetime.now().isoformat())
                    link = entry.get("link", "")
                    all_entries.append({
                        "title": title,
                        "summary": summary,
                        "published": published,
                        "link": link,
                        "source": feed_url,
                    })
            except Exception:
                continue
        seen = set()
        unique = []
        for article in all_entries:
            if article["title"] not in seen:
                seen.add(article["title"])
                unique.append(article)
        self.news_cache = unique[:max_articles]
        return self.news_cache

    def analyze_sentiment(self, text):
        blob = TextBlob(text)
        polarity = blob.sentiment.polarity
        subjectivity = blob.sentiment.subjectivity
        if polarity > 0.15:
            label = "positive"
        elif polarity < -0.15:
            label = "negative"
        else:
            label = "neutral"
        return {"polarity": round(polarity, 3), "subjectivity": round(subjectivity, 3),
                "label": label}

    def classify_sector_impact(self, text):
        text_lower = text.lower()
        impacted_sectors = {}
        for sector, keywords in self.sector_keywords.items():
            score = sum(1 for kw in keywords if re.search(r'\b' + re.escape(kw) + r'\b', text_lower))
            if score > 0:
                impacted_sectors[sector] = score
        return sorted(impacted_sectors.items(), key=lambda x: -x[1])

    def assess_indian_market_impact(self, article):
        combined = article["title"] + " " + article["summary"]
        sentiment = self.analyze_sentiment(combined)
        sectors = self.classify_sector_impact(combined)
        impact_score = sentiment["polarity"] * 10

        article_sectors = [s[0] for s in sectors[:3]]
        stocks_impacted = {}
        for s in article_sectors:
            if s in SECTORS_IMPACT:
                stocks_impacted[s] = SECTORS_IMPACT[s]["stocks"]

        return {
            "sentiment": sentiment,
            "impact_score": round(impact_score, 2),
            "sectors_impacted": article_sectors,
            "affected_stocks": stocks_impacted,
            "severity": "high" if abs(impact_score) > 5 else "medium" if abs(impact_score) > 2 else "low",
        }

    def run_analysis(self):
        print(f"\n{'='*60}")
        print(f"  AGENT: {self.name}")
        print(f"  ROLE: {self.role}")
        print(f"{'='*60}")

        articles = self.fetch_news()
        print(f"\n[+] Fetched {len(articles)} articles worldwide")

        analyzed = []
        for article in articles:
            impact = self.assess_indian_market_impact(article)
            if impact["severity"] != "low" or impact["sectors_impacted"]:
                analyzed.append({**article, "impact": impact})

        analyzed.sort(key=lambda x: -abs(x["impact"]["impact_score"]))

        print(f"\n[+] Top market-moving stories:\n")
        for item in analyzed[:8]:
            sent = item["impact"]["sentiment"]["label"]
            sent_icon = {"positive": "+", "negative": "-", "neutral": "~"}
            print(f"  [{sent_icon.get(sent, '?')}] {item['title'][:90]}")
            print(f"      Sentiment: {sent.upper()} | Score: {item['impact']['impact_score']:+.1f}"
                  f" | Sectors: {', '.join(item['impact']['sectors_impacted'][:3]) or 'general'}")
            print(f"      Severity: {item['impact']['severity'].upper()}")
            print()

        return analyzed

    def get_summary(self, analyzed_news):
        if not analyzed_news:
            return {"overall_sentiment": "neutral", "bullish_sectors": [],
                    "bearish_sectors": [], "top_stories": [],
                    "market_outlook": "No data available"}

        avg_score = sum(a["impact"]["impact_score"] for a in analyzed_news) / len(analyzed_news)
        sector_scores = {}
        for a in analyzed_news:
            for s in a["impact"]["sectors_impacted"]:
                sector_scores.setdefault(s, []).append(a["impact"]["impact_score"])

        bullish_sectors = []
        bearish_sectors = []
        for s, scores in sector_scores.items():
            avg = sum(scores) / len(scores)
            if avg > 1.5:
                bullish_sectors.append(s)
            elif avg < -1.5:
                bearish_sectors.append(s)

        if avg_score > 2:
            outlook = "BULLISH"
        elif avg_score < -2:
            outlook = "BEARISH"
        else:
            outlook = "NEUTRAL/SIDEWAYS"

        return {
            "overall_sentiment": ("positive" if avg_score > 1 else
                                  "negative" if avg_score < -1 else "neutral"),
            "avg_impact_score": round(avg_score, 2),
            "bullish_sectors": bullish_sectors,
            "bearish_sectors": bearish_sectors,
            "top_stories": [a["title"] for a in analyzed_news[:5]],
            "market_outlook": outlook,
        }
