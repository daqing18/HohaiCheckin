#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$PROJECT_DIR"

# Load optional env file (recommended for systemd)
if [[ -f /etc/hohai-checkin.env ]]; then
  # shellcheck disable=SC1091
  source /etc/hohai-checkin.env
fi

: "${HOHAI_UN:?HOHAI_UN is required}"
: "${HOHAI_PW:?HOHAI_PW is required}"

python3 checkin.py
