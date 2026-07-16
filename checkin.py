import json
import os
import re
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

from dotenv import load_dotenv
from patchright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

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
HTTP_PROXY_URL = os.getenv("HTTP_PROXY_URL", "").strip() or None

if not USERNAME or not PASSWORD:
    raise SystemExit("Missing HOHAI_UN or HOHAI_PW")
if STRICT_PROXY and not HTTP_PROXY_URL:
    raise SystemExit("STRICT_PROXY=true but HTTP_PROXY_URL is empty")

CN_TZ = timezone(timedelta(hours=8))
NOW = datetime.now(CN_TZ)
ARTIFACTS = Path("artifacts")
ARTIFACTS.mkdir(parents=True, exist_ok=True)
TS = NOW.strftime("%Y%m%dT%H%M%S%z")

result = {
    "time": NOW.isoformat(),
    "url": LOGIN_URL,
    "status": "未知状态",
    "signed_today": False,
    "balance": None,
    "note": "",
    "debug_hints": [],
    "proxy_used": None,
}

# ==================== Turnstile 强行注入与检测脚本 ====================
_EXPAND_JS = """
() => {
    var ts = document.querySelector('input[name="cf-turnstile-response"]');
    if (!ts) return 'no-turnstile';
    var el = ts;
    for (var i = 0; i < 20; i++) {
        el = el.parentElement;
        if (!el) break;
        var s = window.getComputedStyle(el);
        if (s.overflow === 'hidden' || s.overflowX === 'hidden' || s.overflowY === 'hidden')
            el.style.overflow = 'visible';
        el.style.minWidth = 'max-content';
    }
    document.querySelectorAll('iframe').forEach(function(f){
        if (f.src && f.src.includes('challenges.cloudflare.com')) {
            f.style.width = '300px'; f.style.height = '65px';
            f.style.minWidth = '300px';
            f.style.visibility = 'visible'; f.style.opacity = '1';
        }
    });
    return 'done';
}
"""

_SOLVED_JS = """
() => {
    var i = document.querySelector('input[name="cf-turnstile-response"]');
    return !!(i && i.value && i.value.length > 20);
}
"""
# ======================================================================


def log(msg: str):
    t = datetime.now(CN_TZ).strftime("%Y-%m-%d %H:%M:%S%z")
    print(f"[{t}] {msg}")


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


def try_login_api_via_page(page):
    payloads = [
        {"username": USERNAME, "password": PASSWORD},
        {"userName": USERNAME, "password": PASSWORD},
        {"email": USERNAME, "password": PASSWORD},
    ]
    for p in payloads:
        try:
            data = page.evaluate(
                """
                async ({ url, payload }) => {
                  const r = await fetch(url, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    credentials: 'include',
                    body: JSON.stringify(payload),
                  });
                  let j = null;
                  try { j = await r.json(); } catch (_) {}
                  return { ok: r.ok, status: r.status, body: j };
                }
                """,
                {"url": API_LOGIN_URL, "payload": p},
            )
            if not data or not data.get("ok"):
                continue
            body = data.get("body") or {}
            token = body.get("token") or (body.get("data") or {}).get("token") or body.get("accessToken") or (body.get("data") or {}).get("accessToken")
            if token:
                return token
        except Exception:
            continue
    return None


def submit_login_form(page):
    try:
        page.wait_for_selector('input[name="password"],input[type="password"],input[autocomplete="current-password"]', timeout=15000)
    except PlaywrightTimeoutError:
        pass

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


def is_signed_card(page) -> bool:
    if page.locator("[data-checkin-card='default']").count() > 0:
        if page.locator("[class*='statusNotChecked']").count() == 0:
            return True
    for txt in ("今日已签到", "签到完成", "签到成功", "已签到", "明日再来", "已经签过"):
        if page.get_by_text(txt).count() > 0:
            return True
    return False


