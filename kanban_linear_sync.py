#!/usr/bin/env python3
"""
kanban_linear_sync.py — Kanban ↔ Linear 자동 동기화 (Step 3 진화)

목적: 양방향 sync로 단일 진실 소스 유지
- Kanban done → Linear Done
- Linear Done → Kanban complete
- 상태 변경 시 mapping.json 갱신

사용:
  python3 kanban_linear_sync.py          # dry-run (기본)
  python3 kanban_linear_sync.py --apply  # 실제 적용

판단 기준:
- Kanban mapping.json에 linear_issue_id 있으면 sync 진행
- 없으면 매핑 추가 안 함 (보수적)
"""

import sys
import json
import sqlite3
import subprocess
from pathlib import Path
from datetime import datetime

HERMES_HOME = Path.home() / ".hermes"
KANBAN_DB = HERMES_HOME / "kanban.db"
MAPPING_FILE = HERMES_HOME / "data" / "kanban_linear_mapping.json"
LINEAR_DONE_STATE = "86cd9d73-2b97-49e9-8b16-95c1d08c29ad"
LINEAR_BACKLOG_STATE = "cec5bc9e-3028-4f51-b3ad-1f60740a1812"


def get_linear_api_key() -> str:
    env_file = HERMES_HOME / ".env"
    for line in env_file.read_text().split("\n"):
        if line.startswith("LINEAR_API_KEY="):
            return line.split("=", 1)[1].strip()
    raise SystemExit("LINEAR_API_KEY not found in .env")


