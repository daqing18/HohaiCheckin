# HohaiCheckin (Docker)

目标：
1) 访问并登录 `https://tv.hohai.eu.org/login`
2) 自动进入 `https://tv.hohai.eu.org/dashboard`
3) 完成签到动作
4) 读取账户余额信息

---

## 1. 配置环境变量
```bash
cp .env.example .env
```
编辑 `.env`：
```env
HOHAI_UN=your_username
HOHAI_PW=your_password
HEADLESS=true
HOHAI_TGTK=
HOHAI_TGID=
```

## 2. Docker 运行（手动）
```bash
chmod +x run_docker.sh
./run_docker.sh
```

运行结果：
- 控制台日志
- `artifacts/result-*.json`

## 3. 使用 systemd 定时启动（推荐）
把仓库放在 `/opt/HohaiCheckin` 后执行：

```bash
sudo cp deploy/systemd/hohai-checkin-docker.service /etc/systemd/system/
sudo cp deploy/systemd/hohai-checkin-docker.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now hohai-checkin-docker.timer
```

手动触发一次：
```bash
sudo systemctl start hohai-checkin-docker.service
```

查看日志：
```bash
sudo journalctl -u hohai-checkin-docker.service -n 200 --no-pager
```

## 4. 退出码
- `0`：成功（`already_signed` / `checked_in_now`）
- `2`：未完成签到（如 `sign_button_not_found` / `checkin_uncertain`）
- `1`：异常失败
