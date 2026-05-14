#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR_DEFAULT="/opt/HohaiCheckin"
SERVICE_NAME="hohai-checkin"
ENV_FILE="/etc/hohai-checkin.env"
LOG_FILE="/var/log/hohai-checkin.log"

red() { printf '\033[31m%s\033[0m\n' "$*"; }
green() { printf '\033[32m%s\033[0m\n' "$*"; }
yellow() { printf '\033[33m%s\033[0m\n' "$*"; }
blue() { printf '\033[36m%s\033[0m\n' "$*"; }

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

check_cmd() {
  command -v "$1" >/dev/null 2>&1
}

detect_phase() {
  blue "=== 预检查（先检测后安装） ==="
  echo "- OS: $(grep PRETTY_NAME= /etc/os-release | cut -d= -f2- | tr -d '"')"
  echo "- Kernel: $(uname -r)"

  if check_cmd python3; then
    echo "- python3: $(python3 --version 2>/dev/null)"
  else
    echo "- python3: 未安装"
  fi

  if python3 -m pip --version >/dev/null 2>&1; then
    echo "- pip: $(python3 -m pip --version 2>/dev/null)"
  else
    echo "- pip: 不可用"
  fi

  if python3 -c 'import playwright' >/dev/null 2>&1; then
    echo "- playwright(py): 已安装"
  else
    echo "- playwright(py): 未安装"
  fi

  if check_cmd rsync; then
    echo "- rsync: 已安装"
  else
    echo "- rsync: 未安装"
  fi

  if systemctl list-unit-files | grep -q "^${SERVICE_NAME}.service"; then
    echo "- ${SERVICE_NAME}.service: 已存在"
  else
    echo "- ${SERVICE_NAME}.service: 未安装"
  fi

  if systemctl list-unit-files | grep -q "^${SERVICE_NAME}.timer"; then
    echo "- ${SERVICE_NAME}.timer: 已存在"
  else
    echo "- ${SERVICE_NAME}.timer: 未安装"
  fi

  echo ""
}

uninstall_all() {
  blue "=== 一键卸载与残留清理 ==="

  local project_dst
  project_dst=$(ask "请输入部署目录（将被删除）" "$PROJECT_DIR_DEFAULT")

  yellow "停止并移除 systemd 单元..."
  systemctl disable --now "${SERVICE_NAME}.timer" 2>/dev/null || true
  systemctl stop "${SERVICE_NAME}.service" 2>/dev/null || true

  rm -f "/etc/systemd/system/${SERVICE_NAME}.service"
  rm -f "/etc/systemd/system/${SERVICE_NAME}.timer"
  systemctl daemon-reload
  systemctl reset-failed || true

  yellow "删除环境文件与日志..."
  rm -f "$ENV_FILE"
  rm -f "$LOG_FILE"

  yellow "删除部署目录..."
  rm -rf "$project_dst"

  green "卸载完成 ✅"
  echo "已清理：service/timer/env/log/project"
  exit 0
}

