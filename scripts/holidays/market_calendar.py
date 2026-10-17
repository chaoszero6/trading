#!/usr/bin/env python3
"""NSE trading-day calendar shared by HermesTrader and CodexTrader.

Ground truth is the NSE ``holiday-master`` API. The hardcoded list below is a
*fallback of last resort* and is only trusted when it is complete enough to be
safe — see ``holiday_map_for_year`` and ``HOLIDAYS_BY_YEAR``.

Fail-safe policy (chosen 2026-09-14): if the API is unreachable AND there is no
usable cache AND no complete local fallback list for the year, we report
``isTradingDay = False`` and warn loudly. A missed paper-trading day costs
nothing; trading on a holiday corrupts the P&L record.
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from urllib.request import Request, build_opener, HTTPCookieProcessor
from http.cookiejar import CookieJar


IST = timezone(timedelta(hours=5, minutes=30))
ROOT = Path(__file__).resolve().parent
CACHE_PATH = ROOT / "market_holidays_cache.json"
NSE_HOLIDAY_API = "https://www.nseindia.com/api/holiday-master?type=trading"
NSE_HOME = "https://www.nseindia.com/"

# Cache is good for the rest of the day it was fetched, plus the following
# weekend/holiday (up to 5 days) — so a Monday run never depends on a Friday
# fetch being fresh, and a stale cache can't silently hide a holiday.
CACHE_MAX_AGE_SECONDS = int(os.environ.get("TRADING_CALENDAR_CACHE_MAX_AGE", 5 * 24 * 60 * 60))
CACHE_FRESH_SECONDS = 24 * 60 * 60

# NSE publishes ~15 trading holidays a year. Anything materially below this for
# a whole year means the list is truncated/partial and must not be trusted to
# decide that a day *is* a trading day.
MIN_EXPECTED_HOLIDAYS_PER_YEAR = 10

# ---------------------------------------------------------------------------
# Fallback list — used ONLY if the NSE API is unreachable. It must be complete
# for the year or it is discarded (see holiday_map_for_year).
#
# 2026: transcribed from the NSE holiday-master API response verified
# 2026-09-14. Twelve of these are weekday holidays that actually stop trading;
# three fall on weekends and are kept for completeness.
# ---------------------------------------------------------------------------
TRADING_HOLIDAYS_2026 = {
    "2026-01-15": "Municipal Corporation Election - Maharashtra",
    "2026-01-26": "Republic Day",
    "2026-02-15": "Mahashivratri",
    "2026-03-03": "Holi",
    "2026-03-21": "Id-Ul-Fitr (Ramadan Eid)",
    "2026-03-26": "Shri Ram Navami",
    "2026-03-31": "Shri Mahavir Jayanti",
    "2026-04-03": "Good Friday",
    "2026-04-14": "Dr. Baba Saheb Ambedkar Jayanti",
    "2026-05-01": "Maharashtra Day",
    "2026-05-28": "Bakri Id",
    "2026-06-26": "Muharram",
    "2026-08-15": "Independence Day",
    "2026-09-14": "Ganesh Chaturthi",
    "2026-10-02": "Mahatma Gandhi Jayanti",
    "2026-10-20": "Dussehra",
    "2026-11-08": "Diwali Laxmi Pujan*",
    "2026-11-10": "Diwali-Balipratipada",
    "2026-11-24": "Prakash Gurpurb Sri Guru Nanak Dev",
    "2026-12-25": "Christmas",
}

HOLIDAYS_BY_YEAR = {
    2026: TRADING_HOLIDAYS_2026,
}


def now_ist():
    return datetime.now(IST)


def extra_holidays():
    """Operator-supplied ad-hoc closures: EXTRA_TRADING_HOLIDAYS=2026-09-15:Reason,2026-09-16"""
    holidays = {}
    raw = os.environ.get("EXTRA_TRADING_HOLIDAYS", "")
    for item in raw.split(","):
        if not item.strip():
            continue
        if ":" in item:
            date_text, reason = item.split(":", 1)
        else:
            date_text, reason = item, "Manual trading holiday"
        date_text = date_text.strip()
        if date_text:
            holidays[date_text] = reason.strip() or "Manual trading holiday"
    return holidays


def parse_nse_date(value):
    text = str(value or "").strip()
    for fmt in ("%d-%b-%Y", "%d-%B-%Y", "%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(text, fmt).date().isoformat()
        except ValueError:
            continue
    return ""


def nse_headers():
    return {
        "User-Agent": "PostmanRuntime/7.26.5",
        "Accept": "application/json,text/plain,*/*",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": "https://www.nseindia.com/resources/exchange-communication-holidays",
    }


def read_cached_holidays(year, max_age_seconds=None):
    """Return (holidays, source, age_seconds) if the cache is usable for `year`."""
    if not CACHE_PATH.exists():
        return {}, "", None
    try:
        payload = json.loads(CACHE_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}, "", None
    if payload.get("year") != year:
        return {}, "", None
    holidays = payload.get("holidays") or {}
    if not holidays:
        return {}, "", None
    limit = CACHE_MAX_AGE_SECONDS if max_age_seconds is None else max_age_seconds
    age = time.time() - float(payload.get("fetchedAt", 0))
    if age > limit:
        return {}, "", age
    return holidays, payload.get("source") or "NSE cached", age


def write_cached_holidays(year, holidays, source):
    tmp_path = CACHE_PATH.with_suffix(".json.tmp")
    tmp_path.write_text(
        json.dumps({
            "year": year,
            "holidays": holidays,
            "source": source,
            "fetchedAt": time.time(),
            "fetchedAtIso": now_ist().isoformat(timespec="seconds"),
        }, indent=2),
        encoding="utf-8",
    )
    tmp_path.replace(CACHE_PATH)


def fetch_nse_holidays(year, retries=2):
    """Hit the NSE holiday API. Raises on failure — no silent fallback here."""
    last_exc = None
    for attempt in range(retries + 1):
        try:
            jar = CookieJar()
            opener = build_opener(HTTPCookieProcessor(jar))
            try:
                opener.open(Request(NSE_HOME, headers=nse_headers()), timeout=15).read()
            except Exception:
                pass  # cookie priming is best-effort; the API call is what matters
            response = opener.open(Request(NSE_HOLIDAY_API, headers=nse_headers()), timeout=20)
            payload = json.loads(response.read().decode("utf-8"))
            holidays = {}
            for segment in ("FO", "CM", "CBM"):
                for row in payload.get(segment, []) or []:
                    date_text = parse_nse_date(row.get("tradingDate"))
                    if date_text and date_text.startswith(str(year)):
                        holidays[date_text] = (
                            row.get("description") or row.get("holiday") or "NSE trading holiday"
                        )
            if not holidays:
                raise RuntimeError("NSE holiday API returned no holidays for the year.")
            write_cached_holidays(year, holidays, "NSE holiday-master API")
            return holidays, "NSE holiday-master API"
        except Exception as exc:  # noqa: BLE001 — network/parse errors alike
            last_exc = exc
            if attempt < retries:
                time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"NSE holiday fetch failed after {retries + 1} attempts: {last_exc}")


def holiday_map_for_year(year):
    """Resolve the holiday map for `year`.

    Returns (holidays, source, trusted).

    ``trusted`` is False when we have neither a fresh fetch, a usable cache, nor
    a complete local fallback — in that case the caller MUST NOT conclude that a
    given day is a trading day.
    """
    try:
        holidays, source = fetch_nse_holidays(year)
        return holidays, source, True
    except Exception as fetch_exc:
        cached, cache_source, age = read_cached_holidays(year)
        if cached:
            age_h = age / 3600 if age is not None else 0
            return cached, f"{cache_source} (stale cache, {age_h:.1f}h old)", True
        fallback = HOLIDAYS_BY_YEAR.get(year, {})
        if len(fallback) >= MIN_EXPECTED_HOLIDAYS_PER_YEAR:
            return dict(fallback), (
                f"complete local fallback list; NSE fetch failed: {fetch_exc}"
            ), True
        # No usable source at all — refuse to guess.
        return dict(fallback), (
            f"NO TRUSTED HOLIDAY SOURCE; NSE fetch failed: {fetch_exc}. "
            f"Only {len(fallback)} local holidays known for {year}."
        ), False


def trading_day_status(moment=None):
    """Full status dict for a given moment (default: now, IST)."""
    moment = moment or now_ist()
    date_text = moment.date().isoformat()
    holidays, source, trusted = holiday_map_for_year(moment.year)
    holiday_map = {**holidays, **extra_holidays()}

    if moment.weekday() >= 5:
        return {
            "isTradingDay": False,
            "reason": "Weekend",
            "date": date_text,
            "source": source,
            "trusted": trusted,
            "message": f"{date_text} is a weekend. Agents will not start.",
        }
    if date_text in holiday_map:
        reason = holiday_map[date_text]
        return {
            "isTradingDay": False,
            "reason": reason,
            "date": date_text,
            "source": source,
            "trusted": trusted,
            "message": f"{date_text} is a trading holiday: {reason}. Agents will not start.",
        }
    if not trusted:
        return {
            "isTradingDay": False,
            "reason": "Unknown — holiday calendar unavailable",
            "date": date_text,
            "source": source,
            "trusted": False,
            "message": (
                f"{date_text}: cannot confirm the market is open — no NSE data, no usable "
                f"cache, no complete local list. FAIL-SAFE: agents will NOT start. "
                f"Fix the calendar or set EXTRA_TRADING_HOLIDAYS to override."
            ),
        }
    return {
        "isTradingDay": True,
        "reason": "Trading day",
        "date": date_text,
        "source": source,
        "trusted": trusted,
        "message": f"{date_text} is a trading day. Agents may run during market hours.",
    }


def should_run_trading(moment=None):
    """Thin boolean wrapper for shells: exit 0 = run, exit 1 = skip."""
    return trading_day_status(moment)["isTradingDay"]


def _format_report(status, now_first=False):
    flag = "RUN " if status["isTradingDay"] else "SKIP"
    lines = [
        f"{flag} | {status['date']} | {status['reason']}",
        f"     source: {status['source']}",
        f"     {status['message']}",
    ]
    if now_first:
        lines.insert(0, f"now(IST): {now_ist().isoformat(timespec='seconds')}")
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="NSE trading-day check. Exit 0 = trade, 1 = skip, 2 = error."
    )
    parser.add_argument("--check", "--is-trading-day", dest="check", action="store_true",
                        help="quiet mode: only the exit code (0 trade / 1 skip)")
    parser.add_argument("--date", help="evaluate a specific date (YYYY-MM-DD, IST)")
    parser.add_argument("--json", action="store_true", help="emit JSON status")
    parser.add_argument("--refresh", action="store_true",
                        help="force a fresh fetch from NSE and rewrite the cache")
    parser.add_argument("--no-fail-safe", action="store_true",
                        help="exit 0 instead of 1 when the calendar is untrusted")
    args = parser.parse_args(argv)

    if args.refresh:
        try:
            holidays, source = fetch_nse_holidays(now_ist().year)
            print(f"Refreshed {len(holidays)} holidays from {source} -> {CACHE_PATH}")
        except Exception as exc:  # noqa: BLE001
            print(f"Refresh failed: {exc}", file=sys.stderr)
            return 2

    moment = None
    if args.date:
        try:
            moment = datetime.strptime(args.date, "%Y-%m-%d").replace(tzinfo=IST)
        except ValueError:
            print(f"Bad --date {args.date!r}; expected YYYY-MM-DD", file=sys.stderr)
            return 2

    status = trading_day_status(moment)

    if args.json:
        print(json.dumps(status, indent=2))
    elif not args.check:
        print(_format_report(status, now_first=moment is None))

    if status["isTradingDay"]:
        return 0
    if args.no_fail_safe and not status["trusted"] and status["reason"].startswith("Unknown"):
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
