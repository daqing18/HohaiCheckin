# HohaiCheckin (GitHub Actions + sing-box)

每天 00:05 (Asia/Shanghai) 通过 GitHub Actions 自动签到。出口经由 runner 内本地 **sing-box** 转发到自建的鉴权 SOCKS5 节点池,使用 `urltest` 自动选优。

## 架构

```
GitHub Actions Runner
  └─ checkin.py (Playwright, headless Chromium)
       └─ HTTP_PROXY_URL=http://127.0.0.1:7890
            └─ sing-box (mixed inbound)
                 └─ urltest selector
                      ├─ socks5: vps-1 (账密)
                      ├─ socks5: vps-2
                      └─ ...
```

为什么要走 sing-box 中转:Chromium 的 `--proxy-server` 不支持 SOCKS5 用户名/密码鉴权,sing-box 在本地承担鉴权与多节点选优,Chromium 只看到一个无鉴权的本地 HTTP 入口,问题彻底消除。

## Secrets

必须:

| Secret | 说明 |
|---|---|
| `HOHAI_UN` | 站点用户名 |
| `HOHAI_PW` | 站点密码 |
| `PROXY_NODES_JSON` | 鉴权 SOCKS5 节点数组(JSON 字符串),格式见下 |

可选:

| Secret | 说明 |
|---|---|
| `HOHAI_TGTK` | Telegram Bot token |
| `HOHAI_TGID` | Telegram chat id |

`PROXY_NODES_JSON` 示例(可包含任意数量节点,全部加入 urltest):

```json
[
  {"tag":"hk-01","server":"hk.example.com","port":1080,"username":"u","password":"p"},
  {"tag":"sg-01","server":"sg.example.com","port":1080,"username":"u","password":"p"},
  {"tag":"jp-01","server":"jp.example.com","port":1080,"username":"u","password":"p"},
  {"tag":"us-01","server":"us.example.com","port":1080,"username":"u","password":"p"}
]
```

字段:`server`/`port`/`username`/`password` 必填,`tag` 选填(用于日志辨识)。

## 节点维护

新增/删除/换密码,只需编辑 `PROXY_NODES_JSON` Secret,**无需改代码**。下一次 workflow 运行会自动渲染新配置。

要升级 sing-box,修改 `.github/workflows/daily-checkin.yml` 中的 `SINGBOX_VERSION` 即可。

## 文件结构

```
.github/workflows/daily-checkin.yml   # workflow:安装 sing-box → 渲染 → 启动 → 健康检查 → 跑 checkin
singbox/config.template.json          # sing-box 配置骨架(inbound/route/log)
tools/render_singbox.py               # 模板 + Secret → 最终 config.json
checkin.py                            # Playwright 签到主脚本
```

## 运行

- 自动:每天 00:05 (Asia/Shanghai),对应 cron `5 16 * * *` (UTC)
- 手动:Actions → Hohai Daily Check-in → Run workflow

## 输出

- `artifacts/result-*.json` —— 签到结果
- `singbox/singbox.log` —— sing-box 运行日志(失败时一并上传)
- Telegram 通知(若配置)

## 本地调试

```bash
pip install -r requirements.txt
python -m playwright install --with-deps chromium

# 自己起一份 sing-box 在本地 7890 端口,然后:
cp .env.example .env
# 编辑 .env 填入账密
python checkin.py
```

## 健康检查行为

workflow 在调用 Playwright 之前,会用 `curl -x http://127.0.0.1:7890` 探一下 `https://tv.hohai.eu.org/login`。HTTP 状态码不在 2xx/3xx 区间则直接失败,避免浪费 Chromium 启动时间。
