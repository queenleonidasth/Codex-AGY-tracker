# Stable Taskbar Position and Fullscreen Visibility Design

## Goal

Keep the Q-Tracker overlay at its current taskbar-relative position and hide it whenever a foreground game or video uses true fullscreen or borderless fullscreen. A normally maximized window must continue showing Q-Tracker because the Windows taskbar remains available.

## Current behavior and root causes

The current horizontal placement is derived from the taskbar rectangle, with the overlay's right edge reserved 230 pixels from the taskbar's right edge. On the current 1920 x 1080 display, the taskbar is `0,1032-1920,1080` and the 400 x 48 overlay is `1290,1032-1690,1080`.

Positioning is recalculated after display, settings, DPI, and Explorer taskbar-created messages. Explorer can temporarily expose invalid or changing taskbar geometry during these transitions. Calling `SetWindowPos` with such geometry can move or collapse the overlay. The overlay also has no foreground-fullscreen visibility policy, so its taskbar-owned popup can remain visible after the Windows taskbar is covered.

## Positioning design

- Preserve the existing 230-pixel right-edge reserve for a horizontal taskbar.
- Preserve the existing configured width behavior; the current effective overlay size remains 400 x 48.
- Calculate the desired overlay rectangle in a pure helper so the anchor rules can be tested without Win32 calls.
- Reject taskbar rectangles with non-positive width or height.
- Remember the last applied overlay rectangle and call `SetWindowPos` only when the valid desired rectangle changes.
- Continue recalculating after display, settings, DPI, and Explorer taskbar-created messages so the relative anchor remains correct after legitimate monitor changes.
- Preserve the current vertical-taskbar fallback behavior.

## Fullscreen detection design

On the existing one-second UI timer:

1. Resolve the foreground window with `GetForegroundWindow`.
2. Ignore missing handles, Q-Tracker itself, and the taskbar itself.
3. Resolve the monitor containing the foreground window and the monitor containing the Q-Tracker taskbar. A fullscreen window on another monitor must not hide this overlay.
4. Read the foreground window's DWM extended frame bounds when available. Fall back to `GetWindowRect` if DWM cannot provide valid bounds.
5. Classify the foreground window as fullscreen only when its bounds cover the entire monitor rectangle within a two-pixel tolerance on every edge.

Comparing with the full monitor rectangle, rather than its work area, distinguishes fullscreen from normal maximization. For the current screen, a window ending at y=1032 is maximized and keeps Q-Tracker visible; a window reaching y=1080 is fullscreen and hides it.

## Visibility transitions

- Track whether Q-Tracker was hidden by fullscreen detection.
- Entering fullscreen calls `ShowWindow(..., SW_HIDE)` once.
- Leaving fullscreen first confirms the stable taskbar-relative position, then calls `ShowWindow(..., SW_SHOWNOACTIVATE)` once so Q-Tracker does not steal focus.
- Repeated timer ticks with the same state perform no redundant show/hide or positioning calls.
- Quota refresh and repaint logic continues while the overlay is hidden, allowing current data to appear immediately when it returns.
- If foreground or monitor information cannot be read, preserve the last confirmed visibility state and retry on the next timer tick. An uncertain result must not trigger a show or hide transition.

## Tests

Automated regression tests will cover:

- Horizontal placement remains exactly 230 pixels from the taskbar's right edge.
- Invalid zero-sized taskbar geometry does not move the overlay.
- An unchanged valid rectangle does not call `SetWindowPos` again.
- A normal maximized window that ends above the taskbar is not fullscreen.
- Exact fullscreen and borderless fullscreen are detected.
- Bounds short by up to two pixels are accepted as fullscreen.
- Bounds short by more than two pixels are not fullscreen.
- A fullscreen foreground window on another monitor does not hide the overlay.
- Entering fullscreen hides once; staying fullscreen does not hide repeatedly.
- Leaving fullscreen restores the position and shows without activation once.

The focused taskbar-widget tests and the full pytest suite must pass. A packaged Windows smoke test will verify normal maximize, browser/video fullscreen, and a borderless fullscreen game when available.

## Scope

This change affects only taskbar overlay positioning and fullscreen visibility. It does not change quota data, dashboard behavior, tray behavior, provider refresh, taskbar text content, taskbar auto-hide settings, or multi-taskbar support.
