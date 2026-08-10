"""
Unit tests for the reliability refactor (commit d2ab9d3 design).

Tests cover:
- QuotaWindow validation (percent clamped 0-100)
- Monotonic guard per-window (5h resets independently of weekly)
- AtomicStateStore (no partial JSON, migration)
- Process flag constants
"""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from quota_models import (
    FetchStatus,
    QuotaWindow,
    ProviderSnapshot,
    WindowType,
    apply_monotonic_guard,
    clamp_percent,
)
from refresh_service import DETACHED_PROCESS


class TestQuotaWindowValidation(unittest.TestCase):
    """Test QuotaWindow clamps values correctly."""

    def test_percent_clamped_above_100(self):
        w = QuotaWindow("5h", remaining_percent=150.0, remaining_fraction=1.5, reset_time="")
        self.assertEqual(w.remaining_percent, 100.0)
        self.assertEqual(w.remaining_fraction, 1.0)

    def test_percent_clamped_below_zero(self):
        w = QuotaWindow("weekly", remaining_percent=-10.0, remaining_fraction=-0.1, reset_time="")
        self.assertEqual(w.remaining_percent, 0.0)
        self.assertEqual(w.remaining_fraction, 0.0)

    def test_normal_values_unchanged(self):
        w = QuotaWindow("5h", remaining_percent=65.3, remaining_fraction=0.653, reset_time="2026-08-01T11:00:00Z")
        self.assertAlmostEqual(w.remaining_percent, 65.3)
        self.assertAlmostEqual(w.remaining_fraction, 0.653)

    def test_reset_in_seconds_non_negative(self):
        w = QuotaWindow("5h", remaining_percent=50.0, remaining_fraction=0.5, reset_time="", reset_in_seconds=-100)
        self.assertEqual(w.reset_in_seconds, 0)


class TestMonotonicGuardPerWindow(unittest.TestCase):
    """
    Bug #1 fix: monotonic guard must compare reset_time per-window,
    NOT using a shared reset_time across windows.
    """

    def test_same_reset_time_clamps_down(self):
        """Within the same window period, percent can only decrease."""
        old = QuotaWindow("5h", remaining_percent=80.0, remaining_fraction=0.8, reset_time="2026-08-01T10:00:00Z")
        new = QuotaWindow("5h", remaining_percent=90.0, remaining_fraction=0.9, reset_time="2026-08-01T10:00:00Z")

        result = apply_monotonic_guard(new, old)
        # Should be clamped to old value (80%) since reset_time hasn't changed
        self.assertEqual(result.remaining_percent, 80.0)
        self.assertEqual(result.remaining_fraction, 0.8)

    def test_different_reset_time_allows_increase(self):
        """New window period: percent can go back to 100%."""
        old = QuotaWindow("5h", remaining_percent=20.0, remaining_fraction=0.2, reset_time="2026-08-01T10:00:00Z")
        new = QuotaWindow("5h", remaining_percent=100.0, remaining_fraction=1.0, reset_time="2026-08-01T15:00:00Z")

        result = apply_monotonic_guard(new, old)
        # New reset_time means new period — accept 100%
        self.assertEqual(result.remaining_percent, 100.0)
        self.assertEqual(result.remaining_fraction, 1.0)

    def test_5h_resets_independently_of_weekly(self):
        """
        The core bug: 5h window gets new reset_time, weekly doesn't.
        Each window must be guarded independently.
        """
        # Old state: both windows at 30%
        old_5h = QuotaWindow("5h", remaining_percent=30.0, remaining_fraction=0.3, reset_time="2026-08-01T10:00:00Z")
        old_weekly = QuotaWindow("weekly", remaining_percent=30.0, remaining_fraction=0.3, reset_time="2026-07-28T00:00:00Z")

        # New data: 5h reset (new reset_time → 100%), weekly same period → should clamp
        new_5h = QuotaWindow("5h", remaining_percent=100.0, remaining_fraction=1.0, reset_time="2026-08-01T15:00:00Z")  # NEW reset_time
        new_weekly = QuotaWindow("weekly", remaining_percent=50.0, remaining_fraction=0.5, reset_time="2026-07-28T00:00:00Z")  # SAME reset_time

        result_5h = apply_monotonic_guard(new_5h, old_5h)
        result_weekly = apply_monotonic_guard(new_weekly, old_weekly)

        # 5h: different reset_time → accept new value (100%)
        self.assertEqual(result_5h.remaining_percent, 100.0)
        # Weekly: same reset_time → clamp to min(50, 30) = 30
        self.assertEqual(result_weekly.remaining_percent, 30.0)

    def test_no_old_window_accepts_new(self):
        """First time seeing a window: accept whatever comes in."""
        new = QuotaWindow("5h", remaining_percent=75.0, remaining_fraction=0.75, reset_time="2026-08-01T10:00:00Z")
        result = apply_monotonic_guard(new, None)
        self.assertEqual(result.remaining_percent, 75.0)

    def test_decrease_always_allowed(self):
        """Quota consumption (decrease) is always accepted."""
        old = QuotaWindow("5h", remaining_percent=80.0, remaining_fraction=0.8, reset_time="2026-08-01T10:00:00Z")
        new = QuotaWindow("5h", remaining_percent=60.0, remaining_fraction=0.6, reset_time="2026-08-01T10:00:00Z")

        result = apply_monotonic_guard(new, old)
        self.assertEqual(result.remaining_percent, 60.0)


