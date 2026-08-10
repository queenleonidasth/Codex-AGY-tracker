import json
from datetime import timezone

from codex_usage import CodexUsageScanner
from quota_models import FetchStatus, ProviderSnapshot, QuotaWindow
from state_store import AtomicStateStore
from usage_service import UsageService


class FixtureProvider:
    def fetch(self):
        return ProviderSnapshot(
            provider_id="codex",
            provider_name="Codex",
            windows={
                "session": QuotaWindow(
                    "session",
                    75,
                    0.75,
                    "2026-08-10T12:00:00Z",
                    label="5H",
                    window_minutes=300,
                )
            },
            status=FetchStatus.OK,
            source="fixture",
            observed_at="2026-08-10T10:00:00Z",
        )


def test_refresh_persists_quota_and_automatic_tokens_offline(tmp_path):
    """One refresh must atomically expose quota and locally aggregated token usage."""
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
        {"codex": FixtureProvider()},
        scanner=CodexUsageScanner([codex_home], timezone_info=timezone.utc),
    )

    service.refresh(force=True)
    state = store.load(force=True)

    assert state["_meta"]["schema_version"] == 3
    assert state["providers"]["codex"]["windows"]["session"]["used_percent"] == 25
    assert state["usage"]["daily"]["2026-08-10"]["codex"]["total"] == 125
    assert state["usage"]["scanner"]["codex"]["version"] == 1

