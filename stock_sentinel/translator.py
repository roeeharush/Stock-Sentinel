from deep_translator import GoogleTranslator


def translate_to_hebrew(text: str) -> str:
    """Translate English text to Hebrew. Returns original text if translation fails."""
    if not text or not text.strip():
        return text
    try:
        return GoogleTranslator(source="en", target="iw").translate(text) or text
    except Exception:
        return text