class TestProcessFlagConstants(unittest.TestCase):
    """Bug #2 fix: verify process creation flag values."""

    def test_detached_process_value(self):
        self.assertEqual(DETACHED_PROCESS, 0x00000008)

    def test_not_combined_with_create_no_window(self):
        """The old buggy value was 0x08000008. We must NOT use that."""
        CREATE_NO_WINDOW = 0x08000000
        self.assertNotEqual(DETACHED_PROCESS, CREATE_NO_WINDOW | 0x00000008)
        self.assertNotEqual(DETACHED_PROCESS, 0x08000008)


class TestAtomicStateStore(unittest.TestCase):
    """Bug #4 fix: atomic writes produce no partial JSON."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.data_file = Path(self.tmpdir) / "test_state.json"

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_atomic_write_produces_valid_json(self):
        from state_store import AtomicStateStore
        store = AtomicStateStore(data_file=self.data_file)
        data = {"rate_limits": {"AGY": {"percent_left": 75.0}}, "last_updated": "2026-08-01T12:00:00"}
        store.save(data)

        # Verify the file contains valid JSON
        with open(self.data_file, "r", encoding="utf-8") as f:
            loaded = json.load(f)
        self.assertEqual(loaded["rate_limits"]["AGY"]["percent_left"], 75.0)

    def test_load_empty_returns_structure(self):
        from state_store import AtomicStateStore
        store = AtomicStateStore(data_file=self.data_file)
        state = store.load()
        self.assertIn("daily", state)
        self.assertIn("monthly", state)
        self.assertIn("rate_limits", state)

    def test_migration_adds_meta(self):
        """Old format (no _meta) gets migrated on load."""
        from state_store import AtomicStateStore
        old_data = {
            "daily": {},
            "monthly": {},
            "total": {},
            "rate_limits": {"AGY": {"percent_left": 60.0}},
            "last_updated": "2026-08-01T10:00:00",
        }
        self.data_file.write_text(json.dumps(old_data))

        store = AtomicStateStore(data_file=self.data_file)
        state = store.load()

        self.assertIn("_meta", state)
        self.assertEqual(state["_meta"]["schema_version"], 2)
        self.assertIn("AGY", state["_meta"]["providers"])

    def test_update_provider_sets_confirmed_at(self):
        """Bug #5 fix: confirmed_at is set per-provider."""
        from state_store import AtomicStateStore
        store = AtomicStateStore(data_file=self.data_file)

        store.update_provider("AGY", {"percent_left": 80.0}, confirmed_at="2026-08-01T12:00:00Z")

        state = store.load(force=True)
        self.assertEqual(
            state["_meta"]["providers"]["AGY"]["confirmed_at"],
            "2026-08-01T12:00:00Z"
        )

    def test_mtime_caching_avoids_reread(self):
        """Repeated loads without file change should use cache."""
        from state_store import AtomicStateStore
        store = AtomicStateStore(data_file=self.data_file)
        store.save({"rate_limits": {"X": 1}, "daily": {}, "monthly": {}, "total": {}})

        state1 = store.load()
        state2 = store.load()
        # Same object (from cache)
        self.assertIs(state1, state2)


class TestProviderSnapshot(unittest.TestCase):
    """Test ProviderSnapshot construction and properties."""

    def test_healthy_status(self):
        snap = ProviderSnapshot(provider_name="AGY", status=FetchStatus.OK)
        self.assertTrue(snap.is_healthy)

    def test_unhealthy_status(self):
        snap = ProviderSnapshot(provider_name="AGY", status=FetchStatus.STALE)
        self.assertFalse(snap.is_healthy)

    def test_get_window(self):
        w = QuotaWindow("5h", 80.0, 0.8, "2026-08-01T10:00:00Z")
        snap = ProviderSnapshot(provider_name="AGY", windows={"5h": w})
        self.assertEqual(snap.get_window("5h"), w)
        self.assertIsNone(snap.get_window("weekly"))


class TestFetchStatus(unittest.TestCase):
    """Test FetchStatus enum values."""

    def test_enum_values(self):
        self.assertEqual(FetchStatus.OK.value, "ok")
        self.assertEqual(FetchStatus.STALE.value, "stale")
        self.assertEqual(FetchStatus.UNAVAILABLE.value, "unavailable")
        self.assertEqual(FetchStatus.ERROR.value, "error")


if __name__ == "__main__":
    unittest.main()
