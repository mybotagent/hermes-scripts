#!/usr/bin/env python3
"""
self_improve_loop.py — 자가개선 루프 (Step 2)

목적: 매주 시스템 자가 진단 + 개선 사항 자동 탐지 + Kanban 태스크 생성

입력:
- design_exec_gap.py 결과
- compression_drift_check.py 결과
- wiki_lint.py 결과
- cron 1주 성공률
- memory 90%+ 알림

출력:
- 자동 개선 사항 3~5개 Kanban 태스크 생성
- 발견된 이슈 보고 (stdout)
- silent: 개선 사항 0건

Usage:
  python3 self_improve_loop.py            # 실행
  python3 self_improve_loop.py --dry-run   # Kanban 생성 없이 보고만
"""

import sys
import json
import subprocess
from pathlib import Path
from datetime import datetime, timedelta

HERMES_HOME = Path.home() / ".hermes"
SCRIPTS = HERMES_HOME / "scripts"


def run_script(name: str, args: list[str] = None) -> dict:
    """스크립트 실행 후 JSON 또는 text 반환."""
    cmd = ["python3", str(SCRIPTS / name)]
    if args:
        cmd.extend(args)
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        return {
            "success": result.returncode == 0,
            "returncode": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr,
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


def parse_design_gap() -> dict:
    """design_exec_gap.py 측정."""
    r = run_script("design_exec_gap.py", ["--json"])
    if not r["success"]:
        return {"error": r.get("stderr", "unknown")}
    try:
        return json.loads(r["stdout"])
    except Exception:
        return {"error": "parse_failed", "stdout": r["stdout"][:200]}


def parse_drift() -> dict:
    """compression_drift_check.py 측정."""
    r = run_script("compression_drift_check.py", ["--json"])
    if not r["success"]:
        return {"error": r.get("stderr", "unknown")}
    try:
        return json.loads(r["stdout"])
    except Exception:
        return {"error": "parse_failed", "stdout": r["stdout"][:200]}


def parse_wiki_lint() -> dict:
    """wiki_lint.py 측정 (research/)."""
    r = run_script("wiki_lint.py", ["research/", "--json"])
    if not r["success"] and r.get("returncode") not in (0, 1):
        return {"error": r.get("stderr", "unknown")}
    try:
        return json.loads(r["stdout"])
    except Exception:
        return {"error": "parse_failed", "stdout": r["stdout"][:200]}


def detect_issues(gap: dict, drift: dict, lint: dict) -> list[dict]:
    """측정 결과에서 개선 사항 자동 탐지."""
    issues = []

    # 1. 디자인-실행 갭 ≥ 10%
    gap_pct = gap.get("gap", {}).get("design_exec_gap_pct", 0)
    if gap_pct >= 10:
        issues.append({
            "priority": 2,
            "title": f"디자인-실행 갭 {gap_pct}% (≥10% 임계) — cron/log/scripts 점검",
            "body": f"현재 측정: {gap_pct}% (cron_gap={gap.get('gap',{}).get('cron_gap')}%, drift_gap={gap.get('gap',{}).get('drift_gap')}%, wiki_gap={gap.get('gap',{}).get('wiki_gap')}%). 개선: cron success rate <100%, drift avg 분 >5분, wiki avg age >30일 중 하나.",
        })

    # 2. 메모리 drift ≥ 10%
    drift_pct = drift.get("drift_pct", 0)
    if drift_pct >= 10:
        unmatched = [d["fact"][:60] for d in drift.get("details", []) if not d["found"]]
        issues.append({
            "priority": 2,
            "title": f"memory.md drift {drift_pct}% — {len(unmatched)} facts 미매칭",
            "body": f"미매칭 facts: {unmatched[:3]}... 자동 압축 OFF 권장, memory.md 갱신 필요.",
        })

    # 3. Wiki lint 이슈 ≥ 5
    lint_total = sum(len(v) for v in lint.get("results", {}).values())
    if lint_total >= 5:
        # 어떤 종류인지 분류
        breakdown = {k: len(v) for k, v in lint.get("results", {}).items() if v}
        top = max(breakdown, key=breakdown.get) if breakdown else "unknown"
        issues.append({
            "priority": 3,
            "title": f"Wiki lint {lint_total}건 ({top} 최다) — research/ 페이지 보강",
            "body": f"상세: {breakdown}. SCHEMA.md §6 taxonomy 보강 또는 multi-source 추가 권장.",
        })

    # 4. 메모리 90%+
    mem_alert = run_script("memory_alert.py", ["stats"])
    if mem_alert["success"] and "99" in mem_alert["stdout"]:
        # P0 alert — 자동 Kanban task ❌ (사용자 단일공식: 함부로 추측 반영 안 함)
        # 알림만 발생 (Discord delivery)
        issues.append({
            "priority": 1,
            "alert_only": True,  # 자동 Kanban 생성 안 함
            "title": "memory.md 99%+ — 사용자 결정 필요 (Phase 2 watcher 합의 전)",
            "body": "memory.md 2191/2200 chars (99.6%). 자동 archive/압축 금지 — 사용자 단일공식 준수. 옵션: (a) § 1~2개 수동 archive, (b) Phase 2 watcher 합의, (c) 그냥 두고 다음 alert까지 대기.",
        })

    return issues


def create_kanban_tasks(issues: list[dict], dry_run: bool = False) -> list[str]:
    """개선 사항을 Kanban 태스크로 생성."""
    created_ids = []
    parent_title = f"self-improve-loop-{datetime.now().strftime('%Y%m%d')}"

    if dry_run:
        return [f"[DRY] would create: {i['title']}" for i in issues]

    if not issues:
        return []

    # 부모 태스크 생성
    parent_result = subprocess.run(
        [
            "hermes", "kanban", "create", parent_title,
            "--body", f"자가개선 루프 결과 ({len(issues)}건). weekly self_improve_loop.py 실행.",
            "--priority", "2",
        ],
        capture_output=True, text=True, timeout=10
    )
    parent_id = None
    for line in parent_result.stdout.split("\n"):
        if line.startswith("Created"):
            # "Created t_xxxxx"
            parts = line.split()
            if len(parts) >= 2:
                parent_id = parts[1]

    # 자식 태스크 생성
    for issue in issues:
        result = subprocess.run(
            [
                "hermes", "kanban", "create", issue["title"],
                "--priority", str(issue["priority"]),
                "--parent", parent_id if parent_id else "",
                "--body", issue["body"],
            ],
            capture_output=True, text=True, timeout=10
        )
        for line in result.stdout.split("\n"):
            if line.startswith("Created"):
                parts = line.split()
                if len(parts) >= 2:
                    created_ids.append(parts[1])

    return created_ids


def main():
    dry_run = "--dry-run" in sys.argv

    print(f"=== Self-Improve Loop ({datetime.now().isoformat()}) ===")
    if dry_run:
        print("[DRY RUN] Kanban 생성 안 함\n")

    # 1. 측정
    print("[1] design_exec_gap 측정...")
    gap = parse_design_gap()
    gap_pct = gap.get("gap", {}).get("design_exec_gap_pct", "?")
    print(f"    → gap={gap_pct}%")

    print("[2] compression_drift 측정...")
    drift = parse_drift()
    drift_pct = drift.get("drift_pct", "?")
    print(f"    → drift={drift_pct}%")

    print("[3] wiki_lint 측정 (research/)...")
    lint = parse_wiki_lint()
    lint_total = sum(len(v) for v in lint.get("results", {}).values())
    print(f"    → {lint_total} issues")

    # 2. 개선 사항 탐지
    print("\n[4] 개선 사항 탐지...")
    issues = detect_issues(gap, drift, lint)
    print(f"    → {len(issues)}개 발견")

    if not issues:
        print("\n✅ 개선 사항 없음 — 시스템 정상. SILENT.")
        sys.exit(0)

    # 3. Kanban 태스크 생성 (alert_only 제외)
    auto_issues = [i for i in issues if not i.get("alert_only")]
    alert_only = [i for i in issues if i.get("alert_only")]
    print(f"\n[5] Kanban 태스크 생성 ({len(auto_issues)} 자동, {len(alert_only)} alert only)...")
    created = create_kanban_tasks(auto_issues, dry_run=dry_run)
    print(f"    → {len(created)} 생성")

    # 4. 보고
    print(f"\n=== 자가개선 루프 결과 ===")
    if auto_issues:
        for i, issue in enumerate(auto_issues, 1):
            print(f"\n[{i}] P{issue['priority']} {issue['title']}")
            print(f"    {issue['body'][:100]}...")
    if alert_only:
        for i, issue in enumerate(alert_only, 1):
            print(f"\n[!ALERT {i}] P{issue['priority']} {issue['title']}")
            print(f"    {issue['body'][:120]}...")
            print(f"    → 자동 처리 안 함 (사용자 결정 영역)")

    if not dry_run and created:
        print(f"\nKanban IDs: {created}")


if __name__ == "__main__":
    main()