def linear_graphql(query: str, variables: dict = None) -> dict:
    """Linear GraphQL 호출."""
    import urllib.request
    api_key = get_linear_api_key()
    payload = json.dumps({"query": query, "variables": variables or {}}).encode()
    req = urllib.request.Request(
        "https://api.linear.app/graphql",
        data=payload,
        headers={
            "Authorization": api_key,
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read())
    except Exception as e:
        return {"error": str(e)}


def get_kanban_done_tasks() -> list[dict]:
    """Kanban에서 status=done인 tasks."""
    conn = sqlite3.connect(str(KANBAN_DB))
    cursor = conn.execute(
        """
        SELECT id, title, status, assignee, completed_at
        FROM tasks
        WHERE status = 'done'
        ORDER BY completed_at DESC
        LIMIT 100
        """
    )
    tasks = [{"id": r[0], "title": r[1], "status": r[2], "assignee": r[3], "completed_at": r[4]} for r in cursor]
    conn.close()
    return tasks


def load_mapping() -> dict:
    if not MAPPING_FILE.exists():
        return {}
    try:
        return json.loads(MAPPING_FILE.read_text())
    except Exception:
        return {}


def save_mapping(mapping: dict) -> None:
    MAPPING_FILE.parent.mkdir(parents=True, exist_ok=True)
    MAPPING_FILE.write_text(json.dumps(mapping, indent=2, ensure_ascii=False))


def sync_done_kanban_to_linear(apply: bool, mapping: dict) -> list[dict]:
    """Kanban done → Linear Done."""
    actions = []
    tasks = get_kanban_done_tasks()

    for task in tasks:
        tid = task["id"]
        if tid not in mapping:
            continue
        linear_id = mapping[tid].get("linear_issue_id")
        if not linear_id:
            # 매핑 없음 → unmapped done task. 자동 issue 생성 권장
            actions.append({
                "type": "unmapped_done",
                "kanban_id": tid,
                "title": task["title"][:60],
                "suggestion": "create linear issue + add to mapping",
            })
            continue

        # Linear 현재 상태 확인
        query = """
        query GetIssue($id: String!) {
          issue(id: $id) { id identifier state { id name } }
        }
        """
        result = linear_graphql(query, {"id": linear_id})
        issue = result.get("data", {}).get("issue")
        if not issue:
            continue

        current_state = issue["state"]["id"]
        if current_state == LINEAR_DONE_STATE:
            continue  # 이미 Done

        actions.append({
            "type": "kanban_done_to_linear_done",
            "kanban_id": tid,
            "linear_id": linear_id,
            "linear_state_now": issue["state"]["name"],
            "title": task["title"][:60],
        })

        if apply:
            mutation = """
            mutation UpdateIssue($id: String!, $stateId: String!) {
              issueUpdate(id: $id, input: { stateId: $stateId }) {
                success issue { identifier state { name } }
              }
            }
            """
            r = linear_graphql(mutation, {"id": linear_id, "stateId": LINEAR_DONE_STATE})
            actions[-1]["applied"] = r.get("data", {}).get("issueUpdate", {}).get("success", False)

    return actions


def sync_linear_done_to_kanban(apply: bool, mapping: dict) -> list[dict]:
    """Linear Done → Kanban complete (mapping 기반)."""
    # 모든 매핑된 Linear issue 한 번에 조회
    linear_ids = list({m.get("linear_issue_id") for m in mapping.values() if m.get("linear_issue_id")})

    if not linear_ids:
        return []

    actions = []
    # 백오프: 5건씩 batch
    for batch_start in range(0, len(linear_ids), 5):
        batch = linear_ids[batch_start:batch_start + 5]
        query = """
        query Issues($ids: [ID!]!) {
          issues(filter: { id: { in: $ids } }) {
            nodes { id identifier title state { id name } }
          }
        }
        """
        r = linear_graphql(query, {"ids": batch})
        nodes = r.get("data", {}).get("issues", {}).get("nodes", [])

        for issue in nodes:
            if issue["state"]["id"] != LINEAR_DONE_STATE:
                continue
            # 매칭되는 Kanban task 찾기
            for tid, m in mapping.items():
                if m.get("linear_issue_id") == issue["identifier"]:
                    # Kanban 상태 확인
                    conn = sqlite3.connect(str(KANBAN_DB))
                    cursor = conn.execute("SELECT status FROM tasks WHERE id = ?", (tid,))
                    row = cursor.fetchone()
                    conn.close()
                    if not row or row[0] == "done":
                        continue
                    actions.append({
                        "type": "linear_done_to_kanban_done",
                        "kanban_id": tid,
                        "linear_id": issue["identifier"],
                        "title": issue["title"][:60],
                    })
                    if apply:
                        subprocess.run(
                            ["hermes", "kanban", "complete", tid,
                             "--summary", f"Auto-sync from Linear {issue['identifier']} Done"],
                            capture_output=True, timeout=10,
                        )
                        actions[-1]["applied"] = True
                    break

    return actions


def main():
    apply = "--apply" in sys.argv

    print(f"=== Kanban ↔ Linear Sync ({datetime.now().isoformat()}) ===")
    if not apply:
        print("[DRY RUN] --apply 플래그로 실제 변경\n")

    mapping = load_mapping()
    print(f"매핑: {len(mapping)}건\n")

    # 1. Kanban done → Linear Done
    print("[1] Kanban done → Linear Done")
    a1 = sync_done_kanban_to_linear(apply, mapping)
    print(f"    → {len(a1)}건 {'적용됨' if apply else '예정'}")
    for a in a1[:5]:
        print(f"      - {a['linear_id']} ({a['linear_state_now']} → Done): {a['title']}")

    # 2. Linear Done → Kanban complete
    print("\n[2] Linear Done → Kanban complete")
    a2 = sync_linear_done_to_kanban(apply, mapping)
    print(f"    → {len(a2)}건 {'적용됨' if apply else '예정'}")
    for a in a2[:5]:
        print(f"      - {a['kanban_id']} ← {a['linear_id']}: {a['title']}")

    total = len(a1) + len(a2)
    if total == 0:
        print("\n✅ 동기화 불필요 — 양쪽 일치. SILENT.")
        sys.exit(0)

    print(f"\n총 {total}건 {'적용' if apply else '대기'}")
    sys.exit(0 if apply else 1)


if __name__ == "__main__":
    main()