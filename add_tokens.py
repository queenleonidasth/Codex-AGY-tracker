"""
CLI Tool to add token usage manually (Antigravity v2).

Usage:
    python add_tokens.py AGY 5000 2000
    python add_tokens.py DeepSeek 10000 3000
    python add_tokens.py Codex 1500 800
    python add_tokens.py Mimo 3000 1000
    python add_tokens.py --status
    python add_tokens.py --demo
"""

import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

from token_tracker import tracker


def show_status():
    today = tracker.get_today_usage()
    print(f"📊 AI Token Usage - {sys.argv[0]}")
    print("-" * 35)
    for p, val in today.items():
        print(f"  {p}: {tracker._format_tokens(val.get('total', 0))} tokens today")
    print("-" * 35)


def add_demo_data():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    demo = [
        ("AGY", 15000, 8000),
        ("AGY", 22000, 12000),
        ("Codex", 8000, 4500),
        ("Codex", 5000, 2000),
        ("DeepSeek", 50000, 25000),
        ("DeepSeek", 30000, 15000),
        ("Mimo", 12000, 6000),
        ("Mimo", 8000, 4000),
    ]
    for provider, inp, out in demo:
        tracker.add_usage(provider, inp, out)
        print(f"  [OK] Added {inp + out:,} tokens to {provider}")
    print("\nStatus updated ✓")


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if len(sys.argv) < 2:
        print(__doc__)
        return

    if sys.argv[1] == "--status":
        show_status()
        return

    if sys.argv[1] == "--demo":
        print("Adding demo data...\n")
        add_demo_data()
        return

    if len(sys.argv) < 4:
        print("Usage: python add_tokens.py <provider> <input_tokens> <output_tokens>")
        print("Providers: AGY, Codex, DeepSeek, Mimo")
        return

    provider = sys.argv[1]
    valid_providers = ["AGY", "Codex", "DeepSeek", "Mimo"]
    
    if provider not in valid_providers:
        print(f"[ERROR] Unknown provider: {provider}")
        return

    try:
        input_tokens = int(sys.argv[2])
        output_tokens = int(sys.argv[3])
    except ValueError:
        print("[ERROR] Token counts must be integers")
        return

    tracker.add_usage(provider, input_tokens, output_tokens)
    print(f"  [OK] Added {input_tokens + output_tokens:,} tokens to {provider}")


if __name__ == "__main__":
    main()
