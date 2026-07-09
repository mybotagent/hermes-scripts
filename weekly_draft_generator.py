#!/usr/bin/env python3
"""
weekly_draft_generator.py — 주간 wiki page 초안 생성 (publish는 사용자 confirm).

SAFE: 파일 write. 사용자가 명시한 영역.
- 금주 작업 통계 → wiki/raw/<YYYY-Wxx>.md
- 기존 wiki 페이지 인용 + todo 추가
"""
import os, json, datetime as dt
from pathlib import Path

_HH = os.environ.get("HERMES_HOME", "/home/ubuntu")
HH = Path(_HH) if _HH.endswith("/.hermes") else Path(_HH) / ".hermes"


def iso_week():
    w = dt.date.today().isocalendar()
    return w.week, w.year


def recent_logfiles(n=14):
    log = HH / "wiki" / "logs" / "2026"
    files = sorted(log.rglob("*.md"), key=lambda f: f.stat().st_mtime, reverse=True)[:n]
    return files


def main():
    week, year = iso_week()
    out_path = HH / "wiki" / "raw" / f"{year}-W{week:02d}-weekly-recap-draft.md"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    files = recent_logfiles()

    body = f"""# 주간 회고 초안 ({year}-W{week:02d})

> 자동 생성 (publish 전 사용자 확인). `wiki/raw/`에 보존.

## Recent log files ({len(files)})
"""
    for f in files:
        rel = f.relative_to(HH)
        title = f.read_text().splitlines()[0] if f.read_text().strip() else "(empty)"
        mtime = dt.datetime.fromtimestamp(f.stat().st_mtime).isoformat(timespec="seconds")
        body += f"- `{rel}` — {mtime}\n"

    body += """
## Skeleton (사용자 채우기)
- 이번 주 핵심 작업 3개
- 발생한 문제 / 해결
- 다음 주 의도

## 결정 / 발견
- (TODO)
"""
    out_path.write_text(body, encoding="utf-8")
    print(f"Wrote: {out_path}")


if __name__ == "__main__":
    main()
