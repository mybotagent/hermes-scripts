#!/usr/bin/env python3
"""
Skill Profile Manager — Hermes Skill Dynamic Selection Phase ②

Usage:
  skill_profile.py list                       Show all profiles
  skill_profile.py active                     Show current active profile
  skill_profile.py skills [profile_name]      Show skills for a profile
  skill_profile.py switch <profile_name>      Switch active profile (logs transition)
  skill_profile.py log                        Show transition history (last 20)
  skill_profile.py suggested <profile_name>   Suggest preloaded skills list for CLI
  skill_profile.py analyze                    Analyze session context → recommend profile
  skill_profile.py mix <p1> <p2>              Enable multi-profile mode (2 profiles)

State:  ~/.hermes/skill-profiles.json
Log:    ~/.hermes/profile_transitions.jsonl
"""

import json
import os
import sys
import time
from pathlib import Path

HERMES_HOME = Path(os.environ.get("HERMES_HOME", os.path.expanduser("~/.hermes")))
CONFIG_PATH = HERMES_HOME / "skill-profiles.json"
LOG_PATH = HERMES_HOME / "profile_transitions.jsonl"


def load_config() -> dict:
    if not CONFIG_PATH.exists():
        print(f"ERROR: Config not found at {CONFIG_PATH}", file=sys.stderr)
        sys.exit(1)
    with open(CONFIG_PATH) as f:
        return json.load(f)


def save_config(cfg: dict):
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_PATH, "w") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)
        f.write("\n")


def log_transition(from_p: str, to_p: str, trigger: str = "manual"):
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    entry = {
        "timestamp": int(time.time()),
        "from_profile": from_p,
        "to_profile": to_p,
        "trigger": trigger,
        "session_id": os.environ.get("HERMES_SESSION_ID", os.environ.get("SESSION_ID", "unknown")),
    }
    with open(LOG_PATH, "a") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def cmd_list():
    cfg = load_config()
    active = cfg.get("active_profile", "")
    profiles = cfg.get("profiles", {})
    print(f"Active profile: {active}\n")
    print(f"{'Profile':20s} {'Skills':>6s}  Description")
    print("-" * 60)
    for name, info in profiles.items():
        marker = "◀" if name == active else " "
        skill_count = len(info.get("skills", []))
        desc = info.get("description", "")
        print(f"{marker} {name:18s} {skill_count:>4d}   {desc}")


def cmd_active():
    cfg = load_config()
    active = cfg.get("active_profile", "none")
    info = cfg.get("profiles", {}).get(active, {})
    print(f"Active: {active}")
    print(f"Label:  {info.get('label', active)}")
    print(f"Skills: {len(info.get('skills', []))}")
    for s in info.get("skills", []):
        print(f"  - {s}")


def cmd_skills():
    cfg = load_config()
    profile_name = sys.argv[2] if len(sys.argv) > 2 else cfg.get("active_profile", "")
    info = cfg.get("profiles", {}).get(profile_name)
    if not info:
        available = ", ".join(cfg.get("profiles", {}).keys())
        print(f"ERROR: Profile '{profile_name}' not found. Available: {available}", file=sys.stderr)
        sys.exit(1)
    for s in info.get("skills", []):
        print(s)


def cmd_switch():
    cfg = load_config()
    if len(sys.argv) < 3:
        print("Usage: skill_profile.py switch <profile_name>", file=sys.stderr)
        sys.exit(1)
    profile_name = sys.argv[2]
    info = cfg.get("profiles", {}).get(profile_name)
    if not info:
        available = ", ".join(cfg.get("profiles", {}).keys())
        print(f"ERROR: Profile '{profile_name}' not found. Available: {available}", file=sys.stderr)
        sys.exit(1)
    old = cfg.get("active_profile", "")
    cfg["active_profile"] = profile_name
    save_config(cfg)
    log_transition(old, profile_name)
    print(f"Switched: {old} → {profile_name}")
    print(f"Skills ({len(info.get('skills', []))}):")
    for s in info.get("skills", []):
        print(f"  - {s}")


