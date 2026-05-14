# HohaiCheckin

Python + Playwright 的 Hohai 每日自动签到脚本（GitHub Actions）。
目标登录地址固定：`https://tv.hohai.eu.org/login`。

## 说明
- 已移除 Cloudflare Workers 版本（`worker.js` / `wrangler.toml`）。
- 主流程仅保留 Python 脚本 `checkin.py`。

## 本地运行（可选）
```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m playwright install chromium
cp .env.example .env
python checkin.py
```

## GitHub Actions 配置
在仓库里设置 Secrets：
- `HOHAI_UN`
- `HOHAI_PW`
- `SOCKS5_PROXY`（可选）
  - 单代理：`socks5://x.x.x.x:port`
  - 多代理 JSON 数组：
    - `[
      "socks5://1.1.1.1:1080",
      "socks5://2.2.2.2:1080"
      ]`
  - 失败会自动切换下一个，全部失败后回退直连
  - 注意：SOCKS5 用户名密码鉴权代理在当前 Playwright/Chromium 链路下不支持
- `HOHAI_TGTK`（可选）
- `HOHAI_TGID`（可选）

## 触发方式
- 自动：每天 08:08（Asia/Shanghai）
- 手动：Actions 页面点 `Run workflow`

## 输出
- `artifacts/result-*.json`
- 同步 Telegram 通知（若配置）

## 状态说明
- `already_signed`：当天已签到
- `checked_in_now`：本次签到成功
- `checkin_uncertain`：点击后未识别成功文案（常见于验证码未通过）
- `sign_button_not_found`：未找到签到入口
- `failed`：运行异常
