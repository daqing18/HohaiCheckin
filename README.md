# HohaiCheckin

Python + Playwright 的 Hohai 每日自动签到脚本，并可运行在 GitHub Actions。
目标登录地址固定为：`https://tv.hohai.eu.org/login`（登录后站点自动跳转）。

## 你要求的变更
- 已删除此前 Node.js 依赖（`node_modules/`, `package.json`, `package-lock.json`, `src/`）
- 改为 Python 实现（`checkin.py`）
- 已添加 GitHub Actions 工作流（`.github/workflows/daily-checkin.yml`）

## 本地运行（可选）
```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m playwright install chromium
cp .env.example .env
# 填写用户名密码
python checkin.py
```

## GitHub Actions 配置
在仓库里设置以下 Secrets：
- `HOHAI_UN`
- `HOHAI_PW`
- `SOCKS5_PROXY`（可选）
  - 支持单个代理：`socks5://x.x.x.x:port`
  - 支持 JSON 数组（同一个变量中多个代理）：
    - `[
      "socks5://1.1.1.1:1080",
      "socks5://2.2.2.2:1080"
      ]`
  - 运行时会按顺序尝试代理，失败自动切换下一个，全部失败后回退直连
  - ⚠️ 当前 Playwright/Chromium 在本流程下不支持 SOCKS5 用户名密码鉴权代理（会报 `does not support socks5 proxy authentication`）

路径：`Settings -> Secrets and variables -> Actions -> New repository secret`

## 触发方式
- 自动：每天 08:08（Asia/Shanghai）
- 手动：Actions 页面点 `Run workflow`

## 结果产物
每次执行会输出到 `artifacts/`：
- `result-*.json`（状态、余额解析、备注）

并通过 `upload-artifact` 上传到本次 Actions 运行中（仅 JSON）。

## Telegram 通知
脚本支持执行后自动发 Telegram 消息。

新增 Secrets：
- `HOHAI_TGTK`
- `HOHAI_TGID`

若不配置 Telegram secrets，脚本会跳过通知，不影响签到流程。

## 状态说明
- `already_signed`：当天已签到
- `checked_in_now`：本次签到成功
- `checkin_uncertain`：点击后未识别成功文案（常见于 Cloudflare 挑战未通过）
- `sign_button_not_found`：未找到签到入口（页面结构可能变化）
- `failed`：运行异常

## 重要建议（务实）
1. **Cloudflare 验证可能拦截云服务器（含 GitHub Actions IP）**。如果风控严格，自动化可能不稳定。
2. 若你发现 Actions 成功率低，建议改为：
   - 在你自己的常用网络环境运行（本机/家用服务器）
   - 或使用持久化会话（后续可加 `storageState` 思路）降低挑战概率。
3. 建议增加失败通知（Telegram/邮件），只在失败时提醒，减少打扰。
