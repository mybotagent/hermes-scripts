#!/usr/bin/env python3
"""
hermes_disk_hygiene.py — 디스크 자동 정리 (autonomous-mode safe)

3-tier 임계치 단일공식:
- df 80%+  caution (silent)
- df 90%+  warn  (사용자 알림 + safe-cleanup 자동)
- df 95%+  critical (사용자 알림 + aggressive safe-cleanup)

점유 측정 6축:
1. df /home 전체 점유율
2. state.db 사이즈 (272 MB default, WAL 별도 측정)
3. state-snapshots 누적 (.db.gz 스냅샷, 30일+ 묵은 것)
4. sessions/*.jsonl (180일+ 자동 압축)
5. logs/*.log + logs/agent.log.* (10MB+ rotated log 압축)
6. hermes-agent/.git/objects/pack/tmp_pack_* (git gc 누락 잔존 — safe)

DRY-first 운영 정책 (사용자):
- DRY_RUN=1 (default): print만, 어떤 mutation도 안 함
- DRY_RUN=0: tier별 safe-cleanup 실행. 단, 사용자 secret/state.db 삭제 ❌.

사용법:
    python3 hermes_disk_hygiene.py            # dry-run only (default)
    DRY_RUN=0 python3 hermes_disk_hygiene.py  # safe-cleanup 실행
"""
from __future__ import annotations
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from datetime import datetime, timezone, timedelta

HERMES_HOME = Path(os.environ.get("HERMES_HOME", Path.home() / ".hermes"))
LOG_DIR = HERMES_HOME / "cron" / "output"
LOG_DIR.mkdir(parents=True, exist_ok=True)
LOG_FILE = LOG_DIR / "hermes-disk-hygiene-latest.log"

# --- Thresholds (단일공식, 사용자 결정 전까지 고정) --------------------
DF_CAUTION = 80
DF_WARN = 90
DF_CRITICAL = 95

STATE_DB_BYTES_WARN = 300 * 1024 * 1024   # 300MB
SNAPSHOT_RETENTION_DAYS = 30
SESSION_RETENTION_DAYS = 180
LOG_SIZE_TRUNCATE = 10 * 1024 * 1024     # rotated log 10MB

DRY_RUN = os.environ.get("DRY_RUN", "1") not in ("0", "false", "False", "")

# At import time, log which mode we are in (helps cron debugging).
import sys as _sys
if _sys.argv[0].endswith("hermes_disk_hygiene.py"):
    pass  # silence


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def log(msg: str) -> None:
    line = f"[{now_iso()}] {msg}"
    print(line)
    with LOG_FILE.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


# --- Tier 1: df /home --------------------------------------------------
def measure_df() -> dict:
    try:
        out = subprocess.run(["df", "--output=pcent,used,avail,target", "/home"],
                              capture_output=True, text=True, timeout=5)
        lines = out.stdout.strip().splitlines()
        if len(lines) < 2:
            return {"pct": 0, "raw": out.stdout}
        # ' 73%  ...  /home'
        parts = lines[1].split()
        pct = int(parts[0].rstrip("%"))
        return {"pct": pct, "raw": lines[1], "parts": parts}
    except Exception as e:
        return {"pct": 0, "error": str(e)}


# --- Tier 2: state.db + WAL ------------------------------------------
def measure_state_db() -> dict:
    p = HERMES_HOME / "state.db"
    shm = HERMES_HOME / "state.db-shm"
    wal = HERMES_HOME / "state.db-wal"
    info = {"path": str(p), "size": p.stat().st_size if p.exists() else 0,
            "shm": shm.stat().st_size if shm.exists() else 0,
            "wal": wal.stat().st_size if wal.exists() else 0}
    return info


# --- Tier 3: state-snapshots (오래된 .db.gz) --------------------------
def measure_snapshots() -> list:
    snap_dir = HERMES_HOME / "state-snapshots"
    if not snap_dir.exists():
        return []
    items = []
    cutoff = datetime.now(timezone.utc) - timedelta(days=SNAPSHOT_RETENTION_DAYS)
    for p in sorted(snap_dir.rglob("state.db.gz")):
        try:
            mtime = datetime.fromtimestamp(p.stat().st_mtime, timezone.utc)
            items.append({"path": str(p), "size": p.stat().st_size,
                           "mtime": mtime.isoformat(timespec="seconds"),
                           "age_days": (datetime.now(timezone.utc) - mtime).days})
        except Exception:
            continue
    return items


