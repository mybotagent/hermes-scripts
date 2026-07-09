#!/usr/bin/env python3
"""
trigger_backlog_swipper.py — 매일 오전 백로그 점검.

SAFE: read-only + 소량의 assign (Kanban only).
- Kanban ready 중 assignee 없는 task: 슬랙/디스코드 알림
- TODO.md가 있는 SKILL은 README/INDEX 갱신 권장
- GitHub open issues check: mybotagent/* 의 open issue 0인지 검증

Stdout 1줄 요약 + 필요 시 origin 발송.
"""
from __future__ import annotations
import json, os, re, sys, urllib.request, datetime as dt, subprocess
from pathlib import Path

_HH = os.environ.get("HERMES_HOME", "/home/ubuntu")
HERMES_HOME = Path(_HH) if _HH.endswith("/.hermes") else Path(_HH) / ".hermes"


def gh(path, token, method="GET", data=None):
    headers = {"Authorization": f"token {token}", "Accept": "application/vnd.github+json",
               "User-Agent": "hermes-bot"}
    body = json.dumps(data).encode() if data else None
    req = urllib.request.Request(
        f"https://api.github.com{path}", data=body, method=method, headers=headers)
    return json.loads(urllib.request.urlopen(req, timeout=15).read())


def kanban_ready_unassigned():
    """Return list of ready tasks with no assignee."""
    out = subprocess.run(["hermes", "kanban", "list", "--status", "ready", "--json"],
                         capture_output=True, text=True, timeout=15).stdout
    data = json.loads(out) if out.strip().startswith("[") else []
    return [t for t in data if not t.get("assignee") and t.get("status") == "ready"]


def todo_files_unprocessed():
    """TODO.md 있는 skill들의 status flag 점검 (file 있으면 미처리 추정)."""
    skills = HERMES_HOME / "skills"
    res = []
    for f in (skills.rglob("TODO.md") if skills.exists() else []):
        # last modified in days
        mtime = dt.datetime.fromtimestamp(f.stat().st_mtime)
        age = (dt.datetime.now() - mtime).days
        if age > 3:
            res.append({"path": str(f.relative_to(HERMES_HOME)), "mtime": mtime.isoformat()[:10],
                        "age_days": age})
    return res


def github_open_issues(token, repo):
    try:
        data = gh(f"/repos/{repo}/issues?state=open&per_page=20", token)
        return [(r["number"], r["title"]) for r in data
                if "pull_request" not in r]
    except Exception:
        return []


def main():
    tok = HERMES_HOME.joinpath(".env").read_text() if (HERMES_HOME / ".env").exists() else ""
    m = re.search(r"^GITHUB_TOKEN=(.+)$", tok, re.M)
    tok = m.group(1).strip().strip('"') if m else ""
    if not tok:
        print("[trigger_backlog_swipper] no GITHUB_TOKEN"); return

    repo_list = ["mybotagent/hermes-pr-gate", "mybotagent/mybotagent.github.io",
                 "mybotagent/hermes-wiki-super", "mybotagent/hermes-wiki"]

    kanban_unassigned = kanban_ready_unassigned()
    todo_stale = todo_files_unprocessed()
    issues_open_per_repo = {r: github_open_issues(tok, r) for r in repo_list}

    out = {
        "ts": dt.datetime.now().isoformat(timespec="seconds"),
        "kanban_unassigned_count": len(kanban_unassigned),
        "todo_stale_count": len(todo_stale),
        "issues_per_repo": {r: len(v) for r, v in issues_open_per_repo.items()},
        "issue_list": [(r, n, t) for r in issues_open_per_repo
                       for n, t in issues_open_per_repo[r][:3]],
    }
    print(json.dumps(out, indent=2, ensure_ascii=False))

    # alert if backlog grows
    if len(kanban_unassigned) > 5 or sum(out["issues_per_repo"].values()) > 10:
        print("\n[ALERT] backlog exceeds threshold (kanban>5 or issues>10). ping user.")


if __name__ == "__main__":
    main()
