# Independent Taskbar Overlay Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** Detach Q-Tracker from Shell_TrayWnd ownership, keep it topmost independently, and use taskbar/fullscreen state only to decide positioning and visibility.

**Architecture:** The popup becomes an unowned WS_EX_TOPMOST tool window. Pure class-name filtering prevents Progman and WorkerW from being treated as fullscreen apps, while the existing timer combines actual taskbar visibility with foreground fullscreen state and performs stateful show/hide transitions.

**Tech Stack:** Python 3.13, ctypes, Win32 User32, Desktop Window Manager API, pytest, PyInstaller

## Global Constraints

- The popup owner must be null.
- WS_EX_TOPMOST is set once at creation; no periodic topmost SetWindowPos loop.
- Shell_TrayWnd remains the geometry and effective-visibility sensor.
- Progman and WorkerW never count as fullscreen applications.
- Missing or invisible taskbar hides the overlay.
- The 230-pixel right reserve and two-pixel fullscreen tolerance remain unchanged.
- Maximize stays visible; fullscreen and borderless fullscreen hide.
- Restore uses SW_SHOWNOACTIVATE and never steals focus.

---

### Task 1: Detach popup ownership and establish topmost style

**Files:**
- Modify: taskbar_widget.py:622-707
- Test: tests/test_taskbar_widget.py:370-390

**Interfaces:**
- Consumes: instance handle, registered class name, and configured width.
- Produces: _create_overlay_popup(instance: HANDLE, class_name: str, width: int) -> HANDLE.

- [ ] **Step 1: Replace the ownership regression test with a failing independence test**

~~~python
def test_overlay_popup_is_unowned_topmost_tool_window(monkeypatch):
    captured = []
    monkeypatch.setattr(
        widget,
        "u32",
        SimpleNamespace(CreateWindowExW=lambda *args: captured.append(args) or 321),
    )

    result = widget._create_overlay_popup(11, "TrackerClass", 400)

    assert result == 321
    assert captured[0][8] is None
    assert captured[0][0] & widget.WS_EX_TOPMOST
    assert captured[0][0] & widget.WS_EX_NOACTIVATE
    assert captured[0][0] & widget.WS_EX_LAYERED
~~~

The test catches either restoring Shell_TrayWnd as owner or omitting topmost after detachment.

- [ ] **Step 2: Run the test and verify RED**

Run: .\.venv\Scripts\python.exe -m pytest tests\test_taskbar_widget.py::test_overlay_popup_is_unowned_topmost_tool_window -q

Expected: FAIL because _create_overlay_popup does not exist and the current helper accepts an owner.

- [ ] **Step 3: Implement the standalone popup**

~~~python
def _create_overlay_popup(
    instance: HANDLE,
    class_name: str,
    width: int,
) -> HANDLE:
    return u32.CreateWindowExW(
        WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE | WS_EX_LAYERED | WS_EX_TOPMOST,
        class_name,
        "Q-Tracker",
        WS_POPUP | WS_VISIBLE,
        0,
        0,
        width,
        48,
        None,
        None,
        instance,
        None,
    )
~~~

Update _create_window to keep waiting for valid taskbar geometry, then call _create_overlay_popup(instance, class_name, configured_width) without passing taskbar.

- [ ] **Step 4: Run the complete taskbar tests**

Run: .\.venv\Scripts\python.exe -m pytest tests\test_taskbar_widget.py -q

Expected: all tests PASS after updating references from _create_taskbar_popup to _create_overlay_popup.

- [ ] **Step 5: Commit**

~~~powershell
git add -- taskbar_widget.py tests/test_taskbar_widget.py
git commit -m "fix: detach overlay from taskbar ownership"
~~~

---

### Task 2: Exclude desktop shell and mirror effective taskbar visibility

**Files:**
- Modify: taskbar_widget.py:100-220,260-465
- Test: tests/test_taskbar_widget.py:20-280

