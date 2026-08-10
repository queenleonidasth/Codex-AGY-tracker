"""Central path and child-process rules for source and PyInstaller modes."""

from __future__ import annotations

import os
import sys
from pathlib import Path


APP_NAME = "AIUsageTracker"
SOURCE_ROOT = Path(__file__).resolve().parent


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def source_root() -> Path:
    return SOURCE_ROOT


def resource_root() -> Path:
    if is_frozen() and getattr(sys, "_MEIPASS", None):
        return Path(sys._MEIPASS).resolve()
    return SOURCE_ROOT


def runtime_dir() -> Path:
    override = os.environ.get("AI_USAGE_TRACKER_DATA_DIR")
    if override:
        return Path(override).expanduser().resolve()
    if is_frozen():
        local_app_data = os.environ.get("LOCALAPPDATA")
        if local_app_data:
            return (Path(local_app_data) / APP_NAME).resolve()
        return (Path.home() / "AppData" / "Local" / APP_NAME).resolve()
    return (SOURCE_ROOT / "data").resolve()


def state_path() -> Path:
    return runtime_dir() / "token_usage.json"


def settings_path() -> Path:
    return runtime_dir() / "config.json"


def log_dir() -> Path:
    return runtime_dir() / "logs"


def build_child_command(*arguments: str) -> list[str]:
    """Build a reliable child command without relying on .py associations or PATH."""
    if is_frozen():
        return [sys.executable, *arguments]
    return [sys.executable, str(SOURCE_ROOT / "app.py"), *arguments]
