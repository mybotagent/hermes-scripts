#!/usr/bin/env bash
# ~/.hermes/scripts/hermes_config_sync.sh
# Hermes config (wiki + skills + scripts + cron + memories) → mybotagent/* GitHub 기록용 push.
# 매일 KST 22:30 (= 13:30 UTC) cron에서 호출.
#
# 단방향: 로컬 → GitHub (사용자 원칙 — github은 기록용, pull/drift ❌)
# 단일공식: 4 sub-steps / failure-isolated / idempotent / no secrets commit
# push-first (사용자 2026-07-09 결정 — "자율운영 안 됨" 진단 후):
#   DRY_RUN=0이 default. cron이 push까지 끝냄. 사용자가 DRY_RUN=1 env로
#   1회 preview만 가능. (rule: github은 기록용, push는 자동)
# 404 sub-step: repo 없으면 그대로 skip (다음 sync 때 자동 retry).
#
# set -uo pipefail (NOT -e: 서브스텝 실패 격리)
set -uo pipefail

# ---- Env ----------------------------------------------------------------
: "${HERMES_HOME:=/home/ubuntu/.hermes}"
: "${HOME:=/home/ubuntu}"
: "${DRY_RUN:=0}"            # default push (2026-07-09 rule)
: "${REPORT_DELIVERY:=origin}"
LOG_DIR="${HERMES_HOME}/cron/output"
mkdir -p "$LOG_DIR"
LOG_FILE="${LOG_DIR}/hermes-config-sync-$(date -u +%Y%m%d-%H%M%S)-UTC.log"

ts() { date -u +%Y-%m-%dT%H:%M:%SZ; }
say() { echo "[$(ts)] $*" | tee -a "$LOG_FILE"; }
die() { say "ERROR: $*" >&2; }

say "===== hermes-config-sync START (DRY_RUN=$DRY_RUN, HERMES_HOME=$HERMES_HOME) ====="

# ---- Step 0: token + access pre-flight ---------------------------------
TOKEN=$(grep ^GITHUB_TOKEN= "${HERMES_HOME}/.env" 2>/dev/null | cut -d= -f2- | tr -d '"' | tr -d "'" || true)
if [ -z "${TOKEN:-}" ]; then
  say "PRE-FLIGHT: GITHUB_TOKEN missing → all push steps skipped (record only)"
  DRY_RUN=1
fi

# repo access probe (HEAD); 200=OK, 404=missing, 401/403=forbidden
gh_repo() {
  local repo="$1"
  curl -sS -o /dev/null -w "%{http_code}" \
    -H "Authorization: token ${TOKEN:-nopentoken}" \
    "https://api.github.com/repos/${repo}" 2>/dev/null || echo "000"
}

# sub-step wrapper: local_path, github_repo, description
# behaviour:
#   - 404 → warn + skip (사용자 confirm 필요 — DESIGN §6)
#   - DRY_RUN=1 → git add + diff, push NO, log만
#   - DRY_RUN=0 → git add + commit + push (only if changed)
#   - 각 sub-step 비-zero exit 격리 (try/catch via `|| true`)
sync_substep() {
  local label="$1" local_path="$2" github_repo="$3" branch="${4:-main}"
  say "--- sub-step: $label ($local_path → $github_repo) ---"

  if [ ! -d "$local_path/.git" ]; then
    say "  SKIP: $local_path is not a git repo (bare clone / init required)"
    return 0
  fi

  local code; code=$(gh_repo "$github_repo")
  case "$code" in
    200) say "  access: 200 OK" ;;
    404) say "  SKIP (404): $github_repo not found — user must create. dry record only."; return 0 ;;
    401|403) say "  SKIP ($code): token lacks access to $github_repo"; return 0 ;;
    *)    say "  SKIP ($code): unknown API response"; return 0 ;;
  esac

  (
    cd "$local_path"
    # fetch origin/main (또는 fallback)
    git fetch origin "$branch" 2>>"$LOG_FILE" || say "  fetch warn"
    # dirty check
    if git diff --quiet HEAD 2>/dev/null && git diff --quiet --cached 2>/dev/null; then
      say "  no local changes"
      exit 0
    fi
    git add -A
    if git diff --cached --quiet; then
      say "  nothing staged"; exit 0
    fi

    if [ "$DRY_RUN" = "1" ]; then
      local n; n=$(git diff --cached --numstat | wc -l)
      say "  DRY: would commit $n file(s) → $github_repo"
      git diff --cached --numstat | head -20 | sed 's/^/    /' >>"$LOG_FILE"
      exit 0
    fi

    git -c user.name="hermes-config-sync[bot]" \
        -c user.email="hermes-config-sync@users.noreply.github.com" \
        commit -m "hermes-config-sync: $(ts) ($label)" >>"$LOG_FILE" 2>&1
    git push origin "$branch" 2>&1 | tee -a "$LOG_FILE"
    say "  PUSHED → $github_repo@$branch"
  ) || say "  sub-step '$label' failed (isolated)"
  return 0
}

