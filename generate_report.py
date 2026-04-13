"""
Stock Sentinel — Professional Hebrew Technical Report & User Manual
Generates: Stock_Sentinel_Full_Specs_Roee.pdf
Run: python generate_report.py
"""
import base64
import os
from pathlib import Path
from datetime import date

# ── Logo embed ────────────────────────────────────────────────────────────────
LOGO_PATH = Path(__file__).parent / "logo.png"
if LOGO_PATH.exists():
    with open(LOGO_PATH, "rb") as f:
        _b64 = base64.b64encode(f.read()).decode()
    LOGO_TAG = f'<img class="logo" src="data:image/png;base64,{_b64}" alt="Stock Sentinel Logo"/>'
else:
    LOGO_TAG = '<div class="logo-placeholder">🦅</div>'

TODAY = date.today().strftime("%d/%m/%Y")

HTML = f"""<!DOCTYPE html>
<html dir="rtl" lang="he">
<head>
<meta charset="UTF-8"/>
<style>
  /* ── Reset & Base ─────────────────────────────────────────────── */
  @import url('https://fonts.googleapis.com/css2?family=Heebo:wght@300;400;600;700;900&display=swap');

  * {{ box-sizing: border-box; margin: 0; padding: 0; }}

  body {{
    font-family: 'Heebo', 'Arial Hebrew', Arial, sans-serif;
    direction: rtl;
    background: #f7f9fc;
    color: #1a2340;
    font-size: 11pt;
    line-height: 1.75;
  }}

  /* ── Colour palette ───────────────────────────────────────────── */
  :root {{
    --navy:   #0d1b3e;
    --navy2:  #162650;
    --gold:   #c8a84b;
    --gold2:  #e8c96a;
    --light:  #eef2f9;
    --muted:  #6b7a99;
    --white:  #ffffff;
    --green:  #1a7f4b;
    --red:    #b32222;
    --border: #d0d8ec;
  }}

  /* ── Cover page ───────────────────────────────────────────────── */
  .cover {{
    background: linear-gradient(160deg, var(--navy) 0%, var(--navy2) 60%, #1e3a6e 100%);
    color: var(--white);
    min-height: 100vh;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    padding: 50px 40px;
    /* Force LTR on the cover so the centered flex column
       isn't shifted by the document-level RTL direction */
    direction: ltr;
    text-align: center;
    page-break-after: always;
  }}

  .cover .logo {{
    width: 260px;
    height: auto;
    max-height: 260px;
    object-fit: contain;
    margin-bottom: 0px;
    /* Lift off the dark background with a subtle glow ring */
    filter: drop-shadow(0 0 32px rgba(200,168,75,0.55))
            drop-shadow(0 8px 24px rgba(0,0,0,0.55));
    /* Slight zoom on render for crispness */
    image-rendering: -webkit-optimize-contrast;
  }}

  .cover .logo-placeholder {{
    font-size: 96px;
    margin-bottom: 28px;
    filter: drop-shadow(0 6px 24px rgba(200,168,75,0.5));
  }}

  /* When the real logo is shown, hide the separate title block —
     the logo image already contains the STOCK SENTINEL wordmark.
     We keep .cover-title in markup as a fallback for the placeholder. */
  .cover:has(.logo) .cover-title,
  .cover:has(.logo) .cover-subtitle {{
    display: none;
  }}

  .cover-title {{
    font-size: 38pt;
    font-weight: 900;
    letter-spacing: 2px;
    color: var(--gold2);
    text-shadow: 0 2px 16px rgba(0,0,0,0.4);
    margin-bottom: 6px;
  }}

  .cover-subtitle {{
    font-size: 14pt;
    font-weight: 300;
    color: #a0b4d8;
    letter-spacing: 3px;
    text-transform: uppercase;
    margin-bottom: 40px;
  }}

  .cover-divider {{
    width: 160px;
    height: 2px;
    background: linear-gradient(to left, transparent, var(--gold2), transparent);
    margin: 28px auto 36px;
  }}

  .cover-meta {{
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    gap: 24px;
    max-width: 680px;
    margin: 0 auto 40px;
  }}

  .meta-card {{
    background: rgba(255,255,255,0.07);
    border: 1px solid rgba(200,168,75,0.25);
    border-radius: 10px;
    padding: 16px 14px;
    direction: rtl;
  }}

  .meta-label {{
    font-size: 8pt;
    color: #7a9cc8;
    letter-spacing: 1.5px;
    text-transform: uppercase;
    margin-bottom: 5px;
  }}

  .meta-value {{
    font-size: 13pt;
    font-weight: 700;
    color: var(--gold2);
  }}

  .cover-badge {{
    background: rgba(200,168,75,0.15);
    border: 1px solid rgba(200,168,75,0.4);
    border-radius: 50px;
    padding: 10px 28px;
    font-size: 10pt;
    color: #c8d8f0;
    letter-spacing: 1px;
  }}

  /* ── Page break control ──────────────────────────────────────── */
  .page-break {{ page-break-before: always; }}

  /* ── Content wrapper ─────────────────────────────────────────── */
  .content {{
    max-width: 760px;
    margin: 0 auto;
    padding: 48px 36px;
  }}

  /* ── Section headers ─────────────────────────────────────────── */
  .section-header {{
    background: linear-gradient(to left, var(--navy), var(--navy2));
    color: var(--white);
    padding: 16px 24px;
    border-radius: 10px 10px 0 0;
    margin-top: 36px;
    margin-bottom: 0;
    display: flex;
    align-items: center;
    gap: 12px;
  }}

  .section-number {{
    background: var(--gold);
    color: var(--navy);
    border-radius: 50%;
    width: 30px;
    height: 30px;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    font-weight: 900;
    font-size: 12pt;
    flex-shrink: 0;
  }}

  .section-title {{
    font-size: 16pt;
    font-weight: 700;
    letter-spacing: 0.5px;
  }}

  .section-body {{
    background: var(--white);
    border: 1px solid var(--border);
    border-top: none;
    border-radius: 0 0 10px 10px;
    padding: 24px 28px;
    margin-bottom: 8px;
  }}

  /* ── Sub-headers ─────────────────────────────────────────────── */
  h3 {{
    font-size: 13pt;
    font-weight: 700;
    color: var(--navy);
    margin: 22px 0 10px;
    padding-right: 12px;
    border-right: 4px solid var(--gold);
  }}

  h4 {{
    font-size: 11.5pt;
    font-weight: 600;
    color: var(--navy2);
    margin: 16px 0 8px;
  }}

  p {{ margin-bottom: 12px; }}

  /* ── Stat cards ──────────────────────────────────────────────── */
  .stats-grid {{
    display: grid;
    grid-template-columns: repeat(4, 1fr);
    gap: 14px;
    margin: 18px 0;
  }}

  .stat-card {{
    background: var(--light);
    border: 1px solid var(--border);
    border-top: 3px solid var(--gold);
    border-radius: 8px;
    padding: 16px 12px;
    text-align: center;
  }}

  .stat-number {{
    font-size: 26pt;
    font-weight: 900;
    color: var(--navy);
    line-height: 1;
    margin-bottom: 4px;
  }}

  .stat-label {{
    font-size: 8.5pt;
    color: var(--muted);
    font-weight: 600;
    letter-spacing: 0.5px;
  }}

  /* ── Feature table ───────────────────────────────────────────── */
  .feature-table {{
    width: 100%;
    border-collapse: collapse;
    margin: 14px 0;
    font-size: 10.5pt;
  }}

  .feature-table th {{
    background: var(--navy);
    color: var(--gold2);
    padding: 11px 14px;
    text-align: right;
    font-weight: 700;
    font-size: 10pt;
    letter-spacing: 0.5px;
  }}

  .feature-table td {{
    padding: 10px 14px;
    border-bottom: 1px solid var(--border);
    vertical-align: top;
  }}

  .feature-table tr:nth-child(even) td {{
    background: var(--light);
  }}

  .feature-table tr:last-child td {{
    border-bottom: none;
  }}

  /* ── Alert type cards ────────────────────────────────────────── */
  .alert-grid {{
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 16px;
    margin: 16px 0;
  }}

  .alert-card {{
    border: 1px solid var(--border);
    border-radius: 10px;
    overflow: hidden;
  }}

  .alert-card-header {{
    padding: 12px 16px;
    font-weight: 700;
    font-size: 12pt;
    display: flex;
    align-items: center;
    gap: 8px;
  }}

  .alert-news   .alert-card-header {{ background: #e8f4fd; color: #0d4f7c; border-bottom: 2px solid #2980b9; }}
  .alert-macro  .alert-card-header {{ background: #eef2f8; color: #1a2e5a; border-bottom: 2px solid var(--navy); }}
  .alert-disc   .alert-card-header {{ background: #fdf6e3; color: #5c4200; border-bottom: 2px solid var(--gold); }}
  .alert-smc    .alert-card-header {{ background: #e8f8ee; color: #155734; border-bottom: 2px solid #27ae60; }}

  .alert-card-body {{
    padding: 14px 16px;
    font-size: 10pt;
    line-height: 1.7;
    background: var(--white);
  }}

  /* ── Schedule timeline ───────────────────────────────────────── */
  .timeline {{
    position: relative;
    padding-right: 28px;
    margin: 16px 0;
  }}

  .timeline::before {{
    content: '';
    position: absolute;
    right: 8px;
    top: 0;
    bottom: 0;
    width: 2px;
    background: linear-gradient(to bottom, var(--gold), var(--navy));
  }}

  .timeline-item {{
    position: relative;
    margin-bottom: 18px;
    background: var(--white);
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 14px 16px;
  }}

  .timeline-item::before {{
    content: '';
    position: absolute;
    right: -24px;
    top: 16px;
    width: 12px;
    height: 12px;
    border-radius: 50%;
    background: var(--gold);
    border: 2px solid var(--white);
    box-shadow: 0 0 0 2px var(--gold);
  }}

  .timeline-time {{
    font-size: 9pt;
    font-weight: 700;
    color: var(--gold);
    letter-spacing: 1px;
    margin-bottom: 4px;
  }}

  .timeline-title {{
    font-weight: 700;
    font-size: 11pt;
    color: var(--navy);
    margin-bottom: 4px;
  }}

  .timeline-desc {{
    font-size: 10pt;
    color: #4a5570;
    line-height: 1.6;
  }}

  /* ── Architecture diagram ────────────────────────────────────── */
  .arch-layer {{
    background: var(--light);
    border: 1px solid var(--border);
    border-right: 4px solid var(--navy);
    border-radius: 6px;
    padding: 12px 16px;
    margin-bottom: 10px;
  }}

  .arch-layer.gold {{ border-right-color: var(--gold); }}
  .arch-layer.green {{ border-right-color: var(--green); }}
  .arch-layer.red {{ border-right-color: #c0392b; }}

  .arch-label {{
    font-size: 8.5pt;
    font-weight: 700;
    color: var(--muted);
    letter-spacing: 1px;
    text-transform: uppercase;
    margin-bottom: 3px;
  }}

  .arch-title {{
    font-weight: 700;
    font-size: 11.5pt;
    color: var(--navy);
    margin-bottom: 3px;
  }}

  .arch-desc {{
    font-size: 10pt;
    color: #4a5570;
  }}

  /* ── Module table ────────────────────────────────────────────── */
  .module-table {{
    width: 100%;
    border-collapse: collapse;
    font-size: 10pt;
    margin: 12px 0;
  }}

  .module-table th {{
    background: var(--navy2);
    color: var(--gold2);
    padding: 9px 12px;
    text-align: right;
    font-size: 9.5pt;
  }}

  .module-table td {{
    padding: 9px 12px;
    border-bottom: 1px solid var(--border);
  }}

  .module-table tr:nth-child(even) td {{
    background: var(--light);
  }}

  .badge {{
    display: inline-block;
    padding: 2px 8px;
    border-radius: 12px;
    font-size: 8.5pt;
    font-weight: 700;
  }}

  .badge-green  {{ background: #d4edda; color: #155724; }}
  .badge-blue   {{ background: #d1ecf1; color: #0c5460; }}
  .badge-gold   {{ background: #fff3cd; color: #856404; }}

  /* ── Callout boxes ───────────────────────────────────────────── */
  .callout {{
    border-radius: 8px;
    padding: 14px 18px;
    margin: 14px 0;
    display: flex;
    gap: 12px;
    align-items: flex-start;
  }}

  .callout-info    {{ background: #e8f4fd; border: 1px solid #bee3f8; }}
  .callout-success {{ background: #e8f8ee; border: 1px solid #b2dfdb; }}
  .callout-warn    {{ background: #fff8e1; border: 1px solid #ffe082; }}

  .callout-icon {{ font-size: 20px; flex-shrink: 0; }}

  .callout-text {{ font-size: 10.5pt; line-height: 1.65; }}

  /* ── Footer ──────────────────────────────────────────────────── */
  .footer {{
    text-align: center;
    padding: 32px;
    color: var(--muted);
    font-size: 9pt;
    border-top: 1px solid var(--border);
    margin-top: 48px;
  }}

  .footer-logo {{ font-size: 22px; margin-bottom: 6px; }}

  ul {{ margin: 8px 0 12px 0; padding-right: 20px; }}
  li {{ margin-bottom: 5px; font-size: 10.5pt; }}

  code {{
    background: #f0f3fa;
    border: 1px solid var(--border);
    border-radius: 4px;
    padding: 1px 6px;
    font-size: 9.5pt;
    font-family: 'Courier New', monospace;
    direction: ltr;
    display: inline-block;
  }}
</style>
</head>
<body>

<!-- ══════════════════════════════════════════════
     COVER PAGE
═══════════════════════════════════════════════ -->
<div class="cover">
  {LOGO_TAG}
  <div class="cover-title">STOCK SENTINEL</div>
  <div class="cover-subtitle">Financial Intelligence Platform</div>
  <div class="cover-divider"></div>

  <div class="cover-meta">
    <div class="meta-card">
      <div class="meta-label">גרסה</div>
      <div class="meta-value">v2.0</div>
    </div>
    <div class="meta-card">
      <div class="meta-label">מהנדס ראשי</div>
      <div class="meta-value">Roee</div>
    </div>
    <div class="meta-card">
      <div class="meta-label">תאריך</div>
      <div class="meta-value">{TODAY}</div>
    </div>
  </div>

  <div class="cover-badge">
    דוח טכני מקצועי ומדריך למשתמש — CONFIDENTIAL
  </div>
</div>


<!-- ══════════════════════════════════════════════
     PAGE 2 — TABLE OF CONTENTS + EXECUTIVE SUMMARY
═══════════════════════════════════════════════ -->
<div class="content page-break">

  <!-- Executive Summary -->
  <div class="section-header">
    <span class="section-number">1</span>
    <span class="section-title">סיכום מנהלים</span>
  </div>
  <div class="section-body">
    <p>
      <strong>Stock Sentinel</strong> הוא מערכת בינה פיננסית אוטומטית לניטור שוק המניות האמריקאי בזמן אמת.
      המערכת משלבת ניתוח טכני מתקדם, עיבוד חדשות חיות, וניתוח מאקרו עולמי — הכל בערוץ Telegram
      בעברית ברמה מקצועית. המטרה: לספק לסוחר הפרטי את רמת המידע שנהנו ממנה עד כה רק בנקי השקעות
      ועמדות מסחר מוסדיות.
    </p>

    <div class="stats-grid">
      <div class="stat-card">
        <div class="stat-number">6,600</div>
        <div class="stat-label">שורות קוד (LOC)</div>
      </div>
      <div class="stat-card">
        <div class="stat-number">280</div>
        <div class="stat-label">בדיקות אוטומטיות</div>
      </div>
      <div class="stat-card">
        <div class="stat-number">17</div>
        <div class="stat-label">מודולים עצמאיים</div>
      </div>
      <div class="stat-card">
        <div class="stat-number">24/7</div>
        <div class="stat-label">ניטור רציף</div>
      </div>
    </div>

    <h3>יתרונות מרכזיים</h3>
    <table class="feature-table">
      <tr>
        <th style="width:22%">יתרון</th>
        <th>תיאור</th>
      </tr>
      <tr>
        <td><strong>⚡ מהירות</strong></td>
        <td>מחזור חדשות כל 5 דקות — המערכת מגיבה לאירועי שוק לפני שרוב הסוחרים בכלל שמעו עליהם</td>
      </tr>
      <tr>
        <td><strong>🎯 דיוק</strong></td>
        <td>לוגיקת SMC (Smart Money Concept) עם 7 פרמטרים טכניים: EMA, VWAP, ATR, RSI, Fibonacci, Pivot Points ו-CDL Patterns</td>
      </tr>
      <tr>
        <td><strong>🔍 פוקוס</strong></td>
        <td>סינון קטליסטורים חכם — רק מבזקים בעלי משמעות פיננסית אמיתית עוברים לסוחר</td>
      </tr>
      <tr>
        <td><strong>🌐 נגישות</strong></td>
        <td>תרגום אוטומטי לעברית פיננסית מקצועית בכל התראה — ללא צורך להבין אנגלית</td>
      </tr>
      <tr>
        <td><strong>🛡️ אמינות</strong></td>
        <td>מקורות מבוססי עובדות בלבד: Reuters, CNBC, WSJ, Financial Times, Yahoo Finance</td>
      </tr>
      <tr>
        <td><strong>🤖 אוטומציה</strong></td>
        <td>פועל לגמרי ללא התערבות אנושית — סורק, מנתח, מתרגם ושולח התראות 24/7</td>
      </tr>
    </table>
  </div>


  <!-- ── Section 2: Features ── -->
  <div class="section-header">
    <span class="section-number">2</span>
    <span class="section-title">יכולות המערכת — רשימה מלאה</span>
  </div>
  <div class="section-body">

    <h3>מנועי הניטור</h3>
    <table class="feature-table">
      <tr>
        <th style="width:28%">יכולה</th>
        <th style="width:15%">סטטוס</th>
        <th>פירוט</th>
      </tr>
      <tr>
        <td><strong>📊 ניתוח SMC טכני</strong></td>
        <td><span class="badge badge-green">פעיל</span></td>
        <td>RSI, EMA 9/21/50/200, ATR, VWAP, Bollinger Bands, MACD, Fibonacci 61.8%, Pivot Points R1/R2/S1/S2, CDL Candlestick Patterns, Volume Spike, Golden Cross</td>
      </tr>
      <tr>
        <td><strong>📢 מנוע חדשות 24/7</strong></td>
        <td><span class="badge badge-green">פעיל</span></td>
        <td>סריקת RSS ממקורות מוסמכים בלבד, זיהוי קטליסטורים בפולטר מילות מפתח, ביטול כפילויות, תרגום לעברית, First-Cycle Silence למניעת הצפה בהפעלה</td>
      </tr>
      <tr>
        <td><strong>🏛️ מאקרו רדאר</strong></td>
        <td><span class="badge badge-green">פעיל</span></td>
        <td>זיהוי אירועים כלכליים ופוליטיים עולמיים (Trump, Fed, CPI, Tariff, Trade War), ניתוח סנטימנט Risk-On/Risk-Off, מיפוי לנכסים מושפעים: SPY, QQQ, DIA</td>
      </tr>
      <tr>
        <td><strong>💎 סורק הזדמנויות</strong></td>
        <td><span class="badge badge-green">פעיל</span></td>
        <td>Market Movers Discovery — מזהה מניות חמות שאינן ב-Watchlist, פילטר R:R מינימלי, אישור סנטימנט + כיוון טכני, CoolDown Tracker</td>
      </tr>
      <tr>
        <td><strong>📈 ניטור עסקות חי</strong></td>
        <td><span class="badge badge-green">פעיל</span></td>
        <td>מעקב אחר עסקות פתוחות כל 2 דקות — עדכון TP/SL, זיהוי פקיעת Horizon</td>
      </tr>
      <tr>
        <td><strong>📉 Validator יומי</strong></td>
        <td><span class="badge badge-green">פעיל</span></td>
        <td>בדיקת ביצועים יומית ב-16:30 ET — אחוז הצלחה, ממוצע R:R, תיעוד ב-SQLite</td>
      </tr>
      <tr>
        <td><strong>📋 דוח ביצועים</strong></td>
        <td><span class="badge badge-green">פעיל</span></td>
        <td>שליחת סיכום יומי ב-17:00 ET — Win Rate, סך עסקות, ממוצע רווח</td>
      </tr>
      <tr>
        <td><strong>🌐 תרגום אוטומטי</strong></td>
        <td><span class="badge badge-green">פעיל</span></td>
        <td>deep-translator (GoogleTranslator) — כותרת + סיכום כל מבזק מתורגמים לעברית פיננסית מקצועית לפני השליחה</td>
      </tr>
    </table>

  </div>
</div>


<!-- ══════════════════════════════════════════════
     PAGE 3 — TECHNICAL DEEP DIVE
═══════════════════════════════════════════════ -->
<div class="content page-break">

  <div class="section-header">
    <span class="section-number">3</span>
    <span class="section-title">ארכיטקטורה טכנית מעמיקה</span>
  </div>
  <div class="section-body">

    <h3>שכבות המערכת</h3>

    <div class="arch-layer gold">
      <div class="arch-label">שכבה 1 — רכישת נתונים</div>
      <div class="arch-title">Data Acquisition Layer</div>
      <div class="arch-desc">
        <strong>scraper.py</strong> — Playwright browser automation לסריקת x.com/Twitter Sentiment Score בזמן אמת.
        <strong>news_scraper.py</strong> — yfinance News API לכותרות חדשות לפי טיקר.
        <strong>rss_provider.py</strong> — feedparser לסריקת RSS ממקורות רוטרס, CNBC, Yahoo, WSJ, FT.
        <strong>scanner.py</strong> — Market Movers Discovery דרך yfinance Gainers/Losers/Active.
      </div>
    </div>

    <div class="arch-layer">
      <div class="arch-label">שכבה 2 — עיבוד ואנליזה</div>
      <div class="arch-title">Processing & Analysis Layer</div>
      <div class="arch-desc">
        <strong>analyzer.py</strong> — 552 שורות לוגיקת SMC מלאה. חישוב 20+ אינדיקטורים על OHLCV.
        <strong>news_engine.py</strong> — 556 שורות מנוע קטליסטורים. סינון מילות מפתח, polarization check,
        warm-up silence, macro radar, ו-dedup seen-set.
        <strong>signal_filter.py</strong> — שקלול combined_sentiment_score() משלושה ערוצים:
        Twitter (40%) + News (35%) + RSS (25%). בדיקת should_alert() + Cooldown.
        <strong>translator.py</strong> — עטיפה ל-deep-translator עם fallback שקט על כשל רשת.
      </div>
    </div>

    <div class="arch-layer green">
      <div class="arch-label">שכבה 3 — פעולה ותקשורת</div>
      <div class="arch-title">Action & Notification Layer</div>
      <div class="arch-desc">
        <strong>notifier.py</strong> — 488 שורות. בניית 4 סוגי הודעות Telegram עם Markdown עשיר.
        <strong>visualizer.py</strong> — matplotlib — יצירת chart_path עם ציר מחיר, EMA, VWAP, Volume.
        <strong>monitor.py</strong> — מעקב עסקות פתוחות. הגעה ל-TP1/TP2/TP3 או SL triggers.
        <strong>db.py</strong> — SQLite persistence: log_alert(), get_daily_stats(), trade lifecycle.
      </div>
    </div>

    <div class="arch-layer red">
      <div class="arch-label">שכבה 4 — תזמון ובקרה</div>
      <div class="arch-title">Orchestration Layer</div>
      <div class="arch-desc">
        <strong>scheduler.py</strong> — APScheduler BlockingScheduler עם CronTrigger + IntervalTrigger.
        כל job רץ ב-asyncio.run() מבודד — Circuit Breaker מובנה לניטור כשלי scraper.
        <strong>validator.py</strong> — בדיקות תקינות יומיות post-market.
        <strong>config.py</strong> — ניהול מרכזי של secrets, watchlist, וכל הפרמטרים.
      </div>
    </div>

    <h3>ארכיטקטורת Async</h3>
    <p>
      המערכת בנויה על <strong>Python asyncio</strong> מלא. כל פעולת I/O ממתינה בלי לחסום את ה-event loop:
    </p>
    <ul>
      <li><code>await scrape_sentiment()</code> — Playwright async בדפדפן</li>
      <li><code>await asyncio.to_thread(_translate_to_hebrew, text)</code> — blocking HTTP לתרגום ב-thread pool</li>
      <li><code>await send_alert()</code> — httpx async לשליחת Telegram</li>
      <li><code>asyncio.run()</code> בכל APScheduler job — בידוד מלא בין מחזורים</li>
    </ul>

    <h3>Circuit Breaker</h3>
    <div class="callout callout-warn">
      <span class="callout-icon">⚠️</span>
      <div class="callout-text">
        אם scraper נכשל N פעמים רצוף (ברירת מחדל: 3), ה-Circuit Breaker נפתח ומדלג על שאר
        הטיקרים במחזור הנוכחי. התראת SYSTEM נשלחת לטלגרם. במחזור הבא — ה-Circuit מתאפס אוטומטית.
      </div>
    </div>

    <h3>First-Cycle Silence (Anti-Flood)</h3>
    <div class="callout callout-success">
      <span class="callout-icon">✅</span>
      <div class="callout-text">
        בהפעלה ראשונה של מנוע החדשות, כל הפריטים הקיימים מסומנים כ"נראו" (dedup set priming)
        <em>ללא שליחת התראות</em>. רק מהמחזור השני ואילך נשלחות התראות על פריטים חדשים בלבד.
        מונע הצפה של 20+ הודעות בהפעלה.
      </div>
    </div>

    <h3>מפת המודולים וגודלם</h3>
    <table class="module-table">
      <tr>
        <th>מודול</th>
        <th>LOC</th>
        <th>תפקיד עיקרי</th>
        <th>סוג</th>
      </tr>
      <tr><td><code>news_engine.py</code></td><td>556</td><td>מנוע קטליסטורים + מאקרו + תרגום</td><td><span class="badge badge-gold">Core</span></td></tr>
      <tr><td><code>analyzer.py</code></td><td>552</td><td>SMC Technical Analysis</td><td><span class="badge badge-gold">Core</span></td></tr>
      <tr><td><code>notifier.py</code></td><td>488</td><td>Telegram message builders + senders</td><td><span class="badge badge-gold">Core</span></td></tr>
      <tr><td><code>scheduler.py</code></td><td>444</td><td>APScheduler orchestration</td><td><span class="badge badge-gold">Core</span></td></tr>
      <tr><td><code>scanner.py</code></td><td>207</td><td>Market Movers Discovery</td><td><span class="badge badge-blue">Service</span></td></tr>
      <tr><td><code>db.py</code></td><td>197</td><td>SQLite persistence</td><td><span class="badge badge-blue">Service</span></td></tr>
      <tr><td><code>models.py</code></td><td>166</td><td>Dataclasses: Alert, NewsFlash, MacroFlash…</td><td><span class="badge badge-blue">Service</span></td></tr>
      <tr><td><code>visualizer.py</code></td><td>119</td><td>matplotlib chart generator</td><td><span class="badge badge-blue">Service</span></td></tr>
      <tr><td><code>monitor.py</code></td><td>114</td><td>Live trade tracker</td><td><span class="badge badge-blue">Service</span></td></tr>
      <tr><td><code>validator.py</code></td><td>111</td><td>Daily performance validator</td><td><span class="badge badge-blue">Service</span></td></tr>
      <tr><td><code>config.py</code></td><td>96</td><td>Configuration &amp; secrets</td><td><span class="badge badge-green">Config</span></td></tr>
      <tr><td><code>translator.py</code></td><td>94</td><td>Hebrew translation wrapper</td><td><span class="badge badge-green">Config</span></td></tr>
      <tr><td><code>signal_filter.py</code></td><td>78</td><td>Sentiment scoring + alerting gate</td><td><span class="badge badge-blue">Service</span></td></tr>
      <tr><td><code>scraper.py</code></td><td>69</td><td>Playwright Twitter/X scraper</td><td><span class="badge badge-blue">Service</span></td></tr>
      <tr><td><code>rss_provider.py</code></td><td>53</td><td>RSS feed parser</td><td><span class="badge badge-blue">Service</span></td></tr>
      <tr><td><code>news_scraper.py</code></td><td>44</td><td>yfinance News API</td><td><span class="badge badge-blue">Service</span></td></tr>
      <tr><td style="font-weight:700">סה"כ</td><td style="font-weight:700">3,388</td><td colspan="2">+ 3,212 שורות בדיקות = <strong>6,600 שורות כולל</strong></td></tr>
    </table>

  </div>
</div>


<!-- ══════════════════════════════════════════════
     PAGE 4 — USER MANUAL
═══════════════════════════════════════════════ -->
<div class="content page-break">

  <div class="section-header">
    <span class="section-number">4</span>
    <span class="section-title">מדריך למשתמש — כל סוגי ההתראות</span>
  </div>
  <div class="section-body">

    <p>
      כל ההתראות נשלחות לערוץ Telegram שהגדרת. להלן פירוט מלא של כל סוג התראה, מה הוא אומר, ואיך לקרוא אותו.
    </p>

    <div class="alert-grid">

      <!-- News Flash -->
      <div class="alert-card alert-news">
        <div class="alert-card-header">📢 מבזק חדשות מתפרצות</div>
        <div class="alert-card-body">
          <strong>מה זה?</strong><br/>
          חדשות שוברות הקשורות ישירות לאחת ממניות ה-Watchlist שלך (NVDA, AMZN וכו').<br/><br/>
          <strong>מבנה ההתראה:</strong><br/>
          📢 מבזק חדשות — NVDA<br/>
          💡 <em>כותרת:</em> [כותרת מתורגמת]<br/>
          📝 <em>סיכום:</em> [ניתוח מתורגם]<br/>
          🔗 קישור למקור<br/>
          ⏰ שעת פרסום UTC<br/><br/>
          <strong>מה לעשות?</strong><br/>
          בדוק את ה-SMC Signal האחרון על הטיקר הזה. אם הכיוון תואם — שקול כניסה.
        </div>
      </div>

      <!-- Macro Flash -->
      <div class="alert-card alert-macro">
        <div class="alert-card-header">🏛️ אירוע מאקרו משמעותי</div>
        <div class="alert-card-body">
          <strong>מה זה?</strong><br/>
          אירוע כלכלי/פוליטי עולמי שמשפיע על השוק הרחב — לא על מניה ספציפית.<br/><br/>
          <strong>דוגמאות למקורות:</strong><br/>
          ✦ הכרזת Fed / Powell על ריבית<br/>
          ✦ נתוני CPI / Inflation<br/>
          ✦ Tariffs / Trade War (Trump)<br/>
          ✦ גאו-פוליטיקה חמה<br/><br/>
          <strong>מבנה ההתראה:</strong><br/>
          📈/📉 סנטימנט (Risk-On/Risk-Off)<br/>
          📊 נכסים: SPY, QQQ, DIA<br/><br/>
          <strong>מה לעשות?</strong><br/>
          📈 Risk-On = חיובי למניות בכלל<br/>
          📉 Risk-Off = לחפש SHORT או לצאת לנזילות
        </div>
      </div>

      <!-- Discovery -->
      <div class="alert-card alert-disc">
        <div class="alert-card-header">💎 גילוי הזדמנות</div>
        <div class="alert-card-body">
          <strong>מה זה?</strong><br/>
          מניות חמות שזוהו מחוץ ל-Watchlist הרגיל. הסורק האוטונומי מצא ניע חריג + אישור SMC.<br/><br/>
          <strong>קריטריוני כניסה:</strong><br/>
          ✦ Volume Spike חריג<br/>
          ✦ R:R מינימלי עמד בסף<br/>
          ✦ סנטימנט + כיוון תואמים<br/>
          ✦ לא בסיס CoolDown<br/><br/>
          <strong>מה לעשות?</strong><br/>
          זו הזדמנות ספקולטיבית — גודל פוזיציה קטן יותר. בדוק Volume ו-Float לפני כניסה.
        </div>
      </div>

      <!-- SMC Signal -->
      <div class="alert-card alert-smc">
        <div class="alert-card-header">📊 אות SMC (סיגנל Watchlist)</div>
        <div class="alert-card-body">
          <strong>מה זה?</strong><br/>
          ה-Alert המלא — ניתוח SMC מקיף על מניה מה-Watchlist שלך.<br/><br/>
          <strong>מה כלול:</strong><br/>
          ✦ כיוון: LONG / SHORT<br/>
          ✦ Entry, Stop Loss, TP1, TP2, TP3<br/>
          ✦ RSI, VWAP, Fibonacci 61.8%<br/>
          ✦ Pivot R1/R2/S1/S2<br/>
          ✦ Institutional Score (1–10)<br/>
          ✦ גרף טכני מצורף<br/><br/>
          <strong>מה לעשות?</strong><br/>
          ✦ Institutional Score ≥ 7 → כניסה מלאה<br/>
          ✦ 5–6 → כניסה חצי<br/>
          ✦ &lt; 5 → רק עקוב, אל תיכנס
        </div>
      </div>

    </div>

    <h3>פרשנות ה-Institutional Score</h3>
    <table class="feature-table">
      <tr>
        <th style="width:18%">ציון</th>
        <th style="width:25%">דירוג</th>
        <th>משמעות ופעולה מומלצת</th>
      </tr>
      <tr>
        <td><strong>8.0 – 10.0</strong></td>
        <td><span class="badge badge-green">⭐ Elite</span></td>
        <td>כל האינדיקטורים מסכימים. כניסה מלאה עם Stop Loss מוגדר. אות מוסדי חזק מאוד.</td>
      </tr>
      <tr>
        <td><strong>6.5 – 7.9</strong></td>
        <td><span class="badge badge-blue">✅ Strong</span></td>
        <td>רוב האינדיקטורים תומכים. כניסה בגודל בינוני. ניהול סיכון קפדני.</td>
      </tr>
      <tr>
        <td><strong>5.0 – 6.4</strong></td>
        <td><span class="badge badge-gold">⚠️ Moderate</span></td>
        <td>אות מעורב. כניסה קטנה בלבד, או המתן לאישור נוסף.</td>
      </tr>
      <tr>
        <td><strong>1.0 – 4.9</strong></td>
        <td>❌ Weak</td>
        <td>אות חלש. לא להיכנס. המערכת בדרך כלל לא תשלח אות בטווח זה.</td>
      </tr>
    </table>

  </div>
</div>


<!-- ══════════════════════════════════════════════
     PAGE 5 — SCHEDULE + SETUP
═══════════════════════════════════════════════ -->
<div class="content page-break">

  <div class="section-header">
    <span class="section-number">5</span>
    <span class="section-title">לוח הזמנים המלא — מה קורה מתי?</span>
  </div>
  <div class="section-body">

    <div class="callout callout-info">
      <span class="callout-icon">🕐</span>
      <div class="callout-text">
        כל השעות בזמן <strong>ET (Eastern Time)</strong> — New York.
        בשעון ישראל: ET + 7 שעות (בחורף), ET + 6 שעות (בקיץ).
      </div>
    </div>

    <div class="timeline">

      <div class="timeline-item">
        <div class="timeline-time">00:00 — 23:59 ET | כל 5 דקות</div>
        <div class="timeline-title">📢 מנוע חדשות + 🏛️ מאקרו רדאר</div>
        <div class="timeline-desc">
          פעיל 24/7 — ללא הגבלת שעות מסחר. סורק RSS ממקורות אמינים.
          מסנן קטליסטורים ואירועי מאקרו. שולח מבזקים מתורגמים לעברית.
        </div>
      </div>

      <div class="timeline-item">
        <div class="timeline-time">09:00 — 15:45 ET | כל 15 דקות</div>
        <div class="timeline-title">📊 מנוע SMC Watchlist</div>
        <div class="timeline-desc">
          ניטור מלא של NVDA, AMZN, SOFI, OKLO, RKLB, FLNC, ANXI, AXTI.
          בכל מחזור: Scrape Twitter → News → RSS → Technical Analysis → Alert Gate.
          שולח אות SMC מלא כולל גרף אם כל התנאים מתקיימים.
        </div>
      </div>

      <div class="timeline-item">
        <div class="timeline-time">09:30 — 16:00 ET | כל 2 דקות</div>
        <div class="timeline-title">📈 ניטור עסקות חי</div>
        <div class="timeline-desc">
          בודק את כל העסקות הפתוחות: האם הגענו ל-TP1, TP2, TP3? האם פוגשים Stop Loss?
          שולח עדכון Telegram ברגע הנוגע בכל רמה.
        </div>
      </div>

      <div class="timeline-item">
        <div class="timeline-time">09:00 — 15:45 ET | כל 15 דקות</div>
        <div class="timeline-title">💎 סורק הזדמנויות</div>
        <div class="timeline-desc">
          Market Movers Discovery — סורק Gainers, Losers, Most Active.
          מריץ ניתוח SMC מלא על כל מניה חמה. שולח Discovery Alert אם עמדה בכל הקריטריונים.
        </div>
      </div>

      <div class="timeline-item">
        <div class="timeline-time">16:30 ET | פעם ביום</div>
        <div class="timeline-title">🔍 Validator יומי (Post-Market)</div>
        <div class="timeline-desc">
          בדיקת ביצועי כל האותות שנשלחו היום. מעדכן DB עם תוצאות בפועל.
          מחשב Win Rate יומי ו-Average R:R.
        </div>
      </div>

      <div class="timeline-item">
        <div class="timeline-time">17:00 ET | פעם ביום</div>
        <div class="timeline-title">📋 דוח ביצועים יומי</div>
        <div class="timeline-desc">
          שליחת סיכום יום המסחר לטלגרם: כמה אותות נשלחו, כמה הצליחו,
          Win Rate, ממוצע R:R, הטיקרים הבולטים.
        </div>
      </div>

    </div>

  </div>


  <!-- Section 6: Setup -->
  <div class="section-header">
    <span class="section-number">6</span>
    <span class="section-title">הגדרה ראשונית — Onboarding למשתמש חדש</span>
  </div>
  <div class="section-body">

    <h3>דרישות מוקדמות</h3>
    <ul>
      <li>Python 3.11+</li>
      <li>חשבון Telegram + Bot Token (<code>@BotFather</code>)</li>
      <li>חשבון X (Twitter) לצורך scraping (cookies נשמרים אוטומטית)</li>
      <li>Windows 10/11 או Linux/macOS עם גישה לאינטרנט</li>
    </ul>

    <h3>צעדי הגדרה</h3>

    <h4>שלב 1 — התקנה</h4>
    <p>
      <code>pip install -r requirements.txt</code><br/>
      <code>playwright install chromium</code>
    </p>

    <h4>שלב 2 — הגדרת סודות</h4>
    <p>
      צור קובץ <code>.env</code> בתיקיית הפרויקט עם:
    </p>
    <ul>
      <li><code>TELEGRAM_BOT_TOKEN=...</code> — ה-token שקיבלת מ-BotFather</li>
      <li><code>TELEGRAM_CHAT_ID=...</code> — ה-Chat ID של הערוץ/קבוצה שלך</li>
    </ul>

    <h4>שלב 3 — התאמת Watchlist</h4>
    <p>
      פתח <code>stock_sentinel/config.py</code> ועדכן את רשימת <code>WATCHLIST</code>
      עם הטיקרים שאתה רוצה לעקוב אחריהם.
    </p>

    <h4>שלב 4 — הפעלה</h4>
    <p>
      <code>python -m stock_sentinel.scheduler</code><br/>
      המערכת תתחיל לפעול אוטומטית. מחזור החדשות הראשון יופעל מיידית.
    </p>

    <div class="callout callout-success">
      <span class="callout-icon">✅</span>
      <div class="callout-text">
        <strong>First-Cycle Silence:</strong> ב-5 הדקות הראשונות המערכת "לומדת" את הסביבה ללא שליחת
        התראות. החל מהמחזור השני — מבזקים אמיתיים בלבד.
      </div>
    </div>

  </div>
</div>


<!-- ══════════════════════════════════════════════
     PAGE 6 — QA & RELIABILITY
═══════════════════════════════════════════════ -->
<div class="content page-break">

  <div class="section-header">
    <span class="section-number">7</span>
    <span class="section-title">איכות ואמינות — תשתית הבדיקות</span>
  </div>
  <div class="section-body">

    <div class="stats-grid">
      <div class="stat-card">
        <div class="stat-number">280</div>
        <div class="stat-label">בדיקות עוברות</div>
      </div>
      <div class="stat-card">
        <div class="stat-number">0</div>
        <div class="stat-label">כשלים</div>
      </div>
      <div class="stat-card">
        <div class="stat-number">15</div>
        <div class="stat-label">קבצי Test</div>
      </div>
      <div class="stat-card">
        <div class="stat-number">100%</div>
        <div class="stat-label">Pass Rate</div>
      </div>
    </div>

    <h3>כיסוי הבדיקות</h3>
    <table class="feature-table">
      <tr>
        <th style="width:35%">קובץ בדיקה</th>
        <th style="width:15%">בדיקות</th>
        <th>מה נבדק</th>
      </tr>
      <tr><td><code>test_news_engine.py</code></td><td>~65</td><td>קטליסטורים, מאקרו, dedup, warm-up, תרגום fallback, polarization</td></tr>
      <tr><td><code>test_notifier.py</code></td><td>~60</td><td>כל סוגי הודעות Telegram, RTL, Hebrew content, URL embedding</td></tr>
      <tr><td><code>test_analyzer.py</code></td><td>~35</td><td>חישובי SMC, EMA, VWAP, ATR, direction logic, TechnicalScore</td></tr>
      <tr><td><code>test_signal_filter.py</code></td><td>~20</td><td>sentiment weighting, should_alert gate, cooldown logic</td></tr>
      <tr><td><code>test_scanner.py</code></td><td>~20</td><td>Market Movers, CoolDown tracker, R:R gate</td></tr>
      <tr><td><code>test_scheduler.py</code></td><td>~15</td><td>async cycle isolation, circuit breaker, job wiring</td></tr>
      <tr><td><code>test_models.py</code></td><td>~12</td><td>Dataclass validation, defaults, Alert/NewsFlash/MacroFlash</td></tr>
      <tr><td><code>test_db.py</code></td><td>~12</td><td>SQLite write/read, daily stats, alert logging</td></tr>
      <tr><td><code>test_monitor.py</code></td><td>~10</td><td>Trade lifecycle, TP/SL triggers, horizon expiry</td></tr>
      <tr><td><code>test_validator.py</code></td><td>~10</td><td>Post-market validation, win rate calculation</td></tr>
      <tr><td>שאר הקבצים</td><td>~21</td><td>scraper, rss_provider, news_scraper, translator</td></tr>
    </table>

    <h3>עקרונות הבדיקות</h3>
    <ul>
      <li><strong>TDD (Test-Driven Development)</strong> — כל פיצ'ר נכתב תחילה כבדיקה כושלת, ואז הקוד</li>
      <li><strong>Mock Isolation</strong> — קריאות רשת (Telegram, Twitter, RSS) מוחלפות ב-AsyncMock</li>
      <li><strong>Translation Bypass</strong> — <code>_translate_to_hebrew</code> מוחלף ב-identity function בכל בדיקות ה-news_engine</li>
      <li><strong>Async Testing</strong> — pytest-asyncio עם <code>@pytest.mark.asyncio</code> לכל פונקציה async</li>
      <li><strong>Fixture Reuse</strong> — helper functions כמו <code>_flash()</code>, <code>_warmed_state()</code>, <code>_make_df()</code> מבטיחים consistency</li>
    </ul>

  </div>


  <!-- Section 8: Sources -->
  <div class="section-header">
    <span class="section-number">8</span>
    <span class="section-title">מקורות המידע המוסמכים</span>
  </div>
  <div class="section-body">

    <div class="callout callout-info">
      <span class="callout-icon">📡</span>
      <div class="callout-text">
        <strong>מדיניות Zero Aggregators:</strong> המערכת מחוברת <em>רק</em> למקורות עם Wire News ישיר.
        אגרגטורים כגון MarketBeat, Motley Fool, Simply Wall St — מוסרו מהמקורות המוזנים.
      </div>
    </div>

    <table class="feature-table">
      <tr>
        <th style="width:25%">מקור</th>
        <th style="width:35%">פיד RSS</th>
        <th>תיאור</th>
      </tr>
      <tr>
        <td><strong>Reuters</strong></td>
        <td><code>feeds.reuters.com/businessNews</code></td>
        <td>סוכנות ידיעות בינלאומית — חדשות עסקים וכלכלה ראשוניות</td>
      </tr>
      <tr>
        <td><strong>CNBC</strong></td>
        <td><code>cnbc.com/id/100003114/rss</code></td>
        <td>ערוץ הפיננסים המוביל בארה"ב — כיסוי שוק בזמן אמת</td>
      </tr>
      <tr>
        <td><strong>Yahoo Finance</strong></td>
        <td><code>finance.yahoo.com/rss/topfinstories</code></td>
        <td>Wire ראשי בלבד — חדשות שוק ב-volume גבוה</td>
      </tr>
      <tr>
        <td><strong>Wall Street Journal</strong></td>
        <td><code>feeds.a.dj.com/RSSMarketsMain.xml</code></td>
        <td>כיסוי שוקי ההון המעמיק ביותר — Dow Jones Markets</td>
      </tr>
      <tr>
        <td><strong>Financial Times</strong></td>
        <td><code>ft.com/rss/home/us</code></td>
        <td>נקודת מבט גלובלית — שוקי US ב-FT</td>
      </tr>
    </table>

  </div>
</div>


<!-- ══════════════════════════════════════════════
     FOOTER
═══════════════════════════════════════════════ -->
<div class="footer">
  <div class="footer-logo">🦅</div>
  <strong>Stock Sentinel Financial Intelligence</strong><br/>
  גרסה v2.0 &nbsp;|&nbsp; מהנדס ראשי: Roee &nbsp;|&nbsp; {TODAY}<br/>
  <em>מסמך זה חסוי ומיועד לשימוש פנימי בלבד</em>
</div>

</body>
</html>"""

# ── Write HTML for Playwright rendering ──────────────────────────────────────
if __name__ == "__main__":
    import asyncio

    HTML_TMP = Path(__file__).parent / "_report_tmp.html"
    PDF_OUT  = Path(__file__).parent / "Stock_Sentinel_Full_Specs_Roee.pdf"

    HTML_TMP.write_text(HTML, encoding="utf-8")
    print("HTML written to temp file")

    async def _render():
        from playwright.async_api import async_playwright
        async with async_playwright() as p:
            browser = await p.chromium.launch()
            page    = await browser.new_page()
            await page.goto(f"file:///{HTML_TMP.as_posix()}")
            await page.wait_for_load_state("networkidle")
            await page.pdf(
                path=str(PDF_OUT),
                format="A4",
                print_background=True,
                margin={"top": "0mm", "bottom": "0mm", "left": "0mm", "right": "0mm"},
            )
            await browser.close()

    asyncio.run(_render())
    HTML_TMP.unlink(missing_ok=True)
    print(f"PDF saved: {PDF_OUT}")
    print(f"Size: {PDF_OUT.stat().st_size / 1024:.0f} KB")
