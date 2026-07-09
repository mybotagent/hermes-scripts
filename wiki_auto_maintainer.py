#!/usr/bin/env python3
"""
wiki_auto_maintainer.py — weekly wiki orphan + broken wikilink + index 불일치 lint.

SAFE: read-only.
출력에 lint 발견만 (수정은 사용자 결정 영역).
"""
import os, re, json, datetime as dt
from pathlib import Path
from collections import defaultdict

_HH = os.environ.get("HERMES_HOME", "/home/ubuntu")
HH = Path(_HH) if _HH.endswith("/.hermes") else Path(_HH) / ".hermes"
WIKI = HH / "wiki"


def all_md(p: Path):
    return [f for f in p.rglob("*.md") if ".git" not in f.parts]


def wikilinks_in(content: str):
    # [[link]] or [text](link.md) variants
    links = set()
    for m in re.finditer(r"\[\[([^\]]+)\]\]", content):
        links.add(m.group(1).strip().split("|")[0])
    for m in re.finditer(r"\]\(([^)]+\.md)\)", content):
        links.add(m.group(1).strip())
    return links


def main():
    files = all_md(WIKI)
    by_name = {f.relative_to(WIKI).as_posix(): f for f in files}
    # simple file name -> path index (without .md suffix)
    by_stem = {p.stem: p.relative_to(WIKI).as_posix() for p in files}

    incoming = defaultdict(int)
    outgoing_broken = []
    for f in files:
        rel = f.relative_to(WIKI).as_posix()
        c = f.read_text(errors="ignore")
        for link in wikilinks_in(c):
            target = link
            if link.endswith(".md"):
                if link not in by_name:
                    outgoing_broken.append((rel, link))
                else:
                    incoming[link] += 1
            else:
                # bare name → look for .md
                if target + ".md" not in by_name and target not in by_stem:
                    outgoing_broken.append((rel, link))
                else:
                    incoming[by_stem.get(target, target + ".md")] += 1

    orphans = sorted([p for p, c in incoming.items() if c == 0])
    broken = sorted(set(outgoing_broken))

    out = {
        "ts": dt.datetime.now().isoformat(timespec="seconds"),
        "files_scanned": len(files),
        "orphans_count": len(orphans),
        "orphan_files": orphans[:20],
        "broken_links_count": len(broken),
        "broken_samples": broken[:20],
    }
    print(json.dumps(out, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
