#!/bin/bash
# self_healing_watchdog.sh — 통합 self-healing (no_agent 단독 wrapper)
# 본체는 self_healing_watchdog.py (bash heredoc 의존성 제거).
#
# 실행: no_agent=true, schedule "*/10 * * * 1-5"
# stdout → 에러 메시지 있을 때만 출력 (없으면 silent)

set -e

HERMES_HOME="${HERMES_HOME:-$HOME/.hermes}"
SCRIPT_DIR="$HERMES_HOME/scripts"
python3 "$SCRIPT_DIR/self_healing_watchdog.py"

exit 0
