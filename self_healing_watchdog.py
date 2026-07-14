#!/usr/bin/env python3
"""self_healing_watchdog.py — 통합 self-healing (no_agent).

sh 실행:
  python3 ~/.hermes/scripts/self_healing_watchdog.py
  출력: 에러/액션이 있을 때만 stdout (없으면 silent)

역할:
  1. Stale lock cleanup (120초+)
  2. Dashboard(9199) 헬스체크 + 재시작
  3. jobs.json 에러 탐지 + 직접 재실행 (오늘 2회까지)
  4. 404 + 위험 deliver 3회 누적 시 → origin으로 자동 fix
  5. next_run_at 24h+ silent skip
  6. ★ 재시도 2회 초과 시 → 자동 fix → LLM 근본 원인 분석 → Discord webhook 통보

작성: 2026-07-10 — 사용자 지적: "재시도만 하지 말고 근본 원인 찾아서 해결"
"""
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.request
from datetime import datetime, timezone

# ── 상수 ──
HERMES_HOME = os.environ.get('HERMES_HOME') or os.path.expanduser('~/.hermes')
JOBS_JSON = f'{HERMES_HOME}/cron/jobs.json'
JOBS_JSON_BAK = f'{HERMES_HOME}/cron/jobs.json.bak'
LOCK_FILE = f'{HERMES_HOME}/cron/.tick.lock'
FLAG_FILE = f'{HERMES_HOME}/cron/.heal_needed'
RETRY_DB = f'{HERMES_HOME}/cron/.heal_retries.json'
ERR_404_DB = f'{HERMES_HOME}/cron/.heal_404_retries.json'
ROOT_CAUSE_DB = f'{HERMES_HOME}/cron/.heal_root_cause.json'
HEAL_LOG = f'{HERMES_HOME}/cron/.heal_history.log'
HERMES_CLI = 'python3 -m hermes_cli.main'
NOW_EPOCH = int(datetime.now(tz=timezone.utc).timestamp())
TODAY = datetime.now(tz=timezone.utc).strftime('%Y-%m-%d')

DANGEROUS_DELIVER = re.compile(r'^discord:\d+(:\d*)?$')
SKIP_THRESHOLD_HOURS = 24
LLM_CACHE_TTL_HOURS = 1   # v2: 6h → 1h — 자동 fix 안 되는 진단은 더 자주 재평가
STALE_LOCK_SEC = 120
OLD_LOCK_SEC = 1800   # 자동 fix 임계 (30분)


# ── env helper ──
def _env_lookup(key):
    # v2 (2026-07-13): 멀티 후보 — Discord env, main .env 둘 다 시도
    candidates = [
        f'{HERMES_HOME}/.env.discord_webhook',
        f'{HERMES_HOME}/.env',
        f'{os.path.expanduser("~")}/.env',
    ]
    for env_path in candidates:
        if not os.path.exists(env_path):
            continue
        try:
            with open(env_path) as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith('#'):
                        continue
                    if line.startswith(f'{key}='):
                        val = line.split('=', 1)[1].strip().strip('"').strip("'")
                        if val:
                            return val
        except Exception:
            continue
    return ''


DEEPSEEK_KEY = os.environ.get('DEEPSEEK_API_KEY') or _env_lookup('DEEPSEEK_API_KEY')
DISCORD_WEBHOOK = (
    os.environ.get('DISCORD_WEBHOOK_ROOT_CAUSE')
    or _env_lookup('DISCORD_WEBHOOK_ROOT_CAUSE')
)


# ── 1. Stale lock cleanup ──
def cleanup_stale_lock():
    if not os.path.exists(LOCK_FILE):
        return None
    try:
        age = NOW_EPOCH - int(os.path.getmtime(LOCK_FILE))
    except Exception:
        return None
    if age > STALE_LOCK_SEC:
        try:
            os.remove(LOCK_FILE)
            return f'stale .tick.lock 제거 ({age}초)'
        except Exception:
            return None
    return None


