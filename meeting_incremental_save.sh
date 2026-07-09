#!/bin/bash
# Meeting Incremental Save — 회의 중간 저장 자동화
#
# 사용법:
#   meeting_incremental_save.sh HHMM_topic-slug                     # 오늘 회의 (auto-detect 최신 날짜)
#   meeting_incremental_save.sh YYYY-MM-DD HHMM_topic-slug          # 명시적 날짜
#   meeting_incremental_save.sh HHMM_topic-slug "Phase 3 결정"      # 커스텀 메시지
#
# 동작:
#   1. meeting-notes/YYYY/MM/DD/HHMM_topic-slug/ 위치 확인
#   2. agenda.md의 frontmatter status (in-progress / done)
#   3. discussion.md의 Phase 수 카운트
#   4. git add + commit + push (in-progress snapshot)
#
# aiprofit 명시 요구 (2026-06-29):
#   - 회의 시작하면 폴더 + 빈 4파일 즉시
#   - 매 Phase 끝마다 incremental commit + push
#   - 회의 도중 강제 종료 시점에도 GitHub에 백업 보장

set +e
# set -e 의도적으로 사용 안 함 — grep -c의 exit 1도 정상 처리하기 위함.
# 우리는 모든 단계를 명시적으로 처리하므로 set -e 의존 불필요.
# 이걸로 중간 exit도 안전하게 (사용자가 Ctrl-C 등으로 끊어도 일부 단계가 끝난 상태로 남음)

NOTES_DIR="${HOME}/meeting-notes"

# 1) 날짜 폴더 결정 (YYYY/MM/DD)
DATE_DIR=""
if [[ "$1" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}$ ]]; then
    # 1st arg = 날짜
    YYYY="${1%-[0-9][0-9]-[0-9][0-9]}"
    MM_DD="${1#*-}"
    MM="${MM_DD%-[0-9][0-9]}"
    DD="${MM_DD#*-}"
    DATE_DIR="$NOTES_DIR/$YYYY/$MM/$DD"
    shift  # 날짜 인자 소비
fi

SLUG="${1:?Usage: $0 [YYYY-MM-DD] HHMM_topic-slug [commit message]}"
CUSTOM_MSG="${2:-}"

# 2) 명시적 날짜 없으면 최신 YYYY/MM/DD 폴더 선택
if [ -z "$DATE_DIR" ] || [ ! -d "$DATE_DIR" ]; then
    DATE_DIR=""
    LATEST_TS=""
    while IFS= read -r line; do
        TS=$(echo "$line" | awk '{print $1}')
        DIR=$(echo "$line" | awk '{print $2}')
        [ -z "$DIR" ] && continue
        case "$DIR" in *".git"*) continue ;; esac
        REL="${DIR#$NOTES_DIR/}"
        if [[ "$REL" =~ ^[0-9]{4}/[0-9]{2}/[0-9]{2}$ ]]; then
            if [ -z "$LATEST_TS" ] || awk "BEGIN {exit !($TS > $LATEST_TS)}"; then
                LATEST_TS="$TS"
                DATE_DIR="$DIR"
            fi
        fi
    done < <(find "$NOTES_DIR" -mindepth 3 -maxdepth 3 -type d -printf '%T@ %p\n' 2>/dev/null)
fi

if [ -z "$DATE_DIR" ] || [ ! -d "$DATE_DIR" ]; then
    echo "❌ meeting-notes 날짜 폴더 없음 (YYYY/MM/DD)" >&2
    exit 1
fi

MEETING_DIR="$DATE_DIR/$SLUG"
if [ ! -d "$MEETING_DIR" ]; then
    echo "❌ 회의 폴더 없음: $MEETING_DIR" >&2
    echo "Available in $(basename $DATE_DIR):" >&2
    ls "$DATE_DIR" | sed 's/^/    /' >&2
    exit 1
fi

# 3) Phase 카운트 (빈 파일이면 0)
if [ -s "$MEETING_DIR/discussion.md" ]; then
    PHASE_COUNT=$(grep -c "^## Phase" "$MEETING_DIR/discussion.md" 2>/dev/null || true)
    PHASE_COUNT="${PHASE_COUNT:-0}"
else
    PHASE_COUNT=0
fi

if [ -s "$MEETING_DIR/decisions.md" ]; then
    DECISION_COUNT=$(grep -c "^## " "$MEETING_DIR/decisions.md" 2>/dev/null || true)
    DECISION_COUNT="${DECISION_COUNT:-0}"
else
    DECISION_COUNT=0
fi

NEXT_STEPS_EXISTS="no"
[ -s "$MEETING_DIR/next_steps.md" ] && NEXT_STEPS_EXISTS="yes"

# Status (frontmatter의 status: 라인) — exit 1 안전
STATUS=$( (grep "^status:" "$MEETING_DIR/agenda.md" 2>/dev/null || true) | head -1 | awk '{print $2}')
[ -z "$STATUS" ] && STATUS="unknown"

# 커밋 메시지
if [ -n "$CUSTOM_MSG" ]; then
    MSG="$CUSTOM_MSG"
else
    SHORT_SLUG=$(basename "$SLUG")
    MSG="Meeting $SHORT_SLUG: incremental snapshot (phases=$PHASE_COUNT, decisions=$DECISION_COUNT, next_steps=$NEXT_STEPS_EXISTS, status=$STATUS)"
fi

echo "📦 Meeting incremental save"
echo "   폴더: $MEETING_DIR"
echo "   phases: $PHASE_COUNT / decisions: $DECISION_COUNT / next_steps: $NEXT_STEPS_EXISTS / status: $STATUS"
echo "   msg: $MSG"
echo ""

cd "$NOTES_DIR"

# 변경 확인
CHANGED=$(git status --porcelain)
if [ -z "$CHANGED" ]; then
    echo "✅ 변경 없음 — push 스킵"
    exit 0
fi

git add -A
if git commit -m "$MSG" 2>&1 | head -3; then
    echo ""
    echo "✅ commit 완료. push 진행..."
    if git push origin main 2>&1 | tail -2; then
        echo ""
        echo "✅ push 완료. 회의 진행 안전."
    else
        echo "⚠️ push 실패 — 로컬에는 저장됨, 다음 commit에서 재시도"
    fi
else
    echo "❌ commit 실패"
    exit 1
fi

