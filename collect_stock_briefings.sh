#!/bin/bash
# Hermes Stock Briefings Collector
# 수집: ~/.hermes/cron/output/<job_id>/latest → hermes-stock-briefings/<YYYY-MM-DD>/<순서>-<이름>.md
# 실행: 매일 크론잡 완료 후 (또는 수동)
# 리포트만 저장 (프롬프트/스킬 프리앰블 제거)

set -euo pipefail

REPO_DIR="$HOME/hermes-stock-briefings"
CRON_OUTPUT_DIR="$HOME/.hermes/cron/output"
GIT_NAME="Hermes Bot"
GIT_EMAIL="hermes@aiprofit.dev"

# ============================================================
# 설정: 주식 크론잡 ID → 저장 파일명 (순서 접두사)
# ============================================================
declare -A JOBS
JOBS["6297df83d4f3"]="01-오전-포트폴리오-브리핑"
JOBS["2916cc9c2ceb"]="02-미국-증시-브리핑"
JOBS["b96583fa9d27"]="03-매크로-전략-리포트"
JOBS["afebf6cb0ab1"]="04-LangGraph-파이프라인"
JOBS["d3080e6f3789"]="05-매월-전략-리포트"
JOBS["18510b01362d"]="06-월간-성과-검증"
JOBS["23a0c9333175"]="07-월간-성장-일관성"
JOBS["d92ed6044d32"]="08-주간-스크리너"

# ============================================================
# 최신 output 파일 찾기
# ============================================================
get_latest_output() {
    local job_id="$1"
    local dir="$CRON_OUTPUT_DIR/$job_id"
    if [ ! -d "$dir" ]; then
        echo ""
        return
    fi
    local latest=$(ls -t "$dir" 2>/dev/null | head -1)
    if [ -z "$latest" ]; then
        echo ""
        return
    fi
    echo "$dir/$latest"
}

# ============================================================
# output에서 날짜 추출 (파일명: 2026-06-26_08-18-58.md)
# ============================================================
get_date_from_filename() {
    local filepath="$1"
    local basename=$(basename "$filepath")
    echo "${basename:0:10}"  # YYYY-MM-DD
}

# ============================================================
# 리포트만 추출 (프롬프트/스킬 프리앰블 제거)
# "## Response" 라인 이후의 내용만 저장
# ============================================================
extract_report() {
    local input_file="$1"
    local output_file="$2"

    # "## Response" 라인 찾기
    local response_line=$(grep -n "^## Response" "$input_file" | head -1 | cut -d: -f1)

    if [ -n "$response_line" ] && [ "$response_line" -gt 0 ]; then
        # "## Response" 다음 줄부터 끝까지 추출
        tail -n +$((response_line + 1)) "$input_file" > "$output_file"
    else
        # "## Response" 없으면 "## 역할" 다음부터? 없으면 전체 복사
        local role_line=$(grep -n "^## 역할" "$input_file" | head -1 | cut -d: -f1)
        if [ -n "$role_line" ] && [ "$role_line" -gt 0 ]; then
            local execution_line=$(grep -n "^## 실행 순서\|^## Response" "$input_file" | tail -1 | cut -d: -f1)
            if [ -n "$execution_line" ] && [ "$execution_line" -gt 0 ]; then
                tail -n +$((execution_line + 1)) "$input_file" > "$output_file"
            else
                # 마지막 fallback: "## 역할" 다음 10줄 이후부터
                tail -n +$((role_line + 15)) "$input_file" > "$output_file"
            fi
        else
            # 어떤 헤더도 없으면 전체 복사
            cp "$input_file" "$output_file"
        fi
    fi

    # 혹시 남은 프리앰블 정리: --- 로 시작하는 라인 이후만
    local cleaned=$(grep -n "^---$" "$output_file" | head -1 | cut -d: -f1)
    if [ -n "$cleaned" ] && [ "$cleaned" -gt 2 ] && [ "$cleaned" -lt 20 ]; then
        tail -n +$((cleaned + 1)) "$output_file" > "${output_file}.tmp"
        mv "${output_file}.tmp" "$output_file"
    fi
}

# ============================================================
# 메인
# ============================================================
cd "$REPO_DIR"

# Git config
git config user.name "$GIT_NAME"
git config user.email "$GIT_EMAIL"

UPDATED=0
COPIED_COUNT=0

for job_id in "${!JOBS[@]}"; do
    name="${JOBS[$job_id]}"
    latest=$(get_latest_output "$job_id")

    if [ -z "$latest" ]; then
        echo "⚠️  $job_id ($name): 실행 기록 없음, 스킵"
        continue
    fi

    date_str=$(get_date_from_filename "$latest")
    target_dir="$REPO_DIR/$date_str"
    target_file="$target_dir/$name.md"

    mkdir -p "$target_dir"

    # 임시 파일에 리포트 추출
    tmp_file=$(mktemp)
    extract_report "$latest" "$tmp_file"

    # 이미 같은 내용이면 스킵
    if [ -f "$target_file" ]; then
        if [ "$(md5sum "$tmp_file" | cut -d' ' -f1)" = "$(md5sum "$target_file" | cut -d' ' -f1)" ]; then
            echo "✓  $date_str/$name.md: 변경 없음, 스킵"
            rm -f "$tmp_file"
            continue
        fi
    fi

    mv "$tmp_file" "$target_file"
    echo "✅ $date_str/$name.md: 저장 완료"
    COPIED_COUNT=$((COPIED_COUNT + 1))
    UPDATED=1
done

# ============================================================
# Git push (변경 있을 때만)
# ============================================================
if [ "$UPDATED" -eq 1 ]; then
    git add -A
    TODAY=$(date +%Y-%m-%d)
    HOUR=$(date +%H:%M)
    git commit -m "📊 $TODAY 주식 브리핑 저장 ($HOUR, ${COPIED_COUNT}개)"
    git push origin main 2>&1
    echo "✅ GitHub push 완료 (${COPIED_COUNT}개 파일)"
else
    echo "ℹ️  변경사항 없음, push 생략"
fi
