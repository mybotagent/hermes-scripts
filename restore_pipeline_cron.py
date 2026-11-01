#!/usr/bin/env python3
"""
restore_pipeline_cron.py — 삭제된 18:35 LangGraph 파이프라인 크론 복구

WHY (2026-11-01):
jobs.json 백업 비교 결과 `afebf6cb0ab1` (🧠 LangGraph 파이프라인 18:35)이
2026-08-19 ~ 2026-10-23 사이에 라이브 jobs.json에서 삭제됨.
그 결과 10월 파이프라인 산출물 0건 → 월간 성과 리포트 데이터 없음.

원본 정의는 jobs.json.bak.20260818-201119에서 복원 (invent하지 않음).
"""
import json
import os
import shutil
import sys
from datetime import datetime

JOBS = os.path.expanduser("~/.hermes/cron/jobs.json")
BAK = os.path.expanduser("~/.hermes/cron/jobs.json.bak.20260818-201119")
TARGET_ID = "afebf6cb0ab1"


def main():
    if not os.path.exists(BAK):
        print(f"❌ 백업 없음: {BAK}")
        return 1

    with open(BAK, encoding="utf-8") as f:
        bak = json.load(f)

    original = next((j for j in bak["jobs"] if j["id"] == TARGET_ID), None)
    if not original:
        print(f"❌ 백업에 {TARGET_ID} 없음")
        return 1

    with open(JOBS, encoding="utf-8") as f:
        live = json.load(f)

    if any(j["id"] == TARGET_ID for j in live["jobs"]):
        print(f"✅ {TARGET_ID} 이미 존재 — 복구 불필요")
        return 0

    # 백업
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    bak_path = f"{JOBS}.bak_restore_{stamp}"
    shutil.copy2(JOBS, bak_path)

    # 복원: 상태 필드는 초기화 (과거 에러 정보는 새롭지 않음)
    job = dict(original)
    job["created_at"] = datetime.now().astimezone().isoformat()
    job["last_run_at"] = None
    job["last_status"] = None
    job["last_error"] = None
    job["last_delivery_error"] = None
    job["repeat"] = {"times": None, "completed": 0}
    job["state"] = "scheduled"
    job["enabled"] = True
    job["paused_at"] = None
    job["paused_reason"] = None
    job["fire_claim"] = None
    job["next_run_at"] = None  # 스케줄러가 재계산

    live["jobs"].append(job)

    tmp = JOBS + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(live, f, indent=2, ensure_ascii=False)
    os.replace(tmp, JOBS)

    print(f"✅ {TARGET_ID} 복원 완료")
    print(f"   이름: {job['name']}")
    print(f"   스케줄: {job.get('schedule_display')}")
    print(f"   deliver: {job.get('deliver')}")
    print(f"   백업: {bak_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
