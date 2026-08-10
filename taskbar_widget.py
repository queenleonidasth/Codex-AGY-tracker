"""Small native Windows taskbar overlay backed only by persisted tracker state.

Provider I/O is owned by :mod:`usage_service`; this window merely repaints when
the state fingerprint changes.  Keeping those concerns separate avoids the old
20 Hz top-most loop and overlapping network requests.
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wintypes
from dataclasses import dataclass
from typing import Any, Callable, Optional

from settings import Settings
from state_store import AtomicStateStore
from ui_models import (
    TrackerView,
    build_tracker_view,
    context_detail_lines,
    taskbar_overlay_width,
    taskbar_windows,
)


HANDLE = ctypes.c_void_p
HWND = ctypes.c_void_p
HDC = ctypes.c_void_p
HFONT = ctypes.c_void_p
ATOM = ctypes.c_ushort
BOOL = ctypes.c_int
UINT = ctypes.c_uint
INT = ctypes.c_int
DWORD = ctypes.c_uint
WPARAM = ctypes.c_size_t
LPARAM = ctypes.c_ssize_t
LRESULT = ctypes.c_ssize_t
WNDPROC = ctypes.WINFUNCTYPE(LRESULT, HWND, UINT, WPARAM, LPARAM)

WS_VISIBLE = 0x10000000
WS_POPUP = 0x80000000
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_LAYERED = 0x00080000
WS_EX_TOPMOST = 0x00000008
WS_EX_NOACTIVATE = 0x08000000

WM_DESTROY = 0x0002
WM_PAINT = 0x000F
WM_CLOSE = 0x0010
WM_ERASEBKGND = 0x0014
WM_SETTINGCHANGE = 0x001A
WM_DISPLAYCHANGE = 0x007E
WM_TIMER = 0x0113
WM_RBUTTONDOWN = 0x0204
WM_LBUTTONDBLCLK = 0x0203
WM_DPICHANGED = 0x02E0

CS_HREDRAW = 0x0002
CS_VREDRAW = 0x0001
CS_DBLCLKS = 0x0008
IDC_ARROW = 32512
BK_TRANSPARENT = 1
DT_SINGLELINE = 0x0020
DT_VCENTER = 0x0004
DT_LEFT = 0x0000
DT_NOCLIP = 0x0100
SWP_NOACTIVATE = 0x0010
SWP_NOZORDER = 0x0004
LWA_COLORKEY = 0x00000001
TPM_RETURNCMD = 0x0100
MF_STRING = 0x0000
MF_SEPARATOR = 0x0800
MF_GRAYED = 0x0001
FW_BOLD = 700
DEFAULT_CHARSET = 1
ANTIALIASED_QUALITY = 4
COLORKEY_RGB = 0x00010101
u32 = ctypes.windll.user32
g32 = ctypes.windll.gdi32
k32 = ctypes.windll.kernel32

k32.GetModuleHandleW.argtypes = [ctypes.c_wchar_p]
k32.GetModuleHandleW.restype = HANDLE
u32.FindWindowW.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p]
u32.FindWindowW.restype = HANDLE
u32.GetWindowRect.argtypes = [HANDLE, ctypes.POINTER(wintypes.RECT)]
u32.GetWindowRect.restype = BOOL
u32.GetClientRect.argtypes = [HANDLE, ctypes.POINTER(wintypes.RECT)]
u32.GetClientRect.restype = BOOL
u32.RegisterClassExW.argtypes = [ctypes.c_void_p]
u32.RegisterClassExW.restype = ATOM
u32.CreateWindowExW.argtypes = [DWORD, ctypes.c_wchar_p, ctypes.c_wchar_p, DWORD, INT, INT, INT, INT, HANDLE, HANDLE, HANDLE, ctypes.c_void_p]
u32.CreateWindowExW.restype = HANDLE
u32.ShowWindow.argtypes = [HANDLE, INT]
u32.ShowWindow.restype = BOOL
u32.UpdateWindow.argtypes = [HANDLE]
u32.UpdateWindow.restype = BOOL
u32.DestroyWindow.argtypes = [HANDLE]
u32.DestroyWindow.restype = BOOL
u32.PostQuitMessage.argtypes = [INT]
u32.PostQuitMessage.restype = None
u32.DefWindowProcW.argtypes = [HANDLE, UINT, WPARAM, LPARAM]
u32.DefWindowProcW.restype = LRESULT
u32.SetTimer.argtypes = [HANDLE, ctypes.c_size_t, UINT, ctypes.c_void_p]
u32.SetTimer.restype = ctypes.c_size_t
u32.KillTimer.argtypes = [HANDLE, ctypes.c_size_t]
u32.KillTimer.restype = BOOL
u32.InvalidateRect.argtypes = [HANDLE, ctypes.c_void_p, BOOL]
u32.InvalidateRect.restype = BOOL
u32.BeginPaint.argtypes = [HANDLE, ctypes.c_void_p]
u32.BeginPaint.restype = HDC
u32.EndPaint.argtypes = [HANDLE, ctypes.c_void_p]
u32.EndPaint.restype = BOOL
u32.FillRect.argtypes = [HDC, ctypes.POINTER(wintypes.RECT), HANDLE]
u32.FillRect.restype = INT
u32.DrawTextW.argtypes = [HDC, ctypes.c_wchar_p, INT, ctypes.POINTER(wintypes.RECT), UINT]
u32.DrawTextW.restype = INT
u32.SetLayeredWindowAttributes.argtypes = [HANDLE, ctypes.c_uint, ctypes.c_byte, DWORD]
u32.SetLayeredWindowAttributes.restype = BOOL
u32.SetWindowPos.argtypes = [HANDLE, HANDLE, INT, INT, INT, INT, UINT]
u32.SetWindowPos.restype = BOOL
u32.LoadCursorW.argtypes = [HANDLE, ctypes.c_void_p]
u32.LoadCursorW.restype = HANDLE
u32.GetMessageW.argtypes = [ctypes.c_void_p, HANDLE, UINT, UINT]
u32.GetMessageW.restype = INT
u32.TranslateMessage.argtypes = [ctypes.c_void_p]
u32.TranslateMessage.restype = BOOL
u32.DispatchMessageW.argtypes = [ctypes.c_void_p]
u32.DispatchMessageW.restype = LRESULT
u32.PostMessageW.argtypes = [HANDLE, UINT, WPARAM, LPARAM]
u32.PostMessageW.restype = BOOL
u32.CreatePopupMenu.argtypes = []
u32.CreatePopupMenu.restype = HANDLE
u32.AppendMenuW.argtypes = [HANDLE, UINT, ctypes.c_size_t, ctypes.c_wchar_p]
u32.AppendMenuW.restype = BOOL
u32.TrackPopupMenu.argtypes = [HANDLE, UINT, INT, INT, INT, HANDLE, ctypes.c_void_p]
u32.TrackPopupMenu.restype = INT
u32.DestroyMenu.argtypes = [HANDLE]
u32.DestroyMenu.restype = BOOL
u32.GetCursorPos.argtypes = [ctypes.POINTER(wintypes.POINT)]
u32.GetCursorPos.restype = BOOL
u32.SetForegroundWindow.argtypes = [HANDLE]
u32.SetForegroundWindow.restype = BOOL

g32.CreateSolidBrush.argtypes = [ctypes.c_uint]
g32.CreateSolidBrush.restype = HANDLE
g32.CreateFontW.argtypes = [INT, INT, INT, INT, INT, DWORD, DWORD, DWORD, DWORD, DWORD, DWORD, DWORD, DWORD, ctypes.c_wchar_p]
g32.CreateFontW.restype = HANDLE
g32.SelectObject.argtypes = [HDC, HANDLE]
g32.SelectObject.restype = HANDLE
g32.DeleteObject.argtypes = [HANDLE]
g32.DeleteObject.restype = BOOL
g32.SetBkMode.argtypes = [HDC, INT]
g32.SetBkMode.restype = INT
g32.SetTextColor.argtypes = [HDC, ctypes.c_uint]
g32.SetTextColor.restype = ctypes.c_uint
g32.GetTextExtentPoint32W.argtypes = [HDC, ctypes.c_wchar_p, INT, ctypes.POINTER(wintypes.SIZE)]
g32.GetTextExtentPoint32W.restype = BOOL
g32.CreateCompatibleDC.argtypes = [HDC]
g32.CreateCompatibleDC.restype = HDC
g32.CreateCompatibleBitmap.argtypes = [HDC, INT, INT]
g32.CreateCompatibleBitmap.restype = HANDLE
g32.BitBlt.argtypes = [HDC, INT, INT, INT, INT, HDC, INT, INT, DWORD]
g32.BitBlt.restype = BOOL
g32.DeleteDC.argtypes = [HDC]
g32.DeleteDC.restype = BOOL


class WNDCLASSEX(ctypes.Structure):
    _fields_ = [
        ("cbSize", UINT), ("style", UINT), ("lpfnWndProc", WNDPROC),
        ("cbClsExtra", INT), ("cbWndExtra", INT), ("hInstance", HANDLE),
        ("hIcon", HANDLE), ("hCursor", HANDLE), ("hbrBackground", HANDLE),
        ("lpszMenuName", ctypes.c_wchar_p), ("lpszClassName", ctypes.c_wchar_p),
        ("hIconSm", HANDLE),
    ]


class PAINTSTRUCT(ctypes.Structure):
    _fields_ = [
        ("hdc", HDC), ("fErase", BOOL), ("rcPaint", wintypes.RECT),
        ("fRestore", BOOL), ("fIncUpdate", BOOL), ("rgbReserved", ctypes.c_byte * 32),
    ]


def rgb(value: Any) -> int:
    """Convert a CSS hex color or RGB tuple into a Win32 COLORREF."""
    if isinstance(value, str) and len(value.lstrip("#")) == 6:
        value = value.lstrip("#")
        red, green, blue = int(value[:2], 16), int(value[2:4], 16), int(value[4:], 16)
    elif isinstance(value, (tuple, list)) and len(value) >= 3:
        red, green, blue = (int(value[index]) for index in range(3))
    else:
        red, green, blue = 255, 255, 255
    return red | (green << 8) | (blue << 16)


class FontCache:
    def __init__(self) -> None:
        self.handle: Optional[HANDLE] = None
        self.key: Optional[tuple[str, int]] = None

    def get(self, name: str, size: int) -> HANDLE:
        key = (name, size)
        if self.handle is None or self.key != key:
            self.cleanup()
            self.handle = g32.CreateFontW(size, 0, 0, 0, FW_BOLD, 0, 0, 0, DEFAULT_CHARSET, 0, 0, ANTIALIASED_QUALITY, 0, name)
            self.key = key
        return self.handle

    def cleanup(self) -> None:
        if self.handle:
            g32.DeleteObject(self.handle)
            self.handle = None
            self.key = None


@dataclass
class _Runtime:
    store: AtomicStateStore
    settings: Settings
    on_open: Callable[[], Any]
    on_refresh: Callable[[], Any]
    view: TrackerView
    hwnd: Optional[HWND] = None
    ticks: int = 0


_runtime: Optional[_Runtime] = None
_wndproc_ref: Optional[WNDPROC] = None
_background_brush: Optional[HANDLE] = None
_font_cache = FontCache()


def request_close() -> None:
    """Ask the UI thread to close; safe to call from the tray thread."""
    if _runtime is not None and _runtime.hwnd:
        u32.PostMessageW(_runtime.hwnd, WM_CLOSE, 0, 0)


def _reposition(hwnd: HWND) -> None:
    if _runtime is None:
        return
    taskbar = u32.FindWindowW("Shell_TrayWnd", None)
    bounds = wintypes.RECT()
    if not taskbar or not u32.GetWindowRect(taskbar, ctypes.byref(bounds)):
        return
    taskbar_width = bounds.right - bounds.left
    taskbar_height = bounds.bottom - bounds.top
    width = taskbar_overlay_width(
        int(_runtime.settings.display.get("width", 460)),
        taskbar_width,
    )
    if taskbar_width >= taskbar_height:
        height = taskbar_height
        x = max(bounds.left, bounds.right - width - 230)
        y = bounds.top
    else:
        width = taskbar_width
        height = min(180, max(60, taskbar_height - 150))
        x = bounds.left
        y = bounds.bottom - height - 100
    u32.SetWindowPos(hwnd, None, x, y, width, height, SWP_NOZORDER | SWP_NOACTIVATE)


def _draw_text(hdc: HDC, text: str, x: int, height: int) -> int:
    rectangle = wintypes.RECT(x, 0, x + 600, height)
    u32.DrawTextW(hdc, text, -1, ctypes.byref(rectangle), DT_SINGLELINE | DT_VCENTER | DT_LEFT | DT_NOCLIP)
    size = wintypes.SIZE()
    g32.GetTextExtentPoint32W(hdc, text, len(text), ctypes.byref(size))
    return x + size.cx


def _paint(hwnd: HWND) -> None:
    if _runtime is None:
        return
    paint = PAINTSTRUCT()
    hdc = u32.BeginPaint(hwnd, ctypes.byref(paint))
    if not hdc:
        return
    rectangle = wintypes.RECT()
    u32.GetClientRect(hwnd, ctypes.byref(rectangle))
    width, height = max(1, rectangle.right), max(1, rectangle.bottom)
    memory_dc = g32.CreateCompatibleDC(hdc)
    bitmap = g32.CreateCompatibleBitmap(hdc, width, height)
    old_bitmap = g32.SelectObject(memory_dc, bitmap)
    brush = g32.CreateSolidBrush(COLORKEY_RGB)
    u32.FillRect(memory_dc, ctypes.byref(rectangle), brush)
    g32.DeleteObject(brush)
    g32.SetBkMode(memory_dc, BK_TRANSPARENT)
    font = _font_cache.get(
        str(_runtime.settings.display.get("font_name", "Segoe UI Variable Display")),
        int(_runtime.settings.display.get("font_size", 18)),
    )
    old_font = g32.SelectObject(memory_dc, font)

    x = 10
    providers = _runtime.view.providers
    if not providers:
        g32.SetTextColor(memory_dc, rgb((170, 178, 195)))
        _draw_text(memory_dc, "AI Usage — waiting for data", x, height)
    for provider_index, provider in enumerate(providers):
        style = _runtime.settings.provider_styles.get(provider.provider_id, {})
        g32.SetTextColor(memory_dc, rgb(style.get("color", "#6CB6FF")))
        x = _draw_text(memory_dc, provider.display_name, x, height) + 6
        if provider.indicator:
            g32.SetTextColor(memory_dc, rgb("#FFB454" if provider.status == "stale" else "#FF6B6B"))
            x = _draw_text(memory_dc, provider.indicator, x, height) + 5
        windows = taskbar_windows(provider)
        if not windows:
            g32.SetTextColor(memory_dc, rgb((170, 178, 195)))
            x = _draw_text(memory_dc, "—", x, height)
        for window_index, window in enumerate(windows):
            color = "#FF6B6B" if window.severity == "critical" else "#FFB454" if window.severity == "warning" else "#D4D9E5"
            g32.SetTextColor(memory_dc, rgb(color))
            x = _draw_text(memory_dc, f"{window.remaining_percent:.0f}%", x, height)
            g32.SetTextColor(memory_dc, rgb((125, 132, 150)))
            x = _draw_text(memory_dc, window.short_label, x, height) + 5
            if window_index < len(windows) - 1:
                x = _draw_text(memory_dc, "·", x, height) + 5
        if provider_index < len(providers) - 1:
            g32.SetTextColor(memory_dc, rgb((95, 103, 123)))
            x = _draw_text(memory_dc, " | ", x + 5, height) + 8

    g32.SelectObject(memory_dc, old_font)
    g32.BitBlt(hdc, 0, 0, width, height, memory_dc, 0, 0, 0x00CC0020)
    g32.SelectObject(memory_dc, old_bitmap)
    g32.DeleteObject(bitmap)
    g32.DeleteDC(memory_dc)
    u32.EndPaint(hwnd, ctypes.byref(paint))


def _show_menu(hwnd: HWND) -> None:
    if _runtime is None:
        return
    menu = u32.CreatePopupMenu()
    try:
        u32.AppendMenuW(menu, MF_STRING, 1, "Open dashboard")
        u32.AppendMenuW(menu, MF_STRING, 2, "Refresh now")
        u32.AppendMenuW(menu, MF_SEPARATOR, 0, None)
        for detail in context_detail_lines(_runtime.view):
            u32.AppendMenuW(menu, MF_STRING | MF_GRAYED, 0, detail[:160])
        u32.AppendMenuW(menu, MF_SEPARATOR, 0, None)
        u32.AppendMenuW(menu, MF_STRING, 9, "Exit")
        point = wintypes.POINT()
        u32.GetCursorPos(ctypes.byref(point))
        u32.SetForegroundWindow(hwnd)
        command = u32.TrackPopupMenu(menu, TPM_RETURNCMD, point.x, point.y, 0, hwnd, None)
    finally:
        u32.DestroyMenu(menu)
    if command == 1:
        _runtime.on_open()
    elif command == 2:
        _runtime.on_refresh()
    elif command == 9:
        u32.PostMessageW(hwnd, WM_CLOSE, 0, 0)


def _wnd_proc(hwnd: HWND, message: int, wparam: int, lparam: int) -> int:
    if _runtime is None:
        return u32.DefWindowProcW(hwnd, message, wparam, lparam)
    try:
        if message == WM_TIMER:
            _runtime.ticks += 1
            view = build_tracker_view(_runtime.store.load(), _runtime.settings.enabled_providers)
            if view.fingerprint != _runtime.view.fingerprint:
                _runtime.view = view
                u32.InvalidateRect(hwnd, None, 0)
            return 0
        if message == WM_PAINT:
            _paint(hwnd)
            return 0
        if message == WM_ERASEBKGND:
            return 1
        if message in (WM_DISPLAYCHANGE, WM_SETTINGCHANGE, WM_DPICHANGED):
            _reposition(hwnd)
            return 0
        if message == WM_LBUTTONDBLCLK:
            _runtime.on_open()
            return 0
        if message == WM_RBUTTONDOWN:
            _show_menu(hwnd)
            return 0
        if message == WM_CLOSE:
            u32.KillTimer(hwnd, 1)
            u32.DestroyWindow(hwnd)
            return 0
        if message == WM_DESTROY:
            _font_cache.cleanup()
            u32.PostQuitMessage(0)
            return 0
    except Exception:
        # UI callback failures must not tear down Explorer's taskbar overlay.
        return u32.DefWindowProcW(hwnd, message, wparam, lparam)
    return u32.DefWindowProcW(hwnd, message, wparam, lparam)


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


def _create_window() -> bool:
    global _wndproc_ref, _background_brush
    if _runtime is None:
        return False
    taskbar = u32.FindWindowW("Shell_TrayWnd", None)
    if not taskbar:
        return False
    instance = k32.GetModuleHandleW(None)
    class_name = "AIUsageTrackerTaskbarV1"
    _wndproc_ref = WNDPROC(_wnd_proc)
    _background_brush = g32.CreateSolidBrush(COLORKEY_RGB)
    window_class = WNDCLASSEX()
    window_class.cbSize = ctypes.sizeof(WNDCLASSEX)
    window_class.style = CS_HREDRAW | CS_VREDRAW | CS_DBLCLKS
    window_class.lpfnWndProc = _wndproc_ref
    window_class.hInstance = instance
    window_class.hCursor = u32.LoadCursorW(None, IDC_ARROW)
    window_class.hbrBackground = _background_brush
    window_class.lpszClassName = class_name
    if not u32.RegisterClassExW(ctypes.byref(window_class)):
        return False
    _runtime.hwnd = _create_taskbar_popup(
        instance,
        class_name,
        taskbar,
        int(_runtime.settings.display.get("width", 460)),
    )
    if not _runtime.hwnd:
        return False
    u32.SetLayeredWindowAttributes(_runtime.hwnd, COLORKEY_RGB, 0, LWA_COLORKEY)
    _reposition(_runtime.hwnd)
    u32.SetTimer(
        _runtime.hwnd,
        1,
        int(_runtime.settings.display.get("update_interval_ms", 1_000)),
        None,
    )
    u32.ShowWindow(_runtime.hwnd, 5)
    u32.UpdateWindow(_runtime.hwnd)
    return True


def run_taskbar(
    store: AtomicStateStore,
    settings: Settings,
    on_open: Callable[[], Any],
    on_refresh: Callable[[], Any],
) -> int:
    """Run the native taskbar message loop on the calling thread."""
    global _runtime, _background_brush
    _runtime = _Runtime(
        store=store,
        settings=settings,
        on_open=on_open,
        on_refresh=on_refresh,
        view=build_tracker_view(store.load(), settings.enabled_providers),
    )
    try:
        if not _create_window():
            return 1
        message = wintypes.MSG()
        while True:
            result = u32.GetMessageW(ctypes.byref(message), None, 0, 0)
            if result <= 0:
                break
            u32.TranslateMessage(ctypes.byref(message))
            u32.DispatchMessageW(ctypes.byref(message))
        return 0
    finally:
        _font_cache.cleanup()
        if _background_brush:
            g32.DeleteObject(_background_brush)
            _background_brush = None
        _runtime = None


if __name__ == "__main__":
    from app import main

    raise SystemExit(main([]))