# --- Tier 4: sessions/*.jsonl ----------------------------------------
def measure_sessions() -> dict:
    sess = HERMES_HOME / "sessions"
    if not sess.exists():
        return {"count": 0, "old": [], "total": 0}
    total = 0
    old = []
    cutoff = datetime.now(timezone.utc) - timedelta(days=SESSION_RETENTION_DAYS)
    for p in sess.glob("session_*.json"):
        try:
            sz = p.stat().st_size
            total += sz
            mtime = datetime.fromtimestamp(p.stat().st_mtime, timezone.utc)
            if mtime < cutoff:
                old.append({"path": str(p), "size": sz, "mtime": mtime.isoformat(timespec="seconds")})
        except Exception:
            continue
    return {"count": len(list(sess.glob("session_*.json"))), "old_count": len(old),
             "old_total": sum(o["size"] for o in old), "old": old[:5],
             "total": total}


# --- Tier 5: logs/ -----------------------------------------------------
def measure_logs() -> dict:
    log_dir = HERMES_HOME / "logs"
    if not log_dir.exists():
        return {"rotated": [], "total": 0}
    items = []
    total = 0
    for p in log_dir.glob("*.log.*"):  # rotated logs (agent.log.1/2/3 etc)
        try:
            sz = p.stat().st_size
            total += sz
            if sz >= LOG_SIZE_TRUNCATE:
                items.append({"path": str(p), "size": sz, "age": p.stat().st_mtime})
        except Exception:
            continue
    return {"rotated": items, "count": len(items), "total": total}


# --- Tier 6: tmp_pack_ 잔존 ------------------------------------------
def measure_tmp_pack() -> dict:
    items = []
    for d in HERMES_HOME.glob("**/.git/objects/pack/"):
        if not d.is_dir():
            continue
        for p in d.glob("tmp_pack_*"):
            try:
                items.append({"path": str(p), "size": p.stat().st_size})
            except Exception:
                continue
    return {"count": len(items), "total": sum(i["size"] for i in items),
             "items": items[:5]}


# --- Actions (DRY-first, safe 패턴) -----------------------------------
def safe_action(label: str, fn, *args) -> bool:
    """DRY_RUN=1이면 print만, 0이면 fn 실행. 실패해도 격리."""
    if DRY_RUN:
        log(f"DRY: would {label} ({args})")
        return False
    try:
        log(f"ACT: {label}")
        fn(*args)
        log(f"  → OK")
        return True
    except Exception as e:
        log(f"  → FAIL: {e}")
        return False


def cleanup_snapshot(item: dict) -> None:
    Path(item["path"]).unlink()


def cleanup_log(item: dict) -> None:
    # rotation truncate: 0 byte로 비우지 않고 마지막 1000줄만 keep (심볼릭 압축)
    p = Path(item["path"])
    try:
        with p.open("rb") as f:
            f.seek(0, 2)
            size = f.tell()
        if size <= 1024 * 1024:
            return
        # keep last 1MB
        with p.open("rb") as f:
            f.seek(size - 1024 * 1024)
            data = f.read()
        with p.open("wb") as f:
            f.write(data)
    except Exception:
        pass


def git_gc_specific(pack_dir: str) -> None:
    """Run git gc in the .git's parent repo (one level up from objects/pack)."""
    p = Path(pack_dir)
    # .../objects/pack/  → repo root is 4 levels up
    repo_root = p.parent.parent.parent
    if (repo_root / ".git").exists():
        subprocess.run(["git", "gc", "--prune=now"], cwd=repo_root,
                        capture_output=True, timeout=120)


