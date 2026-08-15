# Stable Taskbar Position and Fullscreen Visibility Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Keep Q-Tracker anchored 230 pixels from the taskbar's right edge and hide it only while a foreground window on the same monitor uses fullscreen or borderless fullscreen.

**Architecture:** Keep behavior in the existing native `taskbar_widget.py` module, but isolate geometry classification in pure helpers. The existing one-second UI timer samples foreground-window state, while `_Runtime` stores the last applied position and last confirmed fullscreen visibility state to suppress redundant Win32 calls.

**Tech Stack:** Python 3.13, `ctypes`, Win32 User32, Desktop Window Manager API, pytest

## Global Constraints

- Preserve the horizontal right-edge reserve at exactly 230 pixels.
- Preserve the current effective overlay size of 400 x 48 on the current 1920 x 1080 display.
- Use a two-pixel fullscreen edge tolerance.
- Normally maximized windows keep Q-Tracker visible.
- Fullscreen and borderless fullscreen windows hide Q-Tracker only on the taskbar's monitor.
- Restoring Q-Tracker must not activate it or steal focus.
- Preserve the user's existing uncommitted zero-geometry and Explorer-recovery changes in `taskbar_widget.py` and `tests/test_taskbar_widget.py`.
- Do not change quota data, dashboard, tray, provider refresh, taskbar text, taskbar auto-hide settings, or multi-taskbar behavior.

---

### Task 1: Stable taskbar-relative geometry

**Files:**
- Modify: `taskbar_widget.py:226-350`
- Test: `tests/test_taskbar_widget.py`

**Interfaces:**
- Consumes: taskbar bounds as `(left, top, right, bottom)` and configured width as `int`.
- Produces: `_taskbar_overlay_position(taskbar_bounds: tuple[int, int, int, int], configured_width: int) -> tuple[int, int, int, int] | None`; `_Runtime.last_position: tuple[int, int, int, int] | None`.

- [ ] **Step 1: Add failing placement and deduplication tests**

```python
def _rect_reader(bounds):
    def read(_hwnd, rect_pointer):
        rect = rect_pointer._obj
        rect.left, rect.top, rect.right, rect.bottom = bounds
        return 1
    return read


def test_horizontal_position_keeps_230_pixel_right_reserve():
    assert widget._taskbar_overlay_position((0, 1032, 1920, 1080), 460) == (
        1290, 1032, 400, 48
    )


def test_taskbar_position_rejects_zero_sized_bounds():
    assert widget._taskbar_overlay_position((0, 0, 0, 0), 400) is None


def test_reposition_skips_unchanged_valid_position(monkeypatch):
    runtime = _runtime(_view("test"))
    runtime.last_position = (1290, 1032, 400, 48)
    calls = []
    monkeypatch.setattr(widget, "_runtime", runtime)
    monkeypatch.setattr(widget, "u32", SimpleNamespace(
        FindWindowW=lambda *_: 99,
        GetWindowRect=_rect_reader((0, 1032, 1920, 1080)),
        SetWindowPos=lambda *args: calls.append(args) or 1,
    ))

    assert widget._reposition(100) is True
    assert calls == []
```

- [ ] **Step 2: Run placement tests and verify RED**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_taskbar_widget.py -k "horizontal_position or taskbar_position_rejects or reposition_skips" -q
```

Expected: FAIL because the pure placement helper and stored-position behavior do not exist.

- [ ] **Step 3: Implement pure placement and stable repositioning**

Add `last_position` to `_Runtime`, then calculate the target before calling Win32:

```python
TASKBAR_RIGHT_RESERVE = 230


def _taskbar_overlay_position(taskbar_bounds, configured_width):
    left, top, right, bottom = taskbar_bounds
    taskbar_width = right - left
    taskbar_height = bottom - top
    if taskbar_width <= 0 or taskbar_height <= 0:
        return None
    width = taskbar_overlay_width(configured_width, taskbar_width)
    if taskbar_width >= taskbar_height:
        return max(left, right - width - TASKBAR_RIGHT_RESERVE), top, width, taskbar_height
    width = taskbar_width
    height = min(180, max(60, taskbar_height - 150))
    return left, bottom - height - 100, width, height