# ── 2. Dashboard 헬스체크 ──
def check_dashboard():
    try:
        out = subprocess.run(
            'ss -tlnp 2>/dev/null | grep -q ":9199 "',
            shell=True, timeout=3,
        )
        if out.returncode == 0:
            return None
    except Exception:
        return None
    try:
        subprocess.Popen(
            'nohup hermes dashboard --port 9199 --host 127.0.0.1 '
            '--skip-build --no-open >/dev/null 2>&1 &',
            shell=True, start_new_session=True,
        )
        time.sleep(2)
        return 'Dashboard(:9199) 재시작 명령 전송'
    except Exception as e:
        return f'Dashboard 재시작 시도 실패: {str(e)[:80]}'


# ── DB helpers ──
def load_db(path):
    if not os.path.exists(path):
        return {}
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return {}


def save_db(path, obj):
    try:
        tmp = path + '.tmp'
        with open(tmp, 'w') as f:
            json.dump(obj, f, indent=1)
        os.replace(tmp, path)
        return True
    except Exception:
        return False


# ── 자동 fix 후보 판정 (LLM 호출 전 시도) ──
def suggest_auto_fix(jid, name, deliver, last_error):
    """(fix_action_keyword, description) 또는 (None, 설명) 반환.
    fix_action_keyword는 apply_fix()에서 매칭."""
    err = (last_error or '').lower()

    if '404' in err and DANGEROUS_DELIVER.match(deliver or ''):
        return ('reset_deliver_to_origin', 'discord 404: 잘못된 thread/forum ID → origin 복구')

    if any(k in err for k in ('lock', 'stale', 'another tick is running')):
        if os.path.exists(LOCK_FILE):
            try:
                age = NOW_EPOCH - int(os.path.getmtime(LOCK_FILE))
            except Exception:
                age = 0
            if age > OLD_LOCK_SEC:
                return ('remove_stale_lock', f'{age}초 stale lock 강제 정리')

    if 'modulenotfounderror' in err or 'no module named' in err:
        return ('reload_env', 'venv 또는 PYTHONPATH 확인 필요')

    if '429' in err:
        return ('wait_backoff', 'rate limit — 자연 cooldown 60분 대기')

    return (None, '자동 fix 매핑 없음 — LLM 분석 or 수동 개입 필요')


def apply_fix(fix_action):
    """시스템이 즉시 적용 가능한 fix. 성공 여부 반환. jobs.json 변경 시 job_data는 외부에서."""
    if fix_action == 'reset_deliver_to_origin':
        # caller가 j_ref 변경 + persist
        return True
    if fix_action == 'remove_stale_lock':
        try:
            os.remove(LOCK_FILE)
            return True
        except Exception:
            return False
    return False


