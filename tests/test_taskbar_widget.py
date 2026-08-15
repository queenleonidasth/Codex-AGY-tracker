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
        last_position=None,
        fullscreen_hidden=False,
    )


def _rect_reader(bounds):
    def read(_hwnd, rect_pointer):
        rect = rect_pointer._obj
        rect.left, rect.top, rect.right, rect.bottom = bounds
        return 1

    return read


def _monitor_info_reader(bounds_by_monitor):
    def read(monitor, info_pointer):
        bounds = bounds_by_monitor[monitor]
        info = info_pointer._obj
        (
            info.rcMonitor.left,
            info.rcMonitor.top,
            info.rcMonitor.right,
            info.rcMonitor.bottom,
        ) = bounds
        return 1

    return read


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


def test_horizontal_position_keeps_230_pixel_right_reserve():
    """A geometry refresh must preserve the user's current taskbar-relative anchor."""
    assert widget._taskbar_overlay_position((0, 1032, 1920, 1080), 460) == (
        1290,
        1032,
        400,
        48,
    )


def test_taskbar_position_rejects_zero_sized_bounds():
    """Transient Explorer geometry must not collapse or move the overlay."""
    assert widget._taskbar_overlay_position((0, 0, 0, 0), 400) is None


def test_reposition_skips_unchanged_valid_position(monkeypatch):
    """Repeated display notifications must not move an already-correct overlay."""
    runtime = _runtime(_view("test"))
    runtime.settings.display = {"width": 460}
    runtime.last_position = (1290, 1032, 400, 48)
    set_position_calls = []
    monkeypatch.setattr(widget, "_runtime", runtime)
    monkeypatch.setattr(
        widget,
        "u32",
        SimpleNamespace(
            FindWindowW=lambda *_: 99,
            GetWindowRect=_rect_reader((0, 1032, 1920, 1080)),
            SetWindowPos=lambda *args: set_position_calls.append(args) or 1,
        ),
    )

    assert widget._reposition(100) is True
    assert set_position_calls == []


def test_maximized_work_area_does_not_cover_monitor():
    """A maximized app that leaves the taskbar visible must keep Q-Tracker visible."""
    assert widget._rect_covers_monitor(
        (0, 0, 1920, 1032),
        (0, 0, 1920, 1080),
    ) is False


def test_borderless_fullscreen_covers_monitor():
    """A borderless app covering the complete monitor must hide Q-Tracker."""
    assert widget._rect_covers_monitor(
        (0, 0, 1920, 1080),
        (0, 0, 1920, 1080),
    ) is True


def test_fullscreen_tolerates_two_pixel_rounding_only():
    """DPI rounding may miss two pixels, but a larger gap is not fullscreen."""
    monitor = (0, 0, 1920, 1080)

    assert widget._rect_covers_monitor((1, 2, 1918, 1079), monitor) is True
    assert widget._rect_covers_monitor((0, 0, 1917, 1080), monitor) is False


def test_foreground_fullscreen_on_taskbar_monitor_is_detected(monkeypatch):
    """A same-monitor borderless foreground window must request hiding."""
    monkeypatch.setattr(
        widget,
        "u32",
        SimpleNamespace(
            GetForegroundWindow=lambda: 200,
            FindWindowW=lambda *_: 300,
            IsWindowVisible=lambda _h: 1,
            IsIconic=lambda _h: 0,
            MonitorFromWindow=lambda _h, _flags: 10,
            GetMonitorInfoW=_monitor_info_reader({10: (0, 0, 1920, 1080)}),
            GetWindowRect=_rect_reader((0, 0, 1920, 1080)),
        ),
    )
    monkeypatch.setattr(
        widget,
        "dwmapi",
        SimpleNamespace(DwmGetWindowAttribute=lambda *_: -1),
    )

    assert widget._foreground_fullscreen_on_taskbar_monitor(100) is True


def test_foreground_fullscreen_on_other_monitor_is_ignored(monkeypatch):
    """Fullscreen on another monitor must not hide this taskbar's overlay."""
    monkeypatch.setattr(
        widget,
        "u32",
        SimpleNamespace(
            GetForegroundWindow=lambda: 200,
            FindWindowW=lambda *_: 300,
            IsWindowVisible=lambda _h: 1,
            IsIconic=lambda _h: 0,
            MonitorFromWindow=lambda h, _flags: 10 if h == 200 else 20,
            GetMonitorInfoW=_monitor_info_reader(
                {10: (1920, 0, 3840, 1080), 20: (0, 0, 1920, 1080)}
            ),
        ),
    )

    assert widget._foreground_fullscreen_on_taskbar_monitor(100) is False