```

Change `_reposition` to return `False` for missing/invalid geometry, return `True` without a Win32 call when the tuple equals `last_position`, and store the tuple only after `SetWindowPos` succeeds.

- [ ] **Step 4: Run focused tests and verify GREEN**

Run: `.\.venv\Scripts\python.exe -m pytest tests\test_taskbar_widget.py -q`

Expected: all taskbar-widget tests PASS, including the existing zero-geometry tests.

- [ ] **Step 5: Commit stable positioning**

```powershell
git add -- taskbar_widget.py tests/test_taskbar_widget.py
git commit -m "fix: stabilize taskbar overlay position"
```

---

### Task 2: Fullscreen geometry classification

**Files:**
- Modify: `taskbar_widget.py:25-170,226-260,350-435`
- Test: `tests/test_taskbar_widget.py`

**Interfaces:**
- Consumes: foreground handle, taskbar handle, DWM/User32 window bounds, and monitor bounds.
- Produces: `_rect_covers_monitor(window_bounds: tuple[int, int, int, int], monitor_bounds: tuple[int, int, int, int], tolerance: int = 2) -> bool`; `_foreground_fullscreen_on_taskbar_monitor(overlay_hwnd: HWND) -> bool | None`.

- [ ] **Step 1: Add failing pure fullscreen-classification tests**

```python
def test_maximized_work_area_does_not_cover_monitor():
    assert widget._rect_covers_monitor((0, 0, 1920, 1032), (0, 0, 1920, 1080)) is False


def test_borderless_fullscreen_covers_monitor():
    assert widget._rect_covers_monitor((0, 0, 1920, 1080), (0, 0, 1920, 1080)) is True


def test_fullscreen_tolerates_two_pixel_rounding_only():
    monitor = (0, 0, 1920, 1080)
    assert widget._rect_covers_monitor((1, 2, 1918, 1079), monitor) is True
    assert widget._rect_covers_monitor((0, 0, 1917, 1080), monitor) is False
```

- [ ] **Step 2: Run classifier tests and verify RED**

Run: `.\.venv\Scripts\python.exe -m pytest tests\test_taskbar_widget.py -k "cover_monitor or fullscreen_tolerates" -q`

Expected: FAIL because `_rect_covers_monitor` does not exist.

- [ ] **Step 3: Implement Win32 types, bounds helpers, and classifier**

Define `MONITORINFO`, signatures for `GetForegroundWindow`, `MonitorFromWindow`, `GetMonitorInfoW`, `IsWindowVisible`, `IsIconic`, and `DwmGetWindowAttribute`, then implement:

```python
class MONITORINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", DWORD),
        ("rcMonitor", wintypes.RECT),
        ("rcWork", wintypes.RECT),
        ("dwFlags", DWORD),
    ]


u32.GetForegroundWindow.argtypes = []
u32.GetForegroundWindow.restype = HWND
u32.MonitorFromWindow.argtypes = [HWND, DWORD]
u32.MonitorFromWindow.restype = HANDLE
u32.GetMonitorInfoW.argtypes = [HANDLE, ctypes.POINTER(MONITORINFO)]
u32.GetMonitorInfoW.restype = BOOL
u32.IsWindowVisible.argtypes = [HWND]
u32.IsWindowVisible.restype = BOOL
u32.IsIconic.argtypes = [HWND]
u32.IsIconic.restype = BOOL
dwmapi.DwmGetWindowAttribute.argtypes = [HWND, DWORD, ctypes.c_void_p, DWORD]
dwmapi.DwmGetWindowAttribute.restype = ctypes.c_long