# ── LLM 호출 (DeepSeek API) ──
def call_llm_analyze(jid, name, deliver, status, last_error, recent_history):
    if not DEEPSEEK_KEY:
        # v2 (2026-07-13): 키 진짜 없으면 거짓 진단 대신 silent + retry 마커
        # 이전: 'LLM 키 미설정' → confidence:low → 무한 알림 루프
        return {
            'root_cause': 'watchdog LLM 키 미설정 — 자동 fix 시도 생략, 다음 사이클에 retry',
            'fix_action': 'silence_until_key_present',
            'auto_fixable': False,
            'confidence': 'low',
            'note': 'DEEPSEEK_API_KEY 누락 — alert 대신 silent',
        }
    prompt = '\n'.join([
        '너는 시스템 자동복구 분석가다. 아래 cron 작업이 실패했어.',
        '**구체적인 근본 원인** 1~2문장, **즉시 적용 가능한 자동 fix** (auto_fixable=True/False), **사용자가 확인해야 할 결정** 3가지 필드로 JSON만 답해.',
        '',
        'cron:',
        f'- id: {jid}',
        f'- name: {name}',
        f'- status: {status}',
        f'- deliver: {deliver}',
        f'- last_error: {last_error[:300]}',
        f'- recent_history: {recent_history[-3:]}',
        '',
        '응답 스키마 (JSON):',
        'root_cause, fix_action, auto_fixable(bool), confidence(high|medium|low) — 4개 필드 JSON만 답해.',
    ])
    try:
        req_body = json.dumps({
            'model': 'deepseek-chat',
            'messages': [{'role': 'user', 'content': prompt}],
            'temperature': 0.2,
            'max_tokens': 400,
        }).encode()
        req = urllib.request.Request(
            'https://api.deepseek.com/v1/chat/completions',
            data=req_body,
            headers={
                'Authorization': f'Bearer {DEEPSEEK_KEY}',
                'Content-Type': 'application/json',
            },
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            payload = json.loads(resp.read().decode())
        text = payload['choices'][0]['message']['content'].strip()
        m = re.search(r'\{[\s\S]*\}', text)
        if not m:
            raise ValueError('JSON 추출 실패')
        parsed = json.loads(m.group(0))
        parsed.setdefault('auto_fixable', False)
        parsed.setdefault('confidence', 'low')
        parsed.setdefault('root_cause', text[:200])
        parsed.setdefault('fix_action', '수동 진단 필요')
        return parsed
    except Exception as e:
        return {
            'root_cause': f'LLM 호출 실패: {str(e)[:100]}',
            'fix_action': '수동 진단 필요',
            'auto_fixable': False,
            'confidence': 'low',
            'note': f'llm_error: {str(e)[:80]}',
        }


# ── Discord webhook ──
def send_discord(webhook_url, title, body, color=0xff5555):
    if not webhook_url:
        return False
    embed = {
        'title': title,
        'description': body[:1900],
        'color': color,
        'footer': {'text': 'hermes self-healing watchdog (root-cause) | 2026-07-10'},
        'timestamp': datetime.now(tz=timezone.utc).isoformat(),
    }
    payload = json.dumps({'embeds': [embed]}).encode()
    try:
        req = urllib.request.Request(webhook_url, data=payload, headers={'Content-Type': 'application/json'})
        with urllib.request.urlopen(req, timeout=8) as resp:
            return resp.status in (200, 204)
    except Exception:
        return False


# ============================================================
# Main
# ============================================================
def main():
    msgs = []

    msg = cleanup_stale_lock()
    if msg:
        msgs.append(f'⛓️  {msg}')

    msg = check_dashboard()
    if msg:
        msgs.append(f'🏥 {msg}')

    if not os.path.exists(JOBS_JSON):
        return

    with open(JOBS_JSON) as f:
        jobs_data = json.load(f)
    jobs_list = jobs_data.get('jobs', [])

    retries = load_db(RETRY_DB)
    err_404_db = load_db(ERR_404_DB)
    root_cause_db = load_db(ROOT_CAUSE_DB)
    retries.setdefault(TODAY, {})

    healed = []
    skipped = []
    skipped_perm = []
    auto_fixed = []
    skipped_remote = []
    root_cause_actions = []

    jobs_dirty = False

    for j in jobs_list:
        status = j.get('last_status', '')
        delivery_error = j.get('last_delivery_error') or ''
        jid = j.get('id', '')
        name = j.get('name', jid[:12])
        deliver = j.get('deliver', '')

        needs_heal = (status == 'error') or (status == 'ok' and bool(delivery_error))
        if not needs_heal:
            continue
        if jid == 'af8dcb9a1cce':
            continue

        err = delivery_error.lower()
        code_match = None
        for code in ('401', '403', '404', '429', '500', '502', '503', '504'):
            if code in err:
                code_match = code
                break

        if status == 'ok' and code_match in ('401', '403'):
            skipped_perm.append((jid, name, code_match, delivery_error[:80]))
            continue

        if status == 'ok' and delivery_error:
            next_run_at = j.get('next_run_at')
            if next_run_at:
                try:
                    nr_dt = datetime.fromisoformat(next_run_at.replace('Z', '+00:00'))
                    hours_until = (nr_dt - datetime.fromtimestamp(NOW_EPOCH, tz=timezone.utc)).total_seconds() / 3600
                    if hours_until > SKIP_THRESHOLD_HOURS:
                        skipped_remote.append((jid, name, hours_until))
                        continue
                except Exception:
                    pass

        # 404 + 위험 deliver 누적
        if code_match == '404' and DANGEROUS_DELIVER.match(deliver):
            count = err_404_db.get(jid, 0) + 1
            err_404_db[jid] = count
            if count >= 3:
                old_deliver = deliver
                j['deliver'] = 'origin'
                jobs_dirty = True
                auto_fixed.append((jid, name, old_deliver, count, 'OK'))
                err_404_db[jid] = 0
            continue

        day_retries = retries[TODAY].get(jid, 0)

        # ─────────────────────────────────────────────────────
        # ★ 재시도 2회 초과 → 자동 fix → LLM 분석 → Discord 통보
        # ─────────────────────────────────────────────────────
        if day_retries >= 2:
            fix_action, fix_desc = suggest_auto_fix(jid, name, deliver, delivery_error)
            fix_applied = False

            if fix_action == 'reset_deliver_to_origin':
                # 변경: caller에서 이미 dirty 마킹은 다음 루프에서, 하지만 즉시 적용
                try:
                    j['deliver'] = 'origin'
                    jobs_dirty = True
                    fix_applied = True
                    err_404_db[jid] = 0
                    auto_fixed.append((jid, name, deliver, 999, f'AUTO_FIX[reset_deliver]: {fix_desc}'))
                except Exception as e:
                    auto_fixed.append((jid, name, deliver, 999, f'AUTO_FIX_ERR: {str(e)[:60]}'))
            elif fix_action == 'remove_stale_lock':
                if apply_fix('remove_stale_lock'):
                    fix_applied = True
                    auto_fixed.append((jid, name, deliver, 999, f'AUTO_FIX[stale_lock]: {fix_desc}'))
            else:
                # reload_env / wait_backoff / None → 자동 적용 불가
                pass

            if fix_applied:
                save_db(JOBS_JSON, jobs_data) if False else None  # defer save at end
                retries[TODAY][jid] = 0
                root_cause_actions.append((jid, name, 'auto_fix_only', fix_desc, 'APPLIED', True))
                continue

            # ─────────────────────────────────────────────────
            # LLM 분석 (캐시 우선)
            # ─────────────────────────────────────────────────
            recent_history = []
            try:
                with open(HEAL_LOG) as hl:
                    lines = hl.readlines()[-20:]
                    recent_history = [l.strip() for l in lines if jid[:12] in l]
            except Exception:
                pass

            cached = root_cause_db.get(jid)
            if cached and (NOW_EPOCH - cached.get('ts', 0)) < LLM_CACHE_TTL_HOURS * 3600:
                llm_result = cached['result']
                llm_source = 'cache'
            else:
                llm_result = call_llm_analyze(jid, name, deliver, status, delivery_error, recent_history)
                llm_source = 'live'
                root_cause_db[jid] = {'ts': NOW_EPOCH, 'result': llm_result}

            root_cause = llm_result.get('root_cause', 'unknown')
            fix_action_rec = llm_result.get('fix_action', '수동 진단 필요')
            confidence = llm_result.get('confidence', 'low')
            auto_fixable = llm_result.get('auto_fixable', False)

            bool_fix = '예 (자동 fix 가능)' if auto_fixable else '아니오 (수동 확인 필요)'
            # v2 (2026-07-13): silence_until_key_present → Discord 알림 skip (무한 알림 방지)
            if fix_action_rec == 'silence_until_key_present':
                discord_sent = False
                root_cause_actions.append((
                    jid, name, root_cause, fix_action_rec,
                    'SILENT_NO_KEY', False,
                ))
                skipped.append((jid, name, day_retries))
                continue
            title = f'🔴 재시도 초과 + 근본 원인 ({confidence} conf)'
            body = '\n'.join([
                f'**job**: `{name}` (`{jid[:12]}`)',
                f'**status**: `{status}` · **err**: `{delivery_error[:200]}`',
                f'**deliver**: `{deliver}`',
                '',
                f'**🎯 근본 원인**: {root_cause}',
                '',
                f'**🛠 권고 fix**: {fix_action_rec}',
                '',
                f'**🤖 자동 fix 가능**: {bool_fix}',
                f'**📡 분석 출처**: {llm_source}',
            ])
            discord_sent = send_discord(DISCORD_WEBHOOK, title, body)

            root_cause_actions.append((
                jid, name, root_cause, fix_action_rec,
                'AWAITING_MANUAL' if not auto_fixable else 'FIXABLE_BUT_NOT_YET',
                discord_sent,
            ))
            skipped.append((jid, name, day_retries))
            continue

        # ─────────────────────────────────────────────────────
        # 일반 retry (2회 미만)
        # ─────────────────────────────────────────────────────
        try:
            result = subprocess.run(
                f'{HERMES_CLI} cron run {jid} --accept-hooks',
                shell=True, capture_output=True, text=True, timeout=30,
            )
            retries[TODAY][jid] = day_retries + 1
            stdout_short = (result.stdout or '').strip()[:80]
            stderr_short = (result.stderr or '').strip()[:80]
            msg_text = stdout_short if result.returncode == 0 else stderr_short
            healed.append((jid, name, code_match or 'unknown', msg_text))
        except Exception as e:
            retries[TODAY][jid] = day_retries + 1
            healed.append((jid, name, code_match or 'unknown', f'CLI_ERROR: {str(e)[:60]}'))

    # ─────────────────────────────────────────────────
    # persist
    # ─────────────────────────────────────────────────
    if jobs_dirty:
        # backup → atomic write
        try:
            shutil.copy2(JOBS_JSON, JOBS_JSON_BAK)
            save_db(JOBS_JSON, jobs_data)
        except Exception:
            pass

    save_db(RETRY_DB, retries)
    save_db(ERR_404_DB, err_404_db)
    save_db(ROOT_CAUSE_DB, root_cause_db)

    ts = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    try:
        with open(HEAL_LOG, 'a') as hl:
            for jid, name, code, _ in healed:
                job = next((x for x in jobs_list if x.get('id') == jid), {})
                kind = f'delivery_retry_triggered[{code}]' if (
                    job.get('last_status') == 'ok' and job.get('last_delivery_error')
                ) else 'retry_triggered'
                hl.write(f'{ts} {jid} {name} {kind}\n')
            for jid, name, code, snippet in skipped_perm:
                hl.write(f'{ts} {jid} {name} permanent_error[{code}] {snippet}\n')
            for jid, name, old_deliver, count, status_msg in auto_fixed:
                hl.write(f'{ts} {jid} {name} AUTO_FIX count={count} old={old_deliver} [{status_msg}]\n')
            for jid, name, hours in skipped_remote:
                hl.write(f'{ts} {jid} {name} skip_retry_next_run_too_far ({hours:.1f}h)\n')
            for entry in root_cause_actions:
                jid, name, root_cause, fix_action_rec, status, *rest = entry
                dc = rest[0] if rest else False
                dc_str = f' discord={"OK" if dc else "FAIL"}'
                hl.write(
                    f'{ts} {jid} {name} ROOT_CAUSE_ANALYZED status={status}'
                    f' cause={root_cause[:60]} fix={fix_action_rec[:60]}{dc_str}\n'
                )
    except Exception:
        pass

    if os.path.exists(FLAG_FILE):
        try:
            os.remove(FLAG_FILE)
        except Exception:
            pass

    # ─────────────────────────────────────────────────
    # 출력
    # ─────────────────────────────────────────────────
    has_output = False
    if healed:
        has_output = True
        print(f'[HEAL] {len(healed)} job(s) 재실행 시작')
        for jid, name, code, msg in healed:
            print(f'  ✅ {jid[:12]}: {name} [{code}] → {msg}')
    if skipped:
        has_output = True
        print(f'  ⚠️  {len(skipped)} job(s) 재시도 초과 — 근본 원인 분석 발동')
        for jid, name, cnt in skipped:
            print(f'  - {jid[:12]}: {name} ({cnt}회)')
    if skipped_perm:
        has_output = True
        print(f'  🚫 {len(skipped_perm)} job(s) 영구 에러 — 수동 개입 필요')
        for jid, name, code, snippet in skipped_perm:
            print(f'  ! {jid[:12]}: {name} [{code}] {snippet}')
    if auto_fixed:
        has_output = True
        print(f'  🔧 {len(auto_fixed)} job(s) AUTO-FIX')
        for jid, name, old, cnt, msg in auto_fixed:
            print(f'  + {jid[:12]}: {name} (누적 {cnt}회) {old} → {msg}')
    if root_cause_actions:
        has_output = True
        print(f'  🧠 {len(root_cause_actions)} job(s) LLM 근본 원인 분석 → Discord 통보')
        for entry in root_cause_actions:
            jid, name, root_cause, fix_action_rec, status, *rest = entry
            dc = rest[0] if rest else False
            print(f'  · {jid[:12]}: {name} | discord={"✅" if dc else "❌"}')
            print(f'    원인: {root_cause[:100]}')
            print(f'    fix : {fix_action_rec[:100]} [{status}]')

    if not has_output and msgs:
        for m in msgs:
            print(m)


if __name__ == '__main__':
    main()
