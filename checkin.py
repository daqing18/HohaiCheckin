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


def parse_proxy_candidates(raw: str):
    if not raw:
        return []
    v = raw.strip()
    if not v:
        return []
    if v.startswith("["):
        try:
            arr = json.loads(v)
            if isinstance(arr, list):
                return [str(x).strip() for x in arr if str(x).strip()]
        except Exception:
            pass
    return [v]


def build_proxy_config(proxy: str):
    p = proxy.strip()
    if not p:
        return None
    if not p.startswith("socks5://"):
        return {"server": p}
    body = p[len("socks5://"):]
    if "@" not in body:
        return {"server": p}

    creds, _, hostport = body.rpartition("@")
    if not hostport:
        return {"server": p}

    if ":" not in creds:
        return {
            "server": f"socks5://{hostport}",
            "username": urllib.parse.unquote(creds),
        }

    user, password = creds.split(":", 1)
    return {
        "server": f"socks5://{hostport}",
        "username": urllib.parse.unquote(user),
        "password": urllib.parse.unquote(password),
    }


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

    data = {"chat_id": TG_CHAT_ID, "text": text, "disable_web_page_preview": "true"}
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
        if re.search(r"余额|balance|wallet", line, re.IGNORECASE):
            return line
    return None


def has_turnstile(page):
    return any(re.search(r"cloudflare|turnstile", f.url, re.IGNORECASE) for f in page.frames)


def login_via_api(context):
    payloads = [
        {"username": USERNAME, "password": PASSWORD},
        {"userName": USERNAME, "password": PASSWORD},
        {"email": USERNAME, "password": PASSWORD},
        {"email": USERNAME, "passwd": PASSWORD},
    ]
    for p in payloads:
        try:
            r = context.request.post(API_LOGIN_URL, data=p, timeout=15000)
            if not r.ok:
                continue
            data = r.json()
            token = (
                data.get("token")
                or (data.get("data") or {}).get("token")
                or (data.get("data") or {}).get("accessToken")
                or data.get("accessToken")
            )
            if token:
                return token
        except Exception:
            continue
    return None


def fill_login_form(page):
    user_selectors = [
        'input[name="username"]',
        'input[name="email"]',
        'input[type="email"]',
        'input[autocomplete="username"]',
        'input[placeholder*="用户"]',
        'input[placeholder*="账号"]',
        'input[placeholder*="邮箱"]',
        'input[id*="user" i]',
        'input[id*="email" i]',
        'form input[type="text"]',
    ]
    pass_selectors = [
        'input[type="password"]',
        'input[autocomplete="current-password"]',
        'input[placeholder*="密码"]',
        'input[id*="pass" i]',
    ]

    user_locator = page.locator(", ".join(user_selectors)).first
    pass_locator = page.locator(", ".join(pass_selectors)).first

    if user_locator.count() > 0 and pass_locator.count() > 0:
        user_locator.fill(USERNAME)
        pass_locator.fill(PASSWORD)
        submit = page.locator(
            'button:has-text("登录"), button:has-text("Sign in"), button:has-text("Login"), button[type="submit"], [role="button"]:has-text("登录")'
        ).first
        if submit.count() > 0:
            submit.click()
            return True

    # JS fallback (for dynamic wrappers)
    filled = page.evaluate(
        """
        ({u,p}) => {
          const candidates = Array.from(document.querySelectorAll('input'));
          const pass = candidates.find(i => i.type === 'password' || /pass|密码/i.test(i.name||'') || /pass|密码/i.test(i.id||'') || /密码/.test(i.placeholder||''));
          const user = candidates.find(i => i !== pass && (
            i.type === 'email' || i.autocomplete === 'username' || /user|email|账号|邮箱|用户/i.test(i.name||'') || /user|email/i.test(i.id||'') || /账号|邮箱|用户/.test(i.placeholder||'') || i.type === 'text'
          ));
          if (!user || !pass) return {ok:false, why:'no-input'};
          user.focus(); user.value = u; user.dispatchEvent(new Event('input', {bubbles:true})); user.dispatchEvent(new Event('change', {bubbles:true}));
          pass.focus(); pass.value = p; pass.dispatchEvent(new Event('input', {bubbles:true})); pass.dispatchEvent(new Event('change', {bubbles:true}));
          const btn = Array.from(document.querySelectorAll('button,[role="button"],input[type="submit"]')).find(b => /登录|sign in|login/i.test((b.innerText||b.value||'').trim()));
          if (btn) { btn.click(); return {ok:true}; }
          return {ok:false, why:'no-submit'};
        }
        """,
        {"u": USERNAME, "p": PASSWORD},
    )
    return bool(filled and filled.get("ok"))


