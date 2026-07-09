#!/bin/bash
# ~/.hermes/scripts/memory_sync.sh
# Memory Tool → GitHub Wiki 수동 동기화 1회 실행 (가장 작은 watcher).
# 사용법: ./memory_sync.sh "TITLE" "BODY"
#
# Audit 2026-07-02:
#   - HEREDOC injection risk → printf with quoted BODY (single-pass)
#   - Stale "a-step-3" tag/trace replaced with "manual memory-sync"
#   - Hardcoded paths moved to WIKI_DIR / SLOT_DIR / RAW_DIR (env override)
#   - Cron log dir ensured (mkdir -p) at runtime
#   - Slug regex normalized (tr -s) — collapse repeated dashes
set -euo pipefail

TITLE="${1:?title required}"
BODY="${2:-body required}"

# Paths (env override for portability)
WIKI_DIR="${WIKI_DIR:-$HOME/.hermes/wiki}"
RAW_DIR="${RAW_DIR:-$WIKI_DIR/raw/sync}"
SLOT_DIR="${SLOT_DIR:-$WIKI_DIR/architecture/memory-snapshots}"
LOG_DIR="${LOG_DIR:-$HOME/.hermes/logs}"

mkdir -p "$RAW_DIR" "$SLOT_DIR" "$LOG_DIR"

DATE=$(date +%Y-%m-%d)
TS=$(date +%Y-%m-%d-%H%M)
# Slug: lowercase → collapse whitespace → dash → drop non-alnum/dash → squelch repeats
SLUG=$(printf '%s' "$TITLE" | tr '[:upper:]' '[:lower:]' | tr -s ' ' '-' | tr -cd '[:alnum:]-')

# Raw source (Karpathy wiki-save pattern)
{
  cat <<EOF
---
source: memory_sync.sh (manual)
ingested: $DATE
trigger: manual memory-sync
---

EOF
  printf '%s\n' "$BODY"
} > "$RAW_DIR/$TS-$SLUG.md"

# Page snapshot
{
  cat <<EOF
---
title: $TITLE
created: $DATE
tags: [memory-sync, snapshot]
sources: [raw/sync/$TS-$SLUG.md]
related: [../hermes-memory-pipeline.md]
---

# $TITLE

EOF
  printf '%s\n' "$BODY"
  cat <<'FOOTER'

## Provenance
- Manual watcher (memory_sync.sh)
- Reference: architecture/hermes-memory-pipeline.md
FOOTER
} > "$SLOT_DIR/$TS-$SLUG.md"

# commit + push (only if changes staged)
cd "$WIKI_DIR"
git add raw/sync architecture/memory-snapshots
git diff --cached --quiet && { echo "no changes"; exit 0; }
git commit -m "memory-sync: $TITLE"
git push origin main

echo "DONE memory-sync pushed: $TITLE"
echo "  raw: raw/sync/$TS-$SLUG.md"
echo "  page: architecture/memory-snapshots/$TS-$SLUG.md"

# Step 4 (optional, recommended): submodule sync + Neo4j reindex (~12s)
# Required for query.py to see the new page in search results.
if [ -x "$HOME/.hermes/scripts/wiki_reindex.sh" ]; then
  echo "Step 4: wiki_reindex.sh (submodule sync + Neo4j reindex)..."
  "$HOME/.hermes/scripts/wiki_reindex.sh" 2>&1 | tail -5 || echo "  (wiki_reindex.sh failed, ignorable)"
fi