FULLSCREEN_TOLERANCE_PX = 2
DWMWA_EXTENDED_FRAME_BOUNDS = 9
MONITOR_DEFAULTTONULL = 0


def _rect_covers_monitor(window_bounds, monitor_bounds, tolerance=FULLSCREEN_TOLERANCE_PX):
    window_left, window_top, window_right, window_bottom = window_bounds
    monitor_left, monitor_top, monitor_right, monitor_bottom = monitor_bounds
    return (
        window_left <= monitor_left + tolerance
        and window_top <= monitor_top + tolerance
        and window_right >= monitor_right - tolerance
        and window_bottom >= monitor_bottom - tolerance
    )
```

Use DWM extended frame bounds first and `GetWindowRect` as fallback. Return `None` when a required handle or rectangle cannot be read, `False` for invisible/iconic/self/taskbar/other-monitor foreground windows, and the classifier result otherwise.

- [ ] **Step 4: Add same-monitor, other-monitor, and unknown-state tests**

Use `SimpleNamespace` Win32 fakes to prove a fullscreen foreground on the taskbar monitor returns `True`, the same geometry on another monitor returns `False`, and a missing foreground handle returns `None`.

- [ ] **Step 5: Run focused tests and verify GREEN**

Run: `.\.venv\Scripts\python.exe -m pytest tests\test_taskbar_widget.py -k "monitor or fullscreen" -q`

Expected: all selected tests PASS.

- [ ] **Step 6: Commit fullscreen classification**

```powershell
git add -- taskbar_widget.py tests/test_taskbar_widget.py
git commit -m "feat: detect fullscreen apps on taskbar monitor"
```

---

### Task 3: Non-activating visibility transitions

**Files:**
- Modify: `taskbar_widget.py:226-260,435-470,565-580`
- Test: `tests/test_taskbar_widget.py`

**Interfaces:**
- Consumes: `_foreground_fullscreen_on_taskbar_monitor(hwnd) -> bool | None` and `_reposition(hwnd) -> bool`.
- Produces: `_sync_fullscreen_visibility(hwnd: HWND) -> None`; `_Runtime.fullscreen_hidden: bool`.

- [ ] **Step 1: Add failing transition tests**

```python
def test_entering_fullscreen_hides_once(monkeypatch):
    runtime = _runtime(_view("test"))
    runtime.fullscreen_hidden = False
    calls = []
    monkeypatch.setattr(widget, "_runtime", runtime)
    monkeypatch.setattr(widget, "_foreground_fullscreen_on_taskbar_monitor", lambda _h: True)
    monkeypatch.setattr(widget, "u32", SimpleNamespace(
        ShowWindow=lambda *args: calls.append(args)
    ))

    widget._sync_fullscreen_visibility(100)
    widget._sync_fullscreen_visibility(100)

    assert calls == [(100, widget.SW_HIDE)]
    assert runtime.fullscreen_hidden is True


def test_leaving_fullscreen_repositions_and_shows_without_activation(monkeypatch):
    runtime = _runtime(_view("test"))
    runtime.fullscreen_hidden = True
    calls = []
    monkeypatch.setattr(widget, "_runtime", runtime)
    monkeypatch.setattr(widget, "_foreground_fullscreen_on_taskbar_monitor", lambda _h: False)
    monkeypatch.setattr(widget, "_reposition", lambda h: calls.append(("position", h)) or True)
    monkeypatch.setattr(widget, "u32", SimpleNamespace(
        ShowWindow=lambda h, mode: calls.append(("show", h, mode))
    ))

    widget._sync_fullscreen_visibility(100)

    assert calls == [("position", 100), ("show", 100, widget.SW_SHOWNOACTIVATE)]
    assert runtime.fullscreen_hidden is False
```

Add a third test proving a `None` detection result preserves state without calling `ShowWindow`.

- [ ] **Step 2: Run transition tests and verify RED**

Run: `.\.venv\Scripts\python.exe -m pytest tests\test_taskbar_widget.py -k "entering_fullscreen or leaving_fullscreen or uncertain_fullscreen" -q`

Expected: FAIL because the visibility synchronizer and constants do not exist.

- [ ] **Step 3: Implement stateful show/hide transitions**

```python
SW_HIDE = 0
SW_SHOWNOACTIVATE = 4


def _sync_fullscreen_visibility(hwnd):
    if _runtime is None or not hwnd:
        return
    fullscreen = _foreground_fullscreen_on_taskbar_monitor(hwnd)
    if fullscreen is None:
        return
    if fullscreen and not _runtime.fullscreen_hidden:
        u32.ShowWindow(hwnd, SW_HIDE)
        _runtime.fullscreen_hidden = True
    elif not fullscreen and _runtime.fullscreen_hidden:
        _reposition(hwnd)
        u32.ShowWindow(hwnd, SW_SHOWNOACTIVATE)
        _runtime.fullscreen_hidden = False
```

Call `_sync_fullscreen_visibility(hwnd)` once per `WM_TIMER` before loading quota state.

- [ ] **Step 4: Run taskbar tests and verify GREEN**

Run: `.\.venv\Scripts\python.exe -m pytest tests\test_taskbar_widget.py -q`

Expected: all taskbar-widget tests PASS.

- [ ] **Step 5: Commit visibility transitions**

```powershell
git add -- taskbar_widget.py tests/test_taskbar_widget.py
git commit -m "fix: hide taskbar overlay during fullscreen"
```

---

### Task 4: Documentation, regression verification, and packaged smoke test

**Files:**
- Modify: `README.md:110-120`
- Verify: `taskbar_widget.py`
- Verify: `tests/test_taskbar_widget.py`
- Build: `dist/Q-Tracker/Q-Tracker.exe`

**Interfaces:**
- Consumes: completed stable positioning and fullscreen visibility behavior.
- Produces: documented behavior and rebuilt executable.

- [ ] **Step 1: Document behavior**

Add a troubleshooting note that Q-Tracker remains visible for normal maximized windows, hides for fullscreen/borderless fullscreen on the taskbar monitor, and returns without taking focus.

- [ ] **Step 2: Run static and focused verification**

```powershell
.\.venv\Scripts\python.exe -m py_compile taskbar_widget.py
.\.venv\Scripts\python.exe -m pytest tests\test_taskbar_widget.py -q
git diff --check
```

Expected: compilation succeeds, all taskbar tests pass, and diff check emits no errors.

- [ ] **Step 3: Run complete regression suite**

Run: `.\.venv\Scripts\python.exe -m pytest -q`

Expected: all tests PASS with no regressions.

- [ ] **Step 4: Build packaged application**

Run: `powershell -ExecutionPolicy Bypass -File .\build.ps1`

Expected: tests pass inside the build gate and `dist\Q-Tracker\Q-Tracker.exe` is produced.

- [ ] **Step 5: Restart exact packaged executable and inspect geometry**

Stop only the running process whose path is exactly `C:\Users\QUEEN\Q-Tracker\dist\Q-Tracker\Q-Tracker.exe`, start the rebuilt executable hidden, and enumerate its overlay. Assert its rectangle remains `1290,1032-1690,1080` while the taskbar remains `0,1032-1920,1080`.

- [ ] **Step 6: Exercise automated visibility smoke states where available**

Inspect the live overlay's owner, visibility, and position. Confirm the owner remains `Shell_TrayWnd`. If a foreground fullscreen or borderless window is available, confirm the overlay hides within one timer interval and returns without activation after leaving fullscreen. Record any game/video verification that cannot be safely automated.

- [ ] **Step 7: Commit documentation and final implementation state**

```powershell
git add -- README.md taskbar_widget.py tests/test_taskbar_widget.py
git commit -m "docs: describe fullscreen taskbar behavior"
```
