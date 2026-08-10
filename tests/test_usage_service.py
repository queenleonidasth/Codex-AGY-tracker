import json
import threading
import time
from datetime import timezone

from codex_usage import CodexUsageScanner
from quota_models import (
    FetchStatus,
    ProviderErrorKind,
    ProviderFetchError,
    ProviderSnapshot,
    QuotaWindow,
)
from state_store import AtomicStateStore
from usage_service import RefreshScheduler, UsageService


def _snapshot(remaining, *, reset="2026-08-10T12:00:00Z", status=FetchStatus.OK):
    return ProviderSnapshot(
        provider_id="codex",
        provider_name="Codex",
        windows={
            "session": QuotaWindow(
                "session", remaining, remaining / 100, reset, label="5H", window_minutes=300
            )
        },
        status=status,
        source="live_api",
        observed_at="2026-08-10T10:00:00Z",
        refreshed_at="2026-08-10T10:00:00Z",
    )


class FakeProvider:
    def __init__(self, results):
        self.results = list(results)
        self.calls = 0

    def fetch(self):
        result = self.results[min(self.calls, len(self.results) - 1)]
        self.calls += 1
        if isinstance(result, Exception):
            raise result
        return result


class Clock:
    def __init__(self):
        self.value = 1_000.0

    def __call__(self):
        return self.value


def test_success_result_is_cached_for_sixty_seconds(tmp_path):
    """Frequent UI reads must not repeatedly call provider APIs."""
    clock = Clock()
    provider = FakeProvider([_snapshot(80), _snapshot(70)])
    service = UsageService(
        AtomicStateStore(tmp_path / "state.json"), {"codex": provider}, clock=clock
    )

    assert service.refresh("codex")["codex"].windows["session"].remaining_percent == 80
    clock.value += 59
    assert service.refresh("codex")["codex"].windows["session"].remaining_percent == 80
    assert provider.calls == 1
    clock.value += 2
    assert service.refresh("codex")["codex"].windows["session"].remaining_percent == 70
    assert provider.calls == 2


def test_rate_limited_failure_is_cached_for_five_minutes(tmp_path):
    """A 429 response must not be retried every normal refresh tick."""
    clock = Clock()
    provider = FakeProvider(
        [ProviderFetchError(ProviderErrorKind.RATE_LIMITED, "Too many requests"), _snapshot(60)]
    )
    service = UsageService(
        AtomicStateStore(tmp_path / "state.json"), {"codex": provider}, clock=clock
    )

    first = service.refresh("codex")["codex"]
    clock.value += 299
    second = service.refresh("codex")["codex"]

    assert first.status is FetchStatus.RATE_LIMITED
    assert second.status is FetchStatus.RATE_LIMITED
    assert provider.calls == 1
    clock.value += 2
    assert service.refresh("codex")["codex"].status is FetchStatus.OK
    assert provider.calls == 2


def test_failure_reuses_last_good_windows_but_keeps_error_status(tmp_path):
    """A timeout should preserve useful values without lying that they are fresh."""
    provider = FakeProvider(
        [_snapshot(40), ProviderFetchError(ProviderErrorKind.TIMEOUT, "Timed out")]
    )
    store = AtomicStateStore(tmp_path / "state.json")
    service = UsageService(store, {"codex": provider})
    service.refresh("codex", force=True)

    failed = service.refresh("codex", force=True)["codex"]

    assert failed.windows["session"].remaining_percent == 40
    assert failed.status is FetchStatus.ERROR
    assert failed.message == "Timed out"
    assert failed.observed_at == "2026-08-10T10:00:00Z"
    persisted = store.load(force=True)["providers"]["codex"]
    assert persisted["status"] == "error"
    assert persisted["windows"]["session"]["remaining_percent"] == 40


def test_same_reset_window_cannot_bounce_remaining_quota_up(tmp_path):
    """A cached provider response must not undo usage inside the same reset period."""
    provider = FakeProvider([_snapshot(40), _snapshot(75)])
    service = UsageService(
        AtomicStateStore(tmp_path / "state.json"), {"codex": provider}
    )

    service.refresh("codex", force=True)
    second = service.refresh("codex", force=True)["codex"]

    assert second.status is FetchStatus.OK
    assert second.windows["session"].remaining_percent == 40


def test_changed_reset_window_allows_quota_to_refill(tmp_path):
    """Monotonic protection must not pin a newly reset window to the old low value."""
    provider = FakeProvider(
        [_snapshot(10, reset="2026-08-10T12:00:00Z"), _snapshot(100, reset="2026-08-10T17:00:00Z")]
    )
    service = UsageService(
        AtomicStateStore(tmp_path / "state.json"), {"codex": provider}
    )

    service.refresh("codex", force=True)
    second = service.refresh("codex", force=True)["codex"]

    assert second.windows["session"].remaining_percent == 100


