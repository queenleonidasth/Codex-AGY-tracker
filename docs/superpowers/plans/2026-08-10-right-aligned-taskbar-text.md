# Right-Aligned Taskbar Text Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Right-align the compact quota text inside the existing 400 px overlay with a 12 px visual margin from its right edge.

**Architecture:** Convert the current imperative painter into a small render-segment pipeline: build the exact text/color/gap segments, measure them with the selected GDI font, compute one right-aligned start coordinate, then draw the measured segments. Window geometry, ownership and repaint policy remain untouched.

**Tech Stack:** Python 3.13, pytest, ctypes/Win32 GDI, PyInstaller, PowerShell

## Global Constraints

- Horizontal start is `max(10, client_width - content_width - 12)`.
- Waiting text uses the same right-alignment rule.
- Existing text, colors, severity indicators, separators and compact provider selection remain unchanged.
- Overlay width, 230 px taskbar reserve, owner relationship, Z-order, timer and non-erasing repaint remain unchanged.

---

### Task 1: Measured Render Segments

**Files:**
- Modify: `taskbar_widget.py:210-330`
- Modify: `tests/test_taskbar_widget.py`

**Interfaces:**
- Consumes: `TrackerView`, provider styles, and `taskbar_windows(provider)`
- Produces: `RenderSegment(text: str, color: int, gap_after: int)`
- Produces: `_render_segments(view: TrackerView, provider_styles: dict[str, dict[str, object]]) -> tuple[RenderSegment, ...]`
- Produces: `_right_aligned_start(client_width: int, content_width: int) -> int`

- [ ] **Step 1: Add failing pure layout tests**

```python
def test_right_aligned_start_keeps_twelve_pixel_margin():
    assert widget._right_aligned_start(client_width=400, content_width=320) == 68


def test_right_aligned_start_falls_back_to_left_margin_for_overflow():
    assert widget._right_aligned_start(client_width=400, content_width=410) == 10
```

- [ ] **Step 2: Add failing render-segment test**

```python
from ui_models import ProviderView, WindowView


def _window(window_id: str, label: str, remaining: float) -> WindowView:
    return WindowView(window_id, label, label, remaining, 100 - remaining, None, "—", "normal")


def _provider(provider_id: str, name: str, windows: tuple[WindowView, ...]) -> ProviderView:
    return ProviderView(provider_id, name, "ok", "", name, windows, "test", None, None, "now", "test", "")


def test_render_segments_preserve_compact_provider_text_order():
    view = TrackerView(
        providers=(
            _provider("agy", "Antigravity", (_window("session", "5H", 91), _window("weekly", "W", 94))),
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
        "Antigravity", "91%", "5H", "·", "94%", "W", " | ", "Codex", "46%", "W"
    ]
    assert segments[-1].gap_after == 0
```

- [ ] **Step 3: Run focused tests and verify RED**

Run: `.\.venv\Scripts\python.exe -m pytest tests\test_taskbar_widget.py -q`

Expected: tests fail because `_right_aligned_start` and `_render_segments` do not exist.

- [ ] **Step 4: Implement segment construction and layout**

