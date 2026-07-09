#!/usr/bin/env python3
"""
design_exec_gap.py — 디자인-실행 갭 측정

목적: cron skill 정의(디자인) vs 실제 실행(실행) 갭을 정량 측정.

3개 metric:
1. Cron success rate (last 7d): ok / total
2. Cron drift (last 30d avg latency): expected vs actual run time
3. Wiki freshness (last updated days)

Usage:
  python3 design_exec_gap.py            # 측정
  python3 design_exec_gap.py --json     # JSON
"""

import sys
import json
import sqlite3
import subprocess
from datetime import datetime, timedelta
from pathlib import Path

HERMES_HOME = Path.home() / ".hermes"
STATE_DB = HERMES_HOME / "state.db"


def cron_success_rate() -> dict:
    """Hermes cron list 결과에서 last_status 추출."""
    result = subprocess.run(
        ["hermes", "cron", "list"],
        capture_output=True, text=True, timeout=10
    )
    output = result.stdout
    total = output.count("Last run:")
    ok = output.count("ok")
    failed = output.count("failed") + output.count("error")
    silent = total - ok - failed  # 빈 출력은 silent (정상)

    rate = round(ok / total * 100, 1) if total else 0.0
    return {
        "total": total,
        "ok": ok,
        "failed": failed,
        "silent": silent,
        "success_pct": rate,
    }


def cron_drift() -> dict:
    """예약 시각 vs 실제 실행 시각 차이 (avg 분)."""
    if not STATE_DB.exists():
        return {"avg_drift_min": None, "samples": 0}

    conn = sqlite3.connect(str(STATE_DB))
    cutoff = (datetime.now() - timedelta(days=7)).timestamp()
    cursor = conn.execute(
        """
        SELECT tool_calls FROM messages
        WHERE tool_name = 'cronjob'
        AND timestamp > ?
        ORDER BY id DESC LIMIT 100
        """,
        (cutoff,),
    )
    drifts = []
    for row in cursor:
        try:
            data = json.loads(row[0]) if row[0] else {}
            # expected vs actual
            exp = data.get("expected_run_at")
            act = data.get("actual_run_at")
            if exp and act:
                d = (act - exp) / 60  # minutes
                drifts.append(abs(d))
        except Exception:
            pass
    conn.close()

    return {
        "avg_drift_min": round(sum(drifts) / len(drifts), 2) if drifts else None,
        "samples": len(drifts),
    }


def wiki_freshness() -> dict:
    """wiki/*.md 평균 updated 경과일."""
    wiki = HERMES_HOME / "wiki"
    if not wiki.exists():
        return {"avg_age_days": None}

    ages = []
    for md in wiki.rglob("*.md"):
        try:
            mtime = md.stat().st_mtime
            age = (datetime.now().timestamp() - mtime) / 86400
            ages.append(age)
        except Exception:
            pass

    return {
        "total_pages": len(ages),
        "avg_age_days": round(sum(ages) / len(ages), 1) if ages else None,
        "max_age_days": round(max(ages), 1) if ages else None,
    }


def compute_gap(cron: dict, drift: dict, wiki: dict) -> dict:
    """디자인-실행 갭 % 산정 (합성 metric)."""
    # Cron 실패율: 0~100%
    cron_gap = round(100 - cron["success_pct"], 1) if cron["success_pct"] else 0

    # Drift: avg_drift_min > 5분이면 gap, 30분이면 max
    if drift["avg_drift_min"] is None:
        drift_gap = 0
    else:
        drift_gap = min(100, round(drift["avg_drift_min"] / 30 * 100, 1))

    # Wiki staleness: avg > 90일이면 max
    wiki_gap = 0
    if wiki["avg_age_days"]:
        wiki_gap = min(100, round(wiki["avg_age_days"] / 90 * 100, 1))

    # 가중 평균 (cron 50%, drift 30%, wiki 20%)
    gap = round(cron_gap * 0.5 + drift_gap * 0.3 + wiki_gap * 0.2, 1)

    return {
        "cron_gap": cron_gap,
        "drift_gap": drift_gap,
        "wiki_gap": wiki_gap,
        "design_exec_gap_pct": gap,
    }


def main():
    json_mode = "--json" in sys.argv

    cron = cron_success_rate()
    drift = cron_drift()
    wiki = wiki_freshness()
    gap = compute_gap(cron, drift, wiki)

    result = {
        "measured_at": datetime.now().isoformat(),
        "cron": cron,
        "drift": drift,
        "wiki": wiki,
        "gap": gap,
    }

    if json_mode:
        print(json.dumps(result, indent=2))
    else:
        print("=== Design-Execution Gap Report ===")
        print(f"measured: {result['measured_at']}")
        print()
        print("[Cron]")
        print(f"  total: {cron['total']}, ok: {cron['ok']}, failed: {cron['failed']}, silent: {cron['silent']}")
        print(f"  success rate: {cron['success_pct']}%")
        print()
        print("[Drift]")
        print(f"  avg_drift_min: {drift['avg_drift_min']}, samples: {drift['samples']}")
        print()
        print("[Wiki]")
        print(f"  total_pages: {wiki['total_pages']}, avg_age: {wiki['avg_age_days']}d")
        print()
        print("[Design-Execution Gap]")
        print(f"  cron_gap:    {gap['cron_gap']}%")
        print(f"  drift_gap:   {gap['drift_gap']}%")
        print(f"  wiki_gap:    {gap['wiki_gap']}%")
        print(f"  ─────────────────────")
        print(f"  TOTAL GAP:   {gap['design_exec_gap_pct']}%")

        verdict = "✓ OK (<10%)" if gap["design_exec_gap_pct"] < 10 else \
                  "⚠ WARN (10-30%)" if gap["design_exec_gap_pct"] < 30 else \
                  "✗ FAIL (>30%)"
        print(f"  verdict: {verdict}")

    sys.exit(0 if gap["design_exec_gap_pct"] < 30 else 1)


if __name__ == "__main__":
    main()