"""Per-user Windows startup registration (no administrator rights required)."""

from __future__ import annotations

import subprocess
from typing import Any, Sequence


RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
VALUE_NAME = "AIUsageTracker"


def _registry(registry: Any = None):
    if registry is not None:
        return registry
    import winreg

    return winreg


def set_startup(
    enabled: bool,
    command: Sequence[str],
    *,
    registry: Any = None,
) -> None:
    """Enable or disable only this application's HKCU Run value."""
    backend = _registry(registry)
    if enabled:
        if not command:
            raise ValueError("A startup command is required when enabling startup")
        command_line = subprocess.list2cmdline([str(argument) for argument in command])
        with backend.CreateKeyEx(
            backend.HKEY_CURRENT_USER, RUN_KEY, 0, backend.KEY_SET_VALUE
        ) as key:
            backend.SetValueEx(key, VALUE_NAME, 0, backend.REG_SZ, command_line)
        return
    try:
        with backend.OpenKey(
            backend.HKEY_CURRENT_USER, RUN_KEY, 0, backend.KEY_SET_VALUE
        ) as key:
            backend.DeleteValue(key, VALUE_NAME)
    except FileNotFoundError:
        pass


def is_startup_enabled(*, registry: Any = None) -> bool:
    backend = _registry(registry)
    try:
        with backend.OpenKey(
            backend.HKEY_CURRENT_USER, RUN_KEY, 0, backend.KEY_READ
        ) as key:
            value, _kind = backend.QueryValueEx(key, VALUE_NAME)
        return bool(str(value).strip())
    except (FileNotFoundError, OSError):
        return False

