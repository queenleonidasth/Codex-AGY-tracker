# Independent Taskbar Overlay Design

## Goal

Make Q-Tracker independent from the Windows taskbar window's ownership and Z-order while continuing to use taskbar geometry and effective visibility as the source of truth for positioning and show/hide behavior.

## Root cause

The original popup was owned by Shell_TrayWnd, and fullscreen detection also misclassified the desktop shell. Those issues are already fixed by making the popup independent and excluding Progman and WorkerW. The remaining interaction bug occurs when clicking the taskbar: Windows temporarily moves Shell_TrayWnd above the still-visible Q-Tracker popup. Relative Z-order is currently repaired only by the configurable data timer, normally every 1,000 milliseconds, so Q-Tracker appears to disappear until the next data tick even though it was never hidden.

## Window ownership and Z-order

- Create the Q-Tracker popup with no owner handle.
- Add WS_EX_TOPMOST at creation so normal foreground-window activation cannot place the overlay behind another taskbar-area window.
- Keep WS_EX_TOOLWINDOW, WS_EX_NOACTIVATE, and WS_EX_LAYERED so the overlay stays out of Alt+Tab, does not take focus, and retains transparent rendering.
- Keep the topmost extended style at creation, subscribe to `EVENT_SYSTEM_FOREGROUND`, and repair relative Z-order immediately when Windows activates a taskbar/shell surface. If Shell_TrayWnd is above Q-Tracker, raise Q-Tracker with SetWindowPos(HWND_TOPMOST) using SWP_NOMOVE, SWP_NOSIZE, and SWP_NOACTIVATE. If Q-Tracker is already above the taskbar, make no SetWindowPos call.
- Keep the 10-millisecond shell-state timer as a fallback for Explorer reorder events that do not emit a foreground notification. The event hook is the primary path so a taskbar click does not expose an occluded frame.
- Continue using Shell_TrayWnd only to calculate the existing 230-pixel right reserve and taskbar-relative rectangle.

## Timer responsibilities and interaction latency

- Keep the existing configurable data timer, normally 1,000 milliseconds, for loading persisted quota state and rebuilding the rendered view.
- Add a fixed 10-millisecond shell-state timer for taskbar/fullscreen visibility and relative Z-order fallback only. It must not load quota state or repaint an unchanged view.
- Subscribe to the foreground event with an out-of-context WinEvent hook. When taskbar or Start/Search shell activation occurs, repair Q-Tracker before the next compositor frame whenever Windows delivers the event.
- Clicking the taskbar may temporarily place Shell_TrayWnd above the independent topmost popup. The event hook must repair that order immediately; the shell-state timer remains a safety net.
- Timer messages must be distinguished by their timer IDs so shell-state checks never trigger data refresh work.

## Taskbar state and fullscreen policy

The shell-state timer will calculate an overlay presentation state:

1. If Shell_TrayWnd is missing or not visible, hide the overlay.
2. If the foreground window is a Windows shell surface (desktop classes Progman/WorkerW or shell processes such as explorer.exe, SearchHost.exe, StartMenuExperienceHost.exe, and ShellExperienceHost.exe), treat it as normal shell activity and show the overlay.
3. If a visible, non-iconic foreground application on the taskbar monitor covers the full monitor within the existing two-pixel tolerance, hide the overlay.
4. Otherwise show the overlay.
5. If a transient Win32 read prevents a confident result, preserve the last confirmed visibility state and retry on the next shell-state timer tick.

A normally maximized window still ends at the work-area boundary and keeps Q-Tracker visible. Fullscreen and borderless fullscreen continue hiding it.

## Explorer lifecycle

Because Q-Tracker is no longer owned by Shell_TrayWnd, an Explorer/taskbar restart does not destroy or reorder the overlay as an owned popup. While the taskbar handle is missing the overlay hides. When TaskbarCreated or the timer observes a valid taskbar again, Q-Tracker recalculates its position and shows without activation.

Initial creation still waits for valid taskbar geometry so the standalone overlay never flashes at 0,0.

## Tests

Regression tests will prove:

- Popup creation includes WS_EX_TOPMOST and passes no owner.
- The desktop shell classes Progman and WorkerW never count as fullscreen.
- A normal application covering the monitor still counts as fullscreen.
- Missing or invisible taskbar state hides the overlay once.
- Restored taskbar state repositions and shows the overlay with SW_SHOWNOACTIVATE.
- Repeated timer ticks do not issue redundant show/hide or positioning calls.
- A taskbar above the visible overlay triggers one non-activating Z-order repair, while an already-correct order triggers no repair.
- The 10-millisecond shell-state timer performs fallback visibility and Z-order synchronization without loading quota state.
- The configurable data timer continues loading quota state without duplicating shell-state work.
- The foreground WinEvent hook repairs taskbar overlap without waiting for the fallback timer and is unhooked when the overlay closes.
- Windows shell processes used by Start/Search never count as fullscreen applications.
- Existing 230-pixel positioning, Maximize, borderless fullscreen, zero-geometry, and Explorer retry tests continue passing.

The full test suite, PyInstaller build, and packaged smoke tests will verify owner is zero, topmost is enabled, Desktop and Start/Search clicks keep the overlay visible without a visible occlusion interval, taskbar clicks are repaired by the foreground event path with the timer as fallback, Maximize keeps it visible, and borderless fullscreen hides and restores it.

## Scope

This change does not register an AppBar, reserve desktop work area, change taskbar auto-hide settings, add multi-taskbar support, or change quota, dashboard, tray, refresh, and rendering behavior.
