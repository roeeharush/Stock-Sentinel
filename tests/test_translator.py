from unittest.mock import patch
from stock_sentinel.translator import translate_to_hebrew, TRADING_GLOSSARY, _apply_glossary


def test_translate_returns_string():
    with patch("stock_sentinel.translator.GoogleTranslator") as MockTranslator:
        MockTranslator.return_value.translate.return_value = "NVDA פורצת"
        result = translate_to_hebrew("NVDA breaks out")
    assert result == "NVDA פורצת"


def test_translate_fallback_on_error():
    with patch("stock_sentinel.translator.GoogleTranslator") as MockTranslator:
        MockTranslator.return_value.translate.side_effect = Exception("network error")
        result = translate_to_hebrew("NVDA breaks out")
    assert result == "NVDA breaks out"


def test_translate_empty_returns_empty():
    result = translate_to_hebrew("")
    assert result == ""


def test_glossary_has_expected_keys():
    required = {"Bullish", "Bearish", "Breakout", "Gap Up", "Resistance", "Support", "Beat"}
    assert required.issubset(TRADING_GLOSSARY.keys())


def test_apply_glossary_case_insensitive():
    result = _apply_glossary("NVDA is bullish after a breakout near resistance")
    assert "מגמה שורית/אופטימי" in result
    assert "פריצה" in result
    assert "רמת התנגדות" in result
    assert "NVDA" in result  # ticker preserved


def test_apply_glossary_preserves_ticker_and_numbers():
    result = _apply_glossary("$NVDA gap up to $150.00 with a beat of guidance")
    assert "$NVDA" in result
    assert "$150.00" in result
    assert "פתיחה בפער עולה" in result
    assert "עקיפת תחזיות" in result
    assert "תחזית חברה" in result


def test_apply_glossary_multi_word_before_single():
    """'Short Squeeze' must substitute before 'Short' can mis-match it."""
    result = _apply_glossary("A short squeeze sent SOFI higher")
    assert "שורט סקוויז" in result
    assert "Short" not in result  # fully consumed by multi-word match


def test_translate_with_glossary_mixed_sentence():
    """Glossary substitution fires before deep-translator is called."""
    with patch("stock_sentinel.translator.GoogleTranslator") as MockTranslator:
        MockTranslator.return_value.translate.return_value = "משפט מתורגם"
        result = translate_to_hebrew("NVDA beat guidance and is Bullish after a Gap Up near Resistance")
    # translator was called with glossary-substituted text, not the raw English
    call_arg = MockTranslator.return_value.translate.call_args[0][0]
    assert "עקיפת תחזיות" in call_arg
    assert "מגמה שורית/אופטימי" in call_arg
    assert "פתיחה בפער עולה" in call_arg
    assert "רמת התנגדות" in call_arg
    assert result == "משפט מתורגם"
