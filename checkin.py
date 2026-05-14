import json
import os
import re
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

from dotenv import load_dotenv
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError


load_dotenv()

LOGIN_URL = "https://tv.hohai.eu.org/login"
USERNAME = os.getenv("HOHAI_UN")
PASSWORD = os.getenv("HOHAI_PW")
HEADLESS = os.getenv("HEADLESS", "true").lower() == "true"
TG_BOT_TOKEN = os.getenv("HOHAI_TGTK")
TG_CHAT_ID = os.getenv("HOHAI_TGID")
SOCKS5_PROXY = os.getenv("SOCKS5_PROXY")

if not USERNAME or not PASSWORD:
    raise SystemExit("Missing HOHAI_UN or HOHAI_PW")

artifacts = Path("artifacts")
artifacts.mkdir(parents=True, exist_ok=True)
CN_TZ = timezone(timedelta(hours=8))
now_cn = datetime.now(CN_TZ)
ts = now_cn.strftime("%Y%m%dT%H%M%S%z")

result = {
    "time": now_cn.isoformat(),
    "url": LOGIN_URL,
    "status": "unknown",
    "signed_today": False,
    "balance": None,
    "note": "",
    "debug_hints": [],
}


def log_step(message: str):
    now = datetime.now(CN_TZ).strftime("%Y-%m-%d %H:%M:%S%z")
    print(f"[{now}] {message}")


def send_telegram_notification(payload: dict):
    if not TG_BOT_TOKEN or not TG_CHAT_ID:
        return

    status_map = {
        "already_signed": "今日已签到",
        "checked_in_now": "本次签到成功",
        "checkin_uncertain": "签到结果不确定",
        "sign_button_not_found": "未找到签到入口",
        "failed": "执行失败",
    }
    signed_text = "是" if payload.get("signed_today") else "否"
    status_text = status_map.get(payload.get("status"), str(payload.get("status")))
    icon = "🟢" if payload.get("signed_today") else "🔴"

    text = (
        f"{icon} Hohai 自动签到通知\n"
        f"📌 状态：{status_text}\n"
        f"🗓️ 今日是否已签到：{signed_text}\n"
        f"💰 账户余额：{payload.get('balance') or '未识别'}\n"
        f"📝 备注：{payload.get('note') or '无'}\n"
        f"⏰ 时间：{payload.get('time')}"
    )

    data = {
        "chat_id": TG_CHAT_ID,
        "text": text,
        "disable_web_page_preview": "true",
    }
    body = urllib.parse.urlencode(data).encode("utf-8")
    req = urllib.request.Request(
        url=f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMessage",
        data=body,
        method="POST",
    )
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    try:
        with urllib.request.urlopen(req, timeout=15):
            pass
    except Exception as e:
        print(f"[warn] telegram notify failed: {e}")


def save_result_and_exit(code: int = 0):
    result_path = artifacts / f"result-{ts}.json"
    result_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    send_telegram_notification(result)
    raise SystemExit(code)


def detect_balance(text: str):
    for line in text.splitlines():
        line = line.strip()
        if re.search(r"余额|balance", line, re.IGNORECASE):
            return line
    return None


with sync_playwright() as p:
    launch_kwargs = {
        "headless": HEADLESS,
        "args": ["--disable-blink-features=AutomationControlled"],
    }
    log_step("启动浏览器")
    if SOCKS5_PROXY:
        launch_kwargs["proxy"] = {"server": SOCKS5_PROXY}

    browser = p.chromium.launch(**launch_kwargs)
    context = browser.new_context(viewport={"width": 1366, "height": 900})
    page = context.new_page()

    try:
        # 1) go login page first
        log_step(f"正在访问 {LOGIN_URL}…")
        page.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=60_000)

        # 2) login
        log_step("正在执行登录")
        user_inputs = page.locator('input[name="email"], input[name="username"], input[type="text"], input[placeholder*="用户"], input[placeholder*="账号"], input[placeholder*="邮箱"], input[id*="user" i], input[id*="email" i]')
        pass_inputs = page.locator('input[type="password"], input[placeholder*="密码"], input[id*="pass" i]')

        if user_inputs.count() > 0 and pass_inputs.count() > 0:
            user_input = user_inputs.first
            pass_input = pass_inputs.first
            user_input.fill(USERNAME)
            pass_input.fill(PASSWORD)
            submit = page.locator('button:has-text("登录"), button:has-text("Sign in"), button:has-text("Login"), button[type="submit"], [role="button"]:has-text("登录")').first
            submit.click()
            page.wait_for_timeout(2000)
            page.wait_for_load_state("networkidle")
            log_step("登录流程已提交，等待页面跳转")
        else:
            result["debug_hints"].append("登录页未识别到用户名/密码输入框，可能已处于登录态")
            log_step("未识别到登录输入框，按已登录态继续")

        # 3) wait redirect after login (site should auto-jump to dashboard)
        page.wait_for_load_state("networkidle")
        if page.locator('input[type="password"]').count() > 0:
            log_step("登录失败或仍在登录页")
        else:
            log_step("登录成功（已离开密码输入页）")

        signed_text_a = page.get_by_text("今日已签到")
        signed_text_b = page.get_by_text("签到完成")

        def find_sign_target():
            candidates = [
                page.locator('button:has-text("签到")').first,
                page.locator('[role="button"]:has-text("签到")').first,
                page.locator('div:has-text("签到")').first,
                page.locator('span:has-text("签到")').first,
                page.get_by_text("签到").first,
            ]
            for loc in candidates:
                if loc.count() > 0:
                    return loc
            return None

        sign_target = None
        for _ in range(8):
            already_signed_now = signed_text_a.count() > 0 or signed_text_b.count() > 0
            if already_signed_now:
                break
            sign_target = find_sign_target()
            if sign_target is not None:
                break
            page.wait_for_timeout(2500)

        already_signed_now = signed_text_a.count() > 0 or signed_text_b.count() > 0

        if already_signed_now:
            log_step("检测到今日已签到")
            result["status"] = "already_signed"
            result["signed_today"] = True
        elif sign_target is not None:
            log_step("检测到签到入口，开始点击签到")
            sign_target.click()
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
                log_step("签到成功")
                result["status"] = "checked_in_now"
                result["signed_today"] = True
                if cf_clicked:
                    result["note"] = "Turnstile checkbox clicked (best effort)."
            else:
                log_step("签到结果不确定（未检测到成功文案）")
                result["status"] = "checkin_uncertain"
                result["note"] = "Sign clicked, but success text not found. Likely blocked by Cloudflare challenge."
        else:
            log_step("未找到签到入口")
            result["status"] = "sign_button_not_found"
            result["note"] = "Sign button/card not found. UI may have changed."
            if page.locator('input[type="password"]').count() > 0:
                result["debug_hints"].append("当前页面疑似仍在登录页")
            if any(re.search(r"cloudflare|turnstile", f.url, re.IGNORECASE) for f in page.frames):
                result["debug_hints"].append("检测到 Cloudflare/Turnstile frame")

        page_text = page.locator("body").inner_text()
        result["balance"] = detect_balance(page_text)

        if result["signed_today"]:
            log_step("任务结束：成功")
            save_result_and_exit(0)
        else:
            log_step("任务结束：失败")
            save_result_and_exit(2)

    except Exception as e:
        result["status"] = "failed"
        result["note"] = str(e)
        log_step(f"任务异常：{e}")
        save_result_and_exit(1)
    finally:
        context.close()
        browser.close()
