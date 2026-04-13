"""Tests for stock_sentinel.debate_engine and notifier debate section."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from stock_sentinel.debate_engine import (
    _extract_json,
    _first_point,
    _trade_context,
    run_debate,
)
from stock_sentinel.models import Alert, DebateResult
from stock_sentinel.notifier import build_debate_section, build_message


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _alert(**overrides) -> Alert:
    defaults = dict(
        ticker="NVDA",
        direction="LONG",
        entry=880.0,
        stop_loss=856.0,
        take_profit=928.0,
        take_profit_1=916.0,
        take_profit_3=940.0,
        rsi=42.0,
        sentiment_score=0.6,
        confluence_factors=["EMA 200 Support", "Volume Spike", "MACD Bullish Cross"],
        horizon="SHORT_TERM",
        risk_reward=1.5,
        golden_cross=False,
        rsi_divergence="bullish",
    )
    defaults.update(overrides)
    return Alert(**defaults)


def _debate(**overrides) -> DebateResult:
    defaults = dict(
        ticker="NVDA",
        direction="LONG",
        bull_argument="תמיכה חזקה ב-EMA 200 עם מומנטום עולה.",
        bear_argument="התנגדות חזקה ברמת $920 עלולה לעצור את העלייה.",
        judge_verdict="העסקה מוצדקת עם ניהול סיכון קפדני.",
        confidence_score=72,
        full_bull=json.dumps({"טיעון_ראשי": "תמיכה חזקה ב-EMA 200 עם מומנטום עולה."}),
        full_bear=json.dumps({"טיעון_ראשי": "התנגדות חזקה ברמת $920 עלולה לעצור את העלייה."}),
        full_judge=json.dumps({
            "ציון_ביטחון": 72,
            "הכרעה": "העסקה מוצדקת עם ניהול סיכון קפדני.",
            "נימוק": "גורמי תמיכה טכניים מאששים את הכניסה.",
            "המלצה": "כנס",
        }),
    )
    defaults.update(overrides)
    return DebateResult(**defaults)


# ─────────────────────────────────────────────────────────────────────────────
# _extract_json
# ─────────────────────────────────────────────────────────────────────────────

def test_extract_json_plain():
    raw = '{"טיעון_ראשי": "test", "נקודות_תמיכה": ["a", "b"]}'
    result = _extract_json(raw)
    assert result["טיעון_ראשי"] == "test"


def test_extract_json_with_markdown_fence():
    raw = '```json\n{"ציון_ביטחון": 80, "הכרעה": "כנס"}\n```'
    result = _extract_json(raw)
    assert result["ציון_ביטחון"] == 80


def test_extract_json_raises_on_no_json():
    with pytest.raises(ValueError):
        _extract_json("no json here at all")


# ─────────────────────────────────────────────────────────────────────────────
# _first_point
# ─────────────────────────────────────────────────────────────────────────────

def test_first_point_from_list():
    assert _first_point(["a", "b", "c"]) == "a"


def test_first_point_from_string():
    assert _first_point("direct string") == "direct string"


def test_first_point_empty_list():
    assert _first_point([]) == "[]"


# ─────────────────────────────────────────────────────────────────────────────
# _trade_context
# ─────────────────────────────────────────────────────────────────────────────

def test_trade_context_contains_ticker():
    ctx = _trade_context(_alert(), [])
    assert "NVDA" in ctx


def test_trade_context_contains_entry_price():
    ctx = _trade_context(_alert(entry=880.0), [])
    assert "880" in ctx


def test_trade_context_contains_headlines():
    ctx = _trade_context(_alert(), ["NVDA beats earnings estimates"])
    assert "NVDA beats earnings estimates" in ctx


def test_trade_context_confluence_factors():
    ctx = _trade_context(_alert(), [])
    assert "EMA 200 Support" in ctx


# ─────────────────────────────────────────────────────────────────────────────
# build_debate_section
# ─────────────────────────────────────────────────────────────────────────────

def test_debate_section_header():
    lines = build_debate_section(_debate())
    text  = "\n".join(lines)
    assert "מועצת הסוכנים" in text


def test_debate_section_bull_present():
    lines = build_debate_section(_debate())
    text  = "\n".join(lines)
    assert "השור" in text
    assert "EMA 200" in text


def test_debate_section_bear_present():
    lines = build_debate_section(_debate())
    text  = "\n".join(lines)
    assert "הדוב" in text
    assert "התנגדות" in text


def test_debate_section_judge_verdict():
    lines = build_debate_section(_debate())
    text  = "\n".join(lines)
    assert "השופט" in text
    assert "מוצדקת" in text


def test_debate_section_confidence_score():
    lines = build_debate_section(_debate(confidence_score=72))
    text  = "\n".join(lines)
    assert "72%" in text


def test_debate_section_confidence_bar_green():
    lines = build_debate_section(_debate(confidence_score=80))
    text  = "\n".join(lines)
    assert "🟢" in text


def test_debate_section_confidence_bar_yellow():
    lines = build_debate_section(_debate(confidence_score=60))
    text  = "\n".join(lines)
    assert "🟡" in text


def test_debate_section_confidence_bar_red():
    lines = build_debate_section(_debate(confidence_score=30))
    text  = "\n".join(lines)
    assert "🔴" in text


def test_debate_section_recommendation_enter():
    lines = build_debate_section(_debate())
    text  = "\n".join(lines)
    assert "כנס" in text


def test_debate_section_no_recommendation_when_missing():
    d = _debate()
    d.full_judge = json.dumps({"ציון_ביטחון": 60, "הכרעה": "בדוק שוב", "נימוק": "לא ברור"})
    lines = build_debate_section(d)
    text  = "\n".join(lines)
    # Should still show judge verdict
    assert "השופט" in text


# ─────────────────────────────────────────────────────────────────────────────
# build_message with debate
# ─────────────────────────────────────────────────────────────────────────────

def test_build_message_with_debate_includes_council():
    msg = build_message(_alert(), [], _debate())
    assert "מועצת הסוכנים" in msg


def test_build_message_without_debate_no_council():
    msg = build_message(_alert(), [], None)
    assert "מועצת הסוכנים" not in msg


def test_build_message_with_debate_timestamp_is_last_meaningful_line():
    msg = build_message(_alert(), [], _debate())
    lines = [l for l in msg.split("\n") if l.strip()]
    # Last non-empty line should contain the timestamp marker
    assert "⏰" in lines[-1]


# ─────────────────────────────────────────────────────────────────────────────
# run_debate — disabled when no API key
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_run_debate_returns_none_without_api_key():
    with patch("stock_sentinel.debate_engine.config") as mock_cfg:
        mock_cfg.ANTHROPIC_API_KEY = ""
        result = await run_debate(_alert(), [])
    assert result is None


# ─────────────────────────────────────────────────────────────────────────────
# run_debate — mocked Anthropic calls
# ─────────────────────────────────────────────────────────────────────────────

def _make_mock_response(text: str) -> MagicMock:
    mock_resp = MagicMock()
    mock_resp.content = [MagicMock(text=text)]
    return mock_resp


BULL_JSON = json.dumps({
    "טיעון_ראשי": "מומנטום עולה עם תמיכת EMA 200.",
    "נקודות_תמיכה": ["Golden Cross", "RSI דיברגנס שורי"],
    "יעד_מחיר": "$930 בטווח של שבועיים",
})
BEAR_JSON = json.dumps({
    "טיעון_ראשי": "התנגדות חזקה ב-$915 עשויה לעצור את הרצים.",
    "סיכונים_עיקריים": ["מאקרו שלילי", "ריבית גבוהה"],
    "תרחיש_כישלון": "פריצה מטה של EMA 21 תאשר היפוך",
})
JUDGE_JSON = json.dumps({
    "ציון_ביטחון": 78,
    "הכרעה": "כדאי לכנס עם סטופ הדוק.",
    "נימוק": "גורמי תמיכה מרובים. יחס ס/ת נאות.",
    "המלצה": "כנס",
})


@pytest.mark.asyncio
async def test_run_debate_success():
    call_count = 0

    def fake_call(system, user):
        nonlocal call_count
        call_count += 1
        # Identify agent by the role label in the opening line (before the em-dash)
        if system.startswith('אתה "השור"'):
            return BULL_JSON
        if system.startswith('אתה "הדוב"'):
            return BEAR_JSON
        return JUDGE_JSON

    with patch("stock_sentinel.debate_engine.config") as mock_cfg, \
         patch("stock_sentinel.debate_engine._call_agent", side_effect=fake_call):
        mock_cfg.ANTHROPIC_API_KEY = "fake-key"
        mock_cfg.DEBATE_MODEL      = "claude-haiku-4-5-20251001"
        mock_cfg.DEBATE_MAX_TOKENS = 400
        result = await run_debate(_alert(), ["NVDA up 3%"])

    assert result is not None
    assert result.ticker == "NVDA"
    assert result.confidence_score == 78
    assert "כדאי לכנס" in result.judge_verdict
    assert result.bull_argument != ""
    assert result.bear_argument != ""


@pytest.mark.asyncio
async def test_run_debate_partial_failure_judge():
    """If only the Judge fails, return partial DebateResult with placeholder."""
    call_count = [0]

    def fake_call(system, user):
        call_count[0] += 1
        if system.startswith('אתה "השופט"'):
            raise RuntimeError("Judge API error")
        if system.startswith('אתה "השור"'):
            return BULL_JSON
        return BEAR_JSON

    with patch("stock_sentinel.debate_engine.config") as mock_cfg, \
         patch("stock_sentinel.debate_engine._call_agent", side_effect=fake_call):
        mock_cfg.ANTHROPIC_API_KEY = "fake-key"
        mock_cfg.DEBATE_MODEL      = "claude-haiku-4-5-20251001"
        mock_cfg.DEBATE_MAX_TOKENS = 400
        result = await run_debate(_alert(), [])

    assert result is not None
    assert result.confidence_score == 50   # fallback
    assert "שגיאת API" in result.judge_verdict


# ─────────────────────────────────────────────────────────────────────────────
# Visionary section — build_debate_section UI
# ─────────────────────────────────────────────────────────────────────────────

def test_visionary_section_shown_when_pattern_present():
    """When visionary_pattern is set the 👁️ section appears in the output."""
    debate = _debate(visionary_pattern="דגל שורי", visionary_confirms=True)
    lines = build_debate_section(debate)
    text = "\n".join(lines)
    assert "👁️" in text
    assert "ניתוח ויזואלי" in text
    assert "דגל שורי" in text


def test_visionary_section_hidden_when_no_pattern():
    """When visionary_pattern is empty the 👁️ section is absent."""
    debate = _debate(visionary_pattern="", visionary_confirms=None)
    lines = build_debate_section(debate)
    text = "\n".join(lines)
    assert "👁️" not in text
    assert "ניתוח ויזואלי" not in text


def test_visionary_confirms_shows_checkmark():
    """Confirming Visionary shows ✅."""
    debate = _debate(visionary_pattern="דגל שורי", visionary_confirms=True)
    lines = build_debate_section(debate)
    text = "\n".join(lines)
    assert "✅" in text
    assert "מאשר את הסיגנל" in text


def test_visionary_contradicts_shows_warning():
    """Contradicting Visionary shows ⚠️."""
    debate = _debate(visionary_pattern="ראש וכתפיים", visionary_confirms=False)
    lines = build_debate_section(debate)
    text = "\n".join(lines)
    assert "⚠️" in text
    assert "סותר את הסיגנל" in text


def test_visionary_section_appears_before_agent_council():
    """👁️ section must precede 🧠 section in the output."""
    debate = _debate(visionary_pattern="תחתית כפולה (W-Bottom)", visionary_confirms=True)
    lines = build_debate_section(debate)
    text = "\n".join(lines)
    idx_vision  = text.index("👁️")
    idx_council = text.index("🧠")
    assert idx_vision < idx_council


# ─────────────────────────────────────────────────────────────────────────────
# run_debate — Visionary integration
# ─────────────────────────────────────────────────────────────────────────────

VISIONARY_JSON = json.dumps({
    "תבנית_ויזואלית": "דגל שורי",
    "תיאור": "פריצה מעל רמת ההתנגדות עם עלייה בנפח",
    "מאשר_סיגנל": True,
    "השפעה_על_ביטחון": 12,
})


@pytest.mark.asyncio
async def test_run_debate_without_chart_skips_visionary():
    """run_debate without chart_path returns DebateResult with no visionary data."""
    def fake_call(system, user):
        if system.startswith('אתה "השור"'):
            return BULL_JSON
        if system.startswith('אתה "הדוב"'):
            return BEAR_JSON
        return JUDGE_JSON

    with patch("stock_sentinel.debate_engine.config") as mock_cfg, \
         patch("stock_sentinel.debate_engine._call_agent", side_effect=fake_call):
        mock_cfg.ANTHROPIC_API_KEY = "fake-key"
        mock_cfg.DEBATE_MODEL      = "claude-haiku-4-5-20251001"
        mock_cfg.DEBATE_MAX_TOKENS = 400
        result = await run_debate(_alert(), [], chart_path=None)

    assert result is not None
    assert result.visionary_pattern == ""
    assert result.visionary_confirms is None
    assert result.full_visionary == ""


@pytest.mark.asyncio
async def test_run_debate_with_chart_populates_visionary(tmp_path):
    """run_debate with a real PNG path runs the Visionary and stores results."""
    import os
    # Create a minimal 1x1 PNG (valid PNG header)
    png_bytes = (
        b'\x89PNG\r\n\x1a\n'             # PNG signature
        b'\x00\x00\x00\rIHDR'            # IHDR chunk length + type
        b'\x00\x00\x00\x01'              # width = 1
        b'\x00\x00\x00\x01'              # height = 1
        b'\x08\x02\x00\x00\x00\x90wS\xde'  # bit depth, colour type, crc
        b'\x00\x00\x00\x0cIDATx\x9cc\xf8\x0f\x00\x00\x01\x01\x00\x05\x18\xd8N'
        b'\x00\x00\x00\x00IEND\xaeB`\x82'
    )
    chart = tmp_path / "test_chart.png"
    chart.write_bytes(png_bytes)

    def fake_call(system, user):
        if system.startswith('אתה "השור"'):
            return BULL_JSON
        if system.startswith('אתה "הדוב"'):
            return BEAR_JSON
        return JUDGE_JSON

    def fake_visionary(image_path, context):
        return VISIONARY_JSON

    with patch("stock_sentinel.debate_engine.config") as mock_cfg, \
         patch("stock_sentinel.debate_engine._call_agent", side_effect=fake_call), \
         patch("stock_sentinel.debate_engine._call_visionary_agent", side_effect=fake_visionary):
        mock_cfg.ANTHROPIC_API_KEY = "fake-key"
        mock_cfg.DEBATE_MODEL      = "claude-haiku-4-5-20251001"
        mock_cfg.DEBATE_MAX_TOKENS = 400
        mock_cfg.VISION_MODEL      = "claude-sonnet-4-6"
        mock_cfg.VISION_MAX_TOKENS = 500
        result = await run_debate(_alert(), [], chart_path=str(chart))

    assert result is not None
    assert result.visionary_pattern == "דגל שורי"
    assert result.visionary_confirms is True
    assert result.full_visionary == VISIONARY_JSON


@pytest.mark.asyncio
async def test_run_debate_visionary_parse_failure_graceful(tmp_path):
    """If Visionary returns non-JSON, debate still succeeds with empty pattern."""
    png_bytes = (
        b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR'
        b'\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde'
        b'\x00\x00\x00\x0cIDATx\x9cc\xf8\x0f\x00\x00\x01\x01\x00\x05\x18\xd8N'
        b'\x00\x00\x00\x00IEND\xaeB`\x82'
    )
    chart = tmp_path / "test_chart.png"
    chart.write_bytes(png_bytes)

    def fake_call(system, user):
        if system.startswith('אתה "השור"'):
            return BULL_JSON
        if system.startswith('אתה "הדוב"'):
            return BEAR_JSON
        return JUDGE_JSON

    def fake_visionary_broken(image_path, context):
        return "no json here at all"

    with patch("stock_sentinel.debate_engine.config") as mock_cfg, \
         patch("stock_sentinel.debate_engine._call_agent", side_effect=fake_call), \
         patch("stock_sentinel.debate_engine._call_visionary_agent", side_effect=fake_visionary_broken):
        mock_cfg.ANTHROPIC_API_KEY = "fake-key"
        mock_cfg.DEBATE_MODEL      = "claude-haiku-4-5-20251001"
        mock_cfg.DEBATE_MAX_TOKENS = 400
        mock_cfg.VISION_MODEL      = "claude-sonnet-4-6"
        mock_cfg.VISION_MAX_TOKENS = 500
        result = await run_debate(_alert(), [], chart_path=str(chart))

    assert result is not None
    assert result.visionary_pattern == ""
    assert result.visionary_confirms is None


@pytest.mark.asyncio
async def test_run_debate_visionary_in_judge_prompt(tmp_path):
    """When Visionary runs, its findings appear in the Judge's user message."""
    png_bytes = (
        b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR'
        b'\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde'
        b'\x00\x00\x00\x0cIDATx\x9cc\xf8\x0f\x00\x00\x01\x01\x00\x05\x18\xd8N'
        b'\x00\x00\x00\x00IEND\xaeB`\x82'
    )
    chart = tmp_path / "test_chart.png"
    chart.write_bytes(png_bytes)

    judge_received_prompt: list[str] = []

    def fake_call(system, user):
        if system.startswith('אתה "השופט"'):
            judge_received_prompt.append(user)
            return JUDGE_JSON
        if system.startswith('אתה "השור"'):
            return BULL_JSON
        return BEAR_JSON

    def fake_visionary(image_path, context):
        return VISIONARY_JSON

    with patch("stock_sentinel.debate_engine.config") as mock_cfg, \
         patch("stock_sentinel.debate_engine._call_agent", side_effect=fake_call), \
         patch("stock_sentinel.debate_engine._call_visionary_agent", side_effect=fake_visionary):
        mock_cfg.ANTHROPIC_API_KEY = "fake-key"
        mock_cfg.DEBATE_MODEL      = "claude-haiku-4-5-20251001"
        mock_cfg.DEBATE_MAX_TOKENS = 400
        mock_cfg.VISION_MODEL      = "claude-sonnet-4-6"
        mock_cfg.VISION_MAX_TOKENS = 500
        await run_debate(_alert(), [], chart_path=str(chart))

    assert judge_received_prompt, "Judge was never called"
    assert "סוכן הראייה" in judge_received_prompt[0]
