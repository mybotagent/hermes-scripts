#!/usr/bin/env bash
# verdict_analyzer_weekly.sh — 주 1회 verdict 패턴 분석 (read-only)
set -uo pipefail
if [ -f "${HOME:-/home/ubuntu}/.hermes/.env" ]; then
    set -a; source "${HOME:-/home/ubuntu}/.hermes/.env"; set +a
elif [ -f "${HOME:-/home/ubuntu}/.env" ]; then
    set -a; source "${HOME:-/home/ubuntu}/.env"; set +a
fi
export HERMES_HOME="${HERMES_HOME:-/home/ubuntu/.hermes}"
python3 "${HERMES_HOME}/skills/pr-merge-gate/scripts/verdict_analyzer.py"
