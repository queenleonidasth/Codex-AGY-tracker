"""
Provider-specific quota source adapters.
Part of the reliability refactor (commit d2ab9d3 design).

Each adapter reads raw data from its source and returns a ProviderSnapshot.
No UI, no timer, no persistence. Pure read-and-transform.
"""

from __future__ import annotations

import json
import os
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from quota_models import (
    FetchStatus,
    ProviderSnapshot,
    QuotaWindow,
)

# --- Paths ---
HOME = Path.home()
CODEX_HOME = Path(os.environ.get("CODEX_HOME", HOME / ".codex"))
AGY_QUOTA_CACHE = HOME / ".tokentracker" / "tracker" / "agy_quota_cache.json"

# Freshness threshold: if cache is older than this, mark as STALE
AGY_STALE_THRESHOLD_SECONDS = 300  # 5 minutes


class CodexQuotaSource:
    """
    Reads Codex rate_limits from session rollout JSONL files.

    FIX for Bug #7: Events are selected by timestamp (newest wins),
    NOT by filename sort order. The old code sorted files by name which
    doesn't guarantee chronological order across sessions.
    """

    def __init__(self, codex_home: Optional[Path] = None):
        self.codex_home = codex_home or CODEX_HOME

    def fetch(self) -> ProviderSnapshot:
        """Fetch the most recent Codex rate_limits snapshot."""
        sessions_root = self.codex_home / "sessions"
        if not sessions_root.exists():
            return ProviderSnapshot(
                provider_name="Codex",
                status=FetchStatus.UNAVAILABLE,
                error_message="Codex sessions directory not found",
            )

        best_result = None
        best_timestamp = ""

        # Search last 8 days of session directories
        for days_back in range(8):
            d = date.today() - timedelta(days=days_back)
            day_dir = sessions_root / d.strftime("%Y") / d.strftime("%m") / d.strftime("%d")

            if not day_dir.exists():
                continue

            # Collect ALL rollout files, don't rely on filename sort for recency
            for f in day_dir.glob("rollout-*.jsonl"):
                result = self._find_rate_limits_in_file(f)
                if result and result["timestamp"] > best_timestamp:
                    best_timestamp = result["timestamp"]
                    best_result = result

            # If we found something today, no need to look further back
            if best_result and days_back == 0:
                break

        if not best_result:
            return ProviderSnapshot(
                provider_name="Codex",
                status=FetchStatus.UNAVAILABLE,
                error_message="No rate_limits found in recent sessions",
            )

        return self._build_snapshot(best_result)

    def _find_rate_limits_in_file(self, filepath: Path) -> Optional[dict]:
        """Extract the newest rate_limits entry from a JSONL file."""
        last_rl = None
        last_usage = None
        last_ts = ""

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
                        ts = entry.get("timestamp", "")
                        # FIX: Compare by timestamp, keep newest
                        if ts >= last_ts:
                            last_rl = rl
                            last_usage = info.get("total_token_usage", {})
                            last_ts = ts
        except Exception:
            pass

        if last_rl:
            return {
                "rate_limits": last_rl,
                "token_usage": last_usage,
                "timestamp": last_ts,
                "source_file": filepath.name,
            }
        return None

    def _build_snapshot(self, result: dict) -> ProviderSnapshot:
        """Convert raw rate_limits dict into a ProviderSnapshot."""
        rl = result["rate_limits"]
        primary = rl.get("primary", {})
        used_pct = primary.get("used_percent", 0)
        remaining_pct = 100.0 - float(used_pct)
        window_minutes = primary.get("window_minutes", 0)
        resets_at = primary.get("resets_at", 0)

        # Determine reset time as ISO string
        reset_time_str = ""
        if resets_at:
            try:
                reset_time_str = datetime.fromtimestamp(resets_at, tz=timezone.utc).isoformat()
            except (OSError, ValueError):
                pass

        window = QuotaWindow(
            window_type="primary",
            remaining_percent=remaining_pct,
            remaining_fraction=remaining_pct / 100.0,
            reset_time=reset_time_str,
            reset_in_seconds=max(0, int(resets_at - time.time())) if resets_at else 0,
        )

        return ProviderSnapshot(
            provider_name="Codex",
            windows={"primary": window},
            fetched_at=result["timestamp"] or datetime.now(timezone.utc).isoformat(),
            status=FetchStatus.OK,
            plan_type=rl.get("plan_type", "unknown"),
        )


class AgyQuotaSource:
    """
    Reads AGY quota from the local cache file (agy_quota_cache.json).

    FIX for Bug #5: Distinguishes between "file was written" and
    "quota was confirmed from source" by checking cache mtime.
    Returns STALE status if cache is older than threshold.
    """

    def __init__(self, cache_path: Optional[Path] = None, stale_seconds: int = AGY_STALE_THRESHOLD_SECONDS):
        self.cache_path = cache_path or AGY_QUOTA_CACHE
        self.stale_seconds = stale_seconds

    def fetch(self) -> ProviderSnapshot:
        """Read and parse the AGY quota cache."""
        if not self.cache_path.exists():
            return ProviderSnapshot(
                provider_name="AGY",
                status=FetchStatus.UNAVAILABLE,
                error_message="AGY quota cache file not found",
            )

        # Check freshness based on file mtime
        try:
            mtime = self.cache_path.stat().st_mtime
            age_seconds = time.time() - mtime
        except OSError:
            return ProviderSnapshot(
                provider_name="AGY",
                status=FetchStatus.ERROR,
                error_message="Cannot stat AGY cache file",
            )

        # Parse the cache
        try:
            raw = json.loads(self.cache_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as e:
            return ProviderSnapshot(
                provider_name="AGY",
                status=FetchStatus.ERROR,
                error_message=f"Failed to parse AGY cache: {e}",
            )

        groups = raw.get("groups", {})
        if not groups:
            return ProviderSnapshot(
                provider_name="AGY",
                status=FetchStatus.ERROR,
                error_message="AGY cache has no 'groups' data",
            )

        # Determine status based on age
        status = FetchStatus.OK if age_seconds < self.stale_seconds else FetchStatus.STALE

        # Build windows from groups
        windows: dict[str, QuotaWindow] = {}
        for group_name, group_data in groups.items():
            if not isinstance(group_data, dict):
                continue
            windows[group_name] = QuotaWindow(
                window_type=group_name,
                remaining_percent=group_data.get("remaining_percent", 100.0),
                remaining_fraction=group_data.get("remaining_fraction", 1.0),
                reset_time=group_data.get("reset_time", ""),
                reset_in_seconds=group_data.get("reset_in_seconds", 0),
            )

        # Determine confirmed_at from mtime
        confirmed_at = datetime.fromtimestamp(mtime, tz=timezone.utc).isoformat()

        return ProviderSnapshot(
            provider_name="AGY",
            windows=windows,
            fetched_at=confirmed_at,
            status=status,
            plan_type=raw.get("plan_tier", "unknown"),
        )