# ---- Step ① wiki (이미 origin 설정됨) ----------------------------------
sync_substep "wiki"        "${HERMES_HOME}/wiki"        "mybotagent/hermes-wiki" "main"

# ---- Step ② skills (mirror bare git 필요 — git submodule 변환 옵션) ---
# ~/.hermes/skills는 평범한 fs → mirror bare clone을 만들어 push.
# 첫 실행에서만 init, 이후엔 push만.
SKILLS_MIRROR="${HERMES_HOME}/.mirror/skills.git"
SKILLS_MIRROR_STAGE="${HERMES_HOME}/.mirror/skills-stage"
ensure_mirror_stage() {
  local label="$1" mirror="$2" stage="$3" src="$4" repo="$5"
  shift 5
  # remaining args = extra rsync excludes (label-scoped)
  mkdir -p "$(dirname "$mirror")"
  if [ ! -d "$mirror" ]; then
    (
      # try clone origin first, if 404 user-confirm 대기
      local code; code=$(gh_repo "$repo")
      if [ "$code" = "200" ]; then
        git clone --bare "https://github.com/${repo}.git" "$mirror" 2>>"$LOG_FILE" && \
          say "  mirror clone OK: $repo" && return 0
      else
        say "  mirror init: $repo unreachable ($code) — bare init locally"
        git init --bare "$mirror" >>"$LOG_FILE" 2>&1
        return 0
      fi
    )
  fi
  if [ ! -d "$stage" ]; then
    git clone "$mirror" "$stage" 2>>"$LOG_FILE"
    # seed first-import: track remote main branch (origin 없으면 commit only)
    (
      cd "$stage" 2>/dev/null || return 0
      git checkout -B main 2>/dev/null || true
      git remote set-url origin "https://github.com/${repo}.git" 2>/dev/null || \
        git remote add origin "https://github.com/${repo}.git"
    )
  fi
  # rsync src → stage (excluding obvious junk + per-label extras + own .git)
  rsync -a --delete \
    --exclude '.git' --exclude '.git/' --exclude '.git/**' \
    --exclude '.bundled_manifest' \
    --exclude '__pycache__' --exclude '*.pyc' \
    --exclude '.DS_Store' \
    "$@" \
    "$src"/ "$stage"/ 2>>"$LOG_FILE"
}

say "--- sub-step: skills (mirror) ---"
code=$(gh_repo "mybotagent/hermes-skills")
if [ "$code" = "200" ]; then
  ensure_mirror_stage "skills" "$SKILLS_MIRROR" "$SKILLS_MIRROR_STAGE" \
    "${HERMES_HOME}/skills" "mybotagent/hermes-skills"
  sync_substep "skills-stage" "$SKILLS_MIRROR_STAGE" "mybotagent/hermes-skills" "main"
else
  say "  SKIP (404): mybotagent/hermes-skills — record only. 사용자에게 1회만 생성 요청."
fi

# ---- Step ③ scripts ------------------------------------------------------
SCRIPTS_MIRROR_STAGE="${HERMES_HOME}/.mirror/scripts-stage"
code=$(gh_repo "mybotagent/hermes-scripts")
if [ "$code" = "200" ]; then
  ensure_mirror_stage "scripts" "${HERMES_MIRROR:-${HERMES_HOME}/.mirror/scripts.git}" \
    "$SCRIPTS_MIRROR_STAGE" "${HERMES_HOME}/scripts" "mybotagent/hermes-scripts"
  sync_substep "scripts-stage" "$SCRIPTS_MIRROR_STAGE" "mybotagent/hermes-scripts" "main"
else
  say "  SKIP (404): mybotagent/hermes-scripts — record only."
fi

