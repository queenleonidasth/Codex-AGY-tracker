"""
Auto-fetch REAL quota % from Codex rate_limits + AGY quota cache + TokenTracker data.
Antigravity v2 - Production High-Reliability Edition with Background AGY Refresh.
"""

import json
import os
import sys
import time
import subprocess
from datetime import date, datetime, timedelta
from pathlib import Path

# Paths
SCRIPT_DIR = Path(__file__).parent
DATA_DIR = SCRIPT_DIR / "data"
DATA_FILE = DATA_DIR / "token_usage.json"

HOME = Path.home()
CODEX_HOME = Path(os.environ.get("CODEX_HOME", HOME / ".codex"))
AGY_QUOTA_CACHE = HOME / ".tokentracker" / "tracker" / "agy_quota_cache.json"
AGY_EXE = Path(os.environ.get("LOCALAPPDATA", HOME / "AppData" / "Local")) / "agy" / "bin" / "agy.exe"


def trigger_agy_background_refresh():
    """Trigger background agy -p /usage call to force AGY statusline hook to update cache with zero window flash."""
    if not AGY_EXE.exists():
        return

    try:
        si = subprocess.STARTUPINFO()
        si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        si.wShowWindow = 0  # SW_HIDE
        proc = subprocess.Popen(
            [str(AGY_EXE), "-p", "/usage"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            startupinfo=si,
            creationflags=0x08000008  # CREATE_NO_WINDOW (0x08000000) | DETACHED_PROCESS (0x00000008)
        )
        # Give process 2.5 seconds to write cache, then cleanup if still running
        time.sleep(2.5)
        if proc.poll() is None:
            proc.kill()
    except Exception:
        pass


def fetch_agy_quota_cache():
    """Read AGY quota directly from cache file, triggering background refresh if stale."""
    needs_refresh = True
    if AGY_QUOTA_CACHE.exists():
        try:
            mtime = AGY_QUOTA_CACHE.stat().st_mtime
            if (time.time() - mtime) < 15:
                needs_refresh = False
        except Exception:
            pass

    if needs_refresh:
        trigger_agy_background_refresh()

    if not AGY_QUOTA_CACHE.exists():
        return None

    try:
        cache = json.loads(AGY_QUOTA_CACHE.read_text(encoding="utf-8"))
    except Exception:
        return None

    groups = cache.get("groups", {})
    if not groups:
        return None

    gemini_weekly = groups.get("gemini-weekly") or next((v for k, v in groups.items() if "weekly" in k), {})
    gemini_5h = groups.get("gemini-5h") or next((v for k, v in groups.items() if "5h" in k), {})

    pct_left = gemini_weekly.get("remaining_percent", 100)
    pct_5h_left = gemini_5h.get("remaining_percent", 100)
    reset_time = gemini_weekly.get("reset_time", "")
    plan = cache.get("plan_tier", "?")

    return {
        "percent_left": round(float(pct_left), 1),
        "percent_5h_left": round(float(pct_5h_left), 1),
        "used_percent": round(100.0 - float(pct_left), 1),
        "used_5h_percent": round(100.0 - float(pct_5h_left), 1),
        "reset_time": reset_time,
        "plan_type": plan,
        "all_groups": groups,
    }


def load_usage():
    if DATA_FILE.exists():
        try:
            return json.loads(DATA_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"daily": {}, "monthly": {}, "total": {}, "rate_limits": {}}


def save_usage(usage):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    usage["last_updated"] = datetime.now().isoformat()
    DATA_FILE.write_text(json.dumps(usage, indent=2, ensure_ascii=False), encoding="utf-8")


def fetch_codex_rate_limits():
    """Find the most recent rate_limits from Codex session rollout files."""
    sessions_root = CODEX_HOME / "sessions"
    if not sessions_root.exists():
        return None

    for days_back in range(8):
        d = date.today() - timedelta(days=days_back)
        day_dir = sessions_root / d.strftime("%Y") / d.strftime("%m") / d.strftime("%d")

        if not day_dir.exists():
            continue

        files = sorted(day_dir.glob("rollout-*.jsonl"), reverse=True)
        for f in files:
            rl = _find_rate_limits_in_file(f)
            if rl:
                return rl

    return None


def _find_rate_limits_in_file(filepath):
    last_rl = None
    last_usage = None
    last_ts = None

    try:
        with open(filepath, "r", encoding="utf-8") as f:
            for line in f:
                if "rate_limits" not in line:
                    continue
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue

                payload = entry.get("payload", {})
                rl = payload.get("rate_limits") or payload.get("info", {}).get("rate_limits")

                if rl and isinstance(rl, dict) and rl.get("primary"):
                    info = payload.get("info", {})
                    last_rl = rl
                    last_usage = info.get("total_token_usage", {})
                    last_ts = entry.get("timestamp", "")

    except Exception:
        pass

    if last_rl:
        return {
            "rate_limits": last_rl,
            "token_usage": last_usage,
            "timestamp": last_ts,
            "source_file": filepath.name
        }
    return None


def fetch_all(silent: bool = False):
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    now = datetime.now().strftime('%H:%M:%S')
    if not silent:
        print(f"[{now}] Syncing live quota data...")

    usage = load_usage()

    # Codex
    codex_data = fetch_codex_rate_limits()
    if codex_data:
        rl = codex_data["rate_limits"]
        primary = rl.get("primary", {})
        used_pct = primary.get("used_percent", 0)

        usage.setdefault("rate_limits", {})["Codex"] = {
            "used_percent": round(used_pct, 1),
            "percent_left": round(100 - used_pct, 1),
            "window_minutes": primary.get("window_minutes", 0),
            "resets_at": primary.get("resets_at", 0),
            "plan_type": rl.get("plan_type", "unknown"),
            "timestamp": codex_data["timestamp"],
        }
        if not silent:
            print(f"  [Codex] [OK] {100 - used_pct:.1f}% left (used {used_pct:.1f}%)")

    # AGY
    agy_data = fetch_agy_quota_cache()
    if agy_data:
        old_agy = usage.get("rate_limits", {}).get("AGY", {})
        if old_agy and old_agy.get("reset_time") == agy_data.get("reset_time"):
            old_5h = old_agy.get("percent_5h_left")
            old_wk = old_agy.get("percent_left")
            if old_5h is not None:
                agy_data["percent_5h_left"] = round(min(float(agy_data["percent_5h_left"]), float(old_5h)), 1)
            if old_wk is not None:
                agy_data["percent_left"] = round(min(float(agy_data["percent_left"]), float(old_wk)), 1)

        usage.setdefault("rate_limits", {})["AGY"] = agy_data
        if not silent:
            print(f"  [AGY] [OK] 5h: {agy_data['percent_5h_left']:.1f}% left | Weekly: {agy_data['percent_left']:.1f}% left")

    save_usage(usage)
    if not silent:
        print(f"[{now}] Done [OK]\n")


def main():
    if "--daemon" in sys.argv:
        interval = 5
        print(f"[DAEMON] Auto-fetching live quota every {interval}s. Ctrl+C to stop.\n")
        while True:
            try:
                fetch_all()
                time.sleep(interval)
            except KeyboardInterrupt:
                print("\n[DAEMON] Stopped.")
                break
    else:
        fetch_all()


if __name__ == "__main__":
    main()
