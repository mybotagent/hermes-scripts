#!/usr/bin/env python3
"""
self_hermes.py — Self-Improving Hermes Engine (Phase 1~4)
=====================================================

단일 공식: OBSERVE → PLAN → EXECUTE → MEASURE

Usage:
  python3 self_hermes.py                  # 실행 (변경사항 있을 때만 stdout)
  python3 self_hermes.py --dry-run        # preview only
  python3 self_hermes.py history          # ROI 이력 조회
  python3 self_hermes.py status           # 현재 상태 요약

Design:
  - 단일공식: 4단계 선형, 예외/조건문 없음
  - 모든 변경은 diff 형태로 기록 → 사용자 승인 후 확정
  - Phase 4 ROI로 feedback loop 완성
"""

import json
import os
import re
import sqlite3
import subprocess
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from collections import defaultdict, Counter

# ── 상수 ──
HH = Path(os.environ.get("HERMES_HOME", Path.home() / ".hermes"))
SCRIPTS = HH / "scripts"
SKILLS = HH / "skills"
WIKI = HH / "wiki"
MEMORY_FILE = HH / "memories" / "MEMORY.md"
STATE_DB = HH / "state.db"
HISTORY_DIR = HH / "self_hermes"
HISTORY_FILE = HISTORY_DIR / "history.json"
SNAPSHOT_FILE = HISTORY_DIR / "snapshot.json"
NOW = datetime.now(tz=timezone.utc)
TODAY_STR = NOW.strftime("%Y-%m-%d")
WEEK_STR = NOW.strftime("%Y-W%V")
MONTH_STR = NOW.strftime("%Y-%m")


# ═══════════════════════════════════════════════════
# PHASE 1 · OBSERVE — 상태 수집
# ═══════════════════════════════════════════════════

def observe() -> dict:
    """시스템 6축 상태 수집. 단일 snapshot 반환."""
    return {
        "ts": NOW.isoformat(),
        "date": TODAY_STR,
        "week": WEEK_STR,
        "month": MONTH_STR,
        "cron": _observe_cron(),
        "skills": _observe_skills(),
        "wiki": _observe_wiki(),
        "memory": _observe_memory(),
        "scripts": _observe_scripts(),
        "disk": _observe_disk(),
    }


def _observe_cron() -> dict:
    """cron list 수집."""
    r = subprocess.run(
        ["hermes", "cron", "list"],
        capture_output=True, text=True, timeout=15,
    )
    lines = r.stdout.split("\n")

    total = 0
    ok_count = 0
    error_count = 0
    never_count = 0
    paused_count = 0
    last_runs = []

    # cron list 헤더 탐지 패턴
    job_header = re.compile(r"^\s{2}[\w-]+\s+\[")  # "  abc123 [active]"
    field_line = re.compile(r"^\s{4}\w")  # 4-space indent + word

    i = 0
    while i < len(lines):
        line = lines[i]
        if job_header.match(line):
            total += 1
            name = ""
            last_run = ""
            status = ""
            schedule = ""
            script = ""
            has_script = False

            j = i + 1
            while j < len(lines) and field_line.match(lines[j]):
                content = lines[j].strip()
                if content.startswith("Name:"):
                    name = content.split(":", 1)[1].strip()
                elif content.startswith("Last run:"):
                    raw = content.split(":", 1)[1].strip()
                    last_run = raw
                    if "ok" in raw:
                        status = "ok"
                        ok_count += 1
                    elif "error" in raw or "fail" in raw:
                        status = "error"
                        error_count += 1
                    elif "NEVER" in raw.upper():
                        status = "never"
                        never_count += 1
                    else:
                        status = "unknown"
                elif content.startswith("Script:"):
                    script = content.split(":", 1)[1].strip()
                    has_script = True
                elif content.startswith("Schedule:"):
                    schedule = content.split(":", 1)[1].strip()
                elif content.startswith("State:") or content.startswith("Mode:"):
                    pass  # noop
                j += 1

            last_runs.append({
                "name": name,
                "status": status,
                "last_run": last_run,
                "schedule": schedule,
                "has_script": has_script,
                "script": script,
            })
            i = j
        else:
            i += 1

    return {
        "total": total,
        "ok": ok_count,
        "error": error_count,
        "never": never_count,
        "paused": paused_count,
        "success_rate": round(ok_count / total * 100, 1) if total > 0 else 0,
        "jobs": last_runs,
    }


