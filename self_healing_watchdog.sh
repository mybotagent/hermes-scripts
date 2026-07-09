#!/bin/bash
# self_healing_watchdog.sh — 통합 self-healing (no_agent 단독)
# 역할: stale lock cleanup + 에러 감지 + cron 재실행 + Dashboard 자동복구
#       + 404 deliver 형식 자동 fix (2026-07-01)
#       + next_run_at 24h+ silent skip (2026-07-01 신규) — cron 재실행까지 시간 여유 시 retry noise 방지
#
# 실행: no_agent=true, schedule "*/10 * * * 1-5"
# stdout → 에러 메시지 있을 때만 출력 (없으면 silent)

set -e

HERMES_HOME="${HERMES_HOME:-$HOME/.hermes}"
JOBS_JSON="$HERMES_HOME/cron/jobs.json"
JOBS_JSON_BAK="$HERMES_HOME/cron/jobs.json.bak"
LOCK_FILE="$HERMES_HOME/cron/.tick.lock"
FLAG_FILE="$HERMES_HOME/cron/.heal_needed"
RETRY_DB="$HERMES_HOME/cron/.heal_retries.json"
ERR_404_DB="$HERMES_HOME/cron/.heal_404_retries.json"
NOW_EPOCH=$(date +%s)
TODAY=$(date +%Y-%m-%d)
HEAL_LOG="$HERMES_HOME/cron/.heal_history.log"
HERMES_CLI="python3 -m hermes_cli.main"

# ── 1. Stale lock cleanup ──
if [ -f "$LOCK_FILE" ]; then
    LOCK_AGE=$(( NOW_EPOCH - $(stat -c %Y "$LOCK_FILE" 2>/dev/null || echo "$NOW_EPOCH") ))
    if [ "$LOCK_AGE" -gt 120 ]; then
        rm -f "$LOCK_FILE"
        echo "[$(date '+%H:%M:%S')] ⛓️ stale .tick.lock 제거 (${LOCK_AGE}초)"
    fi
fi

# ── 2. Dashboard(9199) 헬스체크 ──
if ! ss -tlnp 2>/dev/null | grep -q ':9199 '; then
    # Dashboard down → restart
    cd "$HOME" && nohup hermes dashboard --port 9199 --host 127.0.0.1 --skip-build --no-open > /dev/null 2>&1 &
    DASH_PID=$!
    sleep 2
    if ss -tlnp 2>/dev/null | grep -q ':9199 '; then
        echo "[$(date '+%H:%M:%S')] 🏥 Dashboard(:9199) 재시작 완료 (PID $DASH_PID)"
    else
        echo "[$(date '+%H:%M:%S')] 🏥 Dashboard(:9199) 재시작 명령 전송"
    fi
fi

# ── 3. jobs.json 에러 탐지 + 직접 재실행 + 404 deliver 자동 fix + next_run_at 24h+ skip ──
if [ ! -f "$JOBS_JSON" ]; then
    exit 0
fi

python3 -c "
import json, os, subprocess, re, shutil
from datetime import datetime, timezone

with open('$JOBS_JSON') as f:
    data = json.load(f)

jobs_list = data.get('jobs', [])
today = '$TODAY'
now_epoch = $NOW_EPOCH
hermes_cli = '$HERMES_CLI'

retry_db_path = '$RETRY_DB'
retries = {}
if os.path.exists(retry_db_path):
    try:
        with open(retry_db_path) as rf:
            retries = json.load(rf)
    except:
        retries = {}

# 404 deliver 자동 fix 카운터 (2026-07-01)
err_404_db_path = '$ERR_404_DB'
err_404_db = {}
if os.path.exists(err_404_db_path):
    try:
        with open(err_404_db_path) as rf:
            err_404_db = json.load(rf)
    except:
        err_404_db = {}

if today not in retries:
    retries[today] = {}

healed = []
skipped = []
skipped_perm = []   # 401/403 등 재시도 무의미한 영구 에러 (운영자 알림용)
auto_fixed = []     # 404 deliver 자동 fix (2026-07-01)
skipped_remote = [] # next_run_at 24h+ silent skip (2026-07-01 신규)

# 위험 deliver 패턴: discord:{숫자} 또는 discord:{숫자}: 또는 discord:{숫자}: (빈 thread)
# 안전한 패턴: discord:{숫자}:{17-20자리 threadID}
DANGEROUS_DELIVER = re.compile(r'^discord:\d+(:\d*)?$')

# ── 24h 시간 상수 (next_run_at 거리 threshold) ──
SKIP_THRESHOLD_HOURS = 24

