"""
AI Token Usage - Taskbar Text Widget (Windows 11) Antigravity v2 Optimized
Features: GDI Font Caching, Hash-based Smart Invalidation, SSOT Data Management.
"""

import ctypes
import ctypes.wintypes as wintypes
import sys
import os
import json
import time
import threading
import subprocess
from datetime import date
from pathlib import Path

# Import shared tracker singleton (SSOT Pattern) & auto_fetch module
sys.path.insert(0, os.path.dirname(__file__))
from token_tracker import tracker
import auto_fetch

# --- Win32 Handle Types (Safe 64-bit) ---
HANDLE = ctypes.c_void_p
HWND = ctypes.c_void_p
HDC = ctypes.c_void_p
HBRUSH = ctypes.c_void_p
HFONT = ctypes.c_void_p
HMENU = ctypes.c_void_p
HINSTANCE = ctypes.c_void_p
ATOM = ctypes.c_ushort
COLORREF = ctypes.c_uint
BOOL = ctypes.c_int
UINT = ctypes.c_uint
INT = ctypes.c_int
DWORD = ctypes.c_uint
WPARAM = ctypes.c_size_t
LPARAM = ctypes.c_ssize_t
LRESULT = ctypes.c_ssize_t

WNDPROC = ctypes.WINFUNCTYPE(LRESULT, HWND, UINT, WPARAM, LPARAM)

# Constants
WS_VISIBLE = 0x10000000
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_LAYERED = 0x00080000
WS_EX_TOPMOST = 0x00000008
WS_EX_NOACTIVATE = 0x08000000
WS_POPUP = 0x80000000

WM_PAINT = 0x000F
WM_TIMER = 0x0113
WM_DESTROY = 0x0002
WM_RBUTTONDOWN = 0x0204
WM_LBUTTONDBLCLK = 0x0203
WM_ERASEBKGND = 0x0014
WM_CREATE = 0x0001
WM_CLOSE = 0x0010

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
SWP_NOMOVE = 0x0002
SWP_NOSIZE = 0x0001

LWA_COLORKEY = 0x00000001
TPM_RETURNCMD = 0x0100
MF_STRING = 0x0000
MF_SEPARATOR = 0x0800

FW_BOLD = 700
DEFAULT_CHARSET = 1
NONANTIALIASED_QUALITY = 3
COLORKEY_RGB = 0x00FF00FF

u32 = ctypes.windll.user32
g32 = ctypes.windll.gdi32
k32 = ctypes.windll.kernel32