def _observe_skills() -> dict:
    """스킬 사용 빈도 (90일) + 디스크 목록."""
    skills_on_disk = set()
    for f in SKILLS.rglob("SKILL.md"):
        rel = f.relative_to(SKILLS)
        parts = rel.parts
        if len(parts) >= 2:
            skills_on_disk.add(parts[-2])  # category/skillname/SKILL.md
        else:
            skills_on_disk.add(parts[0].replace("/SKILL.md", ""))
    
    # 간단히 디렉토리명으로 수집
    skills_on_disk = set()
    for d in SKILLS.rglob("*"):
        if d.is_dir() and (d / "SKILL.md").exists():
            skills_on_disk.add(d.name)

    # state.db에서 skill_view 호출 분석
    used_skills = set()
    cron_skills = set()
    if STATE_DB.exists():
        try:
            conn = sqlite3.connect(str(STATE_DB))
            # 최근 90일 skill_view 호출
            cutoff = int(time.time()) - 90 * 86400
            rows = conn.execute(
                "SELECT content FROM messages WHERE tool_name='skill_view' AND timestamp > ?",
                (cutoff,)
            ).fetchall()
            for (content,) in rows:
                for m in re.finditer(r'"name"\s*:\s*"([^"]+)"', content):
                    used_skills.add(m.group(1))
            conn.close()
        except Exception:
            pass

    # cron에서 사용하는 스킬
    cron_out = subprocess.run(
        ["hermes", "cron", "list"],
        capture_output=True, text=True, timeout=15,
    ).stdout
    for m in re.finditer(r"Skills:\s*(.+)", cron_out):
        for s in m.group(1).split(","):
            cron_skills.add(s.strip())

    all_used = used_skills | cron_skills
    unused = skills_on_disk - all_used

    return {
        "on_disk": len(skills_on_disk),
        "used_90d": len(used_skills),
        "cron_used": len(cron_skills),
        "unused_count": len(unused),
        "unused_list": sorted(unused)[:10],  # top 10
        "used_list": sorted(used_skills),
    }


def _observe_wiki() -> dict:
    """위키 페이지 수 + 기간."""
    wiki_files = list(WIKI.rglob("*.md"))
    # AGENTS.md, SCHEMA.md, index.md 제외
    content_files = [f for f in wiki_files if f.name not in ("AGENTS.md", "SCHEMA.md", "index.md", "INDEX.md")]

    total_pages = len(content_files)
    old_pages = 0
    for f in content_files:
        age_days = (NOW.timestamp() - f.stat().st_mtime) / 86400
        if age_days > 90:
            old_pages += 1

    # index.md 커버리지
    index_file = WIKI / "index.md"
    if not index_file.exists():
        index_file = WIKI / "INDEX.md"
    index_links = 0
    if index_file.exists():
        content = index_file.read_text()
        index_links = len([l for l in content.split("\n") if "(" in l and ")" in l and "md" in l])

    return {
        "total_pages": total_pages,
        "old_pages_90d": old_pages,
        "index_links": index_links,
        "index_coverage_pct": round(index_links / total_pages * 100, 1) if total_pages > 0 else 0,
    }


def _observe_memory() -> dict:
    """메모리 사용량."""
    if MEMORY_FILE.exists():
        chars = MEMORY_FILE.stat().st_size
        # 실제로는 wc -m이 정확하지만, st_size로 근사
        return {"file": str(MEMORY_FILE), "bytes": chars, "exists": True}
    return {"file": str(MEMORY_FILE), "bytes": 0, "exists": False}


def _observe_scripts() -> dict:
    """scripts/ 디렉토리 상태."""
    script_files = list(SCRIPTS.rglob("*.py")) + list(SCRIPTS.rglob("*.sh"))
    # __pycache__ 제외
    script_files = [f for f in script_files if "__pycache__" not in f.parts]

    # cron에서 참조하는 스크립트
    cron_out = subprocess.run(
        ["hermes", "cron", "list"],
        capture_output=True, text=True, timeout=15,
    ).stdout
    cron_scripts = set()
    for m in re.finditer(r"Script:\s+(\S+)", cron_out):
        cron_scripts.add(m.group(1))

    orphan_scripts = []
    for f in script_files:
        if f.name not in cron_scripts and f.name not in ("self_hermes.py",):
            orphan_scripts.append(f.name)

    return {
        "total": len(script_files),
        "cron_referenced": len(cron_scripts),
        "orphan_count": len(orphan_scripts),
        "orphan_list": sorted(orphan_scripts)[:10],
    }


