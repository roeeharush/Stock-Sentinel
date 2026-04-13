"""Multi-Agent Debate Engine — Bull vs Bear vs Visionary vs Judge.

Four Claude agents collaborate on every trade signal before it reaches the user:

  Agent 1 — הַשּׁוֹר   (The Bull):      argues for the trade succeeding.
  Agent 2 — הַדּוֹב   (The Bear):      plays Devil's Advocate, finds risks.
  Agent 3 — סוֹכֵן הָרְאִיָּה (The Visionary): reads the chart image, identifies
                                         visual patterns (flags, H&S, W-Bottom…)
                                         and reports whether they confirm the signal.
  Agent 4 — הַשּׁוֹפֵּט (The Judge):     weighs all three inputs, assigns a 0-100
                                         confidence score, writes the verdict.

All agents respond in professional Hebrew.
Runs asynchronously (asyncio.to_thread wraps the blocking Anthropic calls).
Gracefully degrades — if the API key is absent or a call fails the caller
receives None and the alert is sent without the debate section.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import re
from datetime import datetime, timezone

import anthropic

from stock_sentinel import config
from stock_sentinel.models import Alert, DebateResult

log = logging.getLogger(__name__)

# ── Shared context builder ────────────────────────────────────────────────────

def _trade_context(alert: Alert, headlines: list[str]) -> str:
    """Build a compact Hebrew trade brief injected into every agent prompt."""
    direction_heb = "קנייה (LONG)" if alert.direction == "LONG" else "מכירה בחסר (SHORT)"
    factors = "\n".join(f"  - {f}" for f in (alert.confluence_factors or []))
    news_block = "\n".join(f"  - {h}" for h in headlines[:5]) if headlines else "  (אין כותרות)"
    return f"""
מניה: {alert.ticker}
כיוון: {direction_heb}
כניסה: ${alert.entry:.2f}  |  סטופ: ${alert.stop_loss:.2f}  |  יעד 1: ${alert.take_profit_1 or alert.take_profit:.2f}
יחס ס/ת: {alert.risk_reward:.1f}  |  RSI: {alert.rsi:.1f}  |  אופק: {alert.horizon}
Golden Cross: {"כן" if alert.golden_cross else "לא"}  |  RSI דיברגנס: {alert.rsi_divergence or "אין"}
גורמי התכנסות:
{factors or "  (לא פורט)"}
חדשות אחרונות:
{news_block}
""".strip()


# ── System prompts ─────────────────────────────────────────────────────────────

_BULL_SYSTEM = """אתה "השור" — אנליסט מסחר אגרסיבי שתמיד מוצא סיבות לכניסה לפוזיציה.
תפקידך: לזהות את הגורמים החזקים ביותר שיובילו להצלחת העסקה.
בדוק: מבנה שוק, מומנטום טכני, גורמי מאקרו תומכים, סנטימנט חיובי, קטליזטורים בחדשות.
ענה בעברית מקצועית בלבד. תשובתך תכלול:
1. טיעון_ראשי: משפט אחד חזק ביותר בזכות העסקה.
2. נקודות_תמיכה: עד 3 נקודות תמיכה קצרות.
3. יעד_מחיר: הערכת יעד מחיר ריאלי עם נימוק קצר.
פורמט תשובה: JSON בלבד בפורמט {"טיעון_ראשי": "...", "נקודות_תמיכה": ["...", "..."], "יעד_מחיר": "..."}"""

_BEAR_SYSTEM = """אתה "הדוב" — אנליסט ריסק מנג'מנט שמחפש את כל הסיכונים האפשריים.
תפקידך: להיות עורך הדין של השטן. מצא סיבות מדוע העסקה עלולה להיכשל.
בדוק: רמות התנגדות קריטיות, גורמי מאקרו שליליים, חסמים טכניים, סיכוני ידיעות, תנודתיות יתר.
ענה בעברית מקצועית בלבד. תשובתך תכלול:
1. טיעון_ראשי: משפט אחד חזק ביותר נגד העסקה.
2. סיכונים_עיקריים: עד 3 סיכונים קצרים.
3. תרחיש_כישלון: תרחיש קצר שבו העסקה מפסידה.
פורמט תשובה: JSON בלבד בפורמט {"טיעון_ראשי": "...", "סיכונים_עיקריים": ["...", "..."], "תרחיש_כישלון": "..."}"""

_VISIONARY_SYSTEM = """אתה "סוכן הראייה" — מנתח תבניות גרפיות בעזרת ראייה ממוחשבת.
תפקידך: לזהות תבניות ויזואליות בגרף ולבדוק האם הן מאשרות את סיגנל ה-SMC הנוכחי.
חפש תבניות כגון: כוס וידית (Cup & Handle), ראש וכתפיים (Head & Shoulders), דגל שורי (Bull Flag), תחתית כפולה (W-Bottom), דגל דובי (Bearish Flag), קודקוד כפול (Double Top), משולש עולה/יורד, פריצת רמה.
בדוק: כיוון הסיגנל (LONG/SHORT) מול התבניות שזיהית. שים לב לנפח, מומנטום, ורמות תמיכה/התנגדות.
ענה בעברית מקצועית בלבד.
פורמט תשובה: JSON בלבד:
{"תבנית_ויזואלית": "שם התבנית בעברית", "תיאור": "תיאור קצר של מה שנראה בגרף", "מאשר_סיגנל": true, "השפעה_על_ביטחון": 10}
כאשר "השפעה_על_ביטחון" הוא מספר בין -20 ל-+20 (חיובי = מחזק, שלילי = מחליש)."""

_JUDGE_SYSTEM = """אתה "השופט" — אנליסט בכיר נייטרלי שמכריע בין כל הצדדים.
תפקידך: לשקול את כל הטיעונים ולהוציא פסיקה מקצועית.
בהתבסס על הטיעונים שהוצגו לך (שור, דוב, וניתוח ויזואלי אם קיים), הגדר:
1. ציון_ביטחון: מספר 0-100 המשקף עד כמה אתה בטוח בהצלחת העסקה.
   חשוב: אם סוכן הראייה זיהה תבנית הסותרת את הסיגנל (כגון ראש וכתפיים בסיגנל LONG), הנמך את הציון.
