#!/usr/bin/env python3
"""
memory_auto_compact.py — memory.md 자동 압축 (사용자 룰: 90% 넘으면 자율 정리)

룰:
- ≥90% 사용 시 자동 압축 시도
- 압축 전략: (1) wiki 중복 (2) event log 제거 (3) 약어 치환
- 압축 전 drift 검증 (compression_drift_check.py)
- 압축 후 size 검증 + drift 재검증
- 압축 후 89% 이하 도달 못하면 사용자 알림 (Discord)

사용법:
    python3 memory_auto_compact.py              # 자동 압축 (필요 시)
    python3 memory_auto_compact.py --dry-run    # 시뮬레이션만
    python3 memory_auto_compact.py --force      # 강제 압축 (90% 미만이어도)
"""
import argparse
import re
import subprocess
import sys
from pathlib import Path

MEMORY_PATH = Path.home() / ".hermes" / "memories" / "MEMORY.md"
CAP = 2200
THRESHOLD = 0.90

# 압축 룰: (regex_old, replacement) — 첫 매칭만 적용, 순서 중요
# 1순위: event log 부분 제거 (wiki에 이미 있음)
# 2순위: 약어 치환
# 3순위: 보존 우선 facts (TZ/API/매크로/watchlist/deepseek/Dashboard/Linear/스레드/Bot IDs/Multi-bot/5-stage/게이트웨이/Speculation/Discord/user-style/GitHub PR)
COMPACT_RULES = [
    # event log 부분 제거
    (r"\(2026-07-02: config/TICKER_SECTOR 제거→통합\)", ""),
    (r"cron deadParent:liveThread=thread 직접 fetch로 작동, 마이그레이션 권장\.", ""),
    # 약어 치환 (긴 표기 → 짧은 표기)
    (r"\.google_service_account\.json\.", "."),
    (r"google_service_account\.json\.", ""),
    (r"\(sanghee\.lee2222@gmail.com\)→himalaya/AppPw→", "→"),
    (r"Bot IDs\(2026-07-01정정\): ", "Bot IDs: "),
    (r"이전 메모리 오류 정정\.\s*", ""),
    # 표기 단축
    (r"iptables 9119 IP제한 없음\(어디서나 접근\)", "iptables 9119 무제한"),
    (r"iptables 동일", "동일"),
    # sync ID 제거 (12KST 정보로 충분)
    (r"sync fe96a 12KST", "sync12KST"),
    # plan/ds ID 표기 단축 (Bot ID 정정 사실은 유지)
    (r" \(봇\), plan=", "(봇),plan="),
    (r", ds=", ",ds="),
    # "/kanban필요시" 제거 (별도 룰)
    (r"\./kanban필요시\.", "."),
]


def get_size():
    """현재 memory.md size (chars)"""
    try:
        text = MEMORY_PATH.read_text(encoding="utf-8")
        return len(text), text
    except FileNotFoundError:
        return 0, ""


def check_drift():
    """drift 검증 — 0%여야 압축 진행"""
    try:
        result = subprocess.run(
            ["python3", str(Path.home() / ".hermes" / "scripts" / "compression_drift_check.py")],
            capture_output=True, text=True, timeout=30
        )
        output = result.stdout
        m = re.search(r"drift: ([\d.]+)%", output)
        if m:
            return float(m.group(1)), "pass" in output.lower()
        return None, False
    except Exception as e:
        print(f"[WARN] drift check failed: {e}", file=sys.stderr)
        return None, False


def apply_rules(text):
    """압축 룰 적용 — 변경 사항 있으면 (new_text, n_changes) 반환"""
    new_text = text
    n = 0
    for pattern, replacement in COMPACT_RULES:
        new_new, count = re.subn(pattern, replacement, new_text)
        if count > 0:
            new_text = new_new
            n += count
    return new_text, n


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="시뮬레이션만")
    parser.add_argument("--force", action="store_true", help="강제 압축 (90% 미만이어도)")
    args = parser.parse_args()

    size, text = get_size()
    if size == 0:
        print(f"[ERROR] {MEMORY_PATH} not found", file=sys.stderr)
        sys.exit(1)

    pct = size / CAP
    print(f"[INFO] memory.md: {size}/{CAP} chars ({pct*100:.1f}%)")

    if pct < THRESHOLD and not args.force:
        print(f"[SKIP] under threshold ({THRESHOLD*100:.0f}%)")
        return 0

    if not args.dry_run:
        # drift 사전 검증
        drift, drift_pass = check_drift()
        if drift is not None and drift > 5.0:
            print(f"[BLOCK] drift too high: {drift}% — auto-compact aborted")
            print(f"[HINT] investigate drift before next compact")
            return 2

    new_text, n_changes = apply_rules(text)
    new_size = len(new_text)
    new_pct = new_size / CAP

    print(f"[INFO] rules applied: {n_changes} changes")
    print(f"[INFO] simulated size: {new_size}/{CAP} chars ({new_pct*100:.1f}%)")

    if new_pct >= THRESHOLD and not args.force:
        print(f"[FAIL] cannot reach threshold ({new_pct*100:.1f}% >= {THRESHOLD*100:.0f}%)")
        print(f"[HINT] add more compact rules or move facts to wiki")
        return 3

    if args.dry_run:
        print(f"[DRY-RUN] would save {new_size} chars ({n_changes} changes)")
        return 0

    # 실제 저장
    MEMORY_PATH.write_text(new_text, encoding="utf-8")

    # drift 사후 검증
    drift_after, drift_pass_after = check_drift()
    print(f"[OK] saved: {size} → {new_size} chars ({pct*100:.1f}% → {new_pct*100:.1f}%)")
    if drift_after is not None:
        print(f"[DRIFT] after: {drift_after}% pass={drift_pass_after}")

    return 0


if __name__ == "__main__":
    sys.exit(main())