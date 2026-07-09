#!/usr/bin/env bash
# daily-repo-orchestrator (mirror-only production)
#
# 매일 07:00 KST (= 22:00 UTC) 호출.
# - harvest/mirror: 실제 (Linear + kanban read+create)
# - fix/PR/email: dry (push 안 함)
# - idempotency: 동일 title 재호출 시 reuse
#
# set -euo pipefail 제거 (cycle 실패해도 cron이 안 죽도록)
set -uo pipefail

# env 로드 (HERMES_HOME 자동 분기)
if [ -f "${HOME:-/home/ubuntu}/.hermes/.env" ]; then
    set -a; source "${HOME:-/home/ubuntu}/.hermes/.env"; set +a
elif [ -f "${HOME:-/home/ubuntu}/.env" ]; then
    set -a; source "${HOME:-/home/ubuntu}/.env"; set +a
else
    echo "[$(date -Iseconds)] .env not found" >&2
    exit 1
fi

export DRY_RUN=0
export DRY_RUN_HARVEST=0   # GitHub read-only
export DRY_RUN_MIRROR=0    # Linear + kanban create (idempotent)
export DRY_RUN_FIX=1       # ❌ push/PR 안 함 (dry)
export DRY_RUN_EMAIL=1     # ❌ email 발송 안 함 (dry)
export HERMES_HOME="${HERMES_HOME:-/home/ubuntu/.hermes}"

LOG_DIR="${HERMES_HOME}/scripts/logs"
mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/orchestrator-$(date +%Y%m%d-%H%M%S).log"

echo "[$(date -Iseconds)] daily-repo-orchestrator mirror-only cycle" | tee -a "$LOG_FILE"
python3 "${HERMES_HOME}/skills/daily-repo-orchestrator/scripts/daily_repo_orchestrator.py" 2>&1 | tee -a "$LOG_FILE"
RC=${PIPESTATUS[0]}
echo "[$(date -Iseconds)] exit=$RC" | tee -a "$LOG_FILE"
exit $RC