def test_nonblocking_single_flight_returns_cached_value(tmp_path):
    """Two refresh requests must never overlap the same provider call."""
    entered = threading.Event()
    release = threading.Event()

    class BlockingProvider:
        def __init__(self):
            self.calls = 0

        def fetch(self):
            self.calls += 1
            if self.calls == 1:
                return _snapshot(80)
            entered.set()
            release.wait(timeout=2)
            return _snapshot(70)

    provider = BlockingProvider()
    service = UsageService(
        AtomicStateStore(tmp_path / "state.json"), {"codex": provider}
    )
    service.refresh("codex", force=True)
    worker = threading.Thread(target=lambda: service.refresh("codex", force=True))
    worker.start()
    assert entered.wait(timeout=1)

    started = time.perf_counter()
    concurrent = service.refresh("codex", force=True)["codex"]
    elapsed = time.perf_counter() - started
    release.set()
    worker.join(timeout=2)

    assert elapsed < 0.2
    assert concurrent.windows["session"].remaining_percent == 80
    assert provider.calls == 2


def test_refresh_persists_automatic_codex_usage_and_scanner_index(tmp_path):
    """Quota refresh must make local Codex token totals visible without manual add commands."""
    codex_home = tmp_path / "codex"
    rollout = codex_home / "sessions" / "2026" / "08" / "10" / "rollout.jsonl"
    rollout.parent.mkdir(parents=True)
    rollout.write_text(
        json.dumps(
            {
                "timestamp": "2026-08-10T01:00:00Z",
                "type": "event_msg",
                "payload": {
                    "type": "token_count",
                    "info": {
                        "model": "gpt-5.6-sol",
                        "last_token_usage": {
                            "input_tokens": 100,
                            "cached_input_tokens": 20,
                            "output_tokens": 25,
                            "reasoning_output_tokens": 5,
                            "total_tokens": 125,
                        },
                    },
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )
    store = AtomicStateStore(tmp_path / "state.json")
    service = UsageService(
        store,
        {"codex": FakeProvider([_snapshot(80)])},
        scanner=CodexUsageScanner([codex_home], timezone_info=timezone.utc),
    )

    service.refresh("codex", force=True)

    state = store.load(force=True)
    assert state["usage"]["daily"]["2026-08-10"]["codex"]["total"] == 125
    assert state["usage"]["total"]["codex"]["cached_input"] == 20
    assert state["usage"]["scanner"]["codex"]["version"] == 1


def test_first_empty_scan_preserves_migrated_codex_usage(tmp_path):
    """An empty/missing rollout directory must not erase imported v1/v2 totals."""
    store = AtomicStateStore(tmp_path / "state.json")

    def seed(state):
        metrics = {"input": 10, "cached_input": 0, "output": 5, "reasoning_output": 0, "total": 15}
        state["usage"]["daily"]["2026-08-10"] = {"codex": dict(metrics)}
        state["usage"]["monthly"]["2026-08"] = {"codex": dict(metrics)}
        state["usage"]["total"]["codex"] = dict(metrics)

    store.mutate(seed)
    service = UsageService(
        store,
        {"codex": FakeProvider([_snapshot(80)])},
        scanner=CodexUsageScanner([tmp_path / "empty-codex"], timezone_info=timezone.utc),
    )

    service.refresh("codex", force=True)
    state = store.load(force=True)

    assert state["usage"]["daily"]["2026-08-10"]["codex"]["total"] == 15
    assert state["usage"]["monthly"]["2026-08"]["codex"]["total"] == 15
    assert state["usage"]["total"]["codex"]["total"] == 15
    assert state["usage"]["scanner"]["codex_baseline"]["total"]["total"] == 15


def test_refresh_scheduler_runs_immediately_and_stops_cleanly():
    """The GUI must own one stoppable refresh loop rather than orphan daemon fetchers."""
    called = threading.Event()

    class RecordingService:
        def __init__(self):
            self.calls = 0

        def refresh(self):
            self.calls += 1
            called.set()

    service = RecordingService()
    scheduler = RefreshScheduler(service, interval_seconds=0.02)

    scheduler.start()
    assert called.wait(timeout=1)
    scheduler.stop(timeout=1)
    calls_after_stop = service.calls
    time.sleep(0.05)

    assert service.calls == calls_after_stop
    assert not scheduler.is_running