**Interfaces:**
- Consumes: foreground HWND, taskbar HWND, GetClassNameW, IsWindowVisible, and current fullscreen geometry helpers.
- Produces: _window_class_name(hwnd: HWND) -> str; _is_desktop_shell_window(hwnd: HWND) -> bool; _taskbar_visible() -> bool; _Runtime.overlay_hidden: bool.

- [ ] **Step 1: Add failing desktop-shell regression tests**

~~~python
def test_desktop_shell_never_counts_as_fullscreen(monkeypatch):
    monkeypatch.setattr(widget, "_window_class_name", lambda _h: "Progman")
    monkeypatch.setattr(
        widget,
        "u32",
        SimpleNamespace(
            GetForegroundWindow=lambda: 200,
            FindWindowW=lambda *_: 300,
            IsWindowVisible=lambda _h: 1,
            IsIconic=lambda _h: 0,
        ),
    )

    assert widget._foreground_fullscreen_on_taskbar_monitor(100) is False


def test_workerw_never_counts_as_fullscreen(monkeypatch):
    monkeypatch.setattr(widget, "_window_class_name", lambda _h: "WorkerW")
    monkeypatch.setattr(
        widget,
        "u32",
        SimpleNamespace(
            GetForegroundWindow=lambda: 200,
            FindWindowW=lambda *_: 300,
            IsWindowVisible=lambda _h: 1,
            IsIconic=lambda _h: 0,
        ),
    )

    assert widget._foreground_fullscreen_on_taskbar_monitor(100) is False
~~~

Run: .\.venv\Scripts\python.exe -m pytest tests\test_taskbar_widget.py -k "desktop_shell or workerw" -q

Expected: FAIL because shell-class exclusion does not exist.

- [ ] **Step 2: Add Win32 class lookup and shell exclusion**

~~~python
DESKTOP_SHELL_CLASSES = frozenset({"Progman", "WorkerW"})


def _window_class_name(hwnd: HWND) -> str:
    class_name = ctypes.create_unicode_buffer(256)
    if not u32.GetClassNameW(hwnd, class_name, len(class_name)):
        return ""
    return class_name.value


def _is_desktop_shell_window(hwnd: HWND) -> bool:
    return _window_class_name(hwnd) in DESKTOP_SHELL_CLASSES
~~~

Bind GetClassNameW and call _is_desktop_shell_window(foreground) before monitor/geometry classification. A desktop shell returns False from _foreground_fullscreen_on_taskbar_monitor.

- [ ] **Step 3: Run shell-exclusion tests and verify GREEN**

Run: .\.venv\Scripts\python.exe -m pytest tests\test_taskbar_widget.py -k "desktop_shell or workerw or foreground_fullscreen" -q

Expected: selected tests PASS and a normal same-monitor fullscreen fixture still returns True.

- [ ] **Step 4: Add failing taskbar-state transition tests**

~~~python
def test_missing_taskbar_hides_overlay_once(monkeypatch):
    runtime = _runtime(_view("test"))
    show_calls = []
    monkeypatch.setattr(widget, "_runtime", runtime)
    monkeypatch.setattr(widget, "u32", SimpleNamespace(
        FindWindowW=lambda *_: 0,
        ShowWindow=lambda *args: show_calls.append(args),
    ))

    widget._sync_overlay_visibility(100)
    widget._sync_overlay_visibility(100)

    assert show_calls == [(100, widget.SW_HIDE)]
    assert runtime.overlay_hidden is True


def test_visible_taskbar_restores_overlay_without_activation(monkeypatch):
    runtime = _runtime(_view("test"))
    runtime.overlay_hidden = True
    calls = []
    monkeypatch.setattr(widget, "_runtime", runtime)
    monkeypatch.setattr(widget, "_taskbar_visible", lambda: True)
    monkeypatch.setattr(
        widget,
        "_foreground_fullscreen_on_taskbar_monitor",
        lambda _h: False,
    )
    monkeypatch.setattr(widget, "_reposition", lambda h: calls.append(("position", h)) or True)
    monkeypatch.setattr(widget, "u32", SimpleNamespace(
        ShowWindow=lambda h, mode: calls.append(("show", h, mode))
    ))

    widget._sync_overlay_visibility(100)

    assert calls == [
        ("position", 100),
        ("show", 100, widget.SW_SHOWNOACTIVATE),
    ]
    assert runtime.overlay_hidden is False
