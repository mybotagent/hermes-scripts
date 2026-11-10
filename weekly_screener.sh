#!/bin/bash
# 주간 스크리너 + 자동퇴출 wrapper
set -e
cd ~/trade-pipeline

# NOTE: cron PATH의 python3는 hermes-agent venv(판다스 미설치)로 resolves되어
# ModuleNotFoundError: pandas로 29회 연속 실패했음(2026-11-09 확인).
# trade-pipeline venv는 pandas/finvizfinance이 모두 설치되어 있으므로 우선 사용.
PY_BIN=""
for cand in "$HOME/trade-pipeline/venv/bin/python3" "$(command -v python3)"; do
    if [ -x "$cand" ] && "$cand" -c "import pandas, numpy" >/dev/null 2>&1; then
        PY_BIN="$cand"; break
    fi
done
if [ -z "$PY_BIN" ]; then
    echo "ERROR: no python3 with pandas found (tried trade-pipeline venv, system python3)" >&2
    exit 1
fi

"$PY_BIN" scripts/auto_expel.py
echo "---"
"$PY_BIN" scripts/finviz_screener.py
