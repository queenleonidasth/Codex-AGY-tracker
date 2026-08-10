"""Atomic single-instance ownership with automatic crash cleanup."""

from __future__ import annotations

import ctypes
import hashlib
import os
import sys
from pathlib import Path
from typing import Any, Optional


ERROR_ALREADY_EXISTS = 183


class SingleInstanceGuard:
    """Own a Windows named mutex, with a locked-file fallback off Windows."""

    def __init__(self, marker_path: Path, *, name: Optional[str] = None):
        self.marker_path = Path(marker_path)
        identity = str(self.marker_path.resolve()).casefold().encode("utf-8")
        suffix = hashlib.sha256(identity).hexdigest()[:24]
        raw_name = name or f"Q-Tracker-{suffix}"
        self.name = raw_name if "\\" in raw_name else f"Local\\{raw_name}"
        self._handle: Any = None
        self._kernel: Any = None
        self._file: Any = None

    def acquire(self) -> bool:
        if self._handle is not None or self._file is not None:
            return True
        self.marker_path.parent.mkdir(parents=True, exist_ok=True)
        acquired = self._acquire_windows() if sys.platform == "win32" else self._acquire_file()
        if not acquired:
            return False
        try:
            self.marker_path.write_text(str(os.getpid()), encoding="ascii")
        except OSError:
            # The mutex/file lock is authoritative; the marker is diagnostic only.
            pass
        return True

    def _acquire_windows(self) -> bool:
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_wchar_p]
        kernel.CreateMutexW.restype = ctypes.c_void_p
        kernel.ReleaseMutex.argtypes = [ctypes.c_void_p]
        kernel.ReleaseMutex.restype = ctypes.c_int
        kernel.CloseHandle.argtypes = [ctypes.c_void_p]
        kernel.CloseHandle.restype = ctypes.c_int
        ctypes.set_last_error(0)
        handle = kernel.CreateMutexW(None, True, self.name)
        if not handle:
            return False
        if ctypes.get_last_error() == ERROR_ALREADY_EXISTS:
            kernel.CloseHandle(handle)
            return False
        self._kernel = kernel
        self._handle = handle
        return True

    def _acquire_file(self) -> bool:
        import fcntl

        handle = open(self.marker_path, "a+b")
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            handle.close()
            return False
        self._file = handle
        return True

    def release(self) -> None:
        if self._handle is not None:
            try:
                self._kernel.ReleaseMutex(self._handle)
            finally:
                self._kernel.CloseHandle(self._handle)
                self._handle = None
                self._kernel = None
        if self._file is not None:
            import fcntl

            try:
                fcntl.flock(self._file.fileno(), fcntl.LOCK_UN)
            finally:
                self._file.close()
                self._file = None
        try:
            if self.marker_path.exists() and self.marker_path.read_text(encoding="ascii").strip() == str(os.getpid()):
                self.marker_path.unlink()
        except (OSError, UnicodeError):
            pass

    def __enter__(self) -> "SingleInstanceGuard":
        if not self.acquire():
            raise RuntimeError("Another Q-Tracker instance is already running")
        return self

    def __exit__(self, *_args: Any) -> None:
        self.release()
