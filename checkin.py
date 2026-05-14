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
DASHBOARD_URL = "https://tv.hohai.eu.org/dashboard"
API_LOGIN_URL = "https://tv.hohai.eu.org/api/auth/login"

USERNAME = os.getenv("HOHAI_UN")
PASSWORD = os.getenv("HOHAI_PW")
HEADLESS = os.getenv("HEADLESS", "true").lower() == "true"
TG_BOT_TOKEN = os.getenv("HOHAI_TGTK")
TG_CHAT_ID = os.getenv("HOHAI_TGID")
STRICT_PROXY = os.getenv("STRICT_PROXY", "true").lower() == "true"

# Top-3 selected from connectivity benchmark (this environment):
# 1) 47.83.168.191:4000  (3/3 success, fastest)
# 2) 45.146.243.133:1080 (3/3 success, slower)
# 3) 47.238.203.170:50000 (2/3 success, very slow, as fallback)
DEFAULT_PROXY_POOL = [
    "http://47.83.168.191:4000",
    "http://45.146.243.133:1080",
    "http://47.238.203.170:50000",
]

if not USERNAME or not PASSWORD:
    raise SystemExit("Missing HOHAI_UN or HOHAI_PW")

CN_TZ = timezone(timedelta(hours=8))
NOW = datetime.now(CN_TZ)
ARTIFACTS = Path("artifacts")
ARTIFACTS.mkdir(parents=True, exist_ok=True)
TS = NOW.strftime("%Y%m%dT%H%M%S%z")

result = {
    "time": NOW.isoformat(),
    "url": LOGIN_URL,
    "status": "unknown",
    "signed_today": False,
    "balance": None,
    "note": "",
    "debug_hints": [],
    "proxy_used": None,
}


def log(msg: str):
    t = datetime.now(CN_TZ).strftime("%Y-%m-%d %H:%M:%S%z")
    print(f"[{t}] {msg}")


def parse_proxy_pool():
    raw = os.getenv("HTTP_PROXY_POOL", "").strip()
    if not raw:
        return DEFAULT_PROXY_POOL
    try:
        arr = json.loads(raw)
        if isinstance(arr, list):
            return [str(x).strip() for x in arr if str(x).strip()]
    except Exception:
        pass
    return DEFAULT_PROXY_POOL


def save_and_exit(code: int):
    out = ARTIFACTS / f"result-{TS}.json"
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    send_telegram(result)
    raise SystemExit(code)


