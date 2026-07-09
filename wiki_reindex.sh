#!/bin/bash
# ~/.hermes/scripts/wiki_reindex.sh
# hermes-wiki submodule sync + Neo4j incremental reindex (hermes 박스 전용).
set -euo pipefail

WIKI_SUPER="${WIKI_SUPER:-$HOME/hermes-wiki-super}"
LOG="${LOG:-$HOME/.hermes/logs/wiki-reindex.log}"

# Log rotation: 1MB 초과 시 roll (.log.bak)
if [ -f "$LOG" ] && [ "$(stat -c %s "$LOG" 2>/dev/null || echo 0)" -gt 1048576 ]; then
  mv "$LOG" "$LOG.bak"
fi

mkdir -p "$(dirname "$LOG")"
cd "$WIKI_SUPER"

# Sync submodule + incremental reindex
git submodule update --remote wiki/hermes-wiki 2>&1 | tail -3
python3 .metagraph/index_incremental.py
