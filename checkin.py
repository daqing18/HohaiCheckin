import json
import os
import re
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

from dotenv import load_dotenv
from patchright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

# 加载环境变量
load_dotenv()

# 配置项
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

# 初始化
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

# Turnstile 注入脚本
_EXPAND_JS = """() => {
    var ts = document.querySelector('input[name="cf-turnstile-response"]');
    if (!ts) return 'no-turnstile';
    var el = ts;
    for (var i = 0; i < 20; i++) {
        el = el.parentElement;
        if (!el) break;
        var s = window.getComputedStyle(el);
        if (s.overflow === 'hidden' || s.overflowX === 'hidden' || s.overflowY === 'hidden')
            el.style.overflow = 'visible';
    }
    document.querySelectorAll('iframe').forEach(function(f){
        if (f.src && f.src.includes('challenges.cloudflare.com')) {
            f.style.width = '300px'; f.style.height = '65px';
            f.style.visibility = 'visible'; f.style.opacity = '1';
        }
    });
    return 'done';
}"""

_SOLVED_JS = """() => {
    var i = document.querySelector('input[name="cf-turnstile-response"]');
    return !!(i && i.value && i.value.length > 20);
}"""

def log(msg: str):
    print(f"[{datetime.now(CN_TZ).strftime('%Y-%m-%d %H:%M:%S')}] {msg}")

def send_telegram(payload: dict):
    if not TG_BOT_TOKEN or not TG_CHAT_ID:
        return
    
    # 格式化时间，去掉毫秒和时区乱码
    raw_time = payload.get('time', '')
    try:
        readable_time = datetime.fromisoformat(raw_time).strftime("%Y-%m-%d %H:%M:%S")
    except:
        readable_time = raw_time

    icon = "🟢" if payload.get("signed_today") else "🔴"
    text = (
        f"{icon} Hohai 自动签到通知\n"
        f"📌 状态：{payload.get('status')}\n"
        f"🗓️ 今日是否已签到：{'是' if payload.get('signed_today') else '否'}\n"
        f"💰 账户余额：{payload.get('balance') or '未识别'}\n"
        f"🌐 代理：{payload.get('proxy_used') or '直连'}\n"
        f"📝 备注：{payload.get('note') or '无'}\n"
        f"⏰ 时间：{readable_time}"
    )
    body = urllib.parse.urlencode({"chat_id": TG_CHAT_ID, "text": text}).encode("utf-8")
    req = urllib.request.Request("https://api.telegram.org/bot"+TG_BOT_TOKEN+"/sendMessage", data=body, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=15): pass
    except Exception as e:
        print(f"Telegram send failed: {e}")

def handle_turnstile(page) -> bool:
    log("处理 Turnstile...")
    for attempt in range(5):
        try: page.evaluate(_EXPAND_JS)
        except: pass
        if page.evaluate(_SOLVED_JS): return True
        
        box = page.evaluate("""() => {
            const el = document.querySelector('iframe[src*="challenges.cloudflare.com"]');
            if(!el) return null;
            const r = el.getBoundingClientRect();
            return {x: r.x, y: r.y, w: r.width, h: r.height};
        }""")
        if box:
            page.mouse.click(box['x'] + box['w']/2, box['y'] + box['h']/2)
        page.wait_for_timeout(2000)
    return False

def run_once(proxy: str | None):
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=HEADLESS)
        context = browser.new_context(proxy={"server": proxy} if proxy else None)
        page = context.new_page()
        page.goto(LOGIN_URL, wait_until="domcontentloaded")
        
        # 简单登录逻辑
        user = page.locator('input[name="username"], input[type="email"]').first
        pwd = page.locator('input[name="password"]').first
        if user.count() > 0:
            user.fill(USERNAME)
            pwd.fill(PASSWORD)
            page.locator('button[type="submit"]').click()
        
        page.wait_for_timeout(3000)
        # 签到逻辑
        sign_btn = page.locator('text="签到"').first
        if sign_btn.count() > 0:
            sign_btn.click()
            handle_turnstile(page)
            page.wait_for_timeout(5000)
            result["signed_today"] = True
            result["status"] = "签到成功"
        else:
            result["status"] = "未找到签到按钮"
            
        save_and_exit(0 if result["signed_today"] else 2)

def save_and_exit(code: int):
    send_telegram(result)
    raise SystemExit(code)

if __name__ == "__main__":
    try:
        run_once(HTTP_PROXY_URL)
    except Exception as e:
        result["status"] = "执行失败"
        result["note"] = str(e)
        save_and_exit(1)
