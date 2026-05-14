#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR_DEFAULT="/opt/HohaiCheckin"
SERVICE_NAME="hohai-checkin"
ENV_FILE="/etc/hohai-checkin.env"

red() { printf '\033[31m%s\033[0m\n' "$*"; }
green() { printf '\033[32m%s\033[0m\n' "$*"; }
yellow() { printf '\033[33m%s\033[0m\n' "$*"; }

require_root() {
  if [[ "${EUID}" -ne 0 ]]; then
    red "请使用 root 或 sudo 运行此脚本。"
    exit 1
  fi
}

ask() {
  local prompt="$1"
  local default="${2:-}"
  local val
  if [[ -n "$default" ]]; then
    read -r -p "$prompt [$default]: " val
    echo "${val:-$default}"
  else
    read -r -p "$prompt: " val
    echo "$val"
  fi
}

ask_secret() {
  local prompt="$1"
  local val
  read -r -s -p "$prompt: " val
  echo
  echo "$val"
}

require_root

yellow "=== HohaiCheckin VPS 交互式部署脚本 ==="

echo ""
PROJECT_SRC=$(ask "请输入当前项目源码目录（应包含 checkin.py）" "$(pwd)")
if [[ ! -f "$PROJECT_SRC/checkin.py" ]]; then
  red "未找到 $PROJECT_SRC/checkin.py，请在项目目录执行或输入正确路径。"
  exit 1
fi

PROJECT_DST=$(ask "请输入部署目录" "$PROJECT_DIR_DEFAULT")
RUN_USER=$(ask "请输入运行用户" "actions")
RUN_GROUP=$(ask "请输入运行用户组" "$RUN_USER")
RUN_TIME=$(ask "请输入每日执行时间（HH:MM，Asia/Shanghai）" "08:08")
HEADLESS=$(ask "HEADLESS 模式（true/false）" "true")

HOHAI_UN=$(ask "Hohai 用户名（HOHAI_UN）")
HOHAI_PW=$(ask_secret "Hohai 密码（HOHAI_PW）")

TG_ENABLE=$(ask "是否配置 Telegram 通知？(y/N)" "N")
HOHAI_TGTK=""
HOHAI_TGID=""
if [[ "$TG_ENABLE" =~ ^[Yy]$ ]]; then
  HOHAI_TGTK=$(ask_secret "Telegram Bot Token（HOHAI_TGTK）")
  HOHAI_TGID=$(ask "Telegram Chat ID（HOHAI_TGID）")
fi

yellow "\n[1/7] 安装系统依赖..."
apt update
apt install -y python3 python3-pip rsync

yellow "[2/7] 同步项目到部署目录..."
mkdir -p "$PROJECT_DST"
rsync -av --delete "$PROJECT_SRC/" "$PROJECT_DST/"
chown -R "$RUN_USER:$RUN_GROUP" "$PROJECT_DST"

if [[ ! -f "$PROJECT_DST/requirements.txt" ]]; then
  red "部署目录缺少 requirements.txt，终止。"
  exit 1
fi

yellow "[3/7] 安装 Python 依赖..."
python3 -m pip install --break-system-packages -r "$PROJECT_DST/requirements.txt"
python3 -m playwright install chromium

yellow "[4/7] 写入环境变量文件 $ENV_FILE ..."
cat > "$ENV_FILE" <<EOF
HOHAI_UN=$HOHAI_UN
HOHAI_PW=$HOHAI_PW
HEADLESS=$HEADLESS
HOHAI_TGTK=$HOHAI_TGTK
HOHAI_TGID=$HOHAI_TGID
EOF
chmod 600 "$ENV_FILE"

SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"
TIMER_FILE="/etc/systemd/system/${SERVICE_NAME}.timer"

HOUR=${RUN_TIME%:*}
MIN=${RUN_TIME#*:}
if [[ ! "$HOUR" =~ ^[0-9]{1,2}$ || ! "$MIN" =~ ^[0-9]{1,2}$ ]]; then
  red "时间格式错误，应为 HH:MM"
  exit 1
fi

# Keep leading zeros safely
printf -v HOUR "%02d" "$HOUR"
printf -v MIN "%02d" "$MIN"

yellow "[5/7] 生成 systemd service/timer..."
cat > "$SERVICE_FILE" <<EOF
[Unit]
Description=Hohai Daily Check-in (Python)
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
WorkingDirectory=$PROJECT_DST
EnvironmentFile=-$ENV_FILE
ExecStart=/usr/bin/python3 $PROJECT_DST/checkin.py
User=$RUN_USER
Group=$RUN_GROUP
Nice=10
StandardOutput=append:/var/log/hohai-checkin.log
StandardError=append:/var/log/hohai-checkin.log
EOF

cat > "$TIMER_FILE" <<EOF
[Unit]
Description=Run Hohai check-in daily

[Timer]
OnCalendar=*-*-* ${HOUR}:${MIN}:00 Asia/Shanghai
Persistent=true
Unit=${SERVICE_NAME}.service

[Install]
WantedBy=timers.target
EOF

yellow "[6/7] 重新加载并启用定时器..."
systemctl daemon-reload
systemctl enable --now "${SERVICE_NAME}.timer"

yellow "[7/7] 立即执行一次自检..."
systemctl start "${SERVICE_NAME}.service"

sleep 1

green "\n部署完成 ✅"
echo "- Service: ${SERVICE_NAME}.service"
echo "- Timer:   ${SERVICE_NAME}.timer"
echo "- Env:     ${ENV_FILE}"
echo ""
echo "查看状态："
echo "  systemctl status ${SERVICE_NAME}.timer"
echo "  systemctl status ${SERVICE_NAME}.service"
echo "  journalctl -u ${SERVICE_NAME}.service -n 200 --no-pager"
echo "  tail -n 200 /var/log/hohai-checkin.log"