def cmd_log():
    if not LOG_PATH.exists():
        print("No transitions logged yet.")
        return
    with open(LOG_PATH) as f:
        lines = f.readlines()
    # Show last 20
    for line in lines[-20:]:
        entry = json.loads(line.strip())
        ts = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(entry.get("timestamp", 0)))
        print(f"{ts}  {entry.get('from_profile','?')} → {entry.get('to_profile','?')}  [{entry.get('trigger','?')}]")


def cmd_suggested():
    cfg = load_config()
    profile_name = sys.argv[2] if len(sys.argv) > 2 else cfg.get("active_profile", "")
    info = cfg.get("profiles", {}).get(profile_name)
    if not info:
        available = ", ".join(cfg.get("profiles", {}).keys())
        print(f"ERROR: Profile '{profile_name}' not found. Available: {available}", file=sys.stderr)
        sys.exit(1)
    skills = info.get("skills", [])
    print(",".join(skills))


def cmd_analyze():
    """Analyze session context → recommend best profile."""
    cfg = load_config()
    profiles = cfg.get("profiles", {})
    from_profile = cfg.get("active_profile", "")
    log_path = LOG_PATH

    # Heuristic: count tool usage patterns from log
    tool_counts = {}
    if log_path.exists():
        with open(log_path) as f:
            for line in f:
                entry = json.loads(line.strip())
                p = entry.get("to_profile", "")
                tool_counts[p] = tool_counts.get(p, 0) + 1

    # Recommend based on recency + frequency
    if tool_counts:
        best = max(tool_counts, key=tool_counts.get)
    else:
        best = list(profiles.keys())[0] if profiles else "개발"

    print(f"Current: {from_profile}")
    print(f"Recommended: {best}")
    print(f"Reason: {'Transition history' if tool_counts else 'Default profile'}")
    print()
    print("To switch:")
    print(f"  skill_profile.py switch {best}")


def cmd_mix():
    """Enable multi-profile mode — merge skills from 2 profiles."""
    cfg = load_config()
    if len(sys.argv) < 4:
        print("Usage: skill_profile.py mix <profile1> <profile2>", file=sys.stderr)
        sys.exit(1)
    p1_name, p2_name = sys.argv[2], sys.argv[3]
    p1 = cfg.get("profiles", {}).get(p1_name)
    p2 = cfg.get("profiles", {}).get(p2_name)
    if not p1:
        print(f"ERROR: Profile '{p1_name}' not found", file=sys.stderr)
        sys.exit(1)
    if not p2:
        print(f"ERROR: Profile '{p2_name}' not found", file=sys.stderr)
        sys.exit(1)

    merged_skills = list(dict.fromkeys(p1.get("skills", []) + p2.get("skills", [])))
    mix_name = f"{p1_name}+{p2_name}"
    cfg["profiles"][mix_name] = {
        "label": f"{p1.get('label', p1_name)} + {p2.get('label', p2_name)}",
        "skills": merged_skills,
        "description": f"Mixed profile: {p1_name} + {p2_name}",
    }
    old = cfg.get("active_profile", "")
    cfg["active_profile"] = mix_name
    save_config(cfg)
    log_transition(old, mix_name, trigger="mix")
    print(f"Mixed profile created: {mix_name}")
    print(f"Skills ({len(merged_skills)}):")
    for s in merged_skills:
        print(f"  - {s}")


COMMANDS = {
    "list": cmd_list,
    "active": cmd_active,
    "skills": cmd_skills,
    "switch": cmd_switch,
    "log": cmd_log,
    "suggested": cmd_suggested,
    "analyze": cmd_analyze,
    "mix": cmd_mix,
}


def main():
    if len(sys.argv) < 2 or sys.argv[1] not in COMMANDS:
        print(__doc__)
        sys.exit(1)
    COMMANDS[sys.argv[1]]()


if __name__ == "__main__":
    main()