2. הכרעה: משפט פסיקה אחד ברור בעברית (המלצה, אזהרה, או דחייה).
3. נימוק: 2-3 משפטים קצרים המסבירים את ההחלטה.
4. המלצה: "כנס" | "הימנע" | "המתן לאישור נוסף"
פורמט תשובה: JSON בלבד בפורמט {"ציון_ביטחון": 75, "הכרעה": "...", "נימוק": "...", "המלצה": "כנס"}"""


# ── Individual agent callers ──────────────────────────────────────────────────

def _call_agent(system_prompt: str, user_message: str) -> str:
    """Blocking Anthropic text call — intended to be run via asyncio.to_thread."""
    client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
    response = client.messages.create(
        model=config.DEBATE_MODEL,
        max_tokens=config.DEBATE_MAX_TOKENS,
        system=system_prompt,
        messages=[{"role": "user", "content": user_message}],
    )
    return response.content[0].text


def _call_visionary_agent(image_path: str, context: str) -> str:
    """Blocking multimodal call with chart PNG — run via asyncio.to_thread.

    Reads *image_path*, base64-encodes it, and sends it together with the
    trade context to the Vision model.  Returns the raw agent response text.
    """
    with open(image_path, "rb") as fh:
        image_data = base64.standard_b64encode(fh.read()).decode("utf-8")

    client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
    response = client.messages.create(
        model=config.VISION_MODEL,
        max_tokens=config.VISION_MAX_TOKENS,
        system=_VISIONARY_SYSTEM,
        messages=[{
            "role": "user",
            "content": [
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": "image/png",
                        "data": image_data,
                    },
                },
                {
                    "type": "text",
                    "text": (
                        f"להלן פרטי הסיגנל:\n\n{context}\n\n"
                        "נתח את הגרף שמוצג ובדוק האם התבניות הויזואליות מאשרות את הסיגנל."
                    ),
                },
            ],
        }],
    )
    return response.content[0].text


def _extract_json(raw: str) -> dict:
    """Extract a JSON object from the agent response, ignoring markdown fences."""
    cleaned = re.sub(r"```(?:json)?", "", raw).replace("```", "").strip()
    match = re.search(r"\{.*\}", cleaned, re.DOTALL)
    if match:
        return json.loads(match.group())
    raise ValueError(f"No JSON found in agent response: {raw[:200]}")


def _first_point(items: list | str) -> str:
    """Return the first string from a list, or the string itself."""
    if isinstance(items, list) and items:
        return str(items[0])
    return str(items)


# ── Public async entry point ──────────────────────────────────────────────────

async def run_debate(
    alert: Alert,
    headlines: list[str],
    chart_path: str | None = None,
) -> DebateResult | None:
    """Run the 4-agent debate for *alert* and return a DebateResult.

    Steps:
      1. Bull, Bear, and Visionary (if chart available) run in parallel.
      2. Judge receives all three inputs and delivers the final verdict.

    Returns None when the API key is absent, or if Bull/Bear both fail.
    Partial failures fall back gracefully.
    chart_path: path to the PNG chart for the Visionary agent (optional).
    """
    if not config.ANTHROPIC_API_KEY:
        log.debug("Debate engine disabled: ANTHROPIC_API_KEY not set")
        return None

    context = _trade_context(alert, headlines)
    bull_prompt = f"להלן פרטי העסקה לניתוח:\n\n{context}"
    bear_prompt = f"להלן פרטי העסקה לניתוח:\n\n{context}"

    # ── Step 1: Bull, Bear (and optionally Visionary) run in parallel ─────────
    visionary_task_included = (
        chart_path is not None
        and os.path.exists(chart_path)
        and config.ANTHROPIC_API_KEY
    )

    bull_raw = bear_raw = visionary_raw = ""
    try:
        if visionary_task_included:
            bull_raw, bear_raw, visionary_raw = await asyncio.gather(
                asyncio.to_thread(_call_agent, _BULL_SYSTEM, bull_prompt),
                asyncio.to_thread(_call_agent, _BEAR_SYSTEM, bear_prompt),
                asyncio.to_thread(_call_visionary_agent, chart_path, context),
            )
        else:
            bull_raw, bear_raw = await asyncio.gather(
                asyncio.to_thread(_call_agent, _BULL_SYSTEM, bull_prompt),
                asyncio.to_thread(_call_agent, _BEAR_SYSTEM, bear_prompt),
            )
    except Exception as exc:
        log.warning("Debate Bull/Bear/Visionary failed: %s", exc)
        return None

    # Parse Bull
    try:
        bull_data = _extract_json(bull_raw)
        bull_main = bull_data.get("טיעון_ראשי", _first_point(bull_raw[:200]))
    except Exception:
        bull_data = {}
        bull_main = bull_raw[:200]

    # Parse Bear
    try:
        bear_data = _extract_json(bear_raw)
        bear_main = bear_data.get("טיעון_ראשי", _first_point(bear_raw[:200]))
    except Exception:
        bear_data = {}
        bear_main = bear_raw[:200]

    # Parse Visionary
    visionary_pattern  = ""
    visionary_confirms: bool | None = None
    if visionary_raw:
        try:
            vis_data          = _extract_json(visionary_raw)
            visionary_pattern = vis_data.get("תבנית_ויזואלית", "")
            visionary_confirms = bool(vis_data.get("מאשר_סיגנל", True))
        except Exception:
            log.debug("Visionary JSON parse failed — raw: %s", visionary_raw[:200])

    # ── Step 2: Judge receives all inputs ─────────────────────────────────────
    judge_prompt = (
        f"להלן פרטי העסקה:\n\n{context}\n\n"
        f"--- טיעון השור ---\n{bull_raw}\n\n"
        f"--- טיעון הדוב ---\n{bear_raw}\n\n"
    )
    if visionary_raw:
        judge_prompt += (
            f"--- ניתוח סוכן הראייה ---\n{visionary_raw}\n\n"
        )
    judge_prompt += "כעת הכרע בין כל הצדדים."

    judge_raw = ""
    try:
        judge_raw = await asyncio.to_thread(_call_agent, _JUDGE_SYSTEM, judge_prompt)
    except Exception as exc:
        log.warning("Debate Judge failed: %s", exc)
        return DebateResult(
            ticker=alert.ticker,
            direction=alert.direction,
            bull_argument=bull_main,
            bear_argument=bear_main,
            judge_verdict="השופט לא הצליח להכריע (שגיאת API)",
            confidence_score=50,
            full_bull=bull_raw,
            full_bear=bear_raw,
            full_judge="",
            full_visionary=visionary_raw,
            visionary_pattern=visionary_pattern,
            visionary_confirms=visionary_confirms,
        )

    try:
        judge_data = _extract_json(judge_raw)
        confidence = int(judge_data.get("ציון_ביטחון", 50))
        confidence = max(0, min(100, confidence))
        verdict    = judge_data.get("הכרעה", judge_raw[:200])
    except Exception:
        confidence = 50
        verdict    = judge_raw[:200]

    return DebateResult(
        ticker=alert.ticker,
        direction=alert.direction,
        bull_argument=bull_main,
        bear_argument=bear_main,
        judge_verdict=verdict,
        confidence_score=confidence,
        full_bull=bull_raw,
        full_bear=bear_raw,
        full_judge=judge_raw,
        full_visionary=visionary_raw,
        visionary_pattern=visionary_pattern,
        visionary_confirms=visionary_confirms,
    )
