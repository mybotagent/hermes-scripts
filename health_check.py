#!/usr/bin/env python3
"""매일 시스템 헬스체크: 서비스 포트, 시스템 리소스, cron 상태"""

import os
import socket
import subprocess
import sys
from datetime import datetime, timedelta, timezone

KST = timezone(timedelta(hours=9))
now = datetime.now(KST)

checks = {
    "서비스": [],
    "시스템": [],
    "크론": [],
}

PASS = "✅"
FAIL = "❌"
WARN = "⚠️"

# ───── 서비스 포트 체크 ─────
services = [
    ("Nginx (Dashboard Proxy)", 9119),
    ("Hermes Dashboard (Backend)", 9199),
    ("API Server", 8642),
    ("Webhook Server", 8644),
]

for name, port in services:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=3):
            checks["서비스"].append(f"{PASS} {name} (:{port})")
    except Exception:
        checks["서비스"].append(f"{FAIL} {name} (:{port}) — 연결 안 됨")

# Gateway systemd
try:
    r = subprocess.run(
        ["systemctl", "--user", "is-active", "hermes-gateway.service"],
        capture_output=True, text=True, timeout=5
    )
    if r.stdout.strip() == "active":
        checks["서비스"].append(f"{PASS} Hermes Gateway (systemd)")
    else:
        checks["서비스"].append(f"{FAIL} Hermes Gateway (systemd) — {r.stdout.strip()}")
except Exception as e:
    checks["서비스"].append(f"{FAIL} Hermes Gateway (systemd) — {e}")

# nginx systemd
try:
    r = subprocess.run(
        ["systemctl", "is-active", "nginx"],
        capture_output=True, text=True, timeout=5
    )
    if r.stdout.strip() == "active":
        checks["서비스"].append(f"{PASS} Nginx (systemd)")
    else:
        checks["서비스"].append(f"{FAIL} Nginx (systemd) — {r.stdout.strip()}")
except Exception as e:
    checks["서비스"].append(f"{FAIL} Nginx (systemd) — {e}")

# ───── 시스템 리소스 ─────
# Disk
try:
    r = subprocess.run(["df", "-h", "/"], capture_output=True, text=True, timeout=5)
    lines = r.stdout.strip().split("\n")
    parts = lines[-1].split()
    used_pct = int(parts[4].rstrip("%"))
    icon = PASS if used_pct < 70 else (WARN if used_pct < 85 else FAIL)
    checks["시스템"].append(f"{icon} Disk /: {used_pct}% ({parts[2]} / {parts[1]})")
except Exception as e:
    checks["시스템"].append(f"{FAIL} Disk: {e}")

# Memory
try:
    r = subprocess.run(["free", "-m"], capture_output=True, text=True, timeout=5)
    parts = r.stdout.strip().split("\n")[1].split()
    total_m = int(parts[1])
    avail_m = int(parts[6])
    used_pct = round((total_m - avail_m) / total_m * 100)
    used_gb = (total_m - avail_m) / 1024
    total_gb = total_m / 1024
    icon = PASS if used_pct < 70 else (WARN if used_pct < 85 else FAIL)
    checks["시스템"].append(f"{icon} Memory: {used_pct}% ({used_gb:.1f}G / {total_gb:.1f}G)")
except Exception as e:
    checks["시스템"].append(f"{FAIL} Memory: {e}")

# Load + Uptime
try:
    r = subprocess.run(["uptime"], capture_output=True, text=True, timeout=5)
    parts = r.stdout.strip().split("load average: ")
    loads = [float(x.strip()) for x in parts[1].split(",")] if len(parts) > 1 else [0, 0, 0]
    cpu_count = os.cpu_count() or 1
    icons = []
    for l in loads:
        ratio = l / cpu_count
        icons.append(PASS if ratio < 0.5 else (WARN if ratio < 1.0 else FAIL))
    checks["시스템"].append(f"부하: {' '.join(icons)} 1m={loads[0]:.2f} 5m={loads[1]:.2f} 15m={loads[2]:.2f} (cores={cpu_count})")

    r2 = subprocess.run(["uptime", "-p"], capture_output=True, text=True, timeout=5)
    checks["시스템"].append(f"🕐 {r2.stdout.strip()}")
except Exception as e:
    checks["시스템"].append(f"{FAIL} Load: {e}")

# ───── 크론 상태 ─────
try:
    r = subprocess.run(
        ["hermes", "cron", "list"],
        capture_output=True, text=True, timeout=15,
        env={**os.environ, "PATH": os.environ.get("PATH", "")}
    )
    if r.returncode == 0 and r.stdout.strip():
        lines = r.stdout.strip().split("\n")
        total = 0
        active = 0
        has_issues = False
        for line in lines:
            ls = line.strip()
            if "[active]" in ls or "[paused]" in ls:
                total += 1
                if "[active]" in ls:
                    active += 1
            if "⚠ Delivery failed" in ls or "error" in ls.lower():
                has_issues = True
        paused = total - active
        checks["크론"].append(f"📊 크론: {total}개 중 {active}개 활성, {paused}개 일시중지")
        if has_issues:
            checks["크론"].append(f"  {WARN} 일부 크론 전송 실패 있음")
        else:
            checks["크론"].append(f"  {PASS} 모든 크론 정상")
    else:
        checks["크론"].append(f"{WARN} 크론 목록 조회 불가")
except Exception as e:
    checks["크론"].append(f"{WARN} 크론 상태: {e}")

# ───── 출력 ─────
print(f"🏥 Hermes 시스템 헬스체크 — {now.strftime('%Y-%m-%d %H:%M KST')}")
print()

all_ok = True
for category, items in checks.items():
    if not items:
        continue
    print(f"─── {category} ───")
    for item in items:
        print(item)
        if item.startswith(FAIL):
            all_ok = False
    print()

# Summary line
summary_parts = []
for category, items in checks.items():
    cnt_ok = 0
    cnt_warn = 0
    cnt_fail = 0
    for item in items:
        if item.startswith(PASS):
            cnt_ok += 1
        elif item.startswith(WARN):
            cnt_warn += 1
        elif item.startswith(FAIL):
            cnt_fail += 1
        else:
            # 깃발 아이콘이 앞에 없는 항목 (통계/데이터 라인) — 내부에서 깃발 검색
            cnt_ok += item.count(PASS)
            cnt_warn += item.count(WARN)
            cnt_fail += item.count(FAIL)
    parts = []
    if cnt_ok: parts.append(f"{PASS}{cnt_ok}")
    if cnt_warn: parts.append(f"{WARN}{cnt_warn}")
    if cnt_fail: parts.append(f"{FAIL}{cnt_fail}")
    summary_parts.append(f"{category}: {' '.join(parts)}")

print(f"--- 요약 ---")
print(" | ".join(summary_parts))
print()
if all_ok:
    print(f"{PASS} 모든 시스템 정상")
else:
    print(f"{FAIL} 일부 서비스 비정상 — 조치 필요!")

sys.exit(0 if all_ok else 1)
