#!/bin/bash
# pr_review_check.sh — PR review 상태 체크 wrapper
# 평일 09:00, 14:00, 19:00 KST 실행
# 변화 있을 때만 Discord 알림

set -uo pipefail

HH="${HERMES_HOME:-/home/ubuntu/.hermes}"
SCRIPT="$HH/scripts/pr_review_monitor.py"
LOG="/tmp/pr_review_check.log"

OUTPUT=$(python3 "$SCRIPT" 2>&1)
RC=$?

echo "$OUTPUT" >> "$LOG"

# 변화 없으면 silent (cron deliver=local)
if echo "$OUTPUT" | grep -qE "\[(STATE|REVIEW|COMMENT|CI)\]"; then
  # 변화 있음 → Discord로 알림
  echo "📬 **PR Review Update**"
  echo "$OUTPUT"
  exit 0  # cron은 정상 종료 (출력으로 알림)
fi

# 변화 없음 → silent
exit 0