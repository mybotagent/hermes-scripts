#!/bin/bash
# ~/.hermes/scripts/wiki_reindex.sh
# hermes-wiki submodule sync + Neo4j incremental reindex (hermes 박스 전용).
set -euo pipefail

WIKI_SUPER="${WIKI_SUPER:-$HOME/hermes-wiki-super}"
LOG="${LOG:-$HOME/.hermes/logs/wiki-reindex.log}"
VENV="${VENV:-$HOME/.venv-neo4j}"

# Log rotation: 1MB 초과 시 roll (.log.bak)
if [ -f "$LOG" ] && [ "$(stat -c %s "$LOG" 2>/dev/null || echo 0)" -gt 1048576 ]; then
  mv "$LOG" "$LOG.bak"
fi

mkdir -p "$(dirname "$LOG")"
cd "$WIKI_SUPER"

# Sync submodule + incremental reindex
git submodule update --remote wiki/hermes-wiki 2>&1 | tail -3

# Use the neo4j venv explicitly (system python3 lacks the neo4j driver)
if [ -x "$VENV/bin/python3" ]; then
  PY="$VENV/bin/python3"
else
  PY="$(command -v python3)"
fi
"$PY" .metagraph/index_incremental.py
