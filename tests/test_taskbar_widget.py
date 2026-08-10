from types import SimpleNamespace

import taskbar_widget as widget
from ui_models import ProviderView, TrackerView, WindowView


def _view(text: str) -> TrackerView:
    return TrackerView(
        providers=(),
        compact_text=text,
        token_totals={"today": 0, "month": 0, "lifetime": 0},
    )


def _runtime(view: TrackerView, ticks: int = 0) -> SimpleNamespace:
    return SimpleNamespace(
        ticks=ticks,
        view=view,
        store=SimpleNamespace(load=lambda: {}),
        settings=SimpleNamespace(enabled_providers=("agy", "codex")),
    )


def _window(window_id: str, label: str, remaining: float) -> WindowView:
    return WindowView(window_id, label, label, remaining, 100 - remaining, None, "—", "normal")


def _provider(provider_id: str, name: str, windows: tuple[WindowView, ...]) -> ProviderView:
    return ProviderView(
        provider_id,
        name,
        "ok",
        "",
        name,
        windows,
        "test",
        None,
        None,
        "now",
        "test",
        "",
    )


def test_right_aligned_start_keeps_twelve_pixel_margin():
    """Short content must end twelve pixels before the overlay's right edge."""
    assert widget._right_aligned_start(client_width=400, content_width=320) == 68


def test_right_aligned_start_falls_back_to_left_margin_for_overflow():
    """Long content must not receive a negative or off-window start coordinate."""
    assert widget._right_aligned_start(client_width=400, content_width=410) == 10


def test_render_segments_preserve_compact_provider_text_order():
    """The alignment refactor must not change which quotas users see or their order."""
    view = TrackerView(
        providers=(
            _provider(
                "agy",
                "Antigravity",
                (_window("session", "5H", 91), _window("weekly", "W", 94)),
            ),
            _provider("codex", "Codex", (_window("weekly", "W", 46),)),
        ),
        compact_text="",
        token_totals={},
    )

    segments = widget._render_segments(
        view,
        {"agy": {"color": "#35C2FF"}, "codex": {"color": "#7FE36A"}},
    )

    assert [segment.text for segment in segments] == [
        "Antigravity",
        "91%",
        "5H",
        "·",
        "94%",
        "W",
        " | ",
        "Codex",
        "46%",
        "W",
    ]
    assert segments[-1].gap_after == 0


def test_render_segments_include_waiting_text_without_providers():
    """The empty-provider state must enter the same measured alignment pipeline."""
    segments = widget._render_segments(_view(""), {})

    assert [segment.text for segment in segments] == ["AI Usage — waiting for data"]
    assert segments[0].gap_after == 0


def test_timer_never_repositions_or_changes_z_order(monkeypatch):
    """Explorer activity must not start a periodic Z-order fight."""
    current = _view("same")
    reposition_calls = []
    set_position_calls = []
    monkeypatch.setattr(widget, "_runtime", _runtime(current, ticks=4))
    monkeypatch.setattr(widget, "build_tracker_view", lambda *_: current)
    monkeypatch.setattr(widget, "_reposition", lambda hwnd: reposition_calls.append(hwnd))
    monkeypatch.setattr(
        widget,
        "u32",
        SimpleNamespace(
            SetWindowPos=lambda *args: set_position_calls.append(args),
            DefWindowProcW=lambda *_: -1,
        ),
    )

    assert widget._wnd_proc(100, widget.WM_TIMER, 0, 0) == 0
    assert reposition_calls == []
    assert set_position_calls == []


def test_changed_view_invalidates_without_background_erase(monkeypatch):
    """A quota update must not expose a transparent frame before repainting."""
    current = _view("old")
    changed = _view("new")
    invalidate_calls = []
    monkeypatch.setattr(widget, "_runtime", _runtime(current))
    monkeypatch.setattr(widget, "build_tracker_view", lambda *_: changed)
    monkeypatch.setattr(
        widget,
        "u32",
        SimpleNamespace(
            InvalidateRect=lambda *args: invalidate_calls.append(args),
            DefWindowProcW=lambda *_: -1,
        ),
    )

    assert widget._wnd_proc(100, widget.WM_TIMER, 0, 0) == 0
    assert widget._runtime.view is changed
    assert invalidate_calls == [(100, None, 0)]


def test_taskbar_popup_uses_owner_without_global_topmost(monkeypatch):
    """Activating Explorer must keep its owned quota popup above the taskbar."""
    captured = []
    monkeypatch.setattr(
        widget,
        "u32",
        SimpleNamespace(CreateWindowExW=lambda *args: captured.append(args) or 321),
    )

    result = widget._create_taskbar_popup(11, "TrackerClass", 77, 400)

    assert result == 321
    assert captured[0][8] == 77
    assert captured[0][0] & widget.WS_EX_TOPMOST == 0


def test_create_window_stops_when_taskbar_owner_is_missing(monkeypatch):
    """A missing Explorer taskbar must not recreate the unstable standalone popup."""
    create_calls = []
    monkeypatch.setattr(
        widget,
        "_runtime",
        SimpleNamespace(
            hwnd=None,
            settings=SimpleNamespace(display={"width": 400, "update_interval_ms": 1_000}),
        ),
    )
    monkeypatch.setattr(widget, "_background_brush", None)
    monkeypatch.setattr(widget, "_wndproc_ref", None)
    monkeypatch.setattr(widget, "_reposition", lambda *_: None)
    monkeypatch.setattr(widget, "k32", SimpleNamespace(GetModuleHandleW=lambda *_: 11))
    monkeypatch.setattr(widget, "g32", SimpleNamespace(CreateSolidBrush=lambda *_: 22))
    monkeypatch.setattr(
        widget,
        "u32",
        SimpleNamespace(
            FindWindowW=lambda *_: 0,
            LoadCursorW=lambda *_: 33,
            RegisterClassExW=lambda *_: 1,
            CreateWindowExW=lambda *args: create_calls.append(args) or 321,
            SetLayeredWindowAttributes=lambda *_: 1,
            SetTimer=lambda *_: 1,
            ShowWindow=lambda *_: 1,
            UpdateWindow=lambda *_: 1,
        ),
    )

    assert widget._create_window() is False
    assert create_calls == []
