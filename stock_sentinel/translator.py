import re
from deep_translator import GoogleTranslator

TRADING_GLOSSARY: dict[str, str] = {
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
