"""
AI Token Usage - System Tray Widget & Dashboard Popup (Antigravity v2 Optimized)
"""

import pystray
from pystray import MenuItem as item
from PIL import Image, ImageDraw, ImageFont
import tkinter as tk
from tkinter import ttk, messagebox
import threading
import sys
import os
from datetime import date

sys.path.insert(0, os.path.dirname(__file__))
from token_tracker import tracker


class TokenTrayIcon:
    """System tray icon with modern popup dashboard."""

    def __init__(self):
        self.icon = None
        self.popup_window = None
        self._create_icon()

    def _create_tray_image(self) -> Image.Image:
        """Create dynamic tray icon showing usage level."""
        size = 64
        img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)

        draw.ellipse([2, 2, size-2, size-2], fill="#1E1E2E", outline="#4FC3F7", width=2)

        try:
            font = ImageFont.truetype("segoeui.ttf", 32)
        except Exception:
            font = ImageFont.load_default()
        
        bbox = draw.textbbox((0, 0), "AI", font=font)
        tw = bbox[2] - bbox[0]
        th = bbox[3] - bbox[1]
        draw.text(((size - tw) / 2, (size - th) / 2 - 2), "AI", fill="#4FC3F7", font=font)

        today = tracker.get_today_usage()
        total_today = sum(p.get("total", 0) for p in today.values())
        arc_extent = min(total_today / 100000 * 360, 360)
        if arc_extent > 0:
            draw.arc([4, 4, size-4, size-4], -90, -90 + arc_extent, fill="#81C784", width=3)

        return img

    def _create_icon(self):
        image = self._create_tray_image()

        menu = pystray.Menu(
            item("📊 Open Dashboard", self._show_dashboard, default=True),
            item("➕ Add Usage", pystray.Menu(
                item("AGY", lambda: self._quick_add("AGY")),
                item("Codex", lambda: self._quick_add("Codex")),
            )),
            item("📋 Today's Summary", self._show_summary),
            pystray.Menu.SEPARATOR,
            item("⚙️ Settings", self._show_settings),
            item("❌ Exit", self._quit),
        )

        self.icon = pystray.Icon("ai_token_tracker", image, "AI Token Tracker v2", menu)

    def _show_dashboard(self, icon=None, item=None):
        threading.Thread(target=self._create_dashboard_window, daemon=True).start()

    def _create_dashboard_window(self):
        if self.popup_window and self.popup_window.winfo_exists():
            self.popup_window.lift()
            return

        root = tk.Tk()
        self.popup_window = root
        root.title("🤖 AI Token Usage Dashboard v2")
        root.geometry("500x600")
        root.configure(bg="#1E1E2E")
        root.resizable(False, False)

        style = ttk.Style()
        style.theme_use("clam")
        style.configure("Dark.TFrame", background="#1E1E2E")
        style.configure("Dark.TLabel", background="#1E1E2E", foreground="#E0E0E0", font=("Segoe UI", 10))
        style.configure("Title.TLabel", background="#1E1E2E", foreground="#FFFFFF", font=("Segoe UI", 14, "bold"))

        main_frame = ttk.Frame(root, style="Dark.TFrame", padding=20)
        main_frame.pack(fill=tk.BOTH, expand=True)

        ttk.Label(main_frame, text="📊 AI Token Usage Dashboard", style="Title.TLabel").pack(pady=(0, 15))
        ttk.Label(main_frame, text=f"📅 {date.today().strftime('%A, %B %d, %Y')}", style="Dark.TLabel").pack(pady=(0, 15))

        providers = tracker.config.get("providers", {})
        today_usage = tracker.get_today_usage()
        month_usage = tracker.get_month_usage()

        for name, info in providers.items():
            card = tk.Frame(main_frame, bg="#2D2D3D", highlightbackground=info["color"], highlightthickness=2, padx=15, pady=10)
            card.pack(fill=tk.X, pady=5)

            tk.Label(card, text=f"{info['icon']} {name}", bg="#2D2D3D", fg=info["color"], font=("Segoe UI", 12, "bold")).pack(anchor="w")
            today_tokens = today_usage.get(name, {}).get("total", 0)
            tk.Label(card, text=f"Today: {tracker._format_tokens(today_tokens)} tokens", bg="#2D2D3D", fg="#B0B0B0", font=("Segoe UI", 9)).pack(anchor="w")

            month_tokens = month_usage.get(name, {}).get("total", 0)
            budget = info.get("monthly_budget", 1)
            pct = min(month_tokens / budget * 100, 100)

            progress_frame = tk.Frame(card, bg="#2D2D3D")
            progress_frame.pack(fill=tk.X, pady=(5, 0))

            canvas = tk.Canvas(progress_frame, height=12, bg="#2D2D3D", highlightthickness=0)
            canvas.pack(fill=tk.X, side=tk.LEFT, expand=True)

            def draw_progress(c, percentage, color):
                c.update_idletasks()
                w = c.winfo_width() or 400
                c.create_rectangle(0, 2, w, 10, fill="#3D3D4D", outline="")
                fill_w = int(w * percentage / 100)
                if fill_w > 0:
                    c.create_rectangle(0, 2, fill_w, 10, fill=color, outline="")

            canvas.bind("<Configure>", lambda e, c=canvas, p=pct, col=info["color"]: draw_progress(c, p, col))
            tk.Label(progress_frame, text=f" {pct:.0f}% of {tracker._format_tokens(budget)}", bg="#2D2D3D", fg="#808080", font=("Segoe UI", 8)).pack(side=tk.RIGHT)

        root.mainloop()

    def _quick_add(self, provider: str):
        tracker.add_usage(provider, 1000, 500)
        if self.icon:
            self.icon.notify(f"Added 1,500 tokens to {provider}", "AI Token Tracker")
            self.icon.icon = self._create_tray_image()

    def _show_summary(self, icon=None, item=None):
        today = tracker.get_today_usage()
        total_today = sum(p.get("total", 0) for p in today.values())
        msg = f"Total Tokens Today: {tracker._format_tokens(total_today)}"
        if self.icon:
            self.icon.notify(msg, "AI Token Summary")

    def _show_settings(self, icon=None, item=None):
        messagebox.showinfo("Settings", "Settings can be modified in data/config.json")

    def _quit(self, icon=None, item=None):
        if self.icon:
            self.icon.stop()

    def run(self):
        self.icon.run()


if __name__ == "__main__":
    app = TokenTrayIcon()
    app.run()
