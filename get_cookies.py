import asyncio
import json
import os
from playwright.async_api import async_playwright

async def save_session():
    async with async_playwright() as pw:
        # פותח דפדפן אמיתי שתוכל לראות
        browser = await pw.chromium.launch(headless=False)
        context = await browser.new_context()
        page = await context.new_page()
        
        print("נא להיכנס לטוויטר ולהתחבר לחשבון החדש...")
        await page.goto('https://x.com/login')
        
        # הסקריפט יחכה כאן עד שתלחץ Enter בטרמינל
        input("אחרי שהתחברת ואתה רואה את ה-Feed, תחזור לכאן ותלחץ Enter...")
        
        # יצירת התיקייה ושמירת הקוקיז
        os.makedirs('session', exist_ok=True)
        cookies = await context.cookies()
        with open('session/x_cookies.json', 'w') as f:
            json.dump(cookies, f)
            
        print(f"הצלחנו! נשמרו {len(cookies)} קוקיז לקובץ session/x_cookies.json")
        await browser.close()

if __name__ == "__main__":
    asyncio.run(save_session())