#!/usr/bin/env python3
"""
evening_optimization_cycle.py — slow-time optimization roll-up.

SAFE: read-only on log files.
- Daily cycle log 통계: 호출 횟수, 평균 duration, 큰 파일/함수 비율
- 자기 비평: 어떤 cron/script가 자주 실패하는지, 어떤 skill이 미사용인지
"""
import json, os, datetime as dt, re, glob
from pathlib import Path
from collections import Counter, defaultdict

_HH = os.environ.get("HERMES_HOME", "/home/ubuntu")
HH = Path(_HH) if _HH.endswith("/.hermes") else Path(_HH) / ".hermes"


def weekly_log_stats():
    log_dir = HH / "scripts" / "logs"
    if not log_dir.exists():
        return {"count": 0}
    cutoff = dt.datetime.now() - dt.timedelta(days=7)
    files = [f for f in log_dir.rglob("*.jsonl")
             if dt.datetime.fromtimestamp(f.stat().st_mtime) > cutoff]
    lines = sum(1 for f in files for _ in f.open(errors="ignore"))
    return {"recent_7d_files": len(files), "recent_7d_lines": lines}


def orchestrator_run_stats():
    """how many daily-repo-orchestrator cycles ran in last 7d"""
    f = HH / "scripts" / "logs" / "daily-repo-*.jsonl"
    files = list(glob.glob(str(f)))
    cycle_done = 0
    for fp in files:
        for line in open(fp, errors="ignore"):
            try:
                r = json.loads(line)
                if r.get("action") == "cycle" and r.get("stage") == "done":
                    cycle_done += 1
            except Exception:
                pass
    return {"daily_repo_orchestrator_cycles_total": cycle_done}


def cron_failure_breakdown():
    out = subprocess_run_safe(["hermes", "cron", "list", "-o", "json"])
    if not out.strip():
        return {}
    try:
        data = json.loads(out).get("jobs", [])
        cnt = Counter()
        for j in data:
            cnt[j.get("last_status", "unknown")] += 1
        return dict(cnt)
    except Exception:
        return {}


def subprocess_run_safe(cmd, timeout=15):
    import subprocess
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout).stdout
    except Exception:
        return ""


def main():
    out = {
        "ts": dt.datetime.now().isoformat(timespec="seconds"),
        "weekly_log_stats": weekly_log_stats(),
        "orchestrator_runs": orchestrator_run_stats(),
        "cron_status_breakdown": cron_failure_breakdown(),
        # TODO: token usage stats (mini, kimi, openai) — 추후
    }
    print(json.dumps(out, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
