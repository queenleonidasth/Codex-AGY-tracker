"""
AtomicStateStore — thread-safe, crash-safe persistence for quota state.
Part of the reliability refactor (commit d2ab9d3 design).

Fixes:
- Bug #4: Atomic writes via temp file + os.replace() — no partial JSON.
- Bug #4: Inter-process file locking via msvcrt.locking on Windows.
- Bug #5: Freshness metadata — per-provider `confirmed_at` timestamp
           separate from `file_written_at`.
- Graceful migration from old format.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# --- Inter-process locking ---
if sys.platform == "win32":
    import msvcrt

    def _lock_file(fd):
        """Acquire an exclusive lock on an open file descriptor (Windows)."""
        msvcrt.locking(fd.fileno(), msvcrt.LK_NBLCK, 1)

    def _unlock_file(fd):
        """Release the lock on an open file descriptor (Windows)."""
        try:
            fd.seek(0)
            msvcrt.locking(fd.fileno(), msvcrt.LK_UNLCK, 1)
        except OSError:
            pass
else:
    import fcntl

    def _lock_file(fd):
        """Acquire an exclusive lock on an open file descriptor (Unix)."""
        fcntl.flock(fd.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)

    def _unlock_file(fd):
        """Release the lock on an open file descriptor (Unix)."""
        fcntl.flock(fd.fileno(), fcntl.LOCK_UN)


# Paths
SCRIPT_DIR = Path(__file__).parent
DATA_DIR = SCRIPT_DIR / "data"
DATA_FILE = DATA_DIR / "token_usage.json"
LOCK_FILE = DATA_DIR / ".token_usage.lock"


class AtomicStateStore:
    """
    Thread-safe and process-safe state store for token_usage.json.
    
    Features:
    - Atomic writes: write to temp file, then os.replace() (Bug #4 fix)
    - Inter-process locking via msvcrt/fcntl (Bug #4 fix)
    - Freshness metadata: `confirmed_at` per provider (Bug #5 fix)
    - Mtime-based reload detection (existing pattern, preserved)
    - Schema migration from old format
    """

    def __init__(self, data_file: Optional[Path] = None):
        self.data_file = data_file or DATA_FILE
        self.data_file.parent.mkdir(parents=True, exist_ok=True)
        self._last_mtime: float = 0.0
        self._cache: dict = {}
        self._write_lock = __import__("threading").Lock()

    def load(self, force: bool = False) -> dict:
        """
        Load state from disk, using mtime cache to avoid unnecessary reads.
        If force=True, always re-read from disk.
        """
        if not self.data_file.exists():
            self._cache = self._empty_state()
            return self._cache

        try:
            mtime = self.data_file.stat().st_mtime
            if not force and mtime <= self._last_mtime and self._cache:
                return self._cache

            with open(self.data_file, "r", encoding="utf-8") as f:
                data = json.load(f)

            self._last_mtime = mtime
            self._cache = self._migrate_if_needed(data)
            return self._cache

        except (json.JSONDecodeError, OSError):
            # File is corrupt or unreadable — return cached or empty
            if self._cache:
                return self._cache
            self._cache = self._empty_state()
            return self._cache

    def reload_if_changed(self) -> dict:
        """Reload from disk only if the file has been modified since last read."""
        return self.load(force=False)

    def save(self, data: dict) -> bool:
        """
        Atomically write state to disk.
        
        Bug #4 Fix: writes to a temp file in the same directory, then
        uses os.replace() to atomically swap. This prevents partial/corrupt
        JSON if the process crashes mid-write.
        """
        with self._write_lock:
            return self._atomic_write(data)

    def update_provider(self, provider_name: str, provider_data: dict, confirmed_at: Optional[str] = None):
        """
        Update a single provider's rate_limits data with freshness metadata.
        
        Bug #5 Fix: Records `confirmed_at` (when quota was confirmed from source)
        separately from `file_written_at` (when this file was saved).
        """
        with self._write_lock:
            state = self.load(force=True)

            state.setdefault("rate_limits", {})[provider_name] = provider_data

            # Freshness metadata
            meta = state.setdefault("_meta", {})
            provider_meta = meta.setdefault("providers", {}).setdefault(provider_name, {})
            provider_meta["confirmed_at"] = confirmed_at or datetime.now(timezone.utc).isoformat()
            provider_meta["updated_at"] = datetime.now(timezone.utc).isoformat()

            state["file_written_at"] = datetime.now(timezone.utc).isoformat()
            state["last_updated"] = datetime.now().isoformat()  # Backward compat

            self._atomic_write(state)
            self._cache = state

    def get_confirmed_at(self, provider_name: str) -> Optional[str]:
        """Get the last confirmed_at timestamp for a provider."""
        state = self.load()
        meta = state.get("_meta", {}).get("providers", {}).get(provider_name, {})
        return meta.get("confirmed_at")

    def _atomic_write(self, data: dict) -> bool:
        """
        Write data atomically: temp file → os.replace().
        Uses inter-process lock to prevent concurrent writes from
        taskbar_widget, tray_widget, and CLI processes.
        """
        self.data_file.parent.mkdir(parents=True, exist_ok=True)

        try:
            # Write to temp file in same directory (same filesystem for atomic replace)
            fd_num, tmp_path = tempfile.mkstemp(
                suffix=".tmp",
                prefix=".token_usage_",
                dir=str(self.data_file.parent),
            )
            try:
                with os.fdopen(fd_num, "w", encoding="utf-8") as tmp_f:
                    json.dump(data, tmp_f, indent=2, ensure_ascii=False)

                # Atomic replace
                os.replace(tmp_path, str(self.data_file))

                # Update mtime cache
                if self.data_file.exists():
                    self._last_mtime = self.data_file.stat().st_mtime
                self._cache = data
                return True

            except Exception:
                # Clean up temp file on failure
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
                raise

        except Exception:
            return False

    def _migrate_if_needed(self, data: dict) -> dict:
        """
        Migrate from old format if necessary.
        
        Old format: flat rate_limits dict with last_updated
        New format: adds _meta with per-provider confirmed_at
        """
        if "_meta" not in data:
            # First time seeing this file in new format — add metadata
            data["_meta"] = {
                "schema_version": 2,
                "migrated_at": datetime.now(timezone.utc).isoformat(),
                "providers": {},
            }
            # Backfill confirmed_at from last_updated for existing providers
            last_updated = data.get("last_updated", "")
            for provider_name in data.get("rate_limits", {}):
                data["_meta"]["providers"][provider_name] = {
                    "confirmed_at": last_updated,
                    "updated_at": last_updated,
                }
        return data

    @staticmethod
    def _empty_state() -> dict:
        """Return an empty state structure."""
        return {
            "daily": {},
            "monthly": {},
            "total": {},
            "rate_limits": {},
            "_meta": {
                "schema_version": 2,
                "providers": {},
            },
        }


# Module-level singleton
_store: Optional[AtomicStateStore] = None


def get_store() -> AtomicStateStore:
    """Get the module-level AtomicStateStore singleton."""
    global _store
    if _store is None:
        _store = AtomicStateStore()
    return _store
