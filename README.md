# HohaiCheckin

已切换为 **VPS 本地运行（.sh + systemd）**，不再依赖 GitHub Actions / venv。

## 目录说明
- `checkin.py`：签到主逻辑（Playwright）
- `checkin.sh`：VPS 执行入口脚本
- `deploy/systemd/hohai-checkin.service`：systemd 服务文件
- `deploy/systemd/hohai-checkin.timer`：systemd 定时器（每天 08:08）

## 1) VPS 一次性安装依赖（系统 Python）
```bash
sudo apt update
sudo apt install -y python3 python3-pip python3-playwright
# 若系统仓库没有 python3-playwright，则用 pip 方式：
# python3 -m pip install --break-system-packages -r /opt/HohaiCheckin/requirements.txt
python3 -m playwright install chromium
```

## 2) 部署项目到 VPS
```bash
sudo mkdir -p /opt/HohaiCheckin
sudo rsync -av --delete ./ /opt/HohaiCheckin/
sudo chown -R actions:actions /opt/HohaiCheckin
sudo chmod +x /opt/HohaiCheckin/checkin.sh
```

## 3) 配置环境变量
创建 `/etc/hohai-checkin.env`：
```bash
sudo tee /etc/hohai-checkin.env >/dev/null <<'EOF'
HOHAI_UN=your_username
HOHAI_PW=your_password
HEADLESS=true

# 可选：代理（支持单个或 JSON 数组）
SOCKS5_PROXY=

# 可选：Telegram 通知
HOHAI_TGTK=
HOHAI_TGID=
EOF
```

## 4) 安装 systemd 服务与定时器
```bash
sudo cp /opt/HohaiCheckin/deploy/systemd/hohai-checkin.service /etc/systemd/system/
sudo cp /opt/HohaiCheckin/deploy/systemd/hohai-checkin.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now hohai-checkin.timer
```

## 5) 手动测试与查看日志
```bash
sudo systemctl start hohai-checkin.service
sudo systemctl status hohai-checkin.service
sudo journalctl -u hohai-checkin.service -n 200 --no-pager
# 或查看文件日志
sudo tail -n 200 /var/log/hohai-checkin.log
```

## 说明
- 输出 JSON：`artifacts/result-*.json`
- 若配置 Telegram，会自动发送结果通知
- 失败常见原因仍是 Cloudflare/验证码策略，而不是脚本语法问题