# Setup argtypes & restype for 64-bit safety
k32.GetModuleHandleW.argtypes = [ctypes.c_wchar_p]; k32.GetModuleHandleW.restype = HANDLE
u32.FindWindowW.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p]; u32.FindWindowW.restype = HANDLE
u32.GetWindowRect.argtypes = [HANDLE, ctypes.POINTER(wintypes.RECT)]; u32.GetWindowRect.restype = BOOL
u32.GetClientRect.argtypes = [HANDLE, ctypes.POINTER(wintypes.RECT)]; u32.GetClientRect.restype = BOOL
u32.RegisterClassExW.argtypes = [ctypes.c_void_p]; u32.RegisterClassExW.restype = ATOM
u32.CreateWindowExW.argtypes = [DWORD, ctypes.c_wchar_p, ctypes.c_wchar_p, DWORD, INT, INT, INT, INT, HANDLE, HANDLE, HANDLE, ctypes.c_void_p]; u32.CreateWindowExW.restype = HANDLE
u32.ShowWindow.argtypes = [HANDLE, INT]; u32.ShowWindow.restype = BOOL
u32.UpdateWindow.argtypes = [HANDLE]; u32.UpdateWindow.restype = BOOL
u32.DestroyWindow.argtypes = [HANDLE]; u32.DestroyWindow.restype = BOOL
u32.PostQuitMessage.argtypes = [INT]; u32.PostQuitMessage.restype = None
u32.DefWindowProcW.argtypes = [HANDLE, UINT, WPARAM, LPARAM]; u32.DefWindowProcW.restype = LRESULT
u32.SetTimer.argtypes = [HANDLE, ctypes.c_size_t, UINT, ctypes.c_void_p]; u32.SetTimer.restype = ctypes.c_size_t
u32.KillTimer.argtypes = [HANDLE, ctypes.c_size_t]; u32.KillTimer.restype = BOOL
u32.InvalidateRect.argtypes = [HANDLE, ctypes.c_void_p, BOOL]; u32.InvalidateRect.restype = BOOL
u32.BeginPaint.argtypes = [HANDLE, ctypes.c_void_p]; u32.BeginPaint.restype = HDC
u32.EndPaint.argtypes = [HANDLE, ctypes.c_void_p]; u32.EndPaint.restype = BOOL
u32.FillRect.argtypes = [HDC, ctypes.POINTER(wintypes.RECT), HANDLE]; u32.FillRect.restype = INT
u32.DrawTextW.argtypes = [HDC, ctypes.c_wchar_p, INT, ctypes.POINTER(wintypes.RECT), UINT]; u32.DrawTextW.restype = INT
u32.SetLayeredWindowAttributes.argtypes = [HANDLE, COLORREF, ctypes.c_byte, DWORD]; u32.SetLayeredWindowAttributes.restype = BOOL
u32.SetWindowPos.argtypes = [HANDLE, HANDLE, INT, INT, INT, INT, UINT]; u32.SetWindowPos.restype = BOOL
u32.LoadCursorW.argtypes = [HANDLE, ctypes.c_void_p]; u32.LoadCursorW.restype = HANDLE
u32.GetMessageW.argtypes = [ctypes.c_void_p, HANDLE, UINT, UINT]; u32.GetMessageW.restype = INT
u32.TranslateMessage.argtypes = [ctypes.c_void_p]; u32.TranslateMessage.restype = BOOL
u32.DispatchMessageW.argtypes = [ctypes.c_void_p]; u32.DispatchMessageW.restype = LRESULT
u32.PostMessageW.argtypes = [HANDLE, UINT, WPARAM, LPARAM]; u32.PostMessageW.restype = BOOL
u32.CreatePopupMenu.argtypes = []; u32.CreatePopupMenu.restype = HANDLE
u32.AppendMenuW.argtypes = [HANDLE, UINT, ctypes.c_size_t, ctypes.c_wchar_p]; u32.AppendMenuW.restype = BOOL
u32.TrackPopupMenu.argtypes = [HANDLE, UINT, INT, INT, INT, HANDLE, ctypes.c_void_p]; u32.TrackPopupMenu.restype = INT
u32.DestroyMenu.argtypes = [HANDLE]; u32.DestroyMenu.restype = BOOL
u32.GetCursorPos.argtypes = [ctypes.POINTER(wintypes.POINT)]; u32.GetCursorPos.restype = BOOL
u32.SetForegroundWindow.argtypes = [HANDLE]; u32.SetForegroundWindow.restype = BOOL

g32.CreateSolidBrush.argtypes = [COLORREF]; g32.CreateSolidBrush.restype = HANDLE
g32.CreateFontW.argtypes = [INT, INT, INT, INT, INT, DWORD, DWORD, DWORD, DWORD, DWORD, DWORD, DWORD, DWORD, ctypes.c_wchar_p]; g32.CreateFontW.restype = HANDLE
g32.SelectObject.argtypes = [HDC, HANDLE]; g32.SelectObject.restype = HANDLE
g32.DeleteObject.argtypes = [HANDLE]; g32.DeleteObject.restype = BOOL
g32.SetBkMode.argtypes = [HDC, INT]; g32.SetBkMode.restype = INT
g32.SetTextColor.argtypes = [HDC, COLORREF]; g32.SetTextColor.restype = COLORREF
g32.GetTextExtentPoint32W.argtypes = [HDC, ctypes.c_wchar_p, INT, ctypes.POINTER(wintypes.SIZE)]; g32.GetTextExtentPoint32W.restype = BOOL
g32.CreateCompatibleDC.argtypes = [HDC]; g32.CreateCompatibleDC.restype = HDC
g32.CreateCompatibleBitmap.argtypes = [HDC, INT, INT]; g32.CreateCompatibleBitmap.restype = HANDLE
g32.BitBlt.argtypes = [HDC, INT, INT, INT, INT, HDC, INT, INT, DWORD]; g32.BitBlt.restype = BOOL
g32.DeleteDC.argtypes = [HDC]; g32.DeleteDC.restype = BOOL


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

