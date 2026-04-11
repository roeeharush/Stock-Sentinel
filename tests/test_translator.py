from unittest.mock import patch
from stock_sentinel.translator import translate_to_hebrew


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