def test_missing_foreground_window_preserves_visibility_state(monkeypatch):
    """A transient missing foreground handle is unknown, not proof of fullscreen."""
    monkeypatch.setattr(
        widget,
        "u32",
        SimpleNamespace(GetForegroundWindow=lambda: 0),
    )

    assert widget._foreground_fullscreen_on_taskbar_monitor(100) is None


def test_entering_fullscreen_hides_once(monkeypatch):
    """Repeated fullscreen timer ticks must issue only one hide transition."""
    runtime = _runtime(_view("test"))
    show_calls = []
    monkeypatch.setattr(widget, "_runtime", runtime)
    monkeypatch.setattr(
        widget,
        "_foreground_fullscreen_on_taskbar_monitor",
        lambda _h: True,
    )
    monkeypatch.setattr(
        widget,
        "u32",
        SimpleNamespace(ShowWindow=lambda *args: show_calls.append(args)),
    )

    widget._sync_fullscreen_visibility(100)
    widget._sync_fullscreen_visibility(100)

    assert show_calls == [(100, widget.SW_HIDE)]
    assert runtime.fullscreen_hidden is True


def test_leaving_fullscreen_repositions_and_shows_without_activation(monkeypatch):
    """Returning from fullscreen must restore position without stealing focus."""
    runtime = _runtime(_view("test"))
    runtime.fullscreen_hidden = True
    calls = []
    monkeypatch.setattr(widget, "_runtime", runtime)
    monkeypatch.setattr(
        widget,
        "_foreground_fullscreen_on_taskbar_monitor",
        lambda _h: False,
    )
    monkeypatch.setattr(
        widget,
        "_reposition",
        lambda hwnd: calls.append(("position", hwnd)) or True,
    )
    monkeypatch.setattr(
        widget,
        "u32",
        SimpleNamespace(
            ShowWindow=lambda hwnd, mode: calls.append(("show", hwnd, mode))
        ),
    )

    widget._sync_fullscreen_visibility(100)

    assert calls == [
        ("position", 100),
        ("show", 100, widget.SW_SHOWNOACTIVATE),
    ]
    assert runtime.fullscreen_hidden is False


def test_uncertain_fullscreen_detection_keeps_last_visibility(monkeypatch):
    """A transient Win32 read failure must not flicker a hidden overlay visible."""
    runtime = _runtime(_view("test"))
    runtime.fullscreen_hidden = True
    show_calls = []
    monkeypatch.setattr(widget, "_runtime", runtime)
    monkeypatch.setattr(
        widget,
        "_foreground_fullscreen_on_taskbar_monitor",
        lambda _h: None,
    )
    monkeypatch.setattr(
        widget,
        "u32",
        SimpleNamespace(ShowWindow=lambda *args: show_calls.append(args)),
    )

    widget._sync_fullscreen_visibility(100)

    assert show_calls == []
    assert runtime.fullscreen_hidden is True


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
    assert segments[1].text == "91%"
    assert segments[1].gap_after == 4
    assert segments[-1].gap_after == 0


def test_render_segments_include_waiting_text_without_providers():
    """The empty-provider state must enter the same measured alignment pipeline."""
    segments = widget._render_segments(_view(""), {})

    assert [segment.text for segment in segments] == ["Q-Tracker — waiting for data"]
    assert segments[0].gap_after == 0


def test_timer_never_repositions_or_changes_z_order(monkeypatch):
    """Explorer activity must not start a periodic Z-order fight."""
    current = _view("same")
    reposition_calls = []
    set_position_calls = []
    visibility_syncs = []
    monkeypatch.setattr(widget, "_runtime", _runtime(current, ticks=4))
    monkeypatch.setattr(widget, "build_tracker_view", lambda *_: current)
    monkeypatch.setattr(widget, "_reposition", lambda hwnd: reposition_calls.append(hwnd))
    monkeypatch.setattr(
        widget,
        "_sync_fullscreen_visibility",
        lambda hwnd: visibility_syncs.append(hwnd),
    )
    monkeypatch.setattr(
        widget,
        "u32",
        SimpleNamespace(
            SetWindowPos=lambda *args: set_position_calls.append(args),
            DefWindowProcW=lambda *_: -1,
        ),
    )

    assert widget._wnd_proc(100, widget.WM_TIMER, 0, 0) == 0
    assert visibility_syncs == [100]
    assert reposition_calls == []
    assert set_position_calls == []


