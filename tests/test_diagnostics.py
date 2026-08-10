import json
import logging
from logging.handlers import RotatingFileHandler

from diagnostics import collect_diagnostics, configure_logging, render_diagnostics
from settings import Settings


def test_diagnostics_whitelists_fields_and_never_emits_auth_values(tmp_path):
    settings = Settings.load(tmp_path / "config.json")
    state = {
        "_meta": {"schema_version": 3, "written_at": "2026-08-10T01:00:00Z"},
        "providers": {
            "codex": {
                "status": "ok",
                "source": "live_api",
                "observed_at": "2026-08-10T01:00:00Z",
                "access_token": "secret-value",
                "message": "Bearer secret-value",
            }
        },
        "usage": {
            "scanner": {
                "codex_diagnostics": {
                    "files_seen": 7,
                    "files_scanned": 2,
                    "malformed_lines": 1,
                    "updated_at": "2026-08-10T01:00:00Z",
                    "refresh_token": "another-secret",
                }
            }
        },
        "auth": {"access_token": "secret-value"},
    }

    rendered = render_diagnostics(collect_diagnostics(settings, state))

    assert "secret-value" not in rendered
    assert "another-secret" not in rendered
    assert "access_token" not in rendered.lower()
    assert "refresh_token" not in rendered.lower()
    parsed = json.loads(rendered)
    assert parsed["providers"]["codex"]["status"] == "ok"
    assert parsed["scanner"]["files_seen"] == 7


def test_logging_uses_bounded_rotating_file(tmp_path):
    logger = configure_logging(tmp_path)
    handlers = [handler for handler in logger.handlers if isinstance(handler, RotatingFileHandler)]

    assert len(handlers) == 1
    assert handlers[0].maxBytes == 1_000_000
    assert handlers[0].backupCount == 3
    assert logger.level == logging.INFO

