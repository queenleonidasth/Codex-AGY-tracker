"""
Auto-fetch REAL quota % from Codex rate_limits + AGY live API + TokenTracker data.
Antigravity v2 - Production High-Reliability Edition with Background AGY Refresh.

Refactored (commit d2ab9d3 design):
- Bug #1 fix: Monotonic guard compares reset_time per-window (5h independent of weekly)
- Bug #2 fix: Uses DETACHED_PROCESS only (named constant, not magic number 0x08000008)
- Bug #3 fix: Uses RefreshCoordinator for single-flight fetch
- Bug #7 fix: Codex events selected by timestamp, not filename sort
- Bug #5 fix: Freshness metadata via AtomicStateStore  
- Incident #5 fix: Do NOT trigger AGY background refresh (agy.exe spawns MCP servers → CMD popup)
"""

import json
import os
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

# --- Real-time AGY API client (same approach as TokenTracker) ---
import agy_api_client

# --- Real-time Codex API client (ChatGPT backend API, same as TokenTracker) ---
import codex_api_client

# --- New reliability modules ---
from quota_models import QuotaWindow, apply_monotonic_guard, FetchStatus
from quota_sources import CodexQuotaSource, AgyQuotaSource
from refresh_service import (
    DETACHED_PROCESS,
    get_coordinator,
    trigger_agy_background_refresh,
)
from state_store import get_store

# Paths
SCRIPT_DIR = Path(__file__).parent
DATA_DIR = SCRIPT_DIR / "data"
DATA_FILE = DATA_DIR / "token_usage.json"

HOME = Path.home()
CODEX_HOME = Path(os.environ.get("CODEX_HOME", HOME / ".codex"))
AGY_QUOTA_CACHE = HOME / ".tokentracker" / "tracker" / "agy_quota_cache.json"
AGY_EXE = Path(os.environ.get("LOCALAPPDATA", HOME / "AppData" / "Local")) / "agy" / "bin" / "agy.exe"

# Source adapters (instantiated once)
_codex_source = CodexQuotaSource()
_agy_source = AgyQuotaSource()


def fetch_agy_quota_cache():
    """
    Fetch AGY quota — real-time from the running AGY language server's HTTP API.

    Uses the same approach as TokenTracker (xiufengsun/TokenTracker):
    1. Detect agy.exe process via wmic (no window, <50ms)
    2. Find its listening TCP port via netstat (no window, <50ms)
    3. POST to localhost API for quota data (no process spawning!)

    Falls back to reading agy_quota_cache.json if AGY is not running.
    Zero CMD popups, zero process creation for AGY itself.

    Returns dict compatible with old callers, or None on failure.
    """
    # PRIMARY: Query the running AGY language server's API directly
    live_cache = agy_api_client.fetch_from_running_agy()
    if live_cache:
        # Use the freshly-fetched cache data (already written to agy_quota_cache.json)
        cache = live_cache
    elif not AGY_QUOTA_CACHE.exists():
        return None
    else:
        # FALLBACK: AGY not running — read last-known cache file
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
    reset_time_5h = gemini_5h.get("reset_time", "")
    plan = cache.get("plan_tier", "?")

    return {
        "percent_left": round(float(pct_left), 1),
        "percent_5h_left": round(float(pct_5h_left), 1),
        "used_percent": round(100.0 - float(pct_left), 1),
        "used_5h_percent": round(100.0 - float(pct_5h_left), 1),
        "reset_time": reset_time,
        "reset_time_5h": reset_time_5h,  # NEW: separate reset_time for 5h window
        "plan_type": plan,
        "all_groups": groups,
    }


def load_usage():
    """Load usage via AtomicStateStore (Bug #4 fix: safe reads)."""
    store = get_store()
    data = store.load()
    if not data.get("daily"):
        data.setdefault("daily", {})
        data.setdefault("monthly", {})
        data.setdefault("total", {})
        data.setdefault("rate_limits", {})
    return data


def save_usage(usage):
    """Save usage via AtomicStateStore (Bug #4 fix: atomic writes)."""
    store = get_store()
    usage["last_updated"] = datetime.now().isoformat()
    store.save(usage)


def fetch_codex_rate_limits():
    """
    Find the most recent rate_limits from Codex session rollout files.
    
    Bug #7 fix: Uses CodexQuotaSource which selects events by timestamp
    (not filename sort order).
    """
    snapshot = _codex_source.fetch()
    if snapshot.status == FetchStatus.UNAVAILABLE:
        return None

    # Convert snapshot back to the legacy dict format for backward compat
    primary_window = snapshot.get_window("primary")
    if not primary_window:
        return None

    return {
        "rate_limits": {
            "primary": {
                "used_percent": round(100.0 - primary_window.remaining_percent, 1),
                "window_minutes": 0,
                "resets_at": 0,
            },
            "plan_type": snapshot.plan_type,
        },
        "timestamp": snapshot.fetched_at,
    }


def _find_rate_limits_in_file(filepath):
    """Legacy wrapper — delegates to CodexQuotaSource._find_rate_limits_in_file."""
    return _codex_source._find_rate_limits_in_file(filepath)


