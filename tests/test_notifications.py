from notifications import NotificationPolicy
from quota_models import FetchStatus, ProviderSnapshot, QuotaWindow
from state_store import AtomicStateStore


def snapshot(remaining=19, reset="A"):
    return ProviderSnapshot(
        provider_id="codex",
        provider_name="Codex",
        status=FetchStatus.OK,
        windows={
            "session": QuotaWindow(
                "session", remaining, remaining / 100, reset, label="5H"
            )
        },
    )


def test_threshold_fires_once_per_reset_window():
    policy = NotificationPolicy((20, 10, 5))

    first = policy.events({}, {"codex": snapshot(remaining=19, reset="A")})
    second = policy.events(policy.apply({}, first), {"codex": snapshot(remaining=18, reset="A")})

    assert len(first) == 1
    assert first[0].threshold == 20
    assert second == []


def test_lower_threshold_and_new_reset_can_fire_again():
    policy = NotificationPolicy((20, 10, 5))
    state = policy.apply({}, policy.events({}, {"codex": snapshot(19, "A")}))

    lower = policy.events(state, {"codex": snapshot(9, "A")})
    state = policy.apply(state, lower)
    new_window = policy.events(state, {"codex": snapshot(19, "B")})

    assert [event.threshold for event in lower] == [10]
    assert len(new_window) == 1
    assert new_window[0].key not in state["notifications"]["sent"]


def test_initial_observation_below_multiple_thresholds_emits_one_notice():
    policy = NotificationPolicy((20, 10, 5))

    events = policy.events({}, {"codex": snapshot(8, "A")})

    assert len(events) == 1
    assert events[0].threshold == 10

    state = policy.apply({}, events)
    assert policy.events(state, {"codex": snapshot(8, "A")}) == []
    assert any(key.endswith("/20") for key in state["notifications"]["sent"])
    assert any(key.endswith("/10") for key in state["notifications"]["sent"])


def test_claim_atomically_persists_notice_key(tmp_path):
    store = AtomicStateStore(tmp_path / "state.json")
    policy = NotificationPolicy((20, 10, 5))

    claimed = policy.claim(store, {"codex": snapshot(19, "A")})
    duplicate = policy.claim(store, {"codex": snapshot(18, "A")})

    assert len(claimed) == 1
    assert claimed[0].key in store.load(force=True)["notifications"]["sent"]
    assert duplicate == []