install_flow() {
  yellow "=== HohaiCheckin VPS 交互式安装 ==="

  local project_src project_dst run_user run_group run_time headless
  project_src=$(ask "请输入当前项目源码目录（应包含 checkin.py）" "$(pwd)")
  if [[ ! -f "$project_src/checkin.py" ]]; then
    red "未找到 $project_src/checkin.py，请在项目目录执行或输入正确路径。"
    exit 1
  fi

  project_dst=$(ask "请输入部署目录" "$PROJECT_DIR_DEFAULT")
  run_user=$(ask "请输入运行用户" "actions")
  run_group=$(ask "请输入运行用户组" "$run_user")
  run_time=$(ask "请输入每日执行时间（HH:MM，Asia/Shanghai）" "08:08")
  headless=$(ask "HEADLESS 模式（true/false）" "true")

  local hohai_un hohai_pw tg_enable hohai_tgtk hohai_tgid
  hohai_un=$(ask "Hohai 用户名（HOHAI_UN）")
  hohai_pw=$(ask_secret "Hohai 密码（HOHAI_PW）")

  tg_enable=$(ask "是否配置 Telegram 通知？(y/N)" "N")
  hohai_tgtk=""
  hohai_tgid=""
  if [[ "$tg_enable" =~ ^[Yy]$ ]]; then
    hohai_tgtk=$(ask_secret "Telegram Bot Token（HOHAI_TGTK）")
    hohai_tgid=$(ask "Telegram Chat ID（HOHAI_TGID）")
  fi

  yellow "[1/7] 安装系统依赖（仅缺失项）..."
  apt update
  local pkgs=()
  check_cmd python3 || pkgs+=(python3)
  python3 -m pip --version >/dev/null 2>&1 || pkgs+=(python3-pip)
  check_cmd rsync || pkgs+=(rsync)
  if [[ ${#pkgs[@]} -gt 0 ]]; then
    apt install -y "${pkgs[@]}"
  else
    echo "依赖已满足，跳过 apt 安装。"
  fi

  yellow "[2/7] 同步项目到部署目录..."
  mkdir -p "$project_dst"
  rsync -av --delete "$project_src/" "$project_dst/"
  chown -R "$run_user:$run_group" "$project_dst"

  if [[ ! -f "$project_dst/requirements.txt" ]]; then
    red "部署目录缺少 requirements.txt，终止。"
    exit 1
  fi

  yellow "[3/7] 安装 Python 依赖（requirements + playwright）..."
  python3 -m pip install --break-system-packages -r "$project_dst/requirements.txt"
  python3 -m playwright install chromium

  yellow "[4/7] 写入环境变量文件 $ENV_FILE ..."
  cat > "$ENV_FILE" <<EOF
HOHAI_UN=$hohai_un
HOHAI_PW=$hohai_pw
HEADLESS=$headless
HOHAI_TGTK=$hohai_tgtk
HOHAI_TGID=$hohai_tgid
EOF
  chmod 600 "$ENV_FILE"

  local service_file timer_file
  service_file="/etc/systemd/system/${SERVICE_NAME}.service"
  timer_file="/etc/systemd/system/${SERVICE_NAME}.timer"

  local hour min
  hour=${run_time%:*}
  min=${run_time#*:}
  if [[ ! "$hour" =~ ^[0-9]{1,2}$ || ! "$min" =~ ^[0-9]{1,2}$ ]]; then
    red "时间格式错误，应为 HH:MM"
    exit 1
  fi
  printf -v hour "%02d" "$hour"
  printf -v min "%02d" "$min"

  yellow "[5/7] 生成 systemd service/timer..."
  cat > "$service_file" <<EOF
[Unit]
Description=Hohai Daily Check-in (Python)
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
WorkingDirectory=$project_dst
EnvironmentFile=-$ENV_FILE
ExecStart=/usr/bin/python3 $project_dst/checkin.py
User=$run_user
Group=$run_group
Nice=10
StandardOutput=append:$LOG_FILE
StandardError=append:$LOG_FILE
EOF

  cat > "$timer_file" <<EOF
[Unit]
Description=Run Hohai check-in daily

[Timer]
OnCalendar=*-*-* ${hour}:${min}:00 Asia/Shanghai
Persistent=true
Unit=${SERVICE_NAME}.service

[Install]
WantedBy=timers.target
EOF

  yellow "[6/7] 启用定时器..."
  systemctl daemon-reload
  systemctl enable --now "${SERVICE_NAME}.timer"

  yellow "[7/7] 立即执行一次自检..."
  systemctl start "${SERVICE_NAME}.service"
  sleep 1

  green "部署完成 ✅"
  echo "查看状态："
  echo "  systemctl status ${SERVICE_NAME}.timer"
  echo "  systemctl status ${SERVICE_NAME}.service"
  echo "  journalctl -u ${SERVICE_NAME}.service -n 200 --no-pager"
  echo "  tail -n 200 $LOG_FILE"
}

main() {
  require_root
  detect_phase

  local action
  action=$(ask "请选择操作: install / uninstall" "install")
  case "$action" in
    install) install_flow ;;
    uninstall) uninstall_all ;;
    *) red "未知操作：$action"; exit 1 ;;
  esac
}

main "$@"
