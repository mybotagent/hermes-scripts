#!/bin/bash
# 주간 스크리너 + 자동퇴출 wrapper
set -e
cd ~/trade-pipeline
python3 scripts/auto_expel.py
echo "---"
python3 scripts/finviz_screener.py
