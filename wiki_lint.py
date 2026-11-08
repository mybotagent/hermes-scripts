#!/usr/bin/env python3
"""
wiki_lint.py — SCHEMA.md 8종 lint 자동 점검

8종 (SCHEMA.md §Lint 참조):
  ① orphan — inbound link 0인 페이지
  ② broken wikilink — [[link]] 대상 없음
  ③ INDEX.md 누락 — 파일은 있는데 index.md에 없음
  ④ frontmatter 검증 — research/ 필수 필드
  ⑤ stale content — research/ updated >90일
  ⑥ 모순 — research/ contested: true frontmatter
  ⑦ 품질 — confidence: low 또는 단일 출처
  ⑧ tag audit — SCHEMA.md taxonomy 외 태그

Usage:
  python3 wiki_lint.py              # 전체 wiki 점검
  python3 wiki_lint.py research/    # research/ 만
  python3 wiki_lint.py --json       # JSON 출력
"""

import sys
import re
from pathlib import Path
from datetime import datetime, timedelta

WIKI = Path.home() / ".hermes" / "wiki"
INDEX = WIKI / "index.md"
SCHEMA = WIKI / "SCHEMA.md"

# Research frontmatter 필수 필드
REQUIRED_FIELDS = ["type", "title", "created", "updated", "tags"]

# 서브모듈 디렉토리 — 부모 wiki index/lint 대상에서 제외 (P19 fix, self_hermes.py와 동일 규칙)
# 서브모듈은 각자 자체 index.md를 가지므로 부모 catalog에 섞지 않는다.
SUBMODULE_DIRS = {"logs", "subagents-library", "trade-pipeline"}

