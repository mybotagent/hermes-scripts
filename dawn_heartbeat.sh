#!/usr/bin/env bash
# dawn_heartbeat.sh — 새벽 15분 heartbeat (KST 0-5시)
# 목적: 시스템 sanity / cron scheduler / GitHub reachability 가벼운 체크.
# 비대중: 다른 활성 cron 발화 시각 ±2분 안이면 90초 sleep → 1회 retry → 그래도 충돌이면 silent exit.
# 출력: 정상 = silent, 이상 = stdout 1줄 + log append.
# SAFE: read-only, 외부 쓰기/푸시/이메일 없음.

set -euo pipefail

LOG=/home/ubuntu/.hermes/cron/output/dawn_heartbeat.log
mkdir -p "$(dirname "$LOG")"

LOCK=/tmp/dawn_heartbeat.lock
if [ -f "$LOCK" ]; then
  old_pid=$(cat "$LOCK" 2>/dev/null || echo 0)
  if [ -n "$old_pid" ] && kill -0 "$old_pid" 2>/dev/null; then
    exit 0
  fi
  rm -f "$LOCK"
fi
echo $$ > "$LOCK"
trap 'rm -f "$LOCK"' EXIT

# 비대중 시각 (KST HH:MM) — 다른 활성 cron 발화 시각
# 자동 추출 시도 → 실패 시 폴백
HERMES_BIN=""
for cand in /home/ubuntu/.hermes/bin/hermes /usr/local/bin/hermes $(command -v hermes 2>/dev/null || true); do
  if [ -x "$cand" ]; then HERMES_BIN="$cand"; break; fi
done

busy_list=$(mktemp)
if [ -n "$HERMES_BIN" ]; then
  $HERMES_BIN cronjob list --json 2>/dev/null | jq -r --arg self "dawn-heartbeat-15m" \
    '.jobs[] | select(.enabled) | select(.name != $self) | .schedule' \
    > "$busy_list" 2>/dev/null || true
fi

# 비대중 가드
now_hm=$(date +%H:%M)
now_min=$((10#${now_hm%:*} * 60 + 10#${now_hm#*:}))

is_busy() {
  local cur_min=$1 list=$2
  # 각 스케줄 표현의 시각/분 파싱 (단순 버전: "분 시 일 월 요일" 또는 "*/N 시")
  while read -r sched; do
    [ -z "$sched" ] && continue
    # 첫 두 필드만 사용
    m=$(echo "$sched" | awk '{print $1}')
    h=$(echo "$sched" | awk '{print $2}')
    # 매 시각 (정시 +30분) 검사
    case " $h " in
      *"*"*|*"0-23"*|*"0-5"*) ;;  # 와일드카드/광범위 → 매 시각
      *) continue ;;
    esac
    # 분 매칭: *, */N, 콤마 리스트
    case "$m" in
      "*"|"*/15"|"*/30"|"*/10")
        # 매 N분 → 정시 0분이면 비교
        if [ "$cur_min" -ge 0 ] 2>/dev/null; then
          # cur_min 자체가 시각 × 60 + 0/15/30/45 인지 확인
          mod=$((cur_min % 60))
          if [ "$mod" -le 2 ] || [ "$mod" -ge 58 ]; then return 0; fi
        fi
        ;;
      "0"|"30"|"29"|"50")
        mod=$((cur_min % 60))
        if [ "$mod" -eq 0 ] || [ "$mod" -eq 29 ] || [ "$mod" -eq 30 ] || [ "$mod" -eq 50 ]; then
          return 0
        fi
        ;;
      *)
        # 콤마 리스트의 첫 토큰만
        first=$(echo "$m" | cut -d, -f1)
        if [ "$first" = "0" ] || [ "$first" = "30" ] || [ "$first" = "29" ] || [ "$first" = "50" ]; then
          mod=$((cur_min % 60))
          if [ "$mod" -eq 0 ] || [ "$mod" -eq 29 ] || [ "$mod" -eq 30 ] || [ "$mod" -eq 50 ]; then
            return 0
          fi
        fi
        ;;
    esac
  done < "$list"
  return 1
}

if is_busy "$now_min" "$busy_list"; then
  sleep 90
  now_hm=$(date +%H:%M)
  now_min=$((10#${now_hm%:*} * 60 + 10#${now_hm#*:}))
  if is_busy "$now_min" "$busy_list"; then
    rm -f "$busy_list"
    exit 0
  fi
fi
rm -f "$busy_list"

# 시스템 sanity
hostname_s=$(hostname)
now_kst=$(TZ=Asia/Seoul date '+%Y-%m-%d %H:%M:%S %Z')

disk_pct=$(df -P / 2>/dev/null | awk 'NR==2 {gsub("%",""); print $5}')
disk_pct=${disk_pct:-0}
mem_avail=$(free -m 2>/dev/null | awk '/^Mem:/ {print $7}')
mem_avail=${mem_avail:-0}
load1=$(uptime 2>/dev/null | awk -F'load average:' '{print $2}' | awk '{print $1}' | tr -d ',' )
load1=${load1:-0}

# cron scheduler sanity
cron_count="?"
if [ -n "$HERMES_BIN" ]; then
  cron_count=$($HERMES_BIN cronjob list --json 2>/dev/null | jq '.count' 2>/dev/null || echo "?")
fi

# GitHub API reachability
if curl -fsS --max-time 5 -o /dev/null -I https://api.github.com 2>/dev/null; then
  gh_status="ok"
else
  gh_status="FAIL"
fi

# Anomaly 검출
anomaly=0
reason=""
if [ "$disk_pct" -ge 90 ] 2>/dev/null; then anomaly=1; reason="${reason} disk=${disk_pct}%"; fi
if [ "$mem_avail" -lt 512 ] 2>/dev/null; then anomaly=1; reason="${reason} mem=${mem_avail}M"; fi
if [ "$gh_status" = "FAIL" ]; then anomaly=1; reason="${reason} gh_unreachable"; fi

line="[${now_kst}] host=${hostname_s} disk=${disk_pct}% mem_avail=${mem_avail}M load1=${load1} cron_count=${cron_count} gh=${gh_status}"
echo "$line" >> "$LOG"

# 정상 = silent, 이상만 stdout
if [ "$anomaly" -eq 1 ]; then
  echo "⚠️ dawn_heartbeat anomaly:${reason} | ${line}"
fi