# --- Font Cache Implementation ---
class FontCache:
    """Caches GDI Font Handle (HFONT) to avoid recreating fonts on every paint cycle."""
    def __init__(self):
        self._hfont = None
        self._name = None
        self._size = None

    def get(self, name: str, size: int) -> HANDLE:
        if self._hfont is None or self._name != name or self._size != size:
            if self._hfont:
                g32.DeleteObject(self._hfont)
            self._hfont = g32.CreateFontW(
                size, 0, 0, 0, FW_BOLD, 0, 0, 0,
                DEFAULT_CHARSET, 0, 0, NONANTIALIASED_QUALITY, 0, name)
            self._name = name
            self._size = size
        return self._hfont

    def cleanup(self):
        if self._hfont:
            g32.DeleteObject(self._hfont)
            self._hfont = None

# Globals
g_hwnd = None
g_running = True
g_wndproc = None
g_font_cache = FontCache()
g_last_state_hash = None
g_timer_ticks = 0


def rgb(*args):
    """
    Convert color input to Win32 COLORREF (0x00BBGGRR).
    Accepts:
      rgb(r, g, b) -> rgb(255, 80, 80)
      rgb([r, g, b]) -> rgb([180, 180, 200])
      rgb("#HEXSTR") -> rgb("#4FC3F7")
    """
    if len(args) == 3:
        return int(args[0]) | (int(args[1]) << 8) | (int(args[2]) << 16)
    elif len(args) == 1:
        color = args[0]
        if isinstance(color, str):
            h = color.lstrip("#")
            if len(h) == 6:
                r = int(h[0:2], 16)
                g = int(h[2:4], 16)
                b = int(h[4:6], 16)
                return r | (g << 8) | (b << 16)
        elif isinstance(color, (list, tuple)) and len(color) >= 3:
            return int(color[0]) | (int(color[1]) << 8) | (int(color[2]) << 16)
    return 0x00FFFFFF


def open_dashboard():
    p = Path(__file__).parent / "tray_widget.py"
    if p.exists():
        os.startfile(str(p))


