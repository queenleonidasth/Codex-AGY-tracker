"""Unified entry point for taskbar, dashboard and command-line refresh modes."""

from __future__ import annotations

import argparse
import subprocess
import threading
from typing import Any, Callable, Optional

from app_paths import build_child_command, runtime_dir, settings_path
from refresh_service import SingleInstanceGuard
from settings import Settings
from state_store import get_store
from usage_service import RefreshScheduler, get_service


CREATE_NO_WINDOW = 0x08000000


def launch_mode(mode: str):
    return subprocess.Popen(
        build_child_command(mode),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=CREATE_NO_WINDOW,
        close_fds=True,
        shell=False,
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="AI quota and token usage tracker")
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--dashboard", action="store_true", help="open the full dashboard")
    modes.add_argument("--refresh", action="store_true", help="refresh provider state once")
    return parser


def main(
    argv: Optional[list[str]] = None,
    *,
    service: Any = None,
    dashboard_factory: Optional[Callable[[], Any]] = None,
) -> int:
    args = _parser().parse_args(argv)
    active_service = service or get_service()

    if args.refresh:
        snapshots = active_service.refresh(force=True)
        for provider_id, snapshot in snapshots.items():
            print(f"{provider_id}: {snapshot.status.value} ({snapshot.source or 'no source'})")
        return 0

    if args.dashboard:
        if dashboard_factory is None:
            from dashboard import Dashboard

            store = get_store()
            settings = Settings.load(settings_path())
            dashboard_factory = lambda: Dashboard(store, active_service, settings)
        dashboard_factory().run()
        return 0

    return _run_default(active_service)


def _run_default(service: Any) -> int:
    from taskbar_widget import request_close, run_taskbar
    from tray_widget import TokenTrayIcon

    settings = Settings.load(settings_path())
    store = get_store()
    guard = SingleInstanceGuard(runtime_dir() / ".instance.lock")
    if not guard.acquire():
        return 0

    scheduler = RefreshScheduler(service, settings.refresh_interval_seconds)
    tray = TokenTrayIcon(
        store=store,
        service=service,
        settings=settings,
        on_open=lambda: launch_mode("--dashboard"),
        on_exit=request_close,
    )

    def refresh() -> None:
        threading.Thread(
            target=service.refresh,
            kwargs={"force": True},
            name="ai-usage-manual-refresh",
            daemon=True,
        ).start()

    try:
        scheduler.start()
        tray.start_detached()
        return run_taskbar(
            store=store,
            settings=settings,
            on_open=lambda: launch_mode("--dashboard"),
            on_refresh=refresh,
        )
    finally:
        scheduler.stop()
        tray.stop()
        guard.release()


if __name__ == "__main__":
    raise SystemExit(main())