# SCHEMA.md §1 태그 taxonomy — 하드코딩 근사치 대신 실제 문서에서 추출
def _load_known_tags() -> set[str]:
    """SCHEMA.md §1 taxonomy 표에서 모든 `tag` 코드를 추출한다.
    근사치 하드코딩 금지 (2026-11-08 주간 cleanup에서 research 태그 오탐 8건 발생)."""
    tags: set[str] = set()
    if not SCHEMA.exists():
        return tags
    content = SCHEMA.read_text(encoding="utf-8", errors="ignore")
    # taxonomy 표는 §1 "~ §2" 섹션 안에 있음
    start = content.find("## 1.")
    end = content.find("## 2.", start)
    section = content[start:end] if start >= 0 and end > start else content
    for line in section.splitlines():
        if not line.strip().startswith("|"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 2:
            continue
        for cell in cells[:-1]:  # 마지막 칸(적용 디렉토리)은 태그가 아님
            for code in re.findall(r"`([a-z0-9][a-z0-9._-]*)`", cell):
                tags.add(code)
    return tags


KNOWN_TAGS = _load_known_tags()


def read_frontmatter(path: Path) -> dict:
    """파일 첫 --- 블록 파싱."""
    try:
        content = path.read_text(encoding="utf-8")
    except Exception:
        return {}
    if not content.startswith("---"):
        return {}
    end = content.find("---", 3)
    if end < 0:
        return {}
    fm = {}
    for line in content[3:end].strip().split("\n"):
        if ":" in line:
            k, v = line.split(":", 1)
            fm[k.strip()] = v.strip()
    return fm


def get_md_files(base: Path):
    """서브모듈 디렉토리(logs/, subagents-library/)는 제외 — P19 fix.
    서브모듈은 자체 index.md를 가지므로 부모 wiki lint/index 대상이 아니다."""
    files = []
    for p in base.rglob("*.md"):
        try:
            rel = p.relative_to(WIKI)
        except ValueError:
            continue
        if rel.parts and rel.parts[0] in SUBMODULE_DIRS:
            continue
        files.append(p)
    return files


def lint_orphan(scope: Path) -> list[str]:
    """① orphan: inbound link 0 — research/ 만.

    index.md는 부모 wiki의 catalog이므로 index에 등록된 페이지는 inbound link가 있는 것으로 본다.
    (research/ 범위만 스캔하면 index에 정상 등록된 페이지가 전부 orphan으로 오탐됨)"""
    issues = []
    pages = get_md_files(scope)
    catalog = INDEX.read_text(encoding="utf-8", errors="ignore") if INDEX.exists() else ""
    for p in pages:
        name = p.name
        if name in catalog or p.stem in catalog:
            continue
        refs = 0
        for other in pages:
            if other == p:
                continue
            if name in other.read_text(encoding="utf-8", errors="ignore"):
                refs += 1
        if refs == 0:
            issues.append(f"orphan: {p.relative_to(WIKI)}")
    return issues


def lint_broken_wikilink(scope: Path) -> list[str]:
    """② [[link]] broken wikilink

    해석 규칙:
      - `[[dir/page]]` 또는 `[[dir/page.md]]` → 경로 형태 (stem 매칭이 아니라 relpath 매칭)
      - `[[page#anchor]]` → 앵커 부분은 무시하고 페이지 경로만 검증
      - `[[link]]` → 문서 예시 placeholder (AGENTS.md/SCHEMA.md 내 설명용) → 무시
    """
    issues = []
    pages = get_md_files(scope)
    page_stems = {p.stem for p in pages}
    relpaths = {str(p.relative_to(WIKI)) for p in pages}
    for p in pages:
        content = p.read_text(encoding="utf-8", errors="ignore")
        for m in re.findall(r"\[\[([^\]]+)\]\]", content):
            target = m.split("|")[0].strip()
            if target in ("link", "링크"):  # 문서 예시 placeholder
                continue
            base = target.split("#")[0].strip()  # 앵커 제거
            if not base:
                continue
            if base in page_stems:
                continue
            if base in relpaths:
                continue
            if f"{base}.md" in relpaths:
                continue
            if Path(base).name in page_stems:
                continue
            issues.append(f"broken wikilink: {p.relative_to(WIKI)} → [[{target}]]")
    return issues


def lint_index_missing(scope: Path) -> list[str]:
    """③ index.md에 없음"""
    issues = []
    if not INDEX.exists():
        return ["INDEX.md missing"]
    index_content = INDEX.read_text(encoding="utf-8", errors="ignore")
    for p in get_md_files(scope):
        # Skip index.md itself
        if p.name == "index.md":
            continue
        if p.name not in index_content and p.stem not in index_content:
            issues.append(f"index missing: {p.relative_to(WIKI)}")
    return issues


def lint_frontmatter(scope: Path) -> list[str]:
    """④ research/ 필수 필드 검증"""
    issues = []
    for p in get_md_files(scope):
        # research/ 만 (AGENTS.md §6)
        if "research" not in p.parts:
            continue
        fm = read_frontmatter(p)
        for field in REQUIRED_FIELDS:
            if field not in fm:
                issues.append(f"frontmatter missing {field}: {p.relative_to(WIKI)}")
    return issues


def lint_stale(scope: Path) -> list[str]:
    """⑤ updated >90d"""
    issues = []
    cutoff = datetime.now() - timedelta(days=90)
    for p in get_md_files(scope):
        if "research" not in p.parts:
            continue
        fm = read_frontmatter(p)
        updated = fm.get("updated", "")
        try:
            d = datetime.strptime(updated, "%Y-%m-%d")
            if d < cutoff:
                issues.append(f"stale (>90d): {p.relative_to(WIKI)} updated={updated}")
        except ValueError:
            pass
    return issues


def lint_contested(scope: Path) -> list[str]:
    """⑥ contested: true"""
    issues = []
    for p in get_md_files(scope):
        if "research" not in p.parts:
            continue
        fm = read_frontmatter(p)
        if fm.get("contested", "").lower() == "true":
            issues.append(f"contested: {p.relative_to(WIKI)}")
    return issues


def lint_quality(scope: Path) -> list[str]:
    """⑦ confidence: low or 단일 출처"""
    issues = []
    for p in get_md_files(scope):
        if "research" not in p.parts:
            continue
        fm = read_frontmatter(p)
        conf = fm.get("confidence", "")
        sources = fm.get("sources", "")
        if conf == "low":
            issues.append(f"low confidence: {p.relative_to(WIKI)}")
        # 단일 출처: sources: [...] 안에 1개
        m = re.match(r"\[(.+?)\]", sources)
        if m and "," not in m.group(1):
            issues.append(f"single source: {p.relative_to(WIKI)}")
    return issues


def lint_tag_audit(scope: Path) -> list[str]:
    """⑧ taxonomy 외 태그 — raw/ 는 제외 (불변 원본 저장소)"""
    issues = []
    for p in get_md_files(scope):
        rel = p.relative_to(WIKI)
        if rel.parts and rel.parts[0] == "raw":
            continue  # AGENTS.md §Five Layers — raw는 절대 수정 금지
        fm = read_frontmatter(p)
        tags_str = fm.get("tags", "")
        if not tags_str:
            continue
        # tags: [a, b, c]
        m = re.match(r"\[(.+?)\]", tags_str)
        if not m:
            continue
        tags = [t.strip().strip("\"'") for t in m.group(1).split(",")]
        for t in tags:
            if t and t not in KNOWN_TAGS:
                issues.append(f"unknown tag: '{t}' in {p.relative_to(WIKI)}")
    return issues


LINTERS = [
    ("① Orphan", lint_orphan),
    ("② Broken wikilink", lint_broken_wikilink),
    ("③ INDEX missing", lint_index_missing),
    ("④ Frontmatter", lint_frontmatter),
    ("⑤ Stale (>90d)", lint_stale),
    ("⑥ Contested", lint_contested),
    ("⑦ Quality", lint_quality),
    ("⑧ Tag audit", lint_tag_audit),
]


def main():
    args = sys.argv[1:]
    json_mode = "--json" in args
    args = [a for a in args if a != "--json"]

    scope = WIKI / (args[0] if args else "research")

    if not scope.exists():
        print(f"Scope not found: {scope}")
        sys.exit(2)

    results = {}
    total = 0
    for name, fn in LINTERS:
        issues = fn(scope)
        results[name] = issues
        total += len(issues)

    if json_mode:
        import json
        print(json.dumps({"scope": str(scope), "results": results, "total": total}, indent=2))
    else:
        print(f"=== Wiki Lint ({scope.relative_to(WIKI)}) ===")
        for name, issues in results.items():
            status = "✓" if not issues else f"⚠ {len(issues)}"
            print(f"{status} {name}")
            for issue in issues[:5]:
                print(f"    {issue}")
            if len(issues) > 5:
                print(f"    ... and {len(issues)-5} more")
        print(f"\nTotal: {total} issues")

    sys.exit(0 if total == 0 else 1)


if __name__ == "__main__":
    main()