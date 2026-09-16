#!/usr/bin/env bash
# dev_harness_create_pr.sh — fork branch에서 upstream(sh-ai-x/dev-harness-kit)으로 PR 생성
# Usage: dev_harness_create_pr.sh <branch-name> <pr-title>
# PR body는 stdin으로 전달 (heredoc)

set -uo pipefail
BRANCH="${1:?usage: dev_harness_create_pr.sh <branch> <title>}"
TITLE="${2:?usage: dev_harness_create_pr.sh <branch> <title>}"
ENV_FILE="$HOME/.hermes/.env"

if [ -f "$ENV_FILE" ]; then
  set -a; source "$ENV_FILE"; set +a
fi
TOKEN="${GH_TOKEN:-${GH_TOKEN_V2:-${GITHUB_TOKEN:-}}}"
[ -z "$TOKEN" ] && { echo "❌ GH_TOKEN/GH_TOKEN_V2/GITHUB_TOKEN 없음"; exit 1; }

BODY="$(cat)"

python3 - "$TOKEN" "$BRANCH" "$TITLE" "$BODY" <<'PYEOF'
import json, sys, urllib.request

token, branch, title, body = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]
payload = {
    "title": title,
    "head": f"mybotagent:{branch}",
    "base": "main",
    "body": body,
}
req = urllib.request.Request(
    "https://api.github.com/repos/sh-ai-x/dev-harness-kit/pulls",
    data=json.dumps(payload).encode(),
    headers={"Authorization": f"token {token}", "Accept": "application/vnd.github+json",
             "Content-Type": "application/json"},
    method="POST",
)
try:
    with urllib.request.urlopen(req, timeout=20) as r:
        d = json.loads(r.read())
        print(f"✅ PR 생성: #{d.get('number')} {d.get('html_url')}")
        print(f"   제목: {d.get('title')}")
except urllib.error.HTTPError as e:
    body = e.read().decode()[:500]
    print(f"❌ PR 생성 실패 ({e.code}): {body}")
    sys.exit(1)
PYEOF