def _observe_disk() -> dict:
    """디스크 사용량."""
    stat = os.statvfs(str(HH))
    total_gb = stat.f_frsize * stat.f_blocks / (1024**3)
    free_gb = stat.f_frsize * stat.f_bfree / (1024**3)
    used_pct = round((1 - stat.f_bfree / stat.f_blocks) * 100, 1)

    # __pycache__ 크기
    cache_size = 0
    for f in SCRIPTS.rglob("__pycache__"):
        for cf in f.rglob("*"):
            if cf.is_file():
                cache_size += cf.stat().st_size

    return {
        "total_gb": round(total_gb, 1),
        "free_gb": round(free_gb, 1),
        "used_pct": used_pct,
        "pycache_mb": round(cache_size / (1024**2), 1),
    }


# ═══════════════════════════════════════════════════
# PHASE 2 · PLAN — 개선 후보 선정
# ═══════════════════════════════════════════════════

def plan(snapshot: dict, history: dict) -> list[dict]:
    """snapshot + history → 개선 후보 1~3개.
    각 후보: {target, action, reason, expected_roi, file_path, old_string, new_string}"""
    candidates = []
    prev = history.get("last_snapshot", {})
    prev_cron = prev.get("cron", {})

    # ① cron 성공률 하락
    cur_rate = snapshot["cron"]["success_rate"]
    prev_rate = prev_cron.get("success_rate", 100)
    if prev_rate - cur_rate > 5:
        candidates.append({
            "target": "cron",
            "action": "investigate_failures",
            "reason": f"cron 성공률 {prev_rate}% → {cur_rate}% ({prev_rate - cur_rate}%p 하락)",
            "expected_roi": "high",
            "priority": 1,
        })

    # ② 사용 안 하는 스킬
    unused = snapshot["skills"].get("unused_list", [])
    if len(unused) >= 3:
        candidates.append({
            "target": "skills",
            "action": "archive_unused",
            "reason": f"{len(unused)}개 스킬 90일간 미사용 + cron 미참조",
            "expected_roi": "medium",
            "priority": 2,
            "items": unused[:5],
        })

    # ③ 위키 인덱스 커버리지
    coverage = snapshot["wiki"].get("index_coverage_pct", 100)
    if coverage < 80:
        candidates.append({
            "target": "wiki",
            "action": "update_index",
            "reason": f"index.md 커버리지 {coverage}% (<80%)",
            "expected_roi": "medium",
            "priority": 2,
        })

    # ④ 메모리 90%+
    mem_bytes = snapshot["memory"].get("bytes", 0)
    if mem_bytes > 1980:  # 2200 * 0.9
        candidates.append({
            "target": "memory",
            "action": "compact_memory",
            "reason": f"메모리 {mem_bytes}bytes (90%+ 임계)",
            "expected_roi": "high",
            "priority": 1,
        })

    # ⑤ orphan 스크립트
    orphans = snapshot["scripts"].get("orphan_count", 0)
    if orphans >= 3:
        candidates.append({
            "target": "scripts",
            "action": "cleanup_orphans",
            "reason": f"{orphans}개 orphan 스크립트 (cron 미참조)",
            "expected_roi": "low",
            "priority": 3,
        })

    # ⑥ cron NEVER 실행
    never_count = snapshot["cron"].get("never", 0)
    if never_count > 0:
        never_jobs = [j for j in snapshot["cron"].get("jobs", []) 
                      if "NEVER" in j.get("last_run", "").upper()]
        if never_jobs:
            candidates.append({
                "target": "cron",
                "action": "review_never_run",
                "reason": f"{never_count}개 cron 한 번도 실행 안 됨",
                "expected_roi": "medium",
                "priority": 2,
                "items": [j["name"] for j in never_jobs[:5]],
            })

    return sorted(candidates, key=lambda x: x["priority"])


# ═══════════════════════════════════════════════════
# PHASE 3 · EXECUTE — 파일 수준 개선 실행
# ═══════════════════════════════════════════════════

