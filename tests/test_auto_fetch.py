import auto_fetch


def test_fetch_all_returns_service_snapshots(monkeypatch):
    """Legacy callers should use the reliable service instead of the old load-update-save sequence."""
    expected = {"codex": object()}

    class Service:
        def refresh(self, provider_id=None, force=False):
            assert provider_id is None
            assert force is True
            return expected

    monkeypatch.setattr(auto_fetch, "get_service", lambda: Service())

    assert auto_fetch.fetch_all(silent=True, force=True) is expected
