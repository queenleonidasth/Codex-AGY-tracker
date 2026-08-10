import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from state_store import AtomicStateStore
from token_tracker import TokenTracker


def test_empty_store_uses_schema_v3_without_legacy_top_level_buckets(tmp_path):
    """A new install must start on the transactional schema rather than recreate schema v2."""
    state = AtomicStateStore(tmp_path / "state.json").load()

    assert state["_meta"]["schema_version"] == 3
    assert state["providers"] == {}
    assert state["usage"] == {"daily": {}, "monthly": {}, "total": {}, "scanner": {}}
    assert "rate_limits" not in state


def test_migration_preserves_usage_and_converts_legacy_quota(tmp_path):
    """Upgrading must not discard the user's totals or present old quota as fresh."""
    path = tmp_path / "state.json"
    path.write_text(
        json.dumps(
            {
                "daily": {"2026-08-10": {"Codex": {"input": 10, "output": 5, "total": 15}}},
                "monthly": {"2026-08": {"Codex": {"input": 10, "output": 5, "total": 15}}},
                "total": {"Codex": {"input": 10, "output": 5, "total": 15}},
                "rate_limits": {
                    "AGY": {
                        "percent_5h_left": 70,
                        "percent_left": 45,
                        "reset_time_5h": "2026-08-10T12:00:00Z",
                        "reset_time": "2026-08-15T00:00:00Z",
                    }
                },
                "last_updated": "2026-08-10T09:00:00Z",
            }
        ),
        encoding="utf-8",
    )

    state = AtomicStateStore(path).load(force=True)

    assert state["usage"]["daily"]["2026-08-10"]["codex"]["total"] == 15
    assert state["providers"]["agy"]["status"] == "stale"
    assert state["providers"]["agy"]["windows"]["session"]["remaining_percent"] == 70
    assert state["providers"]["agy"]["windows"]["weekly"]["remaining_percent"] == 45


def test_mutate_preserves_concurrent_updates_from_separate_store_instances(tmp_path):
    """Two UI/service processes updating different providers must not overwrite each other."""
    path = tmp_path / "state.json"
    first = AtomicStateStore(path)
    second = AtomicStateStore(path)

    def update(provider_id):
        store = first if provider_id == "codex" else second
        for sequence in range(30):
            store.mutate(
                lambda state, p=provider_id, n=sequence: state["providers"].__setitem__(
                    p, {"status": "ok", "sequence": n}
                )
            )

    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(update, ["codex", "agy"]))

    state = first.load(force=True)
    assert set(state["providers"]) == {"codex", "agy"}
    assert state["providers"]["codex"]["sequence"] == 29
    assert state["providers"]["agy"]["sequence"] == 29
    json.loads(path.read_text(encoding="utf-8"))


def test_corrupt_file_is_backed_up_before_mutation_recovers(tmp_path):
    """Recovering from a truncated file must keep evidence instead of silently deleting it."""
    path = tmp_path / "state.json"
    path.write_text("{broken", encoding="utf-8")
    store = AtomicStateStore(path)

    store.mutate(lambda state: state["providers"].update({"codex": {"status": "ok"}}))

    backups = list(tmp_path.glob("state.json.corrupt-*"))
    assert len(backups) == 1
    assert backups[0].read_text(encoding="utf-8") == "{broken"
    assert json.loads(path.read_text(encoding="utf-8"))["providers"]["codex"]["status"] == "ok"


def test_loaded_state_is_a_copy_and_requires_mutate_to_persist(tmp_path):
    """Mutating a cached dictionary outside a transaction must not leak into later reads."""
    store = AtomicStateStore(tmp_path / "state.json")
    store.mutate(lambda state: state["providers"].update({"codex": {"status": "ok"}}))

    loaded = store.load()
    loaded["providers"]["codex"]["status"] = "error"

    assert store.load()["providers"]["codex"]["status"] == "ok"


def test_callback_failure_does_not_write_partial_state(tmp_path):
    """A failed mutation must leave the last valid file untouched."""
    store = AtomicStateStore(tmp_path / "state.json")
    store.mutate(lambda state: state["providers"].update({"codex": {"status": "ok"}}))

    def fail(state):
        state["providers"]["codex"]["status"] = "error"
        raise RuntimeError("stop")

    with pytest.raises(RuntimeError, match="stop"):
        store.mutate(fail)

    assert store.load(force=True)["providers"]["codex"]["status"] == "ok"


def test_token_tracker_adds_all_periods_in_one_transaction(tmp_path):
    """A manual/API usage event must update daily, monthly and lifetime totals together."""
    tracker = TokenTracker(store=AtomicStateStore(tmp_path / "state.json"))

    tracker.add_usage("Codex", input_tokens=100, output_tokens=25)

    assert tracker.get_today_usage()["codex"] == {"input": 100, "output": 25, "total": 125}
    assert tracker.get_month_usage()["codex"]["total"] == 125
    assert tracker.get_total_usage()["codex"]["total"] == 125


@pytest.mark.parametrize("input_tokens,output_tokens", [(-1, 0), (0, -1), (1.5, 0), ("1", 0)])
def test_token_tracker_rejects_invalid_counts(tmp_path, input_tokens, output_tokens):
    """Invalid manual counts must never corrupt integer aggregates."""
    tracker = TokenTracker(store=AtomicStateStore(tmp_path / "state.json"))

    with pytest.raises(ValueError):
        tracker.add_usage("codex", input_tokens=input_tokens, output_tokens=output_tokens)

    assert tracker.get_total_usage() == {}