def run_once(use_proxy: bool, proxy_server: str | None = None):
    with sync_playwright() as p:
        launch_kwargs = {
            "headless": HEADLESS,
            "args": ["--disable-blink-features=AutomationControlled"],
        }
        log_step("启动浏览器")
        if use_proxy and proxy_server:
            proxy_cfg = build_proxy_config(proxy_server)
            launch_kwargs["proxy"] = proxy_cfg
            log_step(f"已启用代理: {proxy_cfg.get('server')}")
        elif SOCKS5_PROXY:
            log_step("使用直连模式（已跳过代理）")

        browser = p.chromium.launch(**launch_kwargs)
        context = browser.new_context(viewport={"width": 1366, "height": 900})
        page = context.new_page()

        try:
            log_step(f"正在访问 {LOGIN_URL}…")
            page.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=60_000)
            page.wait_for_timeout(1000)

            if has_turnstile(page):
                result["debug_hints"].append("登录页检测到 Cloudflare/Turnstile")

            log_step("正在执行登录")
            submitted = fill_login_form(page)
            if submitted:
                log_step("登录表单已提交")
                page.wait_for_timeout(2000)
                try:
                    page.wait_for_load_state("domcontentloaded", timeout=15000)
                    page.wait_for_load_state("networkidle", timeout=8000)
                except PlaywrightTimeoutError:
                    result["debug_hints"].append("登录后页面持续请求，已跳过 networkidle 严格等待")
                    log_step("登录后等待超时，继续后续检测")
            else:
                result["debug_hints"].append("未识别到可提交的登录表单，尝试 API 登录")
                log_step("未识别到可提交的登录表单，尝试 API 登录")
                token = login_via_api(context)
                if token:
                    log_step("API 登录成功，注入 token 并跳转 dashboard")
                    page.evaluate(
                        """
                        (t) => {
                          localStorage.setItem('auth_token', t);
                          sessionStorage.setItem('auth_token', t);
                        }
                        """,
                        token,
                    )
                    page.goto(DASHBOARD_URL, wait_until="domcontentloaded", timeout=60000)
                else:
                    result["debug_hints"].append("API 登录未拿到 token，可能被验证码或风控拦截")
                    log_step("API 登录失败，按当前页继续")

            page.wait_for_timeout(1500)

            # signed/target detection with polling for card flip
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
            for _ in range(10):
                if signed_text_a.count() > 0 or signed_text_b.count() > 0:
                    break
                sign_target = find_sign_target()
                if sign_target is not None:
                    break
                page.wait_for_timeout(2000)

            already_signed_now = signed_text_a.count() > 0 or signed_text_b.count() > 0

            if already_signed_now:
                log_step("检测到今日已签到")
                result["status"] = "already_signed"
                result["signed_today"] = True
            elif sign_target is not None:
                log_step("检测到签到入口，开始点击签到")
                sign_target.click()
                page.wait_for_timeout(1800)

                # best-effort click turnstile checkbox
                for frame in page.frames:
                    if re.search(r"cloudflare|turnstile", frame.url, re.IGNORECASE):
                        checkbox = frame.locator('input[type="checkbox"], div[role="checkbox"], label').first
                        if checkbox.count() > 0:
                            try:
                                checkbox.click(timeout=5000)
                                log_step("已尝试点击验证码控件")
                            except PlaywrightTimeoutError:
                                pass
                        break

                page.wait_for_timeout(3000)
                already_signed_after = signed_text_a.count() > 0 or signed_text_b.count() > 0
                if already_signed_after:
                    log_step("签到成功")
                    result["status"] = "checked_in_now"
                    result["signed_today"] = True
                else:
                    log_step("签到结果不确定")
                    result["status"] = "checkin_uncertain"
                    result["note"] = "Sign clicked, but success text not found. Likely blocked by challenge."
            else:
                log_step("未找到签到入口")
                result["status"] = "sign_button_not_found"
                result["note"] = "Sign button/card not found."
                if page.locator('input[type="password"]').count() > 0:
                    result["debug_hints"].append("当前页面疑似仍在登录页")
                if has_turnstile(page):
                    result["debug_hints"].append("检测到 Cloudflare/Turnstile frame")

            body_text = page.locator("body").inner_text()
            result["balance"] = detect_balance(body_text)

            if result["signed_today"]:
                log_step("任务结束：成功")
                return 0
            log_step("任务结束：失败")
            return 2

        finally:
            context.close()
            browser.close()


proxy_candidates = parse_proxy_candidates(SOCKS5_PROXY)

if proxy_candidates:
    for i, proxy in enumerate(proxy_candidates, start=1):
        try:
            log_step(f"尝试代理 {i}/{len(proxy_candidates)}")
            code = run_once(use_proxy=True, proxy_server=proxy)
            save_result_and_exit(code)
        except Exception as e:
            msg = str(e)
            if "ERR_SOCKS_CONNECTION_FAILED" in msg:
                result["debug_hints"].append(f"代理 {i} 连接失败")
                log_step(f"代理 {i} 连接失败，尝试下一个")
                continue
            if "does not support socks5 proxy authentication" in msg.lower():
                result["debug_hints"].append(f"代理 {i} 为 SOCKS5 鉴权代理，当前浏览器不支持")
                log_step(f"代理 {i} 鉴权不受支持，尝试下一个")
                continue
            result["status"] = "failed"
            result["note"] = msg
            log_step(f"任务异常：{e}")
            save_result_and_exit(1)

    log_step("所有代理均失败，自动回退到直连重试")
    result["debug_hints"].append("所有代理失败，已回退直连")

try:
    code = run_once(use_proxy=False)
    save_result_and_exit(code)
except Exception as e:
    result["status"] = "failed"
    result["note"] = str(e)
    log_step(f"任务异常：{e}")
    save_result_and_exit(1)
