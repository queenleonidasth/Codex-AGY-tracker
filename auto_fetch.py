"""Compatibility CLI for the production provider refresh service."""

from __future__ import annotations

import argparse
import time

from app_paths import settings_path
from refresh_service import trigger_agy_background_refresh
from settings import Settings
from usage_service import RefreshScheduler, get_service


def fetch_all(silent: bool = False, force: bool = False):
    snapshots = get_service().refresh(force=force)
    if not silent:
        for provider_id, snapshot in snapshots.items():
            windows = ", ".join(
                f"{window.label} {window.remaining_percent:.1f}% left"
                for window in snapshot.windows.values()
            ) or "no quota windows"
            print(
                f"[{provider_id}] {snapshot.status.value}: {windows} "
                f"(source={snapshot.source or 'none'})"
            )
    return snapshots


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Refresh AI usage and quota state")
    parser.add_argument("--daemon", action="store_true", help="run one owned background loop")
    parser.add_argument("--force", action="store_true", help="ignore in-memory provider TTL")
    parser.add_argument(
        "--refresh-agy",
        action="store_true",
        help="manually start AGY /usage (may start provider child processes)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.refresh_agy:
        return 0 if trigger_agy_background_refresh() else 1
    if not args.daemon:
        fetch_all(force=args.force)
        return 0

    settings = Settings.load(settings_path())
    scheduler = RefreshScheduler(get_service(), settings.refresh_interval_seconds)
    scheduler.start()
    try:
        while scheduler.is_running:
            time.sleep(0.25)
    except KeyboardInterrupt:
        pass
    finally:
        scheduler.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
