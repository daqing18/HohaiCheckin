# HohaiCheckin (Rebuilt)

目标：
1) 访问并登录 `https://tv.hohai.eu.org/login`
2) 自动跳转/进入 `https://tv.hohai.eu.org/dashboard`
3) 完成签到动作
4) 读取账户余额信息

## 环境准备
```bash
pip install -r requirements.txt
python -m playwright install chromium
```

## 配置
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

## 运行
```bash
python checkin.py
```

输出：
- 终端日志
- `artifacts/result-*.json`

## 自我验证（已内置）
脚本运行后会进行结果判断：
- `already_signed` / `checked_in_now` -> 退出码 `0`
- `checkin_uncertain` / `sign_button_not_found` -> 退出码 `2`
- `failed` -> 退出码 `1`

你可以用退出码快速判定自动化是否成功。
