#!/usr/bin/env python3
"""
self_consistency_check.py — cron health / wiki / memory sanity
SAFE: read-only.
"""
import json, os, re, subprocess, datetime as dt
from pathlib import Path
from collections import Counter

_HH = os.environ.get("HERMES_HOME", "/home/ubuntu")
HH = Path(_HH) if _HH.endswith("/.hermes") else Path(_HH) / ".hermes"


def get_cron_list():
    out = subprocess.run(["hermes", "cron", "list"], capture_output=True, text=True, timeout=15).stdout
    try:
        return json.loads(out).get("jobs", [])
    except Exception:
        return []


def get_wiki_pages(hh):
    """wiki/index.md pages count"""
    f = hh / "wiki" / "index.md"
    if not f.exists():
        f = hh / "wiki" / "INDEX.md"
    if not f.exists():
        return 0
    return sum(1 for line in f.read_text().splitlines() if line.startswith("|"))


def get_skill_count(hh):
    s = hh / "skills"
    if not s.exists():
        return 0
    return sum(1 for _ in s.rglob("SKILL.md"))


def get_memory_size(hh):
    candidates = ["MEMORY.md", "memory.md"]
    for c in candidates:
        p = hh / c
        if p.exists():
            return {"file": c, "lines": sum(1 for _ in p.open())}
    return {"file": None, "lines": 0}


def get_wiki_logs_recent(hh, days=7):
    """logs/2026/* 안 최근 N일 변경 파일 수"""
    log_dir = hh / "wiki" / "logs" / "2026"
    if not log_dir.exists():
        return 0
    cutoff = dt.datetime.now() - dt.timedelta(days=days)
    return sum(1 for f in log_dir.rglob("*.md")
               if dt.datetime.fromtimestamp(f.stat().st_mtime) > cutoff)


def main():
    cron_jobs = get_cron_list()
    last_status = Counter(j.get("last_status", "unknown") for j in cron_jobs)
    failed = [j["name"] for j in cron_jobs if j.get("last_status") == "error"]
    paused = [j["name"] for j in cron_jobs if j.get("state") == "paused"]

    out = {
        "ts": dt.datetime.now().isoformat(timespec="seconds"),
        "cron_total": len(cron_jobs),
        "cron_status_breakdown": dict(last_status),
        "cron_failed_names": failed,
        "cron_paused_names": paused,
        "wiki_pages": get_wiki_pages(HH),
        "skill_count": get_skill_count(HH),
        "memory": get_memory_size(HH),
        "wiki_logs_recent_7d": get_wiki_logs_recent(HH),
    }

    print(json.dumps(out, indent=2, ensure_ascii=False))

    if failed:
        print(f"\n[ALERT] cron failures: {', '.join(failed)}")
    if len(paused) > 2:
        print(f"[INFO] paused cron count > 2: {len(paused)}")


if __name__ == "__main__":
    main()
