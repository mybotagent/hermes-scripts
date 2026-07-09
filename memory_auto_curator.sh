#!/usr/bin/env bash
# memory_auto_curator.sh — 주 1회 wiki/memory 상태 점검 + 보고서
# SAFE: read-only. wiki/memory/skill 상태 점검만 → stdout 리포트.
set -uo pipefail
HH="${HERMES_HOME:-/home/ubuntu/.hermes}"

echo "[memory-curator] $(date -Iseconds)"
echo "--- WIKI TOP-LEVEL ---"
ls -la "$HH/wiki/" 2>/dev/null | head -20
echo "--- INDEX SIZE ---"
for f in INDEX.md index.md; do
  if [ -f "$HH/wiki/$f" ]; then
    wc -l "$HH/wiki/$f" 2>/dev/null
  fi
done
echo "--- MEMORY SIZE ---"
for f in MEMORY.md memory.md; do
  if [ -f "$HH/$f" ]; then
    wc -l "$HH/$f" 2>/dev/null
  fi
done
echo "--- USER SIZE ---"
for f in USER.md user.md; do
  if [ -f "$HH/$f" ]; then
    wc -l "$HH/$f" 2>/dev/null
  fi
done
echo "--- SKILLS ---"
find "$HH/skills" -maxdepth 2 -name "SKILL.md" 2>/dev/null | wc -l
echo "--- RECENT LOG ENTRIES (last 5) ---"
tail -5 "$HH/wiki/LOG.md" 2>/dev/null
echo "--- DONE ---"
