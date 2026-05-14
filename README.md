# HohaiCheckin

最终生产建议：
- **每日自动任务**：VPS `systemd timer`（固定 IP，最稳定）
- **手动补跑**：GitHub Actions + self-hosted runner

---

## 一、VPS 自动运行（主方案）

### 1) 安装依赖（VPS）
```bash
sudo apt update
sudo apt install -y python3 python3-pip
python3 -m pip install --break-system-packages -r /opt/HohaiCheckin/requirements.txt
python3 -m playwright install chromium
```

### 2) 部署代码
```bash
sudo mkdir -p /opt/HohaiCheckin
sudo rsync -av --delete ./ /opt/HohaiCheckin/
sudo chown -R actions:actions /opt/HohaiCheckin
```

### 3) 配置环境变量
```bash
sudo cp /opt/HohaiCheckin/deploy/hohai-checkin.env.example /etc/hohai-checkin.env
sudo nano /etc/hohai-checkin.env
```
填写：
- `HOHAI_UN`
- `HOHAI_PW`
- `HOHAI_TGTK`（可选）
- `HOHAI_TGID`（可选）

### 4) 安装 systemd 服务与定时器
```bash
sudo cp /opt/HohaiCheckin/deploy/systemd/hohai-checkin.service /etc/systemd/system/
sudo cp /opt/HohaiCheckin/deploy/systemd/hohai-checkin.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now hohai-checkin.timer
```

### 5) 手动验证一次
```bash
sudo systemctl start hohai-checkin.service
sudo systemctl status hohai-checkin.service
sudo journalctl -u hohai-checkin.service -n 200 --no-pager
```

---

## 二、GitHub Actions（仅手动补跑）

已改为 `workflow_dispatch` + `self-hosted runner`。  
用途：你想临时手动跑一次时使用，不承担日常定时任务。

---

## 三、运行结果
脚本输出：
- 终端日志
- `artifacts/result-*.json`

退出码：
- `0`：成功（`already_signed` / `checked_in_now`）
- `2`：未完成签到（如 `sign_button_not_found` / `checkin_uncertain`）
- `1`：异常失败