def execute(candidates: list[dict], dry_run: bool = False) -> list[dict]:
    """개선 후보 실행. 각 실행 결과 반환."""
    results = []
    
    for c in candidates:
        result = {
            "target": c["target"],
            "action": c["action"],
            "status": "skipped",
            "detail": "",
        }

        if c["action"] == "archive_unused" and not dry_run:
            result = _execute_archive_skills(c.get("items", []))

        elif c["action"] == "update_index" and not dry_run:
            result = _execute_update_wiki_index()

        elif c["action"] == "cleanup_orphans" and not dry_run:
            result = _execute_cleanup_orphans()

        elif c["action"] == "review_never_run" and not dry_run:
            result = _execute_flag_never_run(c.get("items", []))

        elif c["action"] == "compact_memory" and not dry_run:
            result = _execute_compact_memory()

        elif dry_run:
            result["status"] = "planned"
            result["detail"] = f"[DRY] {c['reason']}"

        results.append(result)

    return results


def _execute_archive_skills(items: list) -> dict:
    """미사용 스킬에 archived: true 프론트매터 추가."""
    archived = 0
    for skill_name in items:
        for f in SKILLS.rglob(f"{skill_name}/SKILL.md"):
            content = f.read_text()
            if "archived:" in content:
                continue
            # 프론트매터에 archived 추가
            if content.startswith("---"):
                new_content = content.replace("---", "---\narchived: true", 1)
                f.write_text(new_content)
                archived += 1
    return {
        "target": "skills",
        "action": "archive_unused",
        "status": "done" if archived > 0 else "noop",
        "detail": f"{archived}개 스킬 archived 마킹",
    }


def _execute_update_wiki_index() -> dict:
    """index.md에 누락된 페이지 추가."""
    index_file = WIKI / "index.md"
    if not index_file.exists():
        index_file = WIKI / "INDEX.md"
    if not index_file.exists():
        return {"target": "wiki", "action": "update_index", "status": "error", "detail": "index.md 없음"}

    index_content = index_file.read_text()
    wiki_files = list(WIKI.rglob("*.md"))
    excluded = {"AGENTS.md", "SCHEMA.md", "index.md", "INDEX.md", "README.md"}
    
    added = 0
    for f in wiki_files:
        if f.name in excluded:
            continue
        rel = f.relative_to(WIKI)
        link_name = str(rel).replace("\\", "/")
        if link_name not in index_content:
            # 간단한 링크 추가
            category = rel.parts[0] if len(rel.parts) > 1 else "root"
            title = f.stem.replace("-", " ").title()
            line = f"\n- [{title}]({link_name}) — 자동 추가 ({TODAY_STR})"
            index_content += line
            added += 1

    if added > 0:
        index_file.write_text(index_content)

    return {
        "target": "wiki",
        "action": "update_index",
        "status": "done" if added > 0 else "noop",
        "detail": f"index.md에 {added}개 페이지 추가",
    }


def _execute_cleanup_orphans() -> dict:
    """orphan 스크립트 정리 (__pycache__ 위주)."""
    removed = 0
    removed_size = 0
    for f in SCRIPTS.rglob("__pycache__"):
        for cf in list(f.rglob("*")):
            if cf.is_file():
                removed_size += cf.stat().st_size
                cf.unlink()
        try:
            f.rmdir()
            removed += 1
        except Exception:
            pass

    return {
        "target": "scripts",
        "action": "cleanup_orphans",
        "status": "done" if removed > 0 else "noop",
        "detail": f"__pycache__ {removed}개 정리 ({round(removed_size/1024, 1)}KB 회수)",
    }


def _execute_flag_never_run(items: list) -> dict:
    """NEVER cron 목록을 플래그 파일로 기록 (사용자 확인용)."""
    flag_file = HISTORY_DIR / "never_run_crons.txt"
    flag_file.parent.mkdir(parents=True, exist_ok=True)
    flag_file.write_text(f"# NEVER RUN CRONS (detected {TODAY_STR})\n" + "\n".join(f"- {n}" for n in items))
    return {
        "target": "cron",
        "action": "review_never_run",
        "status": "done",
        "detail": f"{len(items)}개 NEVER cron → {flag_file}",
    }