def handle_turnstile_with_retry(page) -> bool:
    log("🔍 开始处理 Cloudflare Turnstile 验证...")
    page.wait_for_timeout(2000)

    if page.evaluate(_SOLVED_JS):
        log("✅ Turnstile 已自动静默通过")
        return True

    for attempt in range(5):
        log(f"🔄 正在进行第 {attempt + 1} 轮 Turnstile 突破尝试...")
        
        try:
            page.evaluate(_EXPAND_JS)
        except Exception:
            pass
        page.wait_for_timeout(800)

        if page.evaluate(_SOLVED_JS):
            log(f"✅ Turnstile 在第 {attempt + 1} 轮通过！")
            return True

        widget_box = page.evaluate("""
            () => {
              const el = document.querySelector('.cloudflare-turnstile-container, .turnstile-widget, iframe[src*="challenges.cloudflare.com"]');
              if (!el) return null;
              const r = el.getBoundingClientRect();
              return { x: r.x, y: r.y, w: r.width, h: r.height };
            }
        """)

        if widget_box and widget_box.get("w", 0) > 30:
            x = widget_box["x"] + widget_box["w"] * 0.2
            y = widget_box["y"] + widget_box["h"] * 0.5
            
            log(f"🖱️ 锁定验证码区域，执行拟人滑动点击: ({x:.0f}, {y:.0f})")
            try:
                page.mouse.move(x - 50, y - 50)
                page.wait_for_timeout(200)
                page.mouse.move(x, y, steps=10)
                page.wait_for_timeout(400)
                page.mouse.down()
                page.wait_for_timeout(100)
                page.mouse.up()
            except Exception as e:
                log(f"点击异常: {e}")
        else:
            log("⚠️ 未能获取到验证码模块的有效点击坐标")

        for _ in range(5):
            page.wait_for_timeout(1000)
            if page.evaluate(_SOLVED_JS):
                log(f"✅ Turnstile 验证通过！(第 {attempt + 1} 轮)")
                return True

    log("❌ 5 轮 Turnstile 尝试均未生成有效 Token")
    return False


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

        network_log: list[dict] = []
        static_re = re.compile(r"\.(?:js|css|woff2?|ttf|png|jpe?g|gif|svg|ico|map)(?:\?|$)", re.IGNORECASE)

        def on_requestfinished(req):
            try:
                if "hohai.eu.org" not in req.url or static_re.search(req.url):
                    return
                resp = req.response()
                if resp is None:
                    return
                try:
                    body = resp.text()
                    if len(body) > 2000:
                        body = body[:2000] + "…[truncated]"
                except Exception:
                    body = "<binary or unreadable>"
                network_log.append({
                    "ts": datetime.now(CN_TZ).strftime("%H:%M:%S.%f")[:-3],
                    "method": req.method,
                    "url": req.url,
                    "status": resp.status,
                    "body_excerpt": body,
                })
            except Exception:
                pass

        context.on("requestfinished", on_requestfinished)

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
                token = try_login_api_via_page(page)
                if token:
                    result["debug_hints"].append("页面 API 登录兜底成功")
                    page.evaluate("""(t)=>{localStorage.setItem('auth_token',t);sessionStorage.setItem('auth_token',t);} """, token)
                    page.goto(DASHBOARD_URL, wait_until="domcontentloaded", timeout=60000)
                else:
                    if STRICT_PROXY:
                        result["debug_hints"].append("严格代理模式：页面表单与页面API登录均失败")
                    else:
                        result["debug_hints"].append("表单登录和 API 登录均失败（可能被风控拦截）")

            page.wait_for_timeout(1800)

            sign_target = None
            for _ in range(10):
                if is_signed_card(page):
                    break
                sign_target = find_sign_target(page)
                if sign_target is not None:
                    break
                page.wait_for_timeout(2000)

            if is_signed_card(page):
                result["status"] = "今日已签到"
                result["signed_today"] = True
                log("已识别到今日已签到")
            elif sign_target is not None:
                log("检测到签到入口,执行点击")

                try:
                    page.screenshot(path=str(ARTIFACTS / f"before-click-{TS}.png"), full_page=True)
                    (ARTIFACTS / f"before-click-{TS}.html").write_text(page.content(), encoding="utf-8")
                except Exception as e:
                    result["debug_hints"].append(f"before-click snapshot failed: {e}")

                network_log.clear()
                click_at = datetime.now(CN_TZ).isoformat()

                sign_target.click()

                turnstile_solved = handle_turnstile_with_retry(page)
                if turnstile_solved:
                    result["debug_hints"].append("Turnstile token 已成功生成")
                else:
                    result["debug_hints"].append("Turnstile token 未能生成(超时或被拦截)")

                page.wait_for_timeout(5000)

                try:
                    page.screenshot(path=str(ARTIFACTS / f"after-click-{TS}.png"), full_page=True)
                    (ARTIFACTS / f"after-click-{TS}.html").write_text(page.content(), encoding="utf-8")
                except Exception as e:
                    result["debug_hints"].append(f"after-click snapshot failed: {e}")

                try:
                    (ARTIFACTS / f"network-{TS}.json").write_text(
                        json.dumps({"click_at": click_at, "events": network_log}, ensure_ascii=False, indent=2),
                        encoding="utf-8",
                    )
                except Exception as e:
                    result["debug_hints"].append(f"network log write failed: {e}")

                checkin_api_ok = any(
                    re.search(r"/api/.*(check[-_]?in|sign|task)", ev.get("url", ""), re.IGNORECASE)
                    and 200 <= int(ev.get("status", 0)) < 300
                    for ev in network_log
                )

                if checkin_api_ok:
                    result["status"] = "本次签到成功"
                    result["signed_today"] = True
                    result["debug_hints"].append("检测到签到 API 2xx 响应")
                    log("签到成功 (via API)")
                elif is_signed_card(page):
                    result["status"] = "本次签到成功"
                    result["signed_today"] = True
                    log("签到成功 (via DOM)")
                else:
                    result["status"] = "签到结果不确定"
                    result["note"] = "Clicked sign-in but no checkin API hit nor card state change"
            else:
                result["status"] = "未找到签到入口"
                result["note"] = "No sign-in control found"
                if page.locator('input[type="password"]').count() > 0:
                    result["debug_hints"].append("当前页面疑似仍在登录页")

            result["balance"] = detect_balance_from_dom(page)
            return 0 if result["signed_today"] else 2

        finally:
            context.close()
            browser.close()


try:
    if HTTP_PROXY_URL:
        log(f"使用本地代理入口: {HTTP_PROXY_URL}")
    else:
        log("未配置 HTTP_PROXY_URL，直连运行")
    code = run_once(HTTP_PROXY_URL)
    save_and_exit(code)
except Exception as e:
    result["status"] = "执行失败"
    result["note"] = str(e) or "unknown error"
    result["debug_hints"].append(f"运行异常: {e}")
    save_and_exit(1)