def wnd_proc(hwnd, msg, wparam, lparam):
    global g_running, g_last_state_hash, g_timer_ticks

    try:
        if msg == WM_CREATE:
            ms = tracker.config.get("display", {}).get("update_interval_ms", 3000)
            u32.SetTimer(hwnd, 1, ms, None)
            return 0

        elif msg == WM_TIMER:
            g_timer_ticks += 1
            # Every 15 seconds (5 ticks * 3s), trigger silent background auto_fetch
            if g_timer_ticks % 5 == 0:
                try:
                    threading.Thread(target=auto_fetch.fetch_all, kwargs={"silent": True}, daemon=True).start()
                except Exception:
                    pass

            tracker.reload()
            current_data = (tracker.get_today_usage(), tracker.usage.get("rate_limits", {}))
            current_hash = hash(json.dumps(current_data, sort_keys=True, default=str))
            if current_hash != g_last_state_hash:
                g_last_state_hash = current_hash
                u32.InvalidateRect(hwnd, None, 1)
            return 0

        elif msg == WM_ERASEBKGND:
            return 1

        elif msg == WM_PAINT:
            ps = PAINTSTRUCT()
            hdc = u32.BeginPaint(hwnd, ctypes.byref(ps))
            if not hdc:
                return 0

            rect = wintypes.RECT()
            u32.GetClientRect(hwnd, ctypes.byref(rect))
            w = rect.right - rect.left
            h = rect.bottom - rect.top

            mem_dc = g32.CreateCompatibleDC(hdc)
            mem_bmp = g32.CreateCompatibleBitmap(hdc, w, h)
            old_bmp = g32.SelectObject(mem_dc, mem_bmp)

            br = g32.CreateSolidBrush(COLORKEY_RGB)
            u32.FillRect(mem_dc, ctypes.byref(rect), br)
            g32.DeleteObject(br)

            disp = tracker.config.get("display", {})
            fsz = disp.get("font_size", 18)
            fname = disp.get("font_name", "Segoe UI")

            g32.SetBkMode(mem_dc, BK_TRANSPARENT)
            hfont = g_font_cache.get(fname, fsz)
            old_font = g32.SelectObject(mem_dc, hfont)

            providers = tracker.config.get("providers", {})
            rate_limits = tracker.usage.get("rate_limits", {})
            month = tracker.get_month_usage()
            show_left = disp.get("show_percent_left", False)
            sep_col = disp.get("separator_color", [180, 180, 200])

            x = 10
            sep_color = rgb(110, 115, 135)   # Soft neutral gray for bullet dots
            dim_color = rgb(180, 185, 205)   # Clean light gray for values
            warn_color = rgb(255, 82, 82)    # Soft red highlight when low (<=20%)

            for idx, (name, info) in enumerate(providers.items()):
                col = info.get("color", "#FFFFFF")
                
                # Check real rate limits first!
                rl = rate_limits.get(name, {})
                if "percent_left" in rl:
                    pct_left = rl["percent_left"]
                else:
                    m_tok = month.get(name, {}).get("total", 0)
                    budget = info.get("monthly_budget", 1)
                    used_pct = min(m_tok / budget * 100, 100) if budget > 0 else 0
                    pct_left = max(0, 100 - used_pct)

                # Provider name
                if name == "AGY":
                    agy_colors = [(255, 82, 82), (68, 138, 255), (255, 215, 64)]
                    for ci, ch in enumerate(name):
                        g32.SetTextColor(mem_dc, rgb(agy_colors[ci % len(agy_colors)]))
                        x = _draw(mem_dc, ch, x, h)
                    x += 6
                else:
                    g32.SetTextColor(mem_dc, rgb(col))
                    x = _draw(mem_dc, name, x, h) + 6

                # Percentage display (Ultra Clean & Borderless)
                if name == "AGY" and "percent_5h_left" in rl:
                    pct_5h = rl["percent_5h_left"]
                    pct_wk = rl["percent_left"]
                    
                    # 5-hour %
                    g32.SetTextColor(mem_dc, warn_color if pct_5h <= 20 else dim_color)
                    x = _draw(mem_dc, f"{pct_5h:.1f}%", x, h) + 4
                    
                    # Soft middle dot
                    g32.SetTextColor(mem_dc, sep_color)
                    x = _draw(mem_dc, "·", x, h) + 4
                    
                    # Weekly %
                    g32.SetTextColor(mem_dc, warn_color if pct_wk <= 20 else dim_color)
                    x = _draw(mem_dc, f"{pct_wk:.1f}%", x, h) + 16
                else:
                    g32.SetTextColor(mem_dc, warn_color if pct_left <= 20 else dim_color)
                    x = _draw(mem_dc, f"{pct_left:.1f}%", x, h) + 16

                # Vertical line separator between providers
                if idx < len(providers) - 1:
                    g32.SetTextColor(mem_dc, sep_color)
                    x = _draw(mem_dc, "|", x, h) + 16

            g32.SelectObject(mem_dc, old_font)
            g32.BitBlt(hdc, 0, 0, w, h, mem_dc, 0, 0, 0x00CC0020)

            g32.SelectObject(mem_dc, old_bmp)
            g32.DeleteObject(mem_bmp)
            g32.DeleteDC(mem_dc)

            u32.EndPaint(hwnd, ctypes.byref(ps))
            return 0

        elif msg == WM_LBUTTONDBLCLK:
            open_dashboard()
            return 0

        elif msg == WM_RBUTTONDOWN:
            menu = u32.CreatePopupMenu()
            u32.AppendMenuW(menu, MF_STRING, 1, "Open Dashboard")
            u32.AppendMenuW(menu, MF_STRING, 2, "Refresh")
            u32.AppendMenuW(menu, MF_SEPARATOR, 0, None)
            u32.AppendMenuW(menu, MF_STRING, 3, "Add AGY +1.5K")
            u32.AppendMenuW(menu, MF_STRING, 4, "Add Codex +1.5K")
            u32.AppendMenuW(menu, MF_STRING, 5, "Add DeepSeek +1.5K")
            u32.AppendMenuW(menu, MF_STRING, 6, "Add Mimo +1.5K")
            u32.AppendMenuW(menu, MF_SEPARATOR, 0, None)
            u32.AppendMenuW(menu, MF_STRING, 9, "Exit")

            pt = wintypes.POINT()
            u32.GetCursorPos(ctypes.byref(pt))
            u32.SetForegroundWindow(hwnd)
            cmd = u32.TrackPopupMenu(menu, TPM_RETURNCMD, pt.x, pt.y, 0, hwnd, None)
            u32.DestroyMenu(menu)

            if cmd == 1: open_dashboard()
            elif cmd == 2: tracker.reload(); u32.InvalidateRect(hwnd, None, 1)
            elif cmd in (3, 4, 5, 6):
                names = {3: "AGY", 4: "Codex", 5: "DeepSeek", 6: "Mimo"}
                tracker.add_usage(names[cmd], 1000, 500)
                u32.InvalidateRect(hwnd, None, 1)
            elif cmd == 9: u32.PostMessageW(hwnd, WM_CLOSE, 0, 0)
            return 0

        elif msg == WM_CLOSE:
            g_running = False
            g_font_cache.cleanup()
            u32.KillTimer(hwnd, 1)
            u32.DestroyWindow(hwnd)
            return 0

        elif msg == WM_DESTROY:
            u32.PostQuitMessage(0)
            return 0

    except Exception:
        import traceback; traceback.print_exc()

    return u32.DefWindowProcW(hwnd, msg, wparam, lparam)

