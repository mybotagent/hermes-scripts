#!/bin/bash
# memory_daily_compact.sh — memory_auto_compact.py wrapper
# 매일 06:30 KST 실행
# - 성공 (압축 또는 skip): silent
# - 실패 (룰 부족으로 압축 못 함, drift block): Discord로 알림

set -uo pipefail

HH="${HERMES_HOME:-/home/ubuntu/.hermes}"
SCRIPT="$HH/scripts/memory_auto_compact.py"
LOG="/tmp/memory_compact.log"

# memory 압축 실행 (--force 없이 90% 임계치 자연 검사)
OUTPUT=$(python3 "$SCRIPT" 2>&1)
RC=$?

echo "$OUTPUT" >> "$LOG"

# exit code 의미:
# 0 = OK (skip or 압축 성공)
# 2 = drift block
# 3 = 룰 부족 (압축 못 함)

if [ $RC -eq 0 ]; then
  # silent (cron deliver=local)
  exit 0
elif [ $RC -eq 2 ]; then
  # drift 너무 높음 → 사용자 알림
  echo "⚠ MEMORY AUTO-COMPACT BLOCKED: drift too high"
  echo "$OUTPUT"
  exit 0  # cron 자체는 정상 종료 (출력으로 알림)
elif [ $RC -eq 3 ]; then
  # 룰 부족 → 사용자 알림
  echo "⚠ MEMORY AUTO-COMPACT FAIL: cannot reach <90% with current rules"
  echo "$OUTPUT"
  exit 0
else
  echo "⚠ MEMORY AUTO-COMPACT UNKNOWN ERROR (rc=$RC)"
  echo "$OUTPUT"
  exit 0
fi