# ---- Step ④ cron + memories + cfg (config 레포에) -----------------------
CONFIG_MIRROR_STAGE="${HERMES_HOME}/.mirror/config-stage"
code=$(gh_repo "mybotagent/hermes-config")
if [ "$code" = "200" ]; then
  # ⚠️ config stage: ~/.hermes 전체를 stage에 쓰면 무한 재귀 (.git, .mirror, wiki 등)
  # → HERMES_HOME을 src에 직접 넣지 말고, **선별된 파일들만** stage에 직접 쓴다.
  # ensure_mirror_stage는 더 이상 호출하지 않음 (config 전용 수동 빌드).
  mkdir -p "$CONFIG_MIRROR_STAGE"
  if [ ! -d "$CONFIG_MIRROR_STAGE/.git" ]; then
    git clone "https://github.com/mybotagent/hermes-config.git" "$CONFIG_MIRROR_STAGE" >>"$LOG_FILE" 2>&1 || true
    (
      cd "$CONFIG_MIRROR_STAGE" 2>/dev/null || exit 0
      git checkout -B main 2>/dev/null || true
      git remote set-url origin "https://github.com/mybotagent/hermes-config.git" 2>/dev/null || \
        git remote add origin "https://github.com/mybotagent/hermes-config.git"
    )
  fi
  (
    cd "$CONFIG_MIRROR_STAGE"
    cat > .gitignore <<'GI'
# secrets — 절대 commit ❌
.env
*.token
*.pem
memories/memory-current.md

# noise
cron/output/
cron/jobs.json
cron/jobs.json.*
cron/ticker_*
cron/.*.lock

# local state (mirror 내부)
.mirror/
.git/
GI
    # cron 정의 (jobs.json 제외), memories → people/ memory-snapshot 추출, .env.example, config.yaml
    mkdir -p memories cron
    if [ -f "${HERMES_HOME}/memories/memory.md" ]; then
      cp "${HERMES_HOME}/memories/memory.md" memories/memory-current.md
      # secret line 제거 (\bapi=...) — quote/dollar sign/personal token
      sed -E -i 's/(api_key|token|secret)=[^[:space:]]*/\1=<REDACTED>/g' memories/memory-current.md
    fi
    # cron 정의 (jobs.json만 추출 메타: 이름/스케줄, 내용은 push ❌)
    python3 - <<'PY' 2>>"$LOG_FILE" || true
import json, os
p = os.path.expanduser("~/.hermes/cron/jobs.json")
out = os.path.expanduser("~/.hermes/.mirror/config-stage/cron/jobs.meta.json")
try:
    with open(p) as f: d = json.load(f)
    jobs = d.get('jobs', []) if isinstance(d, dict) else d
    meta = [
        {"name": j.get('name'), "schedule": j.get('schedule'),
         "script": j.get('script'), "enabled": j.get('enabled'),
         "no_agent": j.get('no_agent')}
        for j in jobs if isinstance(j, dict)
    ]
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, 'w') as f:
        json.dump({"count": len(meta), "jobs": meta}, f, indent=2, ensure_ascii=False)
except Exception as e:
    print('jobs.meta.json skip:', e)
PY
    [ -f "${HERMES_HOME}/config.yaml" ] && cp "${HERMES_HOME}/config.yaml" .
    if [ -f "${HERMES_HOME}/.env" ]; then
      # .env.example 생성 (값 비우고 key만)
      awk -F= '/^[A-Z_]+=/{print $1"="}' "${HERMES_HOME}/.env" > .env.example 2>/dev/null || true
    fi
  ) >>"$LOG_FILE" 2>&1
  sync_substep "config-stage" "$CONFIG_MIRROR_STAGE" "mybotagent/hermes-config" "main"
else
  say "  SKIP (404): mybotagent/hermes-config — record only."
fi

# ---- Drift check (records only, non-blocking) ---------------------------
say "--- drift check (record only) ---"
for entry in \
  "wiki:${HERMES_HOME}/wiki" \
  "skills:${SKILLS_MIRROR_STAGE}" \
  "scripts:${SCRIPTS_MIRROR_STAGE}" \
  "config:${CONFIG_MIRROR_STAGE}"; do
  label="${entry%%:*}"
  path="${entry##*:}"
  if [ -d "$path/.git" ] && [ "$DRY_RUN" = "0" ]; then
    (
      cd "$path"
      local_remote=$(git rev-parse --verify origin/main 2>/dev/null || echo "missing")
      local_head=$(git rev-parse --verify HEAD 2>/dev/null || echo "missing")
      say "  $label: local=$local_head remote=$local_remote"
    ) 2>/dev/null
  fi
done

say "===== hermes-config-sync END ====="
# emit one-liner summary for cron delivery
echo "hermes-config-sync done — DRY=$DRY_RUN log=$LOG_FILE"
