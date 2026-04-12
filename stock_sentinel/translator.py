import re
from deep_translator import GoogleTranslator

TRADING_GLOSSARY: dict[str, str] = {
    # Expert Tier — Task 16
    "Bullish Divergence": "דיברגנס שורי (RSI)",
    "Bearish Divergence": "דיברגנס דובי (RSI)",
    "RSI Divergence": "דיברגנס RSI",
    "Divergence": "דיברגנס",
    "Point of Control": "נקודת שליטה (POC)",
    "Golden Cross": "חצייה זהובה (Golden Cross)",
    "Golden Pocket": "כיס הזהב (פיבונאצ'י 0.618–0.65)",
    "Fibonacci": "פיבונאצ'י",
    "Pivot Point": "נקודת ציר",
    "Institutional": "מוסדי",
    # Price Action
    "Gap Up": "פתיחה בפער עולה",
    "Gap Down": "פתיחה בפער יורד",
    "Pullback": "נסיגה לצורך עליה",
    "Consolidation": "דשדוש/התגבשות",
    "Reversal": "היפוך מגמה",
    "Sell-off": "גל מכירות",
    "Rally": "ראלי/רצף עליות",
    "Breakout": "פריצה",
    # Fundamentals
    "Guidance": "תחזית חברה",
    "Beat": "עקיפת תחזיות",
    "Miss": "פספוס תחזיות",
    "Price Target": "מחיר יעד",
    "Upgrade": "העלאת דירוג",
    "Downgrade": "הורדת דירוג",
    # Sentiment & Technicals
    "Bullish": "מגמה שורית/אופטימי",
    "Bearish": "מגמה דובית/פסימי",
    "Overbought": "קניית יתר",
    "Oversold": "מכירת יתר",
    "Short Squeeze": "שורט סקוויז",
    "Resistance": "רמת התנגדות",
    "Support": "רמת תמיכה",
    # Candlestick Patterns
    "Bullish Engulfing": "תבנית בליעה שורית",
    "Engulfing": "תבנית בליעה",
    "Hammer": "פטיש (תבנית נרות)",
    "Shooting Star": "כוכב נופל (תבנית נרות)",
    # Volume & VWAP
    "Volume Spike": "פריצת ווליום",
    "VWAP": "מחיר ממוצע משוקלל לפי נפח",
    # Momentum
    "MACD Bullish": "מד מומנטום עולה (MACD)",
    "MACD Bearish": "מד מומנטום יורד (MACD)",
    "EMA 200 Trend": "מגמת EMA 200",
    "Price below EMA 200": "מחיר מתחת ל-EMA 200",
    # Confluence
    "Confluence": "גורמי התכנסות הטרייד",
    # Horizon & New Indicators
    "Bollinger Band Breakout": "פריצת רצועות בולינגר",
    "Stochastic RSI Crossover": "חצייה של RSI סטוכסטי",
    "ADX Strong Trend": "מגמה חזקה (ADX)",
    "OBV Rising": "נפח מצטבר עולה (OBV)",
    "Short-term": "טווח קצר",
    "Long-term": "לטווח ארוך",
    "TP1 Conservative": "יעד 1 (שמרני)",
    "TP2 Moderate": "יעד 2 (מתון)",
    "TP3 Ambitious": "יעד 3 (שאפתני)",
}

# Sort by length descending so multi-word terms (e.g. "Short Squeeze") match before
# their sub-words (e.g. "Short")
_SORTED_TERMS = sorted(TRADING_GLOSSARY.keys(), key=len, reverse=True)


def _apply_glossary(text: str) -> str:
    """Replace glossary terms case-insensitively, leaving $TICKER and numbers intact."""
    for term in _SORTED_TERMS:
        pattern = re.compile(re.escape(term), re.IGNORECASE)
        text = pattern.sub(TRADING_GLOSSARY[term], text)
    return text


def translate_to_hebrew(text: str) -> str:
    """Translate English text to Hebrew using glossary pre-substitution + deep-translator.

    Steps:
    1. Apply case-insensitive TRADING_GLOSSARY substitutions (preserves $TICKER and numbers).
    2. Pass result to deep-translator for final Hebrew sentence construction.
    3. Returns original text on any error.
    """
    if not text or not text.strip():
        return text
    try:
        preprocessed = _apply_glossary(text)
        return GoogleTranslator(source="en", target="iw").translate(preprocessed) or text
    except Exception:
        return text
