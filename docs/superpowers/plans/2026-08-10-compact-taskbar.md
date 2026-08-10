# Compact Taskbar Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Show only Antigravity 5H and weekly quota plus Codex weekly quota in a taskbar overlay no wider than 400 px.

**Architecture:** Keep every provider window in the shared immutable presentation model, and add a pure taskbar-only selector that returns the required subset. The native taskbar painter consumes that subset while Dashboard and context-menu code continue consuming `ProviderView.windows` unchanged.

**Tech Stack:** Python 3.13, pytest, ctypes/Win32 GDI, PyInstaller, PowerShell

## Global Constraints

- Target format is `Antigravity 94% 5H · 93% W | Codex 80% W`.
- Antigravity taskbar windows are ordered `session`, then `weekly`; Codex uses `weekly`, falling back to `session` and then the first available window.
- Status indicators and existing quota severity colors remain visible.
- Extra windows remain available to Dashboard and context-menu details.
- Horizontal taskbar overlay width must not exceed 400 px.

---

### Task 1: Taskbar Window Selection

**Files:**
- Modify: `ui_models.py`
- Test: `tests/test_ui_models.py`

**Interfaces:**
- Consumes: `ProviderView.windows: tuple[WindowView, ...]` and `ProviderView.provider_id: str`
- Produces: `taskbar_windows(provider: ProviderView) -> tuple[WindowView, ...]`

- [ ] **Step 1: Write failing selector tests**

```python
def test_taskbar_windows_select_agy_session_and_weekly_without_mutating_details():
    provider = build_provider_view(_provider(provider_id="agy", display_name="Antigravity", windows={
        "3p_weekly": _window("3P", 70), "weekly": _window("Weekly", 80), "session": _window("5H", 90)
    }), NOW)
    assert [window.window_id for window in taskbar_windows(provider)] == ["session", "weekly"]
    assert [window.window_id for window in provider.windows] == ["session", "weekly", "3p_weekly"]

def test_taskbar_windows_select_codex_weekly_only_with_fallbacks():
    weekly = build_provider_view(_provider(windows={"session": _window("5H", 90), "weekly": _window("Weekly", 80)}), NOW)
    session = build_provider_view(_provider(windows={"session": _window("5H", 90)}), NOW)
    extra = build_provider_view(_provider(windows={"monthly": _window("Monthly", 70)}), NOW)
    assert [window.window_id for window in taskbar_windows(weekly)] == ["weekly"]
    assert [window.window_id for window in taskbar_windows(session)] == ["session"]
    assert [window.window_id for window in taskbar_windows(extra)] == ["monthly"]
```

- [ ] **Step 2: Verify tests fail for the missing selector**

Run: `.\.venv\Scripts\python.exe -m pytest tests\test_ui_models.py -q`

Expected: collection fails because `taskbar_windows` cannot be imported.

- [ ] **Step 3: Add the pure selector**

```python
def taskbar_windows(provider: ProviderView) -> tuple[WindowView, ...]:
    by_id = {window.window_id: window for window in provider.windows}
    if provider.provider_id == "agy":
        return tuple(by_id[window_id] for window_id in ("session", "weekly") if window_id in by_id)
    if provider.provider_id == "codex":
        for window_id in ("weekly", "session"):
            if window_id in by_id:
                return (by_id[window_id],)
        return provider.windows[:1]
    return ()
```

- [ ] **Step 4: Run focused tests**

Run: `.\.venv\Scripts\python.exe -m pytest tests\test_ui_models.py -q`

Expected: all tests in the file pass.

- [ ] **Step 5: Commit the selector and tests**

```powershell
git add -- ui_models.py tests/test_ui_models.py
git commit -m "feat: select compact taskbar quotas"
```

### Task 2: Native Taskbar Rendering

**Files:**
- Modify: `taskbar_widget.py`
- Test: `tests/test_ui_models.py`

**Interfaces:**
- Consumes: `taskbar_windows(provider: ProviderView) -> tuple[WindowView, ...]`
- Produces: native overlay text using only selected windows and a 400 px horizontal width cap

- [ ] **Step 1: Import and use the selector in `_paint`**

```python
from ui_models import context_detail_lines, taskbar_windows

windows = taskbar_windows(provider)
if not windows:
    # render the unavailable em dash
for window_index, window in enumerate(windows):
    # retain existing percentage, label and severity rendering
    if window_index < len(windows) - 1:
        # render separator
```

- [ ] **Step 2: Cap the horizontal overlay width**

```python
configured_width = int(_runtime.settings.display.get("width", 460))
width = min(configured_width, 400, max(240, taskbar_width - 300))
```

- [ ] **Step 3: Run the complete automated suite and compile check**

Run: `.\.venv\Scripts\python.exe -m pytest -q`

Expected: all tests pass.

Run: `.\.venv\Scripts\python.exe -m compileall -q .`

Expected: exit code 0.

- [ ] **Step 4: Commit the painter change**

```powershell
git add -- taskbar_widget.py
git commit -m "fix: keep taskbar quota display compact"
```

### Task 3: Package and Runtime Verification

**Files:**
- Rebuild: `dist/AIUsageTracker/AIUsageTracker.exe`

**Interfaces:**
- Consumes: committed compact selector and painter
- Produces: verified packaged Windows application running from the rebuilt artifact

- [ ] **Step 1: Stop only the currently packaged tracker process**

Resolve `dist\AIUsageTracker\AIUsageTracker.exe`, list processes whose executable path exactly equals it, and stop only those exact PIDs before PyInstaller replaces the directory.

- [ ] **Step 2: Build the package**

Run: `.\build.ps1`

Expected: tests pass and the script prints the expected executable path.

- [ ] **Step 3: Smoke-test and restart the package**

Start the rebuilt executable hidden, verify a live process has an executable path equal to the rebuilt artifact, and leave that instance running for the user.

- [ ] **Step 4: Perform final repository checks**

Run: `.\.venv\Scripts\python.exe -m pytest -q`

Expected: all tests pass.

Run: `git diff --check` and `git status --short`

Expected: no whitespace errors and no unintended source changes.
