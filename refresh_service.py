"""
RefreshCoordinator — single-flight fetch with backoff and instance guard.
Part of the reliability refactor (commit d2ab9d3 design).

Fixes:
- Bug #2: Uses DETACHED_PROCESS only (not CREATE_NO_WINDOW) with named constant.
- Bug #3: Single-flight lock prevents overlapping fetches per provider.
- Bug #3: Single-instance guard via lockfile for the whole process.
"""

from __future__ import annotations

import os
import sys
import subprocess
import threading
import time
from pathlib import Path
from typing import Callable, Optional

# --- Process Creation Flags (Bug #2 fix) ---
# The old code used 0x08000008 which combines CREATE_NO_WINDOW (0x08000000)
# and DETACHED_PROCESS (0x00000008). These are contradictory:
# - CREATE_NO_WINDOW: new process inherits console but with no window
# - DETACHED_PROCESS: new process has no console at all
# Using both is undefined behavior on some Windows versions.
# Fix: use only DETACHED_PROCESS.
DETACHED_PROCESS = 0x00000008

# Paths
HOME = Path.home()
AGY_EXE = Path(os.environ.get("LOCALAPPDATA", HOME / "AppData" / "Local")) / "agy" / "bin" / "agy.exe"
LOCKFILE_PATH = Path(__file__).parent / "data" / ".instance.lock"


class SingleInstanceGuard:
    """
    Process-level single-instance guard using a lockfile.
    
    Fix for Bug #3: run_taskbar.bat launched new instances without checking
    if one was already running. This guard uses a lockfile with PID to
    prevent multiple instances.
    """

    def __init__(self, lockfile: Optional[Path] = None):
        self.lockfile = lockfile or LOCKFILE_PATH
        self._fd = None

    def acquire(self) -> bool:
        """
        Try to acquire the instance lock.
        Returns True if this is the only instance, False if another is running.
        """
        self.lockfile.parent.mkdir(parents=True, exist_ok=True)

        # Check if lockfile exists and if the PID in it is still alive
        if self.lockfile.exists():
            try:
                old_pid = int(self.lockfile.read_text().strip())
                if self._is_pid_alive(old_pid):
                    return False  # Another instance is running
            except (ValueError, OSError):
                pass  # Stale/corrupt lockfile, proceed to overwrite

        # Write our PID
        try:
            self.lockfile.write_text(str(os.getpid()))
            return True
        except OSError:
            return False

    def release(self):
        """Release the instance lock."""
        try:
            if self.lockfile.exists():
                # Only delete if it's our PID
                pid_in_file = int(self.lockfile.read_text().strip())
                if pid_in_file == os.getpid():
                    self.lockfile.unlink(missing_ok=True)
        except (ValueError, OSError):
            pass

    @staticmethod
    def _is_pid_alive(pid: int) -> bool:
        """Check if a process with given PID is still running (Windows)."""
        if sys.platform == "win32":
            try:
                import ctypes
                kernel32 = ctypes.windll.kernel32
                SYNCHRONIZE = 0x00100000
                handle = kernel32.OpenProcess(SYNCHRONIZE, False, pid)
                if handle:
                    kernel32.CloseHandle(handle)
                    return True
                return False
            except Exception:
                return False
        else:
            # Unix fallback
            try:
                os.kill(pid, 0)
                return True
            except (OSError, ProcessLookupError):
                return False

    def __enter__(self):
        return self.acquire()

    def __exit__(self, *_):
        self.release()


class RefreshCoordinator:
    """
    Coordinates quota fetches with:
    - Single-flight: only one fetch per provider at a time (Bug #3 fix)
    - Exponential backoff on failures
    - Background AGY exe triggering with correct process flags (Bug #2 fix)
    """

    # Backoff config
    INITIAL_BACKOFF_S = 5.0
    MAX_BACKOFF_S = 300.0  # 5 minutes
    BACKOFF_MULTIPLIER = 2.0

    def __init__(self):
        # Per-provider single-flight locks
        self._locks: dict[str, threading.Lock] = {}
        self._lock_guard = threading.Lock()  # Guards the _locks dict itself

        # Per-provider backoff state
        self._backoff: dict[str, float] = {}
        self._last_failure: dict[str, float] = {}

        # Track if a fetch is in-flight per provider
        self._in_flight: dict[str, bool] = {}

    def _get_lock(self, provider: str) -> threading.Lock:
        """Get or create a lock for a specific provider."""
        with self._lock_guard:
            if provider not in self._locks:
                self._locks[provider] = threading.Lock()
            return self._locks[provider]

    def is_in_flight(self, provider: str) -> bool:
        """Check if a fetch is currently in progress for a provider."""
        return self._in_flight.get(provider, False)

    def try_fetch(self, provider: str, fetch_fn: Callable, *args, **kwargs) -> Optional[object]:
        """
        Execute fetch_fn under single-flight protection.
        
        If another fetch for the same provider is already in progress,
        returns None immediately (non-blocking).
        
        Applies exponential backoff on repeated failures.
        """
        lock = self._get_lock(provider)

        # Non-blocking acquire — if locked, another fetch is in flight
        if not lock.acquire(blocking=False):
            return None  # Skip, another fetch is running

        try:
            self._in_flight[provider] = True

            # Check backoff
            if self._should_backoff(provider):
                return None

            # Execute the actual fetch
            result = fetch_fn(*args, **kwargs)

            # Reset backoff on success
            self._backoff.pop(provider, None)
            self._last_failure.pop(provider, None)

            return result

        except Exception:
            self._record_failure(provider)
            return None
        finally:
            self._in_flight[provider] = False
            lock.release()

    def _should_backoff(self, provider: str) -> bool:
        """Check if we should skip this fetch due to backoff."""
        if provider not in self._last_failure:
            return False
        elapsed = time.time() - self._last_failure[provider]
        backoff = self._backoff.get(provider, self.INITIAL_BACKOFF_S)
        return elapsed < backoff

    def _record_failure(self, provider: str):
        """Record a failure and increase backoff."""
        self._last_failure[provider] = time.time()
        current = self._backoff.get(provider, self.INITIAL_BACKOFF_S)
        self._backoff[provider] = min(current * self.BACKOFF_MULTIPLIER, self.MAX_BACKOFF_S)

    def reset_backoff(self, provider: str):
        """Manually reset backoff for a provider (e.g. on user-triggered refresh)."""
        self._backoff.pop(provider, None)
        self._last_failure.pop(provider, None)


def trigger_agy_background_refresh(timeout: float = 2.5) -> bool:
    """
    Trigger background `agy -p /usage` to update the quota cache.
    
    Bug #2 Fix: Uses only DETACHED_PROCESS (0x00000008), not the contradictory
    combination of CREATE_NO_WINDOW | DETACHED_PROCESS (0x08000008).
    Uses STARTUPINFO with SW_HIDE for window suppression.
    
    Returns True if the process was launched successfully.
    """
    if not AGY_EXE.exists():
        return False

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
            creationflags=DETACHED_PROCESS,  # Bug #2 fix: single flag, not 0x08000008
        )

        # Wait for process to write cache, then cleanup
        time.sleep(timeout)
        if proc.poll() is None:
            proc.kill()
        return True

    except Exception:
        return False


# Module-level singleton coordinator
_coordinator = RefreshCoordinator()


def get_coordinator() -> RefreshCoordinator:
    """Get the module-level RefreshCoordinator singleton."""
    return _coordinator