def test_changed_view_invalidates_without_background_erase(monkeypatch):
    """A quota update must not expose a transparent frame before repainting."""
    current = _view("old")
    changed = _view("new")
    invalidate_calls = []
    monkeypatch.setattr(widget, "_runtime", _runtime(current))
    monkeypatch.setattr(widget, "build_tracker_view", lambda *_: changed)
    monkeypatch.setattr(widget, "_sync_fullscreen_visibility", lambda _hwnd: None)
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

    assert widget._create_window(max_retries=1, retry_delay=0) is False
    assert create_calls == []

def test_run_taskbar_sets_retry_timer_when_initial_window_creation_fails(monkeypatch):
    """When Explorer is not available on startup, run_taskbar must set a retry timer instead of exiting immediately."""
    timer_calls = []
    messages = [SimpleNamespace(message=123)]

    def fake_get_message(msg_ptr, *_args):
        if messages:
            msg = messages.pop(0)
            getattr(msg_ptr, "_obj", msg_ptr).message = msg.message
            return 1
        return 0

    monkeypatch.setattr(widget, "_create_window", lambda *args, **kwargs: False)
    monkeypatch.setattr(widget, "build_tracker_view", lambda *_: _view("test"))
    monkeypatch.setattr(
        widget,
        "u32",
        SimpleNamespace(
            SetTimer=lambda *args: timer_calls.append(("set", args)) or 999,
            KillTimer=lambda *args: timer_calls.append(("kill", args)),
            GetMessageW=fake_get_message,
            TranslateMessage=lambda *_: None,
            DispatchMessageW=lambda *_: None,
        ),
    )

    result = widget.run_taskbar(
        store=SimpleNamespace(load=lambda: {}),
        settings=SimpleNamespace(enabled_providers=()),
        on_open=lambda: None,
        on_refresh=lambda: None,
    )

    assert result == 0
    assert ("set", (None, 0, 2000, None)) in timer_calls
    assert ("kill", (None, 999)) in timer_calls


def test_reposition_ignores_zero_dimensions(monkeypatch):
    """Repositioning must not collapse the window if taskbar has not finished layout."""
    set_position_calls = []
    monkeypatch.setattr(widget, "_runtime", _runtime(_view("test")))
    monkeypatch.setattr(
        widget,
        "u32",
        SimpleNamespace(
            FindWindowW=lambda *_: 99,
            GetWindowRect=lambda _h, r: setattr(r._obj, "right", 0) or setattr(r._obj, "bottom", 0) or 1,
            SetWindowPos=lambda *args: set_position_calls.append(args),
        ),
    )

    widget._reposition(100)
    assert set_position_calls == []


def test_create_window_retries_when_taskbar_has_zero_geometry(monkeypatch):
    """When Explorer exists but has 0 width or 0 height, create_window must wait."""
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
    monkeypatch.setattr(widget, "k32", SimpleNamespace(GetModuleHandleW=lambda *_: 11))
    monkeypatch.setattr(widget, "g32", SimpleNamespace(CreateSolidBrush=lambda *_: 22))
    monkeypatch.setattr(
        widget,
        "u32",
        SimpleNamespace(
            FindWindowW=lambda *_: 99,
            GetWindowRect=lambda _h, r: setattr(r._obj, "right", 0) or setattr(r._obj, "bottom", 0) or 1,
            LoadCursorW=lambda *_: 33,
            RegisterClassExW=lambda *_: 1,
            CreateWindowExW=lambda *args: create_calls.append(args) or 321,
            SetLayeredWindowAttributes=lambda *_: 1,
            SetTimer=lambda *_: 1,
            ShowWindow=lambda *_: 1,
            UpdateWindow=lambda *_: 1,
        ),
    )

    assert widget._create_window(max_retries=1, retry_delay=0) is False
    assert create_calls == []


