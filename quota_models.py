"""
Quota data models — dataclasses and enums for structured quota representation.
Part of the reliability refactor (commit d2ab9d3 design).

No UI, no I/O, no timers. Pure data structures with validation.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional


class FetchStatus(enum.Enum):
    """Outcome of a quota fetch attempt."""
    OK = "ok"
    STALE = "stale"              # Data exists but is older than freshness threshold
    UNAVAILABLE = "unavailable"  # Source not reachable / file missing
    ERROR = "error"              # Unexpected failure during fetch


class WindowType(enum.Enum):
    """Known quota window durations."""
    FIVE_HOUR = "5h"
    WEEKLY = "weekly"


@dataclass(slots=True)
class QuotaWindow:
    """A single rate-limit window (e.g. 5-hour or weekly)."""

    window_type: str                    # "5h", "weekly", "3p-5h", etc.
    remaining_percent: float            # 0.0 – 100.0
    remaining_fraction: float           # 0.0 – 1.0
    reset_time: str                     # ISO-8601 timestamp of window reset
    reset_in_seconds: int = 0           # Seconds until window resets (from source)

    def __post_init__(self):
        # Clamp percent to [0, 100]
        self.remaining_percent = max(0.0, min(100.0, float(self.remaining_percent)))
        # Clamp fraction to [0, 1]
        self.remaining_fraction = max(0.0, min(1.0, float(self.remaining_fraction)))
        # Ensure reset_in_seconds is non-negative
        self.reset_in_seconds = max(0, int(self.reset_in_seconds))


@dataclass(slots=True)
class ProviderSnapshot:
    """
    Point-in-time quota snapshot for a single provider.

    `fetched_at` records when the quota was *confirmed from source*,
    distinct from when the state file was written.
    """

    provider_name: str
    windows: dict[str, QuotaWindow] = field(default_factory=dict)
    fetched_at: str = ""                # ISO-8601: when quota was confirmed from source
    status: FetchStatus = FetchStatus.OK
    plan_type: str = "unknown"
    error_message: str = ""

    def __post_init__(self):
        if not self.fetched_at:
            self.fetched_at = datetime.now(timezone.utc).isoformat()

    @property
    def is_healthy(self) -> bool:
        return self.status == FetchStatus.OK

    def get_window(self, window_type: str) -> Optional[QuotaWindow]:
        """Get a specific window by type key (e.g. '5h', 'weekly')."""
        return self.windows.get(window_type)


def clamp_percent(value: float) -> float:
    """Clamp a percent value to [0, 100]."""
    return max(0.0, min(100.0, float(value)))


def apply_monotonic_guard(
    new_window: QuotaWindow,
    old_window: Optional[QuotaWindow],
) -> QuotaWindow:
    """
    Per-window monotonic guard: if the reset_time hasn't changed for THIS
    specific window, the remaining_percent can only decrease (not jump up
    due to stale/cached data).

    FIX for Bug #1: The old code used a single `reset_time` (the weekly one)
    to guard BOTH 5h and weekly values. Now each window is compared against
    its own previous reset_time independently.
    """
    if old_window is None:
        return new_window

    # If the reset_time changed, this is a new window period — accept new value as-is
    if new_window.reset_time != old_window.reset_time:
        return new_window

    # Same window period: value can only decrease (quota consumed, not restored)
    clamped_pct = min(new_window.remaining_percent, old_window.remaining_percent)
    clamped_frac = min(new_window.remaining_fraction, old_window.remaining_fraction)

    return QuotaWindow(
        window_type=new_window.window_type,
        remaining_percent=clamped_pct,
        remaining_fraction=clamped_frac,
        reset_time=new_window.reset_time,
        reset_in_seconds=new_window.reset_in_seconds,
    )