def send_telegram(payload: dict):
    if not TG_BOT_TOKEN or not TG_CHAT_ID:
        return

    icon = "🟢" if payload.get("signed_today") else "🔴"
    text = (
        f"{icon} Hohai 自动签到通知\n"
        f"📌 状态：{payload.get('status')}\n"
        f"🗓️ 今日是否已签到：{'是' if payload.get('signed_today') else '否'}\n"
        f"💰 账户余额：{payload.get('balance') or '未识别'}\n"
        f"🌐 代理：{payload.get('proxy_used') or '直连'}\n"
        f"📝 备注：{payload.get('note') or '无'}\n"
        f"⏰ 时间：{payload.get('time')}"
    )
    body = urllib.parse.urlencode({"chat_id": TG_CHAT_ID, "text": text}).encode("utf-8")
    req = urllib.request.Request(
        url=f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMessage",
        method="POST",
        data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    try:
        with urllib.request.urlopen(req, timeout=15):
            pass
    except Exception as e:
        print(f"[warn] telegram send failed: {e}")


def detect_balance_from_dom(page):
    return page.evaluate(r"""
        () => {
          const labels = [...document.querySelectorAll('span')].filter(s => (s.innerText || '').trim() === '余额');
          for (const label of labels) {
            const card = label.closest('div');
            if (!card) continue;

            const rollers = [...card.querySelectorAll('span.transition-transform')];
            if (rollers.length > 0) {
              const digits = rollers.map(r => {
                const t = r.style.transform || '';
                const m = t.match(/translateY\(-([0-9]+)%\)/);
                if (!m) return '';
                const pct = Number(m[1]);
                return String(Math.round(pct / 10) % 10);
              }).join('');
              const hasDot = (card.innerText || '').includes('.');
              if (digits.length >= 3 && hasDot) return `${digits[0]}.${digits.slice(1)} ¥`;
              if (digits.length > 0) return `${digits} ¥`;
            }

            const txt = (card.innerText || '').replace(/\s+/g, ' ').trim();
            const m2 = txt.match(/([0-9]+(?:\.[0-9]+)?)/);
            if (m2) return `${m2[1]} ¥`;
          }

          const body = (document.body?.innerText || '').replace(/\s+/g, ' ');
          const m3 = body.match(/余额[^0-9]{0,12}([0-9]+(?:\.[0-9]+)?)/);
          if (m3) return `${m3[1]} ¥`;
          return null;
        }
    """)


def try_login_api(context):
    payloads = [
        {"username": USERNAME, "password": PASSWORD},
        {"userName": USERNAME, "password": PASSWORD},
        {"email": USERNAME, "password": PASSWORD},
    ]
    for p in payloads:
        try:
            r = context.request.post(API_LOGIN_URL, data=p, timeout=15000)
            if not r.ok:
                continue
            d = r.json()
            token = d.get("token") or (d.get("data") or {}).get("token") or d.get("accessToken") or (d.get("data") or {}).get("accessToken")
            if token:
                return token
        except Exception:
            continue
    return None


def submit_login_form(page):
    user = page.locator('input[name="username"],input[name="email"],input[type="email"],input[autocomplete="username"],form input[type="text"]').first
    pwd = page.locator('input[name="password"],input[type="password"],input[autocomplete="current-password"]').first
    if user.count() > 0 and pwd.count() > 0:
        user.fill(USERNAME)
        pwd.fill(PASSWORD)
        submit = page.locator('button:has-text("登录"),button:has-text("Login"),button:has-text("Sign in"),button[type="submit"],[role="button"]:has-text("登录")').first
        if submit.count() > 0:
            submit.click()
            return True
    return False


def find_sign_target(page):
    card = page.locator('[data-checkin-card="default"]').first
    if card.count() > 0:
        for c in [
            card.locator('button:has-text("签到")').first,
            card.locator('[role="button"]:has-text("签到")').first,
            card.locator('div:has-text("签到")').first,
            card.locator('span:has-text("签到")').first,
        ]:
            if c.count() > 0:
                return c
        return card

    for c in [
        page.locator('button:has-text("签到")').first,
        page.locator('[role="button"]:has-text("签到")').first,
        page.locator('div:has-text("签到")').first,
        page.locator('span:has-text("签到")').first,
        page.get_by_text("签到").first,
    ]:
        if c.count() > 0:
            return c
    return None


def run_once(proxy: str | None):
    with sync_playwright() as p:
        launch_kwargs = {"headless": HEADLESS}
        if proxy:
            launch_kwargs["proxy"] = {"server": proxy}
            result["proxy_used"] = proxy
            log(f"使用代理: {proxy}")

        browser = p.chromium.launch(**launch_kwargs)
        context = browser.new_context(viewport={"width": 1366, "height": 900})
        page = context.new_page()

        try:
            log(f"访问登录页: {LOGIN_URL}")
            page.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(1200)

            log("尝试页面表单登录")
            submitted = submit_login_form(page)
            if submitted:
                page.wait_for_timeout(2000)
                try:
                    page.wait_for_load_state("domcontentloaded", timeout=15000)
                    page.wait_for_load_state("networkidle", timeout=8000)
                except PlaywrightTimeoutError:
                    result["debug_hints"].append("登录后页面存在持续请求，已跳过 networkidle 严格等待")
            else:
                if STRICT_PROXY:
                    result["debug_hints"].append("严格代理模式：跳过 API 登录兜底，仅允许页面表单登录")
                else:
                    token = try_login_api(context)
                    if token:
                        page.evaluate("""(t)=>{localStorage.setItem('auth_token',t);sessionStorage.setItem('auth_token',t);} """, token)
                        page.goto(DASHBOARD_URL, wait_until="domcontentloaded", timeout=60000)
                    else:
                        result["debug_hints"].append("表单登录和 API 登录均失败（可能被风控拦截）")

            page.wait_for_timeout(1800)

            signed_a = page.get_by_text("今日已签到")
            signed_b = page.get_by_text("签到完成")

            sign_target = None
            for _ in range(10):
                if signed_a.count() > 0 or signed_b.count() > 0:
                    break
                sign_target = find_sign_target(page)
                if sign_target is not None:
                    break
                page.wait_for_timeout(2000)

            if signed_a.count() > 0 or signed_b.count() > 0:
                result["status"] = "already_signed"
                result["signed_today"] = True
                log("已识别到今日已签到")
            elif sign_target is not None:
                log("检测到签到入口，执行点击")
                sign_target.click()
                page.wait_for_timeout(2500)

                for f in page.frames:
                    if re.search(r"cloudflare|turnstile", f.url, re.IGNORECASE):
                        cb = f.locator('input[type="checkbox"], div[role="checkbox"], label').first
                        if cb.count() > 0:
                            try:
                                cb.click(timeout=5000)
                            except PlaywrightTimeoutError:
                                pass
                        break

                page.wait_for_timeout(3000)
                if signed_a.count() > 0 or signed_b.count() > 0:
                    result["status"] = "checked_in_now"
                    result["signed_today"] = True
                    log("签到成功")
                else:
                    result["status"] = "checkin_uncertain"
                    result["note"] = "Clicked sign-in but no success text found"
            else:
                result["status"] = "sign_button_not_found"
                result["note"] = "No sign-in control found"
                if page.locator('input[type="password"]').count() > 0:
                    result["debug_hints"].append("当前页面疑似仍在登录页")

            result["balance"] = detect_balance_from_dom(page)
            return 0 if result["signed_today"] else 2

        finally:
            context.close()
            browser.close()


pool = parse_proxy_pool()
last_error = None
for i, proxy in enumerate(pool, start=1):
    try:
        log(f"尝试代理 {i}/{len(pool)}")
        code = run_once(proxy)
        save_and_exit(code)
    except Exception as e:
        last_error = e
        result["debug_hints"].append(f"代理失败: {proxy}")
        log(f"代理失败: {proxy} -> {e}")

if STRICT_PROXY:
    result["status"] = "failed"
    result["note"] = "All proxies failed in STRICT_PROXY mode"
    result["debug_hints"].append("严格代理模式已启用：禁止直连回退")
    save_and_exit(1)

# non-strict fallback: direct connection
try:
    log("所有代理失败，回退直连")
    result["debug_hints"].append("所有代理失败，已回退直连")
    code = run_once(None)
    save_and_exit(code)
except Exception as e:
    result["status"] = "failed"
    result["note"] = str(e if e else last_error)
    save_and_exit(1)
