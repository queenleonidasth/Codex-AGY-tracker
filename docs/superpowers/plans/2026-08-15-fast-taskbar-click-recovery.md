# Fast Taskbar Click Recovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prevent a visible pause when clicking the Windows taskbar by repairing Q-Tracker visibility and relative Z-order through WinEvent hooks with a dedicated 10-millisecond fallback interval.

**Architecture:** Keep the configurable data-refresh timer responsible only for loading quota state and updating the rendered view. Use foreground and object-reorder WinEvent hooks for immediate conditional Z-order repair, with a second 10-millisecond timer responsible for taskbar/fullscreen visibility and fallback Z-order repair. Timer IDs route each `WM_TIMER` message to exactly one responsibility.

**Tech Stack:** Python 3.13, ctypes, Win32 User32 timers, pytest, PyInstaller

## Global Constraints

- Q-Tracker remains an unowned `WS_EX_TOPMOST | WS_EX_NOACTIVATE` popup.
- The taskbar remains only a geometry, visibility, and relative Z-order sensor.
- The right reserve remains exactly 230 pixels.
- Shell-state synchronization runs every 10 milliseconds as a fallback and performs no quota-state load.
- Data refresh retains its configured interval, normally 1,000 milliseconds, and performs no duplicate shell-state synchronization.
- Fullscreen and borderless fullscreen hide Q-Tracker; Desktop, taskbar, and maximized-window interaction keep it visible.

---

### Task 1: Split data refresh from shell-state synchronization

**Files:**
- Modify: `taskbar_widget.py:45-85, 640-765`
- Test: `tests/test_taskbar_widget.py:430-690`
- Build: `dist/Q-Tracker/Q-Tracker.exe`

**Interfaces:**
- Consumes: `WM_TIMER`, Win32 timer ID in `wparam`, configured `update_interval_ms`, `_sync_overlay_visibility(hwnd)`, and `_ensure_overlay_above_taskbar(hwnd)`.
- Produces: `DATA_REFRESH_TIMER_ID = 1`, `SHELL_SYNC_TIMER_ID = 2`, and `SHELL_SYNC_INTERVAL_MS = 10`.

- [ ] **Step 1: Write failing timer-routing regression tests**

```python
def test_shell_timer_repairs_presentation_without_loading_quota(monkeypatch):
    current = _view("same")
    runtime = _runtime(current, ticks=4)
    calls = []
    runtime.store = SimpleNamespace(load=lambda: calls.append("load"))
    monkeypatch.setattr(widget, "_runtime", runtime)
    monkeypatch.setattr(widget, "_sync_overlay_visibility", lambda hwnd: calls.append(("visibility", hwnd)))
    monkeypatch.setattr(widget, "_ensure_overlay_above_taskbar", lambda hwnd: calls.append(("z-order", hwnd)))
    monkeypatch.setattr(widget, "build_tracker_view", lambda *_: calls.append("view"))

    assert widget._wnd_proc(100, widget.WM_TIMER, widget.SHELL_SYNC_TIMER_ID, 0) == 0
    assert calls == [("visibility", 100), ("z-order", 100)]
    assert runtime.ticks == 4


def test_data_timer_refreshes_quota_without_shell_sync(monkeypatch):
    current = _view("same")
    calls = []
    monkeypatch.setattr(widget, "_runtime", _runtime(current, ticks=4))
    monkeypatch.setattr(widget, "build_tracker_view", lambda *_: calls.append("view") or current)
    monkeypatch.setattr(widget, "_sync_overlay_visibility", lambda _hwnd: calls.append("visibility"))
    monkeypatch.setattr(widget, "_ensure_overlay_above_taskbar", lambda _hwnd: calls.append("z-order"))

    assert widget._wnd_proc(100, widget.WM_TIMER, widget.DATA_REFRESH_TIMER_ID, 0) == 0
    assert calls == ["view"]
    assert widget._runtime.ticks == 5
```

These tests catch re-coupling the fast shell timer to disk-backed state loading and reintroducing the 1,000-millisecond Z-order delay.