def _draw(hdc, text, x, h):
    buf = ctypes.create_unicode_buffer(text)
    tr = wintypes.RECT(x, 0, x + 400, h)
    u32.DrawTextW(hdc, buf, -1, ctypes.byref(tr), DT_SINGLELINE | DT_VCENTER | DT_LEFT | DT_NOCLIP)
    sz = wintypes.SIZE()
    g32.GetTextExtentPoint32W(hdc, buf, len(text), ctypes.byref(sz))
    return x + sz.cx

def create_widget():
    global g_hwnd, g_wndproc
    hinst = k32.GetModuleHandleW(None)
    cls = "AITokenV4"
    g_wndproc = WNDPROC(wnd_proc)

    wc = WNDCLASSEX()
    wc.cbSize = ctypes.sizeof(WNDCLASSEX)
    wc.style = CS_HREDRAW | CS_VREDRAW | CS_DBLCLKS
    wc.lpfnWndProc = g_wndproc
    wc.hInstance = hinst
    wc.hCursor = u32.LoadCursorW(None, IDC_ARROW)
    wc.hbrBackground = g32.CreateSolidBrush(COLORKEY_RGB)
    wc.lpszClassName = cls

    if not u32.RegisterClassExW(ctypes.byref(wc)): return False
    taskbar = u32.FindWindowW("Shell_TrayWnd", None)
    if not taskbar: return False

    tb = wintypes.RECT()
    u32.GetWindowRect(taskbar, ctypes.byref(tb))
    disp = tracker.config.get("display", {})
    w = disp.get("width", 620)
    h = tb.bottom - tb.top
    x = tb.right - w - 280
    y = tb.top

    g_hwnd = u32.CreateWindowExW(
        WS_EX_TOOLWINDOW | WS_EX_TOPMOST | WS_EX_NOACTIVATE | WS_EX_LAYERED,
        cls, "AI Token Widget", WS_POPUP | WS_VISIBLE,
        x, y, w, h, None, None, hinst, None)

    if not g_hwnd: return False
    u32.SetLayeredWindowAttributes(g_hwnd, COLORKEY_RGB, 0, LWA_COLORKEY)
    u32.ShowWindow(g_hwnd, 5)
    u32.UpdateWindow(g_hwnd)
    return True

def keep_top():
    TOPMOST = ctypes.c_void_p(-1)
    while g_running:
        time.sleep(3)
        if g_hwnd and g_running:
            u32.SetWindowPos(g_hwnd, TOPMOST, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE)

def main():
    print("=" * 50)
    print("  AI Token Usage — Taskbar Text Widget v2 (Antigravity Edition)")
    print("  AGY | Codex | DeepSeek | Mimo")
    print("=" * 50)
    if not create_widget(): sys.exit(1)
    threading.Thread(target=keep_top, daemon=True).start()
    msg = wintypes.MSG()
    while True:
        r = u32.GetMessageW(ctypes.byref(msg), None, 0, 0)
        if r <= 0: break
        u32.TranslateMessage(ctypes.byref(msg))
        u32.DispatchMessageW(ctypes.byref(msg))

if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    main()