def _apply_agy_monotonic_guard(agy_data: dict, old_agy: dict) -> dict:
    """
    Bug #1 fix: Apply monotonic guard PER WINDOW.
    
    The old code used a single `reset_time` (weekly) to guard BOTH 5h and weekly.
    When 5h window resets (new reset_time_5h) but weekly hasn't changed,
    the min() clamp incorrectly prevented 5h from going back to 100%.
    
    Fix: Compare reset_time separately for each window.
    """
    if not old_agy:
        return agy_data

    # --- Weekly window guard ---
    old_weekly_reset = old_agy.get("reset_time", "")
    new_weekly_reset = agy_data.get("reset_time", "")

    if old_weekly_reset == new_weekly_reset and old_weekly_reset:
        # Same weekly period: can only decrease
        old_wk = old_agy.get("percent_left")
        if old_wk is not None:
            agy_data["percent_left"] = round(min(float(agy_data["percent_left"]), float(old_wk)), 1)
            agy_data["used_percent"] = round(100.0 - agy_data["percent_left"], 1)

    # --- 5h window guard (INDEPENDENT of weekly) ---
    old_5h_reset = old_agy.get("reset_time_5h", "")
    new_5h_reset = agy_data.get("reset_time_5h", "")

    if old_5h_reset == new_5h_reset and old_5h_reset:
        # Same 5h period: can only decrease
        old_5h = old_agy.get("percent_5h_left")
        if old_5h is not None:
            agy_data["percent_5h_left"] = round(min(float(agy_data["percent_5h_left"]), float(old_5h)), 1)
            agy_data["used_5h_percent"] = round(100.0 - agy_data["percent_5h_left"], 1)
    # else: 5h window has reset (new reset_time_5h) → accept new value as-is (can be 100%)

    return agy_data


def fetch_all(silent: bool = False):
    """
    Main fetch entrypoint. Uses RefreshCoordinator for single-flight (Bug #3 fix).
    """
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    now = datetime.now().strftime('%H:%M:%S')
    if not silent:
        print(f"[{now}] Syncing live quota data...")

    usage = load_usage()
    store = get_store()
    coordinator = get_coordinator()

    # --- Codex (via coordinator for single-flight) ---
    def _do_codex_fetch():
        # PRIMARY: Try real-time ChatGPT backend API (same as TokenTracker)
        live_data = codex_api_client.fetch_codex_live_limits()
        if live_data:
            # Convert live API format to the legacy rate_limits structure
            return {
                "rate_limits": {
                    "primary": {
                        "used_percent": live_data["used_percent"],
                        "window_minutes": live_data["window_minutes"],
                        "resets_at": live_data["resets_at"],
                    },
                    "secondary": live_data.get("secondary"),
                    "plan_type": live_data.get("plan_type", "chatgpt"),
                },
                "timestamp": live_data["timestamp"],
                "source": "live_api",
            }
        # FALLBACK: Read from JSONL rollout files (token expired, network error, etc.)
        return fetch_codex_rate_limits()

    codex_data = coordinator.try_fetch("Codex", _do_codex_fetch)
    if codex_data:
        rl = codex_data["rate_limits"]
        primary = rl.get("primary", {})
        used_pct = primary.get("used_percent", 0)
        secondary = rl.get("secondary")

        provider_data = {
            "used_percent": round(used_pct, 1),
            "percent_left": round(100 - used_pct, 1),
            "window_minutes": primary.get("window_minutes", 0),
            "resets_at": primary.get("resets_at", 0),
            "plan_type": rl.get("plan_type", "unknown"),
            "timestamp": codex_data["timestamp"],
        }

        # Weekly window (subscription accounts have both 5h session + weekly/monthly)
        if secondary and isinstance(secondary, dict):
            provider_data["percent_weekly_left"] = round(100 - secondary.get("used_percent", 0), 1)
            provider_data["used_weekly_percent"] = round(secondary.get("used_percent", 0), 1)
            provider_data["weekly_window_minutes"] = secondary.get("window_minutes", 10080)
            provider_data["weekly_resets_at"] = secondary.get("resets_at", 0)

        usage.setdefault("rate_limits", {})["Codex"] = provider_data

        # Bug #5 fix: record confirmed_at
        store.update_provider("Codex", provider_data, confirmed_at=codex_data["timestamp"])

        if not silent:
            source_tag = "API" if codex_data.get("source") == "live_api" else "JSONL"
            print(f"  [Codex] [OK] {100 - used_pct:.1f}% left (used {used_pct:.1f}%) [{source_tag}]")

    # --- AGY (via coordinator for single-flight) ---
    def _do_agy_fetch():
        return fetch_agy_quota_cache()

    agy_data = coordinator.try_fetch("AGY", _do_agy_fetch)
    if agy_data:
        old_agy = usage.get("rate_limits", {}).get("AGY", {})

        # Bug #1 fix: per-window monotonic guard
        agy_data = _apply_agy_monotonic_guard(agy_data, old_agy)

        usage.setdefault("rate_limits", {})["AGY"] = agy_data

        # Bug #5 fix: record confirmed_at (when cache was last refreshed)
        confirmed_at = None
        if AGY_QUOTA_CACHE.exists():
            try:
                mtime = AGY_QUOTA_CACHE.stat().st_mtime
                confirmed_at = datetime.fromtimestamp(mtime, tz=timezone.utc).isoformat()
            except OSError:
                pass
        store.update_provider("AGY", agy_data, confirmed_at=confirmed_at)

        if not silent:
            print(f"  [AGY] [OK] 5h: {agy_data['percent_5h_left']:.1f}% left | Weekly: {agy_data['percent_left']:.1f}% left")

    save_usage(usage)
    if not silent:
        print(f"[{now}] Done [OK]\n")


def main():
    if "--refresh-agy" in sys.argv:
        # Manual AGY refresh (use only when you WANT a CMD popup momentarily)
        print("[MANUAL] Triggering AGY background refresh (will spawn agy.exe)...")
        trigger_agy_background_refresh()
        print("[MANUAL] Done. Cache should be updated within ~3 seconds.")
    elif "--daemon" in sys.argv:
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