def main() -> int:
    log(f"===== hermes-disk-hygiene START (mode={'DRY' if DRY_RUN else 'PROD'}) =====")

    df = measure_df()
    sdb = measure_state_db()
    snaps = measure_snapshots()
    sess = measure_sessions()
    logs = measure_logs()
    tmp = measure_tmp_pack()

    log(f"DF /home: {df.get('pct')}%  {df.get('raw','')}")
    log(f"state.db: {sdb['size']/1024/1024:.1f} MB  WAL {sdb['wal']/1024/1024:.1f} MB  SHM {sdb['shm']/1024/1024:.1f} MB")
    log(f"snapshots: {len(snaps)} (>{SNAPSHOT_RETENTION_DAYS}d: {[s for s in snaps if s['age_days']>SNAPSHOT_RETENTION_DAYS][:3]})")
    log(f"sessions: {sess['count']} files, >{SESSION_RETENTION_DAYS}d: {sess['old_count']} ({sess['old_total']/1024/1024:.1f} MB)")
    log(f"rotated logs (>=10MB): {logs['count']} files ({logs['total']/1024/1024:.1f} MB total)")
    log(f"tmp_pack_ 잔존: {tmp['count']} files ({tmp['total']/1024/1024:.1f} MB)")

    # --- Decisions -------------------------------------------------------
    pct = df.get("pct", 0)
    tier = "OK"
    if pct >= DF_CRITICAL:
        tier = "CRITICAL"
    elif pct >= DF_WARN:
        tier = "WARN"
    elif pct >= DF_CAUTION:
        tier = "CAUTION"
    log(f"TIER: {tier} (thresholds: {DF_CAUTION}/{DF_WARN}/{DF_CRITICAL}%)")

    actions_taken = []

    # tmp_pack_ 무조건 safe-cleanup 가능 (git gc 잔존 — 항상 safe)
    for it in tmp.get("items", []):
        # safe-action: 실제로는 git gc를 repo에서 실행 (tmp_pack_ 자동 정리)
        if safe_action(f"git gc on {it['path']} (clears tmp_pack_)", git_gc_specific, str(Path(it["path"]).parent)):
            actions_taken.append(f"git_gc {Path(it['path']).parent.parent.parent}")

    # snapshots 30일+ 묵은 것 (사용자 결정 영역 — DRY 모드에선 보고만)
    old_snaps = [s for s in snaps if s["age_days"] > SNAPSHOT_RETENTION_DAYS]
    if old_snaps:
        log(f"SNAPSHOTS >{SNAPSHOT_RETENTION_DAYS}d: {len(old_snaps)}개 (각 {old_snaps[0]['size']/1024/1024:.1f}MB)")
        # DRY 모드에선 alert only (사용자가 'snapshot 삭제 OK' 명시해야만 실행)
        if not DRY_RUN:
            log("  (DRY_RUN=0이지만 snapshot 삭제는 사용자 결정 영역 — alert only 유지)")

    # logs rotated (DRY 모드에선 alert, 0일 때만 1MB로 truncate)
    if logs.get("count", 0) > 0 and (tier in ("WARN", "CRITICAL") or not DRY_RUN):
        for it in logs["rotated"][:3]:
            safe_action(f"truncate rotated log {Path(it['path']).name}", cleanup_log, it)
            actions_taken.append(f"truncate {it['path']}")

    # state.db (사용자 결정 — alert only)
    if sdb["size"] >= STATE_DB_BYTES_WARN:
        log(f"⚠ state.db ≥ {STATE_DB_BYTES_WARN/1024/1024:.0f}MB ({sdb['size']/1024/1024:.1f}MB) — VACUUM 후보 (사용자 결정)")
        log("  → alert only (sqlite3 VACUUM은 사용자 명시 OK 후에만)")

    # sessions 180일+ (DRY 모드 alert only)
    if sess.get("old_count", 0) > 0:
        log(f"sessions >{SESSION_RETENTION_DAYS}d: {sess['old_count']}개 ({sess['old_total']/1024/1024:.1f}MB) — 사용자 결정")
        if not DRY_RUN:
            log("  (DRY_RUN=0이지만 session 삭제는 사용자 결정 영역 — alert only)")

    if tier in ("WARN", "CRITICAL"):
        log(f"⚠ TIER {tier} — 사용자 Discord 알림 권장")
    elif tier == "CAUTION":
        log(f"CAUTION — silent log only (tier escalate <WARN까지 사용자 알림 ❌)")

    log(f"===== hermes-disk-hygiene END (actions={len(actions_taken)}) =====")
    return 0


if __name__ == "__main__":
    sys.exit(main())
