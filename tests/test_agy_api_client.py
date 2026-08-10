import json
from pathlib import Path

import agy_api_client


def test_cache_write_never_opens_destination_for_truncation(tmp_path, monkeypatch):
    cache = tmp_path / "agy_quota_cache.json"
    previous = {"groups": {"weekly": {"remaining_percent": 80}}}
    cache.write_text(json.dumps(previous), encoding="utf-8")
    monkeypatch.setattr(agy_api_client, "AGY_QUOTA_CACHE", cache)
    original_write = Path.write_text

    def interrupt_direct_destination_write(path, *_args, **_kwargs):
        if path == cache:
            original_write(path, "{", encoding="utf-8")
            raise OSError("simulated interruption")
        return original_write(path, *_args, **_kwargs)

    monkeypatch.setattr(Path, "write_text", interrupt_direct_destination_write)

    agy_api_client._write_cache({"groups": {"weekly": {"remaining_percent": 70}}})

    assert json.loads(cache.read_text(encoding="utf-8")) == {
        "groups": {"weekly": {"remaining_percent": 70}}
    }
    assert list(tmp_path.glob("*.tmp")) == []


def test_failed_atomic_replace_keeps_previous_valid_json(tmp_path, monkeypatch):
    cache = tmp_path / "agy_quota_cache.json"
    previous = {"groups": {"weekly": {"remaining_percent": 80}}}
    cache.write_text(json.dumps(previous), encoding="utf-8")
    monkeypatch.setattr(agy_api_client, "AGY_QUOTA_CACHE", cache)
    monkeypatch.setattr(
        agy_api_client.os,
        "replace",
        lambda *_args: (_ for _ in ()).throw(OSError("simulated interruption")),
    )

    agy_api_client._write_cache({"groups": {"weekly": {"remaining_percent": 70}}})

    assert json.loads(cache.read_text(encoding="utf-8")) == previous
    assert list(tmp_path.glob("*.tmp")) == []