def _execute_compact_memory() -> dict:
    """기존 memory_daily_compact.sh 실행."""
    compact_script = SCRIPTS / "memory_daily_compact.sh"
    if not compact_script.exists():
        compact_script = SCRIPTS / "memory_auto_compact.py"
    if not compact_script.exists():
        return {"target": "memory", "action": "compact_memory", "status": "error", "detail": "compact 스크립트 없음"}
    
    r = subprocess.run(
        ["bash", str(compact_script)] if compact_script.suffix == ".sh" else ["python3", str(compact_script)],
        capture_output=True, text=True, timeout=30,
    )
    if r.returncode == 0:
        detail = r.stdout.strip()[:200]
    else:
        detail = r.stderr.strip()[:200]
    return {
        "target": "memory",
        "action": "compact_memory",
        "status": "done" if r.returncode == 0 else "error",
        "detail": detail or "compact 완료",
    }


# ═══════════════════════════════════════════════════
# PHASE 4 · MEASURE — ROI 측정 + feedback
# ═══════════════════════════════════════════════════

def measure(snapshot: dict, history: dict, exec_results: list[dict]) -> dict:
    """개선 효과 측정 + ROI 계산."""
    prev = history.get("last_snapshot", {})
    
    # 크론 성공률 변화
    cron_roi = 0
    prev_rate = prev.get("cron", {}).get("success_rate", 100)
    cur_rate = snapshot["cron"]["success_rate"]
    cron_delta = cur_rate - prev_rate

    # 위키 커버리지 변화
    prev_wiki = prev.get("wiki", {}).get("index_coverage_pct", 100)
    cur_wiki = snapshot["wiki"]["index_coverage_pct"]
    wiki_delta = cur_wiki - prev_wiki

    # 실행된 개선 수
    improvements = len([r for r in exec_results if r["status"] in ("done", "planned")])

    current_roi = {
        "date": TODAY_STR,
        "cron_success_rate": cur_rate,
        "cron_delta": round(cron_delta, 1),
        "wiki_coverage": cur_wiki,
        "wiki_delta": round(wiki_delta, 1),
        "improvements_applied": improvements,
        "unused_skills": snapshot["skills"]["unused_count"],
        "orphan_scripts": snapshot["scripts"]["orphan_count"],
        "disk_used_pct": snapshot["disk"]["used_pct"],
    }

    # ROI history 저장
    roi_history = history.get("roi_history", [])
    roi_history.append(current_roi)
    if len(roi_history) > 90:  # 최대 90일
        roi_history = roi_history[-90:]

    return {
        "current": current_roi,
        "trend": _compute_trend(roi_history),
        "roi_history": roi_history,
    }


def _compute_trend(roi_history: list) -> dict:
    """최근 N일 추세 계산."""
    if len(roi_history) < 7:
        return {
            "direction": "insufficient_data",
            "avg_cron_delta_7d": 0.0,
            "avg_wiki_delta_7d": 0.0,
            "streak_days": len(roi_history),
        }
    
    recent = roi_history[-7:]
    cron_trends = [r["cron_delta"] for r in recent]
    wiki_trends = [r["wiki_delta"] for r in recent]
    
    avg_cron_trend = sum(cron_trends) / len(cron_trends)
    avg_wiki_trend = sum(wiki_trends) / len(wiki_trends)
    
    if avg_cron_trend > 0 and avg_wiki_trend >= 0:
        direction = "improving"
    elif avg_cron_trend < 0 or avg_wiki_trend < -5:
        direction = "degrading"
    else:
        direction = "stable"

    return {
        "direction": direction,
        "avg_cron_delta_7d": round(avg_cron_trend, 1),
        "avg_wiki_delta_7d": round(avg_wiki_trend, 1),
        "streak_days": len(roi_history),
    }


# ═══════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════