```python
@dataclass(frozen=True, slots=True)
class RenderSegment:
    text: str
    color: int
    gap_after: int = 0


def _right_aligned_start(client_width: int, content_width: int) -> int:
    return max(10, client_width - content_width - 12)


def _render_segments(
    view: TrackerView,
    provider_styles: dict[str, dict[str, object]],
) -> tuple[RenderSegment, ...]:
    if not view.providers:
        return (RenderSegment("AI Usage — waiting for data", rgb((170, 178, 195))),)

    segments: list[RenderSegment] = []
    for provider_index, provider in enumerate(view.providers):
        has_next_provider = provider_index < len(view.providers) - 1
        style = provider_styles.get(provider.provider_id, {})
        segments.append(RenderSegment(provider.display_name, rgb(style.get("color", "#6CB6FF")), 6))
        if provider.indicator:
            indicator_color = "#FFB454" if provider.status == "stale" else "#FF6B6B"
            segments.append(RenderSegment(provider.indicator, rgb(indicator_color), 5))
        windows = taskbar_windows(provider)
        if not windows:
            segments.append(RenderSegment("—", rgb((170, 178, 195)), 5 if has_next_provider else 0))
        for window_index, window in enumerate(windows):
            has_next_window = window_index < len(windows) - 1
            quota_color = "#FF6B6B" if window.severity == "critical" else "#FFB454" if window.severity == "warning" else "#D4D9E5"
            segments.append(RenderSegment(f"{window.remaining_percent:.0f}%", rgb(quota_color)))
            label_gap = 5 if has_next_window else 10 if has_next_provider else 0
            segments.append(RenderSegment(window.short_label, rgb((125, 132, 150)), label_gap))
            if has_next_window:
                segments.append(RenderSegment("·", rgb((125, 132, 150)), 5))
        if has_next_provider:
            segments.append(RenderSegment(" | ", rgb((95, 103, 123)), 8))
    return tuple(segments)
```

- [ ] **Step 5: Measure once and draw from the measured segment list**

```python
def _measure_text(hdc: HDC, text: str) -> int:
    size = wintypes.SIZE()
    g32.GetTextExtentPoint32W(hdc, text, len(text), ctypes.byref(size))
    return size.cx


def _draw_text(hdc: HDC, text: str, x: int, height: int) -> None:
    rectangle = wintypes.RECT(x, 0, x + 600, height)
    u32.DrawTextW(hdc, text, -1, ctypes.byref(rectangle), DT_SINGLELINE | DT_VCENTER | DT_LEFT | DT_NOCLIP)


segments = _render_segments(_runtime.view, _runtime.settings.provider_styles)
measured = tuple((segment, _measure_text(memory_dc, segment.text)) for segment in segments)
content_width = sum(text_width + segment.gap_after for segment, text_width in measured)
x = _right_aligned_start(width, content_width)
for segment, text_width in measured:
    g32.SetTextColor(memory_dc, segment.color)
    _draw_text(memory_dc, segment.text, x, height)
    x += text_width + segment.gap_after
```

Remove the old provider/window drawing loop from `_paint`. Keep the existing compatible bitmap, font selection and final `BitBlt` unchanged.

- [ ] **Step 6: Run focused and complete verification**

Run: `.\.venv\Scripts\python.exe -m pytest tests\test_taskbar_widget.py -q`

Expected: all taskbar widget tests pass.

Run: `.\.venv\Scripts\python.exe -m pytest -q`

Expected: the complete suite passes.

Run: `.\.venv\Scripts\python.exe -m compileall -q .`

Expected: exit code 0.

- [ ] **Step 7: Commit the layout change**

```powershell
git add -- taskbar_widget.py tests/test_taskbar_widget.py
git commit -m "fix: align taskbar quota text to the right"
```

### Task 2: Package and Runtime Verification

**Files:**
- Rebuild: `dist/AIUsageTracker/AIUsageTracker.exe`

**Interfaces:**
- Consumes: committed measured-segment painter
- Produces: one running packaged tracker with unchanged taskbar ownership

- [ ] **Step 1: Stop only the exact packaged process and run `build.ps1`**

Resolve `dist\AIUsageTracker\AIUsageTracker.exe`, stop only matching `AIUsageTracker` PIDs, then run `.\build.ps1` and require exit code 0.

- [ ] **Step 2: Start and verify the rebuilt artifact**

Start the executable hidden, poll for at most 10 seconds, and assert exactly one process path equals the rebuilt artifact.

- [ ] **Step 3: Verify taskbar ownership remains intact**

Enumerate top-level windows until class `AIUsageTrackerTaskbarV1` appears, assert `GW_OWNER` equals `Shell_TrayWnd`, activate the taskbar, wait 250 ms, and assert the overlay remains visible with the same owner.

- [ ] **Step 4: Perform final checks**

Run full pytest, compileall, `git diff --check`, and `git status --short`. Require zero test failures, exit code 0, no whitespace errors and a clean worktree.
