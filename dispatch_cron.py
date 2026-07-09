#!/usr/bin/env python3
"""
dispatch_cron.py — cron deliver target 단일 lookup 헬퍼

사용법:
  dispatch_cron.py <topic_keyword>          # → "discord:<home>:<thread>" 또는 "origin"
  dispatch_cron.py --resolve <topic>         # 위와 동일
  dispatch_cron.py --list                    # 전체 topic → thread 매핑 출력
  dispatch_cron.py --validate <deliver_str>  # 위험 패턴 검증

단일 공식: 모든 deliver 결정은 ~/.hermes/data/discord_threads.yaml 1개 lookup.
예외 없음. fallback = origin.
"""
import sys
import yaml
from pathlib import Path

REGISTRY_PATH = Path.home() / ".hermes" / "data" / "discord_threads.yaml"
HOME_CHANNEL = "1510397804139515945"


def load_registry():
    if not REGISTRY_PATH.exists():
        raise SystemExit(f"Registry not found: {REGISTRY_PATH}")
    with open(REGISTRY_PATH) as f:
        return yaml.safe_load(f)


def resolve(topic: str) -> str:
    """topic keyword → discord:<home>:<thread> 또는 origin (fallback)"""
    reg = load_registry()
    rules = reg.get("cron_routing", {}).get("rules", {})
    fallback = reg.get("cron_routing", {}).get("fallback", "origin")
    threads = reg.get("threads", {})

    thread_key = rules.get(topic, fallback)
    if thread_key == "origin" or thread_key == "local":
        return thread_key
    thread_id = threads.get(thread_key)
    if not thread_id:
        return fallback
    return f"discord:{HOME_CHANNEL}:{thread_id}"


def list_topics():
    """전체 매핑 출력"""
    reg = load_registry()
    rules = reg.get("cron_routing", {}).get("rules", {})
    threads = reg.get("threads", {})
    print("=== topic → thread ===")
    for topic, thread_key in rules.items():
        thread_id = threads.get(thread_key, "(unknown)")
        print(f"  {topic:30s} → {thread_key:10s} (discord:{HOME_CHANNEL}:{thread_id})")
    fallback = reg.get("cron_routing", {}).get("fallback", "origin")
    print(f"  {'(fallback)':30s} → {fallback}")


def validate(deliver: str) -> bool:
    """위험 패턴 검증
    위험: home 채널에 thread 없음/빈 thread → 404
    안전: discord:<home>:<17-20자리 threadID> 또는 origin/local
    """
    if deliver in ("origin", "local"):
        print(f"✅ 안전 (special): {deliver!r}")
        return True
    if deliver == "discord:" + HOME_CHANNEL or deliver == f"discord:{HOME_CHANNEL}:":
        print(f"❌ 위험: {deliver!r} (thread 없음 → 404)")
        return False
    if deliver.startswith(f"discord:{HOME_CHANNEL}:"):
        thread_part = deliver.split(":", 2)[2]
        if 17 <= len(thread_part) <= 20 and thread_part.isdigit():
            print(f"✅ 안전: {deliver!r} (threadID {len(thread_part)}자리)")
            return True
        print(f"❌ 위험: {deliver!r} (threadID 형식 오류)")
        return False
    print(f"⚠️ 미검증: {deliver!r}")
    return False


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    if sys.argv[1] == "--list":
        list_topics()
    elif sys.argv[1] == "--validate":
        if len(sys.argv) < 3:
            print("usage: dispatch_cron.py --validate <deliver_str>")
            sys.exit(1)
        ok = validate(sys.argv[2])
        sys.exit(0 if ok else 2)
    elif sys.argv[1] == "--resolve":
        if len(sys.argv) < 3:
            print("usage: dispatch_cron.py --resolve <topic>")
            sys.exit(1)
        print(resolve(sys.argv[2]))
    else:
        # positional: topic keyword
        print(resolve(sys.argv[1]))


if __name__ == "__main__":
    main()
