#!/bin/bash
# hermes_management_update.sh — hermes-management 레포 동기화 + Docker 이미지 업데이트
# 1) git pull (GitHub ↔ local sync)
# 2) 변경 있으면 Docker rebuild
# 경고: 변경사항 없으면 조용히 종료

set -euo pipefail

REPO_DIR="$HOME/hermes-management"
LOG_FILE="$HOME/.hermes/cron/output/hermes_management_update.log"
mkdir -p "$(dirname "$LOG_FILE")"

echo "[$(date '+%Y-%m-%d %H:%M:%S')] Starting hermes-management update check..." >> "$LOG_FILE"

cd "$REPO_DIR"

# 1. git fetch + check for changes
git fetch origin main 2>&1 >> "$LOG_FILE"

LOCAL_HASH=$(git rev-parse HEAD)
REMOTE_HASH=$(git rev-parse origin/main)

if [ "$LOCAL_HASH" = "$REMOTE_HASH" ]; then
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] No changes. Exiting." >> "$LOG_FILE"
    exit 0
fi

# 2. Pull changes
echo "[$(date '+%Y-%m-%d %H:%M:%S')] Changes detected! Pulling..." >> "$LOG_FILE"
git pull origin main 2>&1 >> "$LOG_FILE"

# 3. Docker rebuild if container exists or docker-compose available
if command -v docker &>/dev/null; then
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Rebuilding Docker image..." >> "$LOG_FILE"
    cd "$REPO_DIR"
    docker compose build hermes-management 2>&1 >> "$LOG_FILE"
    
    # Recreate container if running
    if docker ps -a --format '{{.Names}}' | grep -q '^hermes-management$'; then
        echo "[$(date '+%Y-%m-%d %H:%M:%S')] Restarting hermes-management container..." >> "$LOG_FILE"
        docker compose up -d --no-deps hermes-management 2>&1 >> "$LOG_FILE"
    else
        echo "[$(date '+%Y-%m-%d %H:%M:%S')] Container not running. Skipping restart." >> "$LOG_FILE"
    fi
else
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Docker not available. Skipping rebuild." >> "$LOG_FILE"
fi

echo "[$(date '+%Y-%m-%d %H:%M:%S')] Update complete." >> "$LOG_FILE"