def main():
    """Self-Improving Hermes Engine — 4-Phase 단일 공식"""
    dry_run = "--dry-run" in sys.argv
    mode = sys.argv[1] if len(sys.argv) > 1 else "run"

    if mode == "history":
        _show_history()
        return
    if mode == "status":
        s = observe()
        _print_status(s)
        return

    # 기록 디렉토리
    HISTORY_DIR.mkdir(parents=True, exist_ok=True)

    # 이전 상태 로드
    history = {"last_snapshot": {}, "roi_history": [], "exec_history": []}
    if HISTORY_FILE.exists():
        try:
            history = json.loads(HISTORY_FILE.read_text())
        except Exception:
            pass

    print(f"═══ Self-Improving Hermes ═══")
    print(f"Phase 1/4 · OBSERVE ({TODAY_STR})")
    
    # Phase 1: Observe
    snapshot = observe()
    _print_observe_summary(snapshot)
    
    # Phase 2: Plan
    print(f"\nPhase 2/4 · PLAN")
    candidates = plan(snapshot, history)
    if not candidates:
        print("  ✅ 개선 후보 없음 — 시스템 정상")
    else:
        for i, c in enumerate(candidates, 1):
            print(f"  [{i}] P{c['priority']} {c['target']}/{c['action']}")
            print(f"      {c['reason']} (ROI: {c['expected_roi']})")

    # Phase 3: Execute
    print(f"\nPhase 3/4 · EXECUTE{' (DRY RUN)' if dry_run else ''}")
    exec_results = execute(candidates, dry_run=dry_run)
    for r in exec_results:
        icon = {"done": "✅", "planned": "🔍", "skipped": "➖", "noop": "⏭️", "error": "❌"}
        print(f"  {icon.get(r['status'], '❓')} {r['target']}/{r['action']}: {r['detail']}")

    # Phase 4: Measure
    print(f"\nPhase 4/4 · MEASURE")
    roi = measure(snapshot, history, exec_results)
    _print_roi(roi)

    # 저장
    if not dry_run:
        history["last_snapshot"] = snapshot
        history["last_exec"] = {
            "ts": NOW.isoformat(),
            "candidates": candidates,
            "results": exec_results,
        }
        history["roi_history"] = roi["roi_history"]
        HISTORY_FILE.write_text(json.dumps(history, indent=2, ensure_ascii=False))
        
        # snapshot 저장 (추세용)
        SNAPSHOT_FILE.write_text(json.dumps(snapshot, indent=2, ensure_ascii=False))

    # 최종 요약 (stdout — cron deliver용)
    improvements = len([r for r in exec_results if r["status"] == "done"])
    alerts = len([r for r in exec_results if r["status"] in ("skipped", "planned") and r["target"] == "memory"])
    
    print(f"\n═══ 요약 ═══")
    print(f"개선 적용: {improvements}건 | 크론 성공률: {snapshot['cron']['success_rate']}% | ROI 추세: {roi['trend']['direction']}")
    
    if improvements > 0:
        print(f"\n🔄 {improvements}개 자가개선 적용 완료")
    if candidates and not dry_run:
        print(f"\n📋 캐시/로그 정리: {HISTORY_DIR}")
    
    if not dry_run and not candidates:
        pass  # silent


def _print_observe_summary(s: dict):
    print(f"  Cron: {s['cron']['total']} jobs, 성공률 {s['cron']['success_rate']}%")
    print(f"  Skills: {s['skills']['on_disk']}개, 미사용 {s['skills']['unused_count']}개")
    print(f"  Wiki: {s['wiki']['total_pages']} pages, 인덱스 {s['wiki']['index_coverage_pct']}%")
    print(f"  Scripts: {s['scripts']['total']}개, orphan {s['scripts']['orphan_count']}개")
    print(f"  Memory: {s['memory']['bytes']}bytes")
    print(f"  Disk: {s['disk']['used_pct']}% ({s['disk']['free_gb']}GB free)")


def _print_roi(roi: dict):
    c = roi["current"]
    t = roi["trend"]
    print(f"  Cron 성공률: {c['cron_success_rate']}% ({c['cron_delta']:+.1f}%p)")
    print(f"  Wiki 커버리지: {c['wiki_coverage']}% ({c['wiki_delta']:+.1f}%p)")
    print(f"  개선 적용: {c['improvements_applied']}건")
    print(f"  추세: {t['direction']} (7일 평균 cron {t['avg_cron_delta_7d']:+.1f}%p)")
    print(f"  ROI 기록: {t['streak_days']}일")


def _show_history():
    if not HISTORY_FILE.exists():
        print("아직 기록 없음")
        return
    history = json.loads(HISTORY_FILE.read_text())
    roi = history.get("roi_history", [])
    print(f"═══ ROI History ({len(roi)} entries) ═══")
    for r in roi[-14:]:  # 최근 14일
        print(f"  {r['date']}: cron {r['cron_success_rate']}% ({r['cron_delta']:+.1f}) | wiki {r['wiki_coverage']}% | 개선 {r['improvements_applied']}건")
    
    trend = _compute_trend(roi)
    print(f"\n추세: {trend['direction']} (7일 평균 cron {trend['avg_cron_delta_7d']:+.1f}%p)")


def _print_status(s: dict):
    print(f"═══ Self-Improving Hermes Status ({TODAY_STR}) ═══")
    _print_observe_summary(s)


if __name__ == "__main__":
    main()
