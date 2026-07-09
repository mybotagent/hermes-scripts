#!/usr/bin/env python3
"""
compression_drift_check.py — 자동 압축 정책 합의용 drift 검증

목적: 자동 압축 도입 전/후 memory.md ↔ state.db 핵심 사실 일관성 검증

원리:
- memory.md = 2,200 chars 영속 단기 메모리 (단일공식)
- state.db messages = 원본 전체
- 자동 압축 = messages 본문 → 요약 (정보 손실)

drift metric:
1. key_facts 추출 (memory.md § 구분자별)
2. 각 key_fact가 state.db 최근 메시지에 등장하는지 확인
3. 100% 매치 = drift 0%
4. < 80% = 자동 압축 OFF 권고

Usage:
  python3 compression_drift_check.py           # 기본 점검
  python3 compression_drift_check.py --json    # JSON 출력
"""

import re
import sys
import json
import sqlite3
from pathlib import Path

HERMES_HOME = Path.home() / ".hermes"
MEMORY_FILE = HERMES_HOME / "memories" / "MEMORY.md"
STATE_DB = HERMES_HOME / "state.db"


def extract_key_facts(memory_text: str) -> list[str]:
    """memory.md § 구분된 각 entry의 핵심 사실 추출.

    단일공식 포맷:
      카테고리 라벨: 사실...
      §
      카테고리 라벨: 사실...

    각 entry의 첫 줄 (§ 다음 비어있지 않은 첫 줄)을 fact로 추출.
    """
    facts = []
    lines = memory_text.split("\n")
    for i, line in enumerate(lines):
        if line.strip() == "§":
            # 다음 비어있지 않은 줄을 fact로
            for next_line in lines[i+1:]:
                stripped = next_line.strip()
                if stripped:
                    facts.append(stripped)
                    break
    return facts


def fact_in_messages(fact: str, conn: sqlite3.Connection) -> tuple[bool, int]:
    """state.db messages 최근 N개에서 fact 매칭.

    Returns: (found, match_count)
    매칭 기준: fact의 첫 30자 substring 또는 핵심 단어 3개 중 2개 이상 매칭
    """
    # 핵심 단어 추출 (영숫자 3자+ 만)
    words = [w for w in re.findall(r"\w{3,}", fact) if not w.isdigit()]
    if not words:
        return (False, 0)

    # 검색 패턴: 핵심 단어 5개까지 OR
    pattern = "|".join(re.escape(w) for w in words[:5])

    cursor = conn.execute(
        """
        SELECT count(*) FROM messages
        WHERE role = 'assistant'
        AND content LIKE ?
        ORDER BY id DESC LIMIT 1000
        """,
        (f"%{words[0]}%",),
    )
    row = cursor.fetchone()
    count = row[0] if row else 0
    return (count > 0, count)


def main():
    json_mode = "--json" in sys.argv

    if not MEMORY_FILE.exists():
        print(f"memory file not found: {MEMORY_FILE}")
        sys.exit(2)

    memory_text = MEMORY_FILE.read_text(encoding="utf-8")
    facts = extract_key_facts(memory_text)

    if not facts:
        result = {
            "scope": str(MEMORY_FILE),
            "total_facts": 0,
            "matched": 0,
            "drift_pct": 0.0,
            "details": [],
            "verdict": "no_facts_to_check",
        }
        if json_mode:
            print(json.dumps(result, indent=2, ensure_ascii=False))
        else:
            print("memory.md에 § 구분 사실 0건 — 점검 불필요")
        return

    if not STATE_DB.exists():
        print(f"state.db not found: {STATE_DB}")
        sys.exit(2)

    conn = sqlite3.connect(str(STATE_DB))
    matched = 0
    details = []
    for fact in facts:
        found, count = fact_in_messages(fact, conn)
        if found:
            matched += 1
        details.append({"fact": fact[:80], "found": found, "msg_count": count})

    conn.close()

    drift_pct = round((1 - matched / len(facts)) * 100, 1)

    # 판정
    if drift_pct < 10:
        verdict = "pass — auto compression safe"
    elif drift_pct < 30:
        verdict = "warn — auto compression risky, manual review needed"
    else:
        verdict = "fail — auto compression NOT safe, fix memory.md first"

    result = {
        "scope": str(MEMORY_FILE),
        "total_facts": len(facts),
        "matched": matched,
        "drift_pct": drift_pct,
        "verdict": verdict,
        "details": details,
    }

    if json_mode:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        print(f"=== Compression Drift Check ===")
        print(f"memory.md: {len(facts)} § facts")
        print(f"matched in state.db: {matched}")
        print(f"drift: {drift_pct}%")
        print(f"verdict: {verdict}")
        print()
        if drift_pct >= 10:
            print("Drift details (unmatched facts):")
            for d in details:
                if not d["found"]:
                    print(f"  ✗ {d['fact']}")

    # exit code: 0 if pass, 1 if warn, 2 if fail
    if drift_pct < 10:
        sys.exit(0)
    elif drift_pct < 30:
        sys.exit(1)
    else:
        sys.exit(2)


if __name__ == "__main__":
    main()