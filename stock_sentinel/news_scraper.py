import yfinance as yf
from datetime import datetime, timezone
from stock_sentinel.models import NewsSentimentResult

BULLISH_TERMS = {"buy", "bullish", "long", "breakout", "upside", "rally", "surge",
                 "beat", "upgrade", "climbs", "gains", "rises", "strong", "growth"}
BEARISH_TERMS = {"sell", "bearish", "short", "dump", "downside", "crash", "miss",
                 "downgrade", "falls", "drops", "weak", "cut", "loss", "decline"}


def _score_headlines(headlines: list[str]) -> float:
    if not headlines:
        return 0.0
    bull = sum(1 for h in headlines for w in BULLISH_TERMS if w in h.lower())
    bear = sum(1 for h in headlines for w in BEARISH_TERMS if w in h.lower())
    total = bull + bear
    return 0.0 if total == 0 else (bull - bear) / total


def fetch_news_sentiment(ticker: str, max_headlines: int = 10) -> NewsSentimentResult:
    try:
        news = yf.Ticker(ticker).news or []
        # yfinance 1.x nests title at item["content"]["title"]; 0.x had item["title"]
        headlines = []
        for item in news[:max_headlines]:
            title = (item.get("content") or {}).get("title") or item.get("title")
            if title:
                headlines.append(title)
        return NewsSentimentResult(
            ticker=ticker,
            headlines=headlines,
            score=_score_headlines(headlines),
            headline_count=len(headlines),
            fetched_at=datetime.now(timezone.utc),
        )
    except Exception:
        return NewsSentimentResult(
            ticker=ticker,
            headlines=[],
            score=0.0,
            headline_count=0,
            fetched_at=datetime.now(timezone.utc),
            failed=True,
        )
