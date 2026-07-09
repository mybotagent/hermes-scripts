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

# SCHEMA.md §6 taxonomy (근사치 — 실제 taxonomy에서 추출 권장)
KNOWN_TAGS = {
    "research", "analysis", "infra", "architecture", "code", "watchlist",
    "solopreneur", "repos", "entity", "concept", "comparison",
    "wiki", "index", "navigation", "catalog",
    "skill", "memory", "cron", "wiki-save",
}


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
    return list(base.rglob("*.md"))


def lint_orphan(scope: Path) -> list[str]:
    """① orphan: inbound link 0 — research/ 만"""
    issues = []
    pages = get_md_files(scope)
    for p in pages:
        name = p.name
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
    """② [[link]] broken wikilink"""
    issues = []
    pages = get_md_files(scope)
    page_stems = {p.stem for p in pages}
    for p in pages:
        content = p.read_text(encoding="utf-8", errors="ignore")
        for m in re.findall(r"\[\[([^\]]+)\]\]", content):
            target = m.split("|")[0].strip()
            if target not in page_stems:
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
    """⑧ taxonomy 외 태그"""
    issues = []
    for p in get_md_files(scope):
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