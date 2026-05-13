import json
import os
import re
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError


load_dotenv()

URL = os.getenv("HOHAI_URL", "https://tv.hohai.eu.org/dashboard")
USERNAME = os.getenv("HOHAI_USERNAME")
PASSWORD = os.getenv("HOHAI_PASSWORD")
HEADLESS = os.getenv("HEADLESS", "true").lower() == "true"

if not USERNAME or not PASSWORD:
    raise SystemExit("Missing HOHAI_USERNAME or HOHAI_PASSWORD")

artifacts = Path("artifacts")
artifacts.mkdir(parents=True, exist_ok=True)
ts = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")

result = {
    "time": datetime.utcnow().isoformat() + "Z",
    "url": URL,
    "status": "unknown",
    "signed_today": False,
    "balance": None,
    "note": "",
    "screenshot": None,
}


def save_result_and_exit(code: int = 0):
    result_path = artifacts / f"result-{ts}.json"
    result_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(code)


def detect_balance(text: str):
    for line in text.splitlines():
        line = line.strip()
        if re.search(r"余额|balance", line, re.IGNORECASE):
            return line
    return None


with sync_playwright() as p:
    browser = p.chromium.launch(headless=HEADLESS, args=["--disable-blink-features=AutomationControlled"])
    context = browser.new_context(viewport={"width": 1366, "height": 900})
    page = context.new_page()

    try:
        page.goto(URL, wait_until="domcontentloaded", timeout=60_000)

        # login if form exists
        user_input = page.locator('input[name="email"], input[name="username"], input[type="text"]').first
        pass_input = page.locator('input[type="password"]').first
        if user_input.count() > 0 and pass_input.count() > 0:
            user_input.fill(USERNAME)
            pass_input.fill(PASSWORD)
            submit = page.locator('button:has-text("登录"), button:has-text("Sign in"), button:has-text("Login"), button[type="submit"]').first
            submit.click()
            page.wait_for_load_state("networkidle")

        signed_text_a = page.get_by_text("今日已签到")
        signed_text_b = page.get_by_text("签到完成")
        sign_btn = page.locator('button:has-text("签到")').first
        sign_text = page.get_by_text("签到").first

        already_signed_now = signed_text_a.count() > 0 or signed_text_b.count() > 0

        if already_signed_now:
            result["status"] = "already_signed"
            result["signed_today"] = True
        elif sign_btn.count() > 0 or sign_text.count() > 0:
            if sign_btn.count() > 0:
                sign_btn.click()
            else:
                sign_text.click()
            page.wait_for_timeout(1500)

            # Best-effort Cloudflare turnstile click.
            # NOTE: GitHub Actions IP may trigger harder challenge; then manual solve is required.
            cf_clicked = False
            for frame in page.frames:
                if re.search(r"cloudflare|turnstile", frame.url, re.IGNORECASE):
                    checkbox = frame.locator('input[type="checkbox"], div[role="checkbox"], label').first
                    if checkbox.count() > 0:
                        try:
                            checkbox.click(timeout=5000)
                            cf_clicked = True
                            break
                        except PlaywrightTimeoutError:
                            pass

            page.wait_for_timeout(3000)

            already_signed_after = signed_text_a.count() > 0 or signed_text_b.count() > 0
            if already_signed_after:
                result["status"] = "checked_in_now"
                result["signed_today"] = True
                if cf_clicked:
                    result["note"] = "Turnstile checkbox clicked (best effort)."
            else:
                result["status"] = "checkin_uncertain"
                result["note"] = "Sign clicked, but success text not found. Likely blocked by Cloudflare challenge."
        else:
            result["status"] = "sign_button_not_found"
            result["note"] = "Sign button/card not found. UI may have changed."

        page_text = page.locator("body").inner_text()
        result["balance"] = detect_balance(page_text)

        shot = artifacts / f"checkin-{ts}.png"
        page.screenshot(path=str(shot), full_page=True)
        result["screenshot"] = str(shot)

        if result["signed_today"]:
            save_result_and_exit(0)
        else:
            save_result_and_exit(2)

    except Exception as e:
        result["status"] = "failed"
        result["note"] = str(e)
        try:
            shot = artifacts / f"error-{ts}.png"
            page.screenshot(path=str(shot), full_page=True)
            result["screenshot"] = str(shot)
        except Exception:
            pass
        save_result_and_exit(1)
    finally:
        context.close()
        browser.close()
