import sys

import app
from quota_models import FetchStatus, ProviderSnapshot
from settings import Settings


def test_refresh_mode_forces_service_refresh_and_returns_success(capsys):
    """The command-line refresh path must use the same service as the GUI."""
    calls = []

    class Service:
        def refresh(self, provider_id=None, force=False):
            calls.append((provider_id, force))
            return {
                "codex": ProviderSnapshot(
                    provider_id="codex",
                    provider_name="Codex",
                    status=FetchStatus.OK,
                    source="live_api",
                )
            }

    result = app.main(["--refresh"], service=Service())

    assert result == 0
    assert calls == [(None, True)]
    assert "codex: ok" in capsys.readouterr().out.lower()


def test_dashboard_mode_runs_dashboard_on_calling_thread():
    """Tk must own the main thread rather than being started by a tray worker."""
    calls = []

    class Dashboard:
        def run(self):
            calls.append("run")

    result = app.main(["--dashboard"], dashboard_factory=lambda: Dashboard())

    assert result == 0
    assert calls == ["run"]


def test_launch_mode_uses_current_interpreter_without_shell(monkeypatch):
    """A child window must not rely on Python file association or open a command shell."""
    captured = {}

    class Process:
        pass

    def fake_popen(command, **kwargs):
        captured["command"] = command
        captured["kwargs"] = kwargs
        return Process()

    monkeypatch.setattr(app.subprocess, "Popen", fake_popen)

    app.launch_mode("--dashboard")

    assert captured["command"][0] == sys.executable
    assert captured["command"][-1] == "--dashboard"
    assert captured["kwargs"]["shell"] is False
    assert captured["kwargs"]["creationflags"] == app.CREATE_NO_WINDOW


def test_diagnostics_mode_prints_redacted_health_report(tmp_path, monkeypatch, capsys):
    settings = Settings.load(tmp_path / "config.json")

    class Store:
        def load(self):
            return {
                "providers": {
                    "codex": {
                        "status": "ok",
                        "source": "live_api",
                        "access_token": "must-not-leak",
                    }
                }
            }

    monkeypatch.setattr(app, "get_store", lambda: Store())
    monkeypatch.setattr(app.Settings, "load", lambda _path: settings)

    result = app.main(["--diagnostics"], service=object())
    output = capsys.readouterr().out

    assert result == 0
    assert '"status": "ok"' in output
    assert "must-not-leak" not in output
