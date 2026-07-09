#!/usr/bin/env python3
"""
memory_query.py — Tool-as-Memory (단일 tool로 메모리 본문 lazy fetch)

memory.md는 key만 (306 chars, 13.9%).
에이전트가 key를 호출하면 → 위키 페이지 본문 반환.

사용법:
    python3 memory_query.py <key>          # 단일 fact 본문
    python3 memory_query.py --list         # key 목록
    python3 memory_query.py --search <q>   # 검색
    python3 memory_query.py --stats        # 메모리 사용 통계
"""
import argparse
import re
import sys
from pathlib import Path

WIKI_HOME = Path.home() / ".hermes" / "wiki"
MEMORY_FILE = Path.home() / ".hermes" / "memories" / "MEMORY.md"

# Key → wiki 경로 + 1줄 ctx (이 매핑은 MEMORY_MAP.md와 동기 유지)
KEY_MAP = {
    "tz": ("infra/cron-jobs.md", "KST+9, cron07=`0 6`, 21=`0 20`"),
    "api_deepseek": ("infra/environment.md", "DeepSeek flash/pro/chat/reasoner, MiniMax-M3"),
    "api_finnhub": ("infra/environment.md", "300/일 한도"),
    "macro_6stage": ("analysis/methodology.md", "Summary→Macro→Causal→Counter→Structural→Priority"),
    "watchlist": ("watchlist/README.md", "data/watchlist.json 단일소스 (2026-07-02)"),
    "deepseek_key": ("code/scripts.md", "config.yaml, timeout 120s"),
    "deepseek_gcal": ("infra/gmail-himalaya.md", "서비스계정, OAuth만료해결"),
    "dashboard": ("architecture/how-to-use-hermes/06-messaging-platforms.md", "9119/8642, nginx auth_basic"),
    "linear_api": ("infra/environment.md", ".env(exportedX, grep), MCP=client_id"),
    "linear_mirror": ("infra/environment.md", "kanban_linear_mapping.json"),
    "thread_routing": ("infra/discord-gateway.md", "#체크리스트=설문, #일정=캘린더, 주식→#주식-증시"),
    "survey": ("infra/daily-survey.md", "clarify5문항, sync 12KST, private"),
    "bot_ids": ("infra/bot-architecture.md", "aiprofit/채니봇/plan/ds, 환경별 launchd"),
    "multibot": ("infra/bot-architecture.md", "채니봇 단일, 80% 보유 (kanban/cron/wiki/delegate)"),
    "verify_5stage": ("architecture/5-stage-verify.md", "why→what→whether→what→how→validate"),
    "gateway_fix": ("infra/discord-gateway.md", "pyc stale ImportError, HOME_CHANNEL=1522277759660068954"),
    "speculation": ("architecture/speculation-cascade-rule.md", "5번 추측 = 신뢰 손상"),
    "discord_only": ("infra/discord-gateway.md", "OAuth/password, 서버TTY 직접X"),
    "user_style": ("people/aiprofit.md", '"알아서/왜 못함?" = 짧은 진단 + 즉시 액션'),
    "gh_pr_policy": ("infra/github-pr-automation-policy.md", "claude-code-action@v1 금지"),
    "ssot": ("architecture/ssot-single-source-of-truth.md", "경로변경X, API=.env, MEMORY=포인터"),
}


def fetch_page(wiki_path: str, max_chars: int = 1500) -> str:
    """위키 페이지 본문 fetch"""
    full = WIKI_HOME / wiki_path
    if not full.exists():
        return f"[NOT FOUND] {wiki_path}"
    text = full.read_text(encoding="utf-8")
    body = re.sub(r"^---\n.*?\n---\n", "", text, count=1, flags=re.DOTALL)
    return body[:max_chars] + ("\n... (truncated)" if len(body) > max_chars else "")


def main():
    parser = argparse.ArgumentParser(description="Memory query (tool-as-memory)")
    parser.add_argument("key", nargs="?", help="fact key (e.g., tz, watchlist, bot_ids)")
    parser.add_argument("--list", action="store_true", help="key 목록")
    parser.add_argument("--search", help="검색 (대소문자 무시)")
    parser.add_argument("--stats", action="store_true", help="메모리 통계")
    parser.add_argument("--ctx-only", action="store_true", help="위키 fetch 없이 ctx만")
    args = parser.parse_args()

    if args.list:
        print(f"=== Memory Keys ({len(KEY_MAP)}) ===")
        for k, (path, ctx) in KEY_MAP.items():
            exists = "✓" if (WIKI_HOME / path).exists() else "✗"
            print(f"  {exists} {k:20s} → {path}")
        return 0

    if args.search:
        q = args.search.lower()
        for k, (path, ctx) in KEY_MAP.items():
            if q in k or q in ctx.lower():
                print(f"  {k:20s} → {path}  |  {ctx}")
        return 0

    if args.stats:
        mem_chars = len(MEMORY_FILE.read_text(encoding="utf-8")) if MEMORY_FILE.exists() else 0
        cap = 2200
        print(f"memory.md: {mem_chars} chars ({mem_chars/cap*100:.1f}% of {cap})")
        print(f"keys registered: {len(KEY_MAP)}")
        print(f"wiki pages reachable: {sum(1 for k,(p,_) in KEY_MAP.items() if (WIKI_HOME/p).exists())}/{len(KEY_MAP)}")
        return 0

    if not args.key:
        parser.print_help()
        return 1

    if args.key not in KEY_MAP:
        print(f"[ERROR] unknown key: {args.key}", file=sys.stderr)
        print(f"[HINT] use --list or --search <q>", file=sys.stderr)
        return 2

    path, ctx = KEY_MAP[args.key]
    print(f"=== {args.key} ===")
    print(f"ctx: {ctx}")
    print(f"wiki: {path}")
    print(f"---")
    if not args.ctx_only:
        print(fetch_page(path))
    return 0


if __name__ == "__main__":
    sys.exit(main())