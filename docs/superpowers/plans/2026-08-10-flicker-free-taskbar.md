# Flicker-Free Taskbar Overlay Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Keep the quota overlay continuously visible when Explorer's taskbar is clicked and repaint quota changes without a transparent intermediate frame.

**Architecture:** Make the popup owned by `Shell_TrayWnd`, so Windows preserves its order relative to the taskbar without periodic `HWND_TOPMOST` calls. Retain the existing double-buffered GDI painter, but invalidate changed data without background erasure and restrict repositioning to actual display/settings/DPI events.

**Tech Stack:** Python 3.13, pytest, ctypes/Win32 User32 and GDI, PyInstaller, PowerShell

## Global Constraints

- The popup owner is the current `Shell_TrayWnd` handle.
- The popup does not use `WS_EX_TOPMOST`.
- `_reposition` uses `SWP_NOZORDER | SWP_NOACTIVATE`.
- Timer ticks never reposition the popup or change its Z-order.
- Changed presentation data calls `InvalidateRect(hwnd, None, FALSE)`.
- Existing quota text, colors, compact selection, width and horizontal offset remain unchanged.
- Missing `Shell_TrayWnd` makes `_create_window()` return `False` without creating a standalone popup.

---

### Task 1: Win32 Event and Ownership Policy

**Files:**
- Create: `tests/test_taskbar_widget.py`
- Modify: `taskbar_widget.py:58-68`
- Modify: `taskbar_widget.py:244-266`
- Modify: `taskbar_widget.py:362-376`
- Modify: `taskbar_widget.py:404-440`

**Interfaces:**
- Consumes: `_runtime.view.fingerprint`, `build_tracker_view(...)`, `Shell_TrayWnd`, and the existing Win32 message loop
- Produces: `_create_taskbar_popup(instance: HANDLE, class_name: str, owner: HANDLE, width: int) -> HANDLE`
- Produces: timer behavior that only refreshes changed presentation state

- [ ] **Step 1: Add timer regression tests**

```python
from types import SimpleNamespace

import taskbar_widget as widget
from ui_models import TrackerView


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


def test_timer_never_repositions_or_changes_z_order(monkeypatch):
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
```

- [ ] **Step 2: Run the timer tests and verify RED**

Run: `.\.venv\Scripts\python.exe -m pytest tests\test_taskbar_widget.py -q`

Expected: the first test records the legacy `SetWindowPos` call at tick 5, and the second test receives erase flag `1` instead of `0`.

- [ ] **Step 3: Add popup ownership regression test**

```python
def test_taskbar_popup_uses_owner_without_global_topmost(monkeypatch):
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
```

- [ ] **Step 4: Run the owner test and verify RED**

Run: `.\.venv\Scripts\python.exe -m pytest tests\test_taskbar_widget.py::test_taskbar_popup_uses_owner_without_global_topmost -q`

Expected: collection or execution fails because `_create_taskbar_popup` does not exist.

- [ ] **Step 5: Implement owner-based popup creation**

```python
SWP_NOZORDER = 0x0004


def _create_taskbar_popup(
    instance: HANDLE,
    class_name: str,
    owner: HANDLE,
    width: int,
) -> HANDLE:
    return u32.CreateWindowExW(
        WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE | WS_EX_LAYERED,
        class_name,
        "AI Usage Tracker",
        WS_POPUP | WS_VISIBLE,
        0,
        0,
        width,
        48,
        owner,
        None,
        instance,
        None,
    )
```

In `_create_window`, resolve `taskbar = u32.FindWindowW("Shell_TrayWnd", None)` before registering/creating the popup, return `False` when it is missing, and replace the direct `CreateWindowExW` call with `_create_taskbar_popup(instance, class_name, taskbar, configured_width)`.

- [ ] **Step 6: Implement event-driven positioning and painting**

```python
u32.SetWindowPos(
    hwnd,
    None,
    x,
    y,
    width,
    height,
    SWP_NOZORDER | SWP_NOACTIVATE,
)

if message == WM_TIMER:
    _runtime.ticks += 1
    view = build_tracker_view(_runtime.store.load(), _runtime.settings.enabled_providers)
    if view.fingerprint != _runtime.view.fingerprint:
        _runtime.view = view
        u32.InvalidateRect(hwnd, None, 0)
    return 0
```

- [ ] **Step 7: Run focused and complete tests**

Run: `.\.venv\Scripts\python.exe -m pytest tests\test_taskbar_widget.py -q`

Expected: all taskbar widget tests pass.

Run: `.\.venv\Scripts\python.exe -m pytest -q`

Expected: the complete suite passes.

Run: `.\.venv\Scripts\python.exe -m compileall -q .`

Expected: exit code 0.

- [ ] **Step 8: Commit the tested runtime fix**

```powershell
git add -- taskbar_widget.py tests/test_taskbar_widget.py
git commit -m "fix: prevent taskbar overlay flicker"
```

### Task 2: Package and Runtime Verification

**Files:**
- Rebuild: `dist/AIUsageTracker/AIUsageTracker.exe`

**Interfaces:**
- Consumes: committed owner-based overlay and non-erasing repaint policy
- Produces: one running packaged tracker instance built from the verified `main` source

- [ ] **Step 1: Stop only the exact packaged tracker process**

Resolve `dist\AIUsageTracker\AIUsageTracker.exe`, select processes named `AIUsageTracker` whose resolved `Path` exactly matches it, and stop only those PIDs.

- [ ] **Step 2: Build the packaged application**

Run: `.\build.ps1`

Expected: the complete tests pass and PyInstaller produces `dist\AIUsageTracker\AIUsageTracker.exe`.

- [ ] **Step 3: Start and verify one packaged instance**

Start the rebuilt executable with `-WindowStyle Hidden`, poll for at most 10 seconds, and assert exactly one `AIUsageTracker` process has a resolved path equal to the rebuilt artifact.

- [ ] **Step 4: Verify the packaged popup is owned by the taskbar**

Use PowerShell `Add-Type` to expose `FindWindowW`, `GetWindow`, `IsWindowVisible` and `SetForegroundWindow`. Resolve the overlay with title `AI Usage Tracker`, resolve `Shell_TrayWnd`, and assert `GetWindow($overlay, 4)` (`GW_OWNER`) equals the taskbar handle and `IsWindowVisible($overlay)` is true. Call `SetForegroundWindow($taskbar)`, wait 250 ms, and assert the same ownership and visibility again.

- [ ] **Step 5: Perform final verification**

Run: `.\.venv\Scripts\python.exe -m pytest -q`

Expected: the complete suite passes with zero failures.

Run: `.\.venv\Scripts\python.exe -m compileall -q .`

Expected: exit code 0.

Run: `git diff --check` and `git status --short`

Expected: no whitespace errors and a clean worktree.