- [ ] **Step 2: Run the focused tests and verify RED**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_taskbar_widget.py -k "shell_timer_repairs or data_timer_refreshes" -q
```

Expected: FAIL because the timer IDs do not exist and all `WM_TIMER` messages currently perform both responsibilities.

- [ ] **Step 3: Add timer constants and route `WM_TIMER` by ID**

```python
DATA_REFRESH_TIMER_ID = 1
SHELL_SYNC_TIMER_ID = 2
SHELL_SYNC_INTERVAL_MS = 10
```

In `_wnd_proc`, handle `SHELL_SYNC_TIMER_ID` by synchronizing visibility and, only when the runtime is not hidden, repairing Z-order. Handle `DATA_REFRESH_TIMER_ID` by incrementing ticks, loading state, rebuilding the view, and invalidating only on fingerprint change. Delegate unknown timer IDs to `DefWindowProcW`.

```python
if message == WM_TIMER:
    if wparam == SHELL_SYNC_TIMER_ID:
        _sync_overlay_visibility(hwnd)
        if not _runtime.overlay_hidden:
            _ensure_overlay_above_taskbar(hwnd)
        return 0
    if wparam == DATA_REFRESH_TIMER_ID:
        _runtime.ticks += 1
        view = build_tracker_view(
            _runtime.store.load(),
            _runtime.settings.enabled_providers,
        )
        if view.fingerprint != _runtime.view.fingerprint:
            _runtime.view = view
            u32.InvalidateRect(hwnd, None, 0)
        return 0
    return u32.DefWindowProcW(hwnd, message, wparam, lparam)
```

- [ ] **Step 4: Add a failing creation test for both timer registrations**

```python
def test_create_window_registers_data_and_shell_timers(monkeypatch):
    timer_calls = []
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
    monkeypatch.setattr(widget, "_reposition", lambda *_: True)
    monkeypatch.setattr(widget, "k32", SimpleNamespace(GetModuleHandleW=lambda *_: 11))
    monkeypatch.setattr(widget, "g32", SimpleNamespace(CreateSolidBrush=lambda *_: 22))
    monkeypatch.setattr(
        widget,
        "u32",
        SimpleNamespace(
            FindWindowW=lambda *_: 99,
            GetWindowRect=lambda _h, rect: (
                setattr(rect._obj, "left", 0)
                or setattr(rect._obj, "top", 1032)
                or setattr(rect._obj, "right", 1920)
                or setattr(rect._obj, "bottom", 1080)
                or 1
            ),
            LoadCursorW=lambda *_: 33,
            RegisterClassExW=lambda *_: 1,
            CreateWindowExW=lambda *_: 321,
            SetLayeredWindowAttributes=lambda *_: 1,
            SetTimer=lambda *args: timer_calls.append(args) or args[1],
            ShowWindow=lambda *_: 1,
            UpdateWindow=lambda *_: 1,
        ),
    )

    assert widget._create_window(max_retries=1, retry_delay=0) is True
assert timer_calls == [
    (321, widget.DATA_REFRESH_TIMER_ID, 1_000, None),
    (321, widget.SHELL_SYNC_TIMER_ID, 10, None),
]
```

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_taskbar_widget.py -k "registers_data_and_shell_timers" -q
```

Expected: FAIL with only the existing data timer call present.

- [ ] **Step 5: Register and clean up both timers**

Update `_create_window` to register `DATA_REFRESH_TIMER_ID` at the configured interval and `SHELL_SYNC_TIMER_ID` at `SHELL_SYNC_INTERVAL_MS`. Update `WM_CLOSE` to kill both window timers before destroying the overlay.

```python
u32.SetTimer(
    _runtime.hwnd,
    DATA_REFRESH_TIMER_ID,
    int(_runtime.settings.display.get("update_interval_ms", 1_000)),
    None,
)
u32.SetTimer(
    _runtime.hwnd,
    SHELL_SYNC_TIMER_ID,
    SHELL_SYNC_INTERVAL_MS,
    None,
)
```

```python
if message == WM_CLOSE:
    u32.KillTimer(hwnd, DATA_REFRESH_TIMER_ID)
    u32.KillTimer(hwnd, SHELL_SYNC_TIMER_ID)
    u32.DestroyWindow(hwnd)
    return 0
```

- [ ] **Step 6: Verify GREEN and the complete suite**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_taskbar_widget.py -q
.\.venv\Scripts\python.exe -m pytest -q
git diff --check
```

Expected: all tests PASS and diff check reports no errors.

- [ ] **Step 7: Commit, rebuild, restart, and measure the packaged app**

```powershell
git add -- taskbar_widget.py tests/test_taskbar_widget.py
git commit -m "fix: recover immediately after taskbar clicks"
powershell -ExecutionPolicy Bypass -File .\build.ps1
```

Stop and restart only `C:\Users\QUEEN\Q-Tracker\dist\Q-Tracker\Q-Tracker.exe`. Click an empty taskbar area and sample relative Z-order at high frequency; verify `Shell_TrayWnd` stops being above Q-Tracker within 100 milliseconds, the overlay remains `IsWindowVisible=True`, the owner remains zero, and the right reserve remains 230 pixels.
