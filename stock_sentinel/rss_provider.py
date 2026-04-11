import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from stock_sentinel.models import RssSentimentResult

BULLISH_TERMS = {"buy", "bullish", "breakout", "upside", "rally", "surge",
                 "beat", "upgrade", "climbs", "gains", "rises", "strong", "growth"}
BEARISH_TERMS = {"sell", "bearish", "dump", "downside", "crash", "miss",
                 "downgrade", "falls", "drops", "weak", "cut", "loss", "decline"}

_RSS_TEMPLATE = (
    "https://news.google.com/rss/search"
    "?q={ticker}+stock&hl=en-US&gl=US&ceid=US:en"
)
_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; StockSentinel/1.0)"}


def _score_headlines(headlines: list[str]) -> float:
    if not headlines:
        return 0.0
    bull = sum(1 for h in headlines for w in BULLISH_TERMS if w in h.lower())
    bear = sum(1 for h in headlines for w in BEARISH_TERMS if w in h.lower())
    total = bull + bear
    return 0.0 if total == 0 else (bull - bear) / total


def fetch_rss_sentiment(ticker: str, max_headlines: int = 10) -> RssSentimentResult:
    try:
        url = _RSS_TEMPLATE.format(ticker=ticker)
        req = urllib.request.Request(url, headers=_HEADERS)
        with urllib.request.urlopen(req, timeout=10) as resp:
            tree = ET.parse(resp)
        headlines = [
            item.findtext("title", default="")
            for item in tree.findall(".//item")[:max_headlines]
            if item.findtext("title")
        ]
        return RssSentimentResult(
            ticker=ticker,
            headlines=headlines,
            score=_score_headlines(headlines),
            headline_count=len(headlines),
            fetched_at=datetime.now(timezone.utc),
        )
    except Exception:
        return RssSentimentResult(
            ticker=ticker,
            headlines=[],
            score=0.0,
            headline_count=0,
            fetched_at=datetime.now(timezone.utc),
            failed=True,
        )