for j in jobs_list:
    status = j.get('last_status', '')
    delivery_error = j.get('last_delivery_error') or ''
    jid = j.get('id', '')
    name = j.get('name', jid[:12])
    deliver = j.get('deliver', '')

    # ── 자가 치유 대상 판정 ──
    needs_heal = (status == 'error') or (status == 'ok' and bool(delivery_error))
    if not needs_heal:
        continue
    # 자기 자신(agent healer) 제외
    if jid == 'af8dcb9a1cce':
        continue

    # ── 에러 분류 ──
    err = delivery_error.lower()
    code_match = None
    for code in ('401', '403', '404', '429', '500', '502', '503', '504'):
        if code in err:
            code_match = code
            break
    permanent_codes = ('401', '403')
    if status == 'ok' and code_match in permanent_codes:
        skipped_perm.append((jid, name, code_match, delivery_error[:80]))
        continue

    # ── next_run_at 24h+ skip (2026-07-01 신규) ──
    # status='ok' && delivery_error 케이스에서만: cron 재실행까지 시간 여유 있으면 silent skip
    # (예: 매월 1일 cron의 7월 1일 실패 기록 → 8월 1일까지 retry noise 방지)
    if status == 'ok' and delivery_error:
        next_run_at = j.get('next_run_at')
        if next_run_at:
            try:
                nr_dt = datetime.fromisoformat(next_run_at.replace('Z', '+00:00'))
                now_dt = datetime.fromtimestamp(now_epoch, tz=timezone.utc)
                hours_until = (nr_dt - now_dt).total_seconds() / 3600
                if hours_until > SKIP_THRESHOLD_HOURS:
                    skipped_remote.append((jid, name, hours_until))
                    continue
            except Exception:
                pass  # parse 실패 시 기존 retry 로직 진행

    # ── 404 + 위험 deliver 패턴 → 3회 누적 시 자동 fix ──
    if code_match == '404' and DANGEROUS_DELIVER.match(deliver):
        count = err_404_db.get(jid, 0) + 1
        err_404_db[jid] = count
        if count >= 3:
            old_deliver = deliver
            j['deliver'] = 'origin'
            try:
                shutil.copy2('$JOBS_JSON', '$JOBS_JSON_BAK')
                tmp = '$JOBS_JSON' + '.tmp'
                with open(tmp, 'w') as f:
                    json.dump(data, f, indent=2, ensure_ascii=False)
                os.replace(tmp, '$JOBS_JSON')
                auto_fixed.append((jid, name, old_deliver, count, 'OK'))
            except Exception as e:
                auto_fixed.append((jid, name, old_deliver, count, f'FIX_ERROR: {str(e)[:60]}'))
            continue
        # 1~2회 → 카운트만 증가, retry 진행

    day_retries = retries[today].get(jid, 0)
    if day_retries >= 2:
        skipped.append((jid, name, day_retries))
        continue

    # 직접 cron 재실행 via Hermes CLI
    try:
        result = subprocess.run(
            f'{hermes_cli} cron run {jid} --accept-hooks',
            shell=True, capture_output=True, text=True, timeout=30
        )
        retries[today][jid] = day_retries + 1
        healed.append((jid, name, code_match or 'unknown', result.stdout.strip()[:80] if result.returncode == 0 else result.stderr.strip()[:80]))
    except Exception as e:
        retries[today][jid] = day_retries + 1
        healed.append((jid, name, code_match or 'unknown', f'CLI_ERROR: {str(e)[:60]}'))

# retry DB 저장
with open(retry_db_path, 'w') as rf:
    json.dump(retries, rf, indent=1)

# 404 deliver 카운터 저장
with open(err_404_db_path, 'w') as rf:
    json.dump(err_404_db, rf, indent=1)

# 히스토리 로그
ts = '$(date '+%Y-%m-%d %H:%M:%S') KST'
with open('$HEAL_LOG', 'a') as hl:
    for jid, name, code, _ in healed:
        job = next((x for x in jobs_list if x.get('id') == jid), {})
        kind = f'delivery_retry_triggered[{code}]' if (job.get('last_status') == 'ok' and job.get('last_delivery_error')) else 'retry_triggered'
        hl.write(f'{ts} {jid} {name} {kind}\n')
    for jid, name, code, snippet in skipped_perm:
        hl.write(f'{ts} {jid} {name} permanent_error[{code}] {snippet}\n')
    for jid, name, old_deliver, count, status_msg in auto_fixed:
        hl.write(f'{ts} {jid} {name} AUTO_FIX_404_DELIVER count={count} old={old_deliver} -> origin [{status_msg}]\n')
    for jid, name, hours in skipped_remote:
        hl.write(f'{ts} {jid} {name} skip_retry_next_run_too_far ({hours:.1f}h)\n')

# Flag 파일 정리
if os.path.exists('$FLAG_FILE'):
    os.remove('$FLAG_FILE')

# 출력 (skipped_remote는 silent — 다음 cron 실행까지 시간 여유 알림 안 함)
if healed:
    print(f'[HEAL] {len(healed)} job(s) 재실행 시작')
    for jid, name, code, msg in healed:
        print(f'  ✅ {jid[:12]}: {name} [{code}] → {msg}')
if skipped:
    print(f'  ⚠️ {len(skipped)} job(s) 재시도 초과 (오늘 2회)')
    for jid, name, cnt in skipped:
        print(f'  - {jid[:12]}: {name} ({cnt}회)')
if skipped_perm:
    print(f'  🚫 {len(skipped_perm)} job(s) 영구 에러 — 수동 개입 필요')
    for jid, name, code, snippet in skipped_perm:
        print(f'  ! {jid[:12]}: {name} [{code}] {snippet}')
if auto_fixed:
    print(f'  🔧 {len(auto_fixed)} job(s) AUTO-FIX 404 deliver → origin')
    for jid, name, old_deliver, count, status_msg in auto_fixed:
        print(f'  + {jid[:12]}: {name} (누적 {count}회) {old_deliver} → origin [{status_msg}]')
" 2>&1

exit 0
