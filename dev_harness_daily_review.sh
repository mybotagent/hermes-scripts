#!/usr/bin/env bash
# dev_harness_daily_review.sh — dev-harness-kit fork 동기화 + 개선 후보 탐색 (read-only)
# Usage: dev_harness_daily_review.sh
# Output: 후보 목록 (stdout) — agent가 리뷰 후 후보 1개 선택

set -uo pipefail

REPO_DIR="$HOME/dev-harness-kit"
ENV_FILE="$HOME/.hermes/.env"
LOG_FILE="$HOME/.hermes/cron/output/dev-harness-review.log"
mkdir -p "$(dirname "$LOG_FILE")"

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" >> "$LOG_FILE"; }

# token 로드
if [ -f "$ENV_FILE" ]; then
  set -a; source "$ENV_FILE"; set +a
fi
TOKEN="${GH_TOKEN:-${GITHUB_TOKEN:-}}"

echo "=== ① fork 동기화 (리뷰 전 최신 상태 유지 — 반드시 pull) ==="
cd "$REPO_DIR" || { log "REPO_DIR 없음"; echo "❌ $REPO_DIR 없음"; exit 1; }
git checkout main 2>&1 | tail -1
# 리뷰 전 반드시 pull로 최신 상태 유지 (upstream → local main)
# fork main 직접 push 금지 — feature branch만 push
git pull upstream main --ff-only 2>&1 | tail -3 || { log "upstream pull 실패"; echo "⚠️ upstream pull 실패 (네트워크/커밋 충돌 확인)"; exit 1; }

echo ""
echo "=== ② 최근 커밋 ==="
git log --oneline -8 origin/main

echo ""
echo "=== ③ 개선 후보 탐색 (read-only) ==="

# a. skills/ 있는데 docs/skills/ 없는 스킬
echo "--- [a] skills/ ↔ docs/skills/ 불일치 ---"
for s in skills/*/; do
  name=$(basename "$s")
  [ "$name" = "_acp" ] && continue
  if [ ! -f "docs/skills/${name}.md" ]; then
    echo "  docs 누락: $name (skills/ 있음, docs/skills/${name}.md 없음)"
  fi
done

# b. 영어 docs 있는데 .ko.md 없는 스킬
echo "--- [b] .ko.md 누락 ---"
for f in docs/skills/*.md; do
  base=$(basename "$f" .md)
  case "$base" in *.ko) continue;; esac
  if [ ! -f "docs/skills/${base}.ko.md" ]; then
    echo "  ko 누락: $base (docs/skills/${base}.ko.md 없음)"
  fi
done

# c. README.md 스킬 테이블 링크 vs docs 존재
echo "--- [c] README 링크 끊김 ---"
grep -oE 'docs/skills/[a-z0-9-]+\.md' README.md | sort -u | while read -r link; do
  [ -f "$link" ] || echo "  broken link: $link"
done

# d. TODO/FIXME (간단 해결 가능한 것만 후보)
echo "--- [d] TODO/FIXME (스크립트/코드) ---"
grep -rn "TODO\|FIXME" --include="*.py" --include="*.sh" --include="*.js" --include="*.ts" . 2>/dev/null \
  | grep -v ".git/" | grep -v "logs/" | grep -v "node_modules" | head -8

# e. CHANGELOG 최신 엔트리 vs 최근 릴리스 커밋
echo "--- [e] CHANGELOG 최신 엔트리 ---"
head -20 CHANGELOG.md 2>/dev/null | grep -E "^## |^# " | head -3

# f. 열린 PR/이슈 (중복 방지용)
echo "--- [f] 열린 PR ---"
if [ -n "$TOKEN" ]; then
  curl -s -H "Authorization: token $TOKEN" \
    "https://api.github.com/repos/sh-ai-x/dev-harness-kit/pulls?state=open&per_page=10" \
    | python3 -c "
import json,sys
try:
    d=json.load(sys.stdin)
    if isinstance(d,list):
        if not d: print('  (없음)')
        for p in d: print(f\"  #{p['number']} {p['title'][:60]}\")
    else: print('  ERR:', d.get('message','?')[:80])
except Exception as e: print('  parse err:', e)"
else
  echo "  (GITHUB_TOKEN 없음)"
fi

log "review done"
echo ""
echo "=== done ==="
