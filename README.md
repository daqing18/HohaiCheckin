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

## 3. 定时任务（宿主机 cron）
示例：每天 08:08 执行
```cron
8 8 * * * cd /opt/HohaiCheckin && /usr/bin/env bash ./run_docker.sh >> /opt/HohaiCheckin/artifacts/cron.log 2>&1
```

## 4. 退出码
- `0`：成功（`already_signed` / `checked_in_now`）
- `2`：未完成签到（如 `sign_button_not_found` / `checkin_uncertain`）
- `1`：异常失败
