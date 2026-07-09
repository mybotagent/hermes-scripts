#!/usr/bin/env python3
"""
pr_review_monitor.py — PR review 상태 모니터링

지정된 PR의 review/comment/CI 상태를 확인하고 변화 시 알림.

사용법:
    python3 pr_review_monitor.py                 # 모든 모니터링 PR 체크
    python3 pr_review_monitor.py --add <pr_url>  # 모니터링 추가
    python3 pr_review_monitor.py --list          # 모니터링 목록
"""
import json
import subprocess
import sys
from pathlib import Path

STATE_FILE = Path.home() / ".hermes" / "pr_monitor.json"


def load_state():
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
    return {"prs": {}}


def save_state(state):
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2, ensure_ascii=False))


def get_pr_status(repo: str, pr_number: int, token: str) -> dict:
    """PR의 review/comment/CI 상태 조회"""
    try:
        result = subprocess.run(
            ["gh", "pr", "view", str(pr_number), "--repo", repo,
             "--json", "state,reviews,comments,statusCheckRollup,title"],
            capture_output=True, text=True, timeout=30,
            env={"GH_TOKEN": token, "PATH": "/usr/local/bin:/usr/bin:/bin"}
        )
        if result.returncode != 0:
            return {"error": result.stderr.strip()[:200]}
        return json.loads(result.stdout)
    except Exception as e:
        return {"error": str(e)}


def check_changes(pr_url: str, current: dict, prev: dict | None) -> list[str]:
    """이전 대비 변경 사항 추출"""
    changes = []
    if prev is None:
        return ["[NEW] PR 등록됨"]

    if current.get("state") != prev.get("state"):
        changes.append(f"[STATE] {prev.get('state')} → {current.get('state')}")

    curr_reviews = current.get("reviews", [])
    prev_reviews = prev.get("reviews", [])
    if len(curr_reviews) > len(prev_reviews):
        for r in curr_reviews[len(prev_reviews):]:
            changes.append(f"[REVIEW] @{r.get('author', {}).get('login', '?')}: {r.get('state')}")
            if r.get("body"):
                changes.append(f"  └ {r['body'][:200]}")

    curr_comments = current.get("comments", [])
    prev_comments = prev.get("comments", [])
    if len(curr_comments) > len(prev_comments):
        for c in curr_comments[len(prev_comments):]:
            changes.append(f"[COMMENT] @{c.get('author', {}).get('login', '?')}: {c.get('body', '')[:200]}")

    checks_curr = current.get("statusCheckRollup") or []
    checks_prev = prev.get("statusCheckRollup") or []
    for c in checks_curr:
        prev_match = next((p for p in checks_prev if p.get("name") == c.get("name")), None)
        prev_conc = prev_match.get("conclusion") if prev_match else "pending"
        curr_conc = c.get("conclusion") or c.get("status", "?")
        if prev_conc != curr_conc and curr_conc not in ("pending", "queued", "in_progress"):
            changes.append(f"[CI] {c.get('name')}: {prev_conc} → {curr_conc}")

    return changes


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--add", help="PR URL 추가 (https://github.com/owner/repo/pull/123)")
    parser.add_argument("--list", action="store_true", help="모니터링 목록")
    parser.add_argument("--poll-interval", type=int, default=600, help="폴링 간격 (초)")
    args = parser.parse_args()

    state = load_state()

    if args.add:
        # URL 파싱: https://github.com/owner/repo/pull/123
        parts = args.add.rstrip("/").split("/")
        if len(parts) >= 7 and parts[-2] == "pull":
            repo = f"{parts[-4]}/{parts[-3]}"
            pr_num = int(parts[-1])
            state["prs"][args.add] = {"repo": repo, "pr_number": pr_num, "last_check": None}
            save_state(state)
            print(f"[ADD] {repo}#{pr_num}")
        else:
            print("[ERROR] invalid PR URL format")
            return 1
        return 0

    if args.list:
        for url, info in state["prs"].items():
            print(f"  {url} (last check: {info.get('last_check', 'never')})")
        return 0

    if not state["prs"]:
        print("[INFO] 모니터링 PR 없음. --add <url>로 추가")
        return 0

    # PR 체크
    token_file = Path.home() / ".hermes" / ".env"
    token = ""
    if token_file.exists():
        for line in token_file.read_text().splitlines():
            if line.startswith("GITHUB_TOKEN="):
                token = line.split("=", 1)[1].strip()
                break

    if not token:
        print("[ERROR] GITHUB_TOKEN not found in ~/.hermes/.env")
        return 1

    all_changes = []
    for url, info in state["prs"].items():
        current = get_pr_status(info["repo"], info["pr_number"], token)
        if "error" in current:
            print(f"[ERROR] {url}: {current['error']}")
            continue

        prev = info.get("last_data")
        changes = check_changes(url, current, prev)

        info["last_check"] = __import__("datetime").datetime.now().isoformat()
        info["last_data"] = current
        info["last_state"] = current.get("state")

        if changes:
            all_changes.append(f"\n=== {url} ===\n" + "\n".join(changes))

    save_state(state)

    if all_changes:
        print("\n".join(all_changes))
    else:
        print("[OK] 변화 없음")
    return 0


if __name__ == "__main__":
    sys.exit(main())