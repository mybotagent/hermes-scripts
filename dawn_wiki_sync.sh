#!/bin/bash
# 새벽 wiki 동기화 스크립트 (SHO-22 핫픽스 적용)
# LLM 없이 git sync만 수행. no_agent 모드.
# 실행: 매일 04:00 KST (평일)
#
# SHO-22 해결 사항:
#   ① stash → pull → pop 순서
#   ② push rejected 시 pull --rebase && push 재시도
#   ③ orphan submodule 자동 정리
#   ④ set -e 제거하고 개별 실패는 OR 처리 (안전한 진행)

# NOTE: set -e 제거 — 각 단계는 || true 또는 명시적 처리로 안전 보장
# cron set -euo pipefail 호환: bash strict mode 회피용

WIKI_DIR="$HOME/.hermes/wiki"
HERMES_ROOT="$HOME/.hermes"
LOG_PREFIX="[dawn-wiki-sync]"
LOG_DIR="$HERMES_ROOT/logs/dawn-wiki-sync"
mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/$(date '+%Y%m%d_%H%M%S').log"

exec > >(tee -a "$LOG_FILE") 2>&1

echo "$LOG_PREFIX 시작: $(date '+%Y-%m-%d %H:%M KST')"

# 0. orphan submodule 정리 (SHO-22 ③)
echo "$LOG_PREFIX orphan submodule 정리..."
cd "$WIKI_DIR"
git rm --cached code/stock-analysis-toolkit 2>/dev/null || true

# 1. hermes-wiki pull (변경사항 자동 stash, rebase 중단 정리)
echo "$LOG_PREFIX rebase 정리 + stash + pull + pop (SHO-22 ①)..."
cd "$WIKI_DIR"
git rebase --abort 2>/dev/null || true
rm -rf .git/rebase-merge 2>/dev/null || true

# stash → pull → pop 순서 (이슈에서 명시한 권장 순서)
git stash push --include-untracked -m "dawn-wiki-auto-stash" 2>/dev/null || true
# pull 실패는 OR 처리 (set -e 의존 제거)
git pull --rebase origin main || echo "$LOG_PREFIX ⚠️ pull 실패 (무시 가능)"
git stash pop 2>/dev/null || true

# 2. submodule 업데이트 (재귀) — 에러 나도 무시
echo "$LOG_PREFIX submodule 업데이트..."
git submodule update --init --recursive --remote --merge || echo "$LOG_PREFIX ⚠️ submodule 업데이트 실패"

# 3. 변경사항 스테이징
git add -A

# 4. 변경사항 있으면 커밋 + 푸시 (rejected 시 pull 재시도) — SHO-22 ②
if ! git diff --cached --quiet 2>/dev/null; then
    COMMIT_MSG="auto-sync $(date '+%Y-%m-%d %H:%M') KST"
    git commit -m "$COMMIT_MSG"
    echo "$LOG_PREFIX ✅ 커밋: $COMMIT_MSG"

    echo "$LOG_PREFIX git push..."
    # push 시도 1회
    if git push origin main; then
        echo "$LOG_PREFIX ✅ 푸시 완료 (1회)"
    else
        # 실패 → pull --rebase + push 재시도
        echo "$LOG_PREFIX ⚠️ push rejected — pull --rebase 후 재시도 (SHO-22 ②)"
        if git pull --rebase origin main && git push origin main; then
            echo "$LOG_PREFIX ✅ 푸시 완료 (재시도 성공)"
        else
            echo "$LOG_PREFIX ❌ 푸시 최종 실패 — cron self-heal 대상"
            exit 2  # self-healing이 감지할 nonzero exit
        fi
    fi
else
    echo "$LOG_PREFIX ✅ 변경사항 없음 — skip"
fi

echo "$LOG_PREFIX 완료: $(date '+%Y-%m-%d %H:%M KST')"
exit 0
