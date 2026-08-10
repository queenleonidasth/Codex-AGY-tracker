"""Crash-safe, inter-process transactional storage for tracker state."""

from __future__ import annotations

import copy
import json
import logging
import os
import shutil
import sys
import tempfile
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable, Iterator, Optional

from app_paths import state_path
from quota_models import FetchStatus, ProviderSnapshot, QuotaWindow, utc_now_iso


SCHEMA_VERSION = 3
LOGGER = logging.getLogger("ai_usage_tracker")


def _provider_id(name: Any) -> str:
    value = str(name).strip().lower()
    return "agy" if value == "antigravity" else value


def _empty_usage() -> dict[str, dict]:
    return {"daily": {}, "monthly": {}, "total": {}, "scanner": {}}


def _empty_state() -> dict[str, Any]:
    return {
        "_meta": {"schema_version": SCHEMA_VERSION, "written_at": None},
        "providers": {},
        "usage": _empty_usage(),
        "notifications": {"sent": {}},
    }


def _normalize_period_usage(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        return {}
    normalized: dict[str, Any] = {}
    for period, providers in raw.items():
        if not isinstance(providers, dict):
            continue
        normalized[str(period)] = {
            _provider_id(name): copy.deepcopy(value)
            for name, value in providers.items()
            if isinstance(value, dict)
        }
    return normalized


def _normalize_total_usage(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        return {}
    return {
        _provider_id(name): copy.deepcopy(value)
        for name, value in raw.items()
        if isinstance(value, dict)
    }


def _legacy_provider_snapshot(name: str, data: Any, observed_at: str) -> dict[str, Any]:
    provider_id = _provider_id(name)
    display_name = "Antigravity" if provider_id == "agy" else str(name)
    raw = data if isinstance(data, dict) else {}
    windows: dict[str, QuotaWindow] = {}

    if provider_id == "agy":
        if raw.get("percent_5h_left") is not None:
            remaining = float(raw["percent_5h_left"])
            windows["session"] = QuotaWindow(
                "session", remaining, remaining / 100.0,
                str(raw.get("reset_time_5h") or ""), label="5H", window_minutes=300,
            )
        if raw.get("percent_left") is not None:
            remaining = float(raw["percent_left"])
            windows["weekly"] = QuotaWindow(
                "weekly", remaining, remaining / 100.0,
                str(raw.get("reset_time") or ""), label="Weekly", window_minutes=10_080,
            )
    else:
        if raw.get("percent_left") is not None:
            remaining = float(raw["percent_left"])
            window_minutes = int(raw.get("window_minutes") or 300)
            key = "weekly" if window_minutes >= 10_000 and raw.get("percent_weekly_left") is None else "session"
            windows[key] = QuotaWindow(
                key, remaining, remaining / 100.0,
                str(raw.get("reset_time") or ""),
                label="Weekly" if key == "weekly" else "5H",
                window_minutes=window_minutes,
            )
        if raw.get("percent_weekly_left") is not None:
            remaining = float(raw["percent_weekly_left"])
            windows["weekly"] = QuotaWindow(
                "weekly", remaining, remaining / 100.0,
                str(raw.get("weekly_reset_time") or ""),
                label="Weekly", window_minutes=int(raw.get("weekly_window_minutes") or 10_080),
            )

    return ProviderSnapshot(
        provider_id=provider_id,
        provider_name=display_name,
        windows=windows,
        status=FetchStatus.STALE,
        source="legacy_cache",
        observed_at=observed_at,
        refreshed_at=observed_at,
        plan_type=str(raw.get("plan_type") or "unknown"),
        message="Migrated from the previous tracker state",
    ).to_dict()


def migrate_state(raw: Any) -> dict[str, Any]:
    """Return schema v3 without mutating the caller's object."""
    if not isinstance(raw, dict):
        return _empty_state()

    meta = raw.get("_meta") if isinstance(raw.get("_meta"), dict) else {}
    if meta.get("schema_version") == SCHEMA_VERSION and isinstance(raw.get("usage"), dict):
        state = copy.deepcopy(raw)
        state.setdefault("providers", {})
        state.setdefault("notifications", {"sent": {}})
        state["notifications"].setdefault("sent", {})
        usage = state.setdefault("usage", _empty_usage())
        for key in _empty_usage():
            usage.setdefault(key, {})
        state.setdefault("_meta", {})["schema_version"] = SCHEMA_VERSION
        return state

    state = _empty_state()
    observed_at = str(raw.get("last_updated") or raw.get("file_written_at") or "")
    legacy_usage = raw.get("usage") if isinstance(raw.get("usage"), dict) else raw
    state["usage"]["daily"] = _normalize_period_usage(legacy_usage.get("daily"))
    state["usage"]["monthly"] = _normalize_period_usage(legacy_usage.get("monthly"))
    state["usage"]["total"] = _normalize_total_usage(legacy_usage.get("total"))
    if isinstance(legacy_usage.get("scanner"), dict):
        state["usage"]["scanner"] = copy.deepcopy(legacy_usage["scanner"])

    if isinstance(raw.get("providers"), dict):
        state["providers"] = copy.deepcopy(raw["providers"])
    else:
        rate_limits = raw.get("rate_limits")
        if isinstance(rate_limits, dict):
            state["providers"] = {
                _provider_id(name): _legacy_provider_snapshot(name, value, observed_at)
                for name, value in rate_limits.items()
            }

    state["_meta"]["migrated_at"] = utc_now_iso()
    return state


class AtomicStateStore:
    """Serialize each read-modify-write under a lock file shared by processes."""

    def __init__(self, data_file: Optional[Path] = None, lock_timeout: float = 5.0):
        self.data_file = Path(data_file) if data_file is not None else state_path()
        self.lock_file = self.data_file.with_name(f".{self.data_file.name}.lock")
        self.lock_timeout = float(lock_timeout)
        self.data_file.parent.mkdir(parents=True, exist_ok=True)
        self._thread_lock = threading.RLock()
        self._cache = _empty_state()
        self._cache_signature: tuple[int, int] | None = None

    def load(self, force: bool = False) -> dict[str, Any]:
        with self._thread_lock:
            signature = self._signature()
            if not force and signature is not None and signature == self._cache_signature:
                return copy.deepcopy(self._cache)
            if not self.data_file.exists():
                self._cache = _empty_state()
                self._cache_signature = None
                return copy.deepcopy(self._cache)
            try:
                state = migrate_state(json.loads(self.data_file.read_text(encoding="utf-8")))
            except json.JSONDecodeError:
                try:
                    with self._process_lock():
                        state = self._read_fresh_or_recover()
                        state["_meta"]["written_at"] = utc_now_iso()
                        self._atomic_write(state)
                    return copy.deepcopy(state)
                except OSError:
                    return copy.deepcopy(
                        self._cache if self._cache_signature is not None else _empty_state()
                    )
            except OSError:
                return copy.deepcopy(self._cache if self._cache_signature is not None else _empty_state())
            self._cache = state
            self._cache_signature = signature
            return copy.deepcopy(state)

    def reload_if_changed(self) -> dict[str, Any]:
        return self.load(force=False)

    def save(self, data: dict[str, Any]) -> bool:
        try:
            with self._thread_lock, self._process_lock():
                state = migrate_state(copy.deepcopy(data))
                state["_meta"]["written_at"] = utc_now_iso()
                self._atomic_write(state)
            return True
        except OSError:
            return False

    def mutate(self, change: Callable[[dict[str, Any]], Any]) -> dict[str, Any]:
        with self._thread_lock, self._process_lock():
            state = self._read_fresh_or_recover()
            change(state)
            state = migrate_state(state)
            state["_meta"]["written_at"] = utc_now_iso()
            self._atomic_write(state)
            return copy.deepcopy(state)

    def update_provider(
        self, provider_name: str, provider_data: dict[str, Any], confirmed_at: Optional[str] = None
    ) -> None:
        provider_id = _provider_id(provider_name)

        def update(state: dict[str, Any]) -> None:
            if "windows" in provider_data and "status" in provider_data:
                state["providers"][provider_id] = copy.deepcopy(provider_data)
                return
            state["providers"][provider_id] = _legacy_provider_snapshot(
                provider_name, provider_data, confirmed_at or utc_now_iso()
            )

        self.mutate(update)

    def get_confirmed_at(self, provider_name: str) -> Optional[str]:
        provider = self.load().get("providers", {}).get(_provider_id(provider_name), {})
        return provider.get("observed_at") if isinstance(provider, dict) else None

    def _read_fresh_or_recover(self) -> dict[str, Any]:
        if not self.data_file.exists():
            return _empty_state()
        try:
            return migrate_state(json.loads(self.data_file.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError):
            timestamp = time.strftime("%Y%m%d-%H%M%S")
            backup = self.data_file.with_name(f"{self.data_file.name}.corrupt-{timestamp}")
            suffix = 1
            while backup.exists():
                backup = self.data_file.with_name(
                    f"{self.data_file.name}.corrupt-{timestamp}-{suffix}"
                )
                suffix += 1
            shutil.copy2(self.data_file, backup)
            LOGGER.warning("Corrupt tracker state backed up as %s", backup.name)
            return _empty_state()

    @contextmanager
    def _process_lock(self) -> Iterator[None]:
        self.lock_file.parent.mkdir(parents=True, exist_ok=True)
        handle = open(self.lock_file, "a+b")
        try:
            handle.seek(0, os.SEEK_END)
            if handle.tell() == 0:
                handle.write(b"0")
                handle.flush()
            handle.seek(0)
            deadline = time.monotonic() + self.lock_timeout
            while True:
                try:
                    self._lock_handle(handle)
                    break
                except OSError:
                    if time.monotonic() >= deadline:
                        raise TimeoutError(f"Timed out locking {self.lock_file}")
                    time.sleep(0.01)
            try:
                yield
            finally:
                self._unlock_handle(handle)
        finally:
            handle.close()

    @staticmethod
    def _lock_handle(handle) -> None:
        handle.seek(0)
        if sys.platform == "win32":
            import msvcrt

            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)

    @staticmethod
    def _unlock_handle(handle) -> None:
        try:
            handle.seek(0)
            if sys.platform == "win32":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        except OSError:
            pass

    def _atomic_write(self, state: dict[str, Any]) -> None:
        fd, temporary = tempfile.mkstemp(
            prefix=f".{self.data_file.stem}-", suffix=".tmp", dir=self.data_file.parent
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(state, handle, indent=2, ensure_ascii=False)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.data_file)
            self._cache = copy.deepcopy(state)
            self._cache_signature = self._signature()
        except Exception:
            try:
                os.unlink(temporary)
            except OSError:
                pass
            raise

    def _signature(self) -> tuple[int, int] | None:
        try:
            stat = self.data_file.stat()
            return stat.st_mtime_ns, stat.st_size
        except OSError:
            return None

    @staticmethod
    def _empty_state() -> dict[str, Any]:
        return _empty_state()


_store: Optional[AtomicStateStore] = None


def get_store() -> AtomicStateStore:
    global _store
    if _store is None:
        _store = AtomicStateStore()
    return _store
