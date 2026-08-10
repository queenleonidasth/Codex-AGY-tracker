import uuid

from instance_guard import SingleInstanceGuard


def test_named_guard_is_atomic_and_released_for_the_next_instance(tmp_path):
    """The operating-system primitive must make simultaneous startup atomic."""
    marker = tmp_path / ".instance.lock"
    name = f"AIUsageTracker-Test-{uuid.uuid4()}"
    first = SingleInstanceGuard(marker, name=name)
    second = SingleInstanceGuard(marker, name=name)

    try:
        assert first.acquire()
        assert not second.acquire()
        first.release()
        assert second.acquire()
    finally:
        first.release()
        second.release()


def test_stale_pid_marker_does_not_block_after_owner_is_gone(tmp_path):
    marker = tmp_path / ".instance.lock"
    marker.write_text("99999999", encoding="ascii")
    guard = SingleInstanceGuard(marker, name=f"AIUsageTracker-Test-{uuid.uuid4()}")

    try:
        assert guard.acquire()
    finally:
        guard.release()