~~~

Run: .\.venv\Scripts\python.exe -m pytest tests\test_taskbar_widget.py -k "missing_taskbar_hides or visible_taskbar_restores" -q

Expected: FAIL because the current synchronizer treats missing taskbar as unknown and tracks fullscreen_hidden instead of overall visibility.

- [ ] **Step 5: Implement combined taskbar/fullscreen policy**

~~~python
def _taskbar_visible() -> bool:
    taskbar = u32.FindWindowW("Shell_TrayWnd", None)
    return bool(taskbar and u32.IsWindowVisible(taskbar))


def _sync_overlay_visibility(hwnd: HWND) -> None:
    if _runtime is None or not hwnd:
        return
    if not _taskbar_visible():
        should_hide = True
    else:
        fullscreen = _foreground_fullscreen_on_taskbar_monitor(hwnd)
        if fullscreen is None:
            return
        should_hide = fullscreen
    if should_hide and not _runtime.overlay_hidden:
        u32.ShowWindow(hwnd, SW_HIDE)
        _runtime.overlay_hidden = True
    elif not should_hide and _runtime.overlay_hidden:
        _reposition(hwnd)
        u32.ShowWindow(hwnd, SW_SHOWNOACTIVATE)
        _runtime.overlay_hidden = False
~~~

Rename _Runtime.fullscreen_hidden to overlay_hidden, update tests, and call _sync_overlay_visibility from WM_TIMER.

- [ ] **Step 6: Run taskbar tests and commit**

Run: .\.venv\Scripts\python.exe -m pytest tests\test_taskbar_widget.py -q

Expected: all taskbar tests PASS.

~~~powershell
git add -- taskbar_widget.py tests/test_taskbar_widget.py
git commit -m "fix: keep overlay visible on desktop"
~~~

---

### Task 3: Regression verification, rebuild, and packaged smoke tests

**Files:**
- Modify: README.md:115-125
- Verify: taskbar_widget.py
- Verify: tests/test_taskbar_widget.py
- Build: dist/Q-Tracker/Q-Tracker.exe

**Interfaces:**
- Consumes: completed standalone overlay and visibility policy.
- Produces: rebuilt packaged app with documented independent behavior.

- [ ] **Step 1: Update documentation**

State that Q-Tracker is an independent topmost tool window, uses taskbar state only for position/visibility, stays visible on Desktop clicks and Maximize, and hides for fullscreen/borderless fullscreen.

- [ ] **Step 2: Run complete verification**

~~~powershell
.\.venv\Scripts\python.exe -m py_compile taskbar_widget.py
.\.venv\Scripts\python.exe -m pytest tests\test_taskbar_widget.py -q
.\.venv\Scripts\python.exe -m pytest -q
git diff --check
~~~

Expected: compile succeeds, focused and full tests pass, and diff check reports no errors.

- [ ] **Step 3: Rebuild and restart packaged app**

Stop only C:\Users\QUEEN\Q-Tracker\dist\Q-Tracker\Q-Tracker.exe, run powershell -ExecutionPolicy Bypass -File .\build.ps1, and restart that exact executable with a hidden console.

- [ ] **Step 4: Verify the live window and visibility states**

Enumerate QTrackerTaskbarV1 and assert:

- GW_OWNER is zero.
- WS_EX_TOPMOST is present.
- Rectangle is 1290,1032-1690,1080 and right reserve is 230.
- Activating Progman or clicking Desktop does not hide the overlay.
- A maximized form keeps it visible.
- A borderless fullscreen form hides it within one timer interval and it returns afterward.
- The working tree is clean.

- [ ] **Step 5: Commit documentation**

~~~powershell
git add -- README.md
git commit -m "docs: describe independent taskbar overlay"
~~~
