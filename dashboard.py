"""Tk dashboard. All widget mutations are confined to the Tk main thread."""

from __future__ import annotations

import queue
import threading
import tkinter as tk
from tkinter import ttk
from typing import Any

from settings import Settings
from state_store import AtomicStateStore
from ui_models import TrackerView, build_tracker_view, format_tokens


BACKGROUND = "#11131A"
SURFACE = "#1A1E29"
SURFACE_ALT = "#232938"
TEXT = "#F4F6FB"
MUTED = "#9AA4B5"
ACCENT = "#6CB6FF"
WARNING = "#FFB454"
CRITICAL = "#FF6B6B"


class Dashboard:
    def __init__(self, store: AtomicStateStore, service: Any, settings: Settings):
        self.store = store
        self.service = service
        self.settings = settings
        self.root: tk.Tk | None = None
        self.content: ttk.Frame | None = None
        self.status_var: tk.StringVar | None = None
        self._queue: queue.Queue[tuple[str, Any]] = queue.Queue()
        self._refreshing = False

    def run(self) -> None:
        root = tk.Tk()
        self.root = root
        root.title("AI Usage Tracker")
        root.geometry("760x700")
        root.minsize(620, 520)
        root.configure(bg=BACKGROUND)

        style = ttk.Style(root)
        style.theme_use("clam")
        style.configure("App.TFrame", background=BACKGROUND)
        style.configure("Card.TFrame", background=SURFACE)
        style.configure("Title.TLabel", background=BACKGROUND, foreground=TEXT, font=("Segoe UI Variable Display", 20, "bold"))
        style.configure("Subtitle.TLabel", background=BACKGROUND, foreground=MUTED, font=("Segoe UI", 9))
        style.configure("CardTitle.TLabel", background=SURFACE, foreground=TEXT, font=("Segoe UI", 12, "bold"))
        style.configure("CardText.TLabel", background=SURFACE, foreground=MUTED, font=("Segoe UI", 9))
        style.configure("Token.TLabel", background=SURFACE_ALT, foreground=TEXT, font=("Segoe UI", 11, "bold"))
        style.configure("Refresh.TButton", font=("Segoe UI", 9, "bold"), padding=(14, 8))

        outer = ttk.Frame(root, style="App.TFrame", padding=20)
        outer.pack(fill=tk.BOTH, expand=True)

        header = ttk.Frame(outer, style="App.TFrame")
        header.pack(fill=tk.X, pady=(0, 14))
        title_block = ttk.Frame(header, style="App.TFrame")
        title_block.pack(side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Label(title_block, text="AI Usage Tracker", style="Title.TLabel").pack(anchor=tk.W)
        self.status_var = tk.StringVar(value="Loading last known data…")
        ttk.Label(title_block, textvariable=self.status_var, style="Subtitle.TLabel").pack(anchor=tk.W, pady=(3, 0))
        ttk.Button(
            header,
            text="Refresh now",
            command=lambda: self.request_refresh(force=True),
            style="Refresh.TButton",
        ).pack(side=tk.RIGHT)

        canvas = tk.Canvas(outer, bg=BACKGROUND, highlightthickness=0)
        scrollbar = ttk.Scrollbar(outer, orient=tk.VERTICAL, command=canvas.yview)
        canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.content = ttk.Frame(canvas, style="App.TFrame")
        window_id = canvas.create_window((0, 0), window=self.content, anchor="nw")
        self.content.bind(
            "<Configure>", lambda _event: canvas.configure(scrollregion=canvas.bbox("all"))
        )
        canvas.bind("<Configure>", lambda event: canvas.itemconfigure(window_id, width=event.width))

        self._render(build_tracker_view(self.store.load(), self.settings.enabled_providers))
        root.after(100, self._drain_queue)
        root.after(1_000, self._refresh_clock)
        self.request_refresh(force=False)
        root.mainloop()

    def request_refresh(self, force: bool = True) -> None:
        if self._refreshing:
            return
        self._refreshing = True
        if self.status_var is not None:
            self.status_var.set("Refreshing providers and local Codex usage…")

        def worker() -> None:
            try:
                self.service.refresh(force=force)
                self._queue.put(("state", self.store.load(force=True)))
            except Exception as error:
                self._queue.put(("error", str(error) or error.__class__.__name__))

        threading.Thread(target=worker, name="dashboard-refresh", daemon=True).start()

    def _drain_queue(self) -> None:
        if self.root is None:
            return
        while True:
            try:
                kind, value = self._queue.get_nowait()
            except queue.Empty:
                break
            self._refreshing = False
            if kind == "state":
                self._render(build_tracker_view(value, self.settings.enabled_providers))
                if self.status_var is not None:
                    self.status_var.set("Updated from provider sources and local session logs")
            elif self.status_var is not None:
                self.status_var.set(f"Refresh failed: {value}")
        self.root.after(150, self._drain_queue)

    def _refresh_clock(self) -> None:
        if self.root is None:
            return
        self._render(build_tracker_view(self.store.load(), self.settings.enabled_providers))
        self.root.after(30_000, self._refresh_clock)

    def _render(self, view: TrackerView) -> None:
        if self.content is None:
            return
        for child in self.content.winfo_children():
            child.destroy()

        summary = ttk.Frame(self.content, style="Card.TFrame", padding=14)
        summary.pack(fill=tk.X, pady=(0, 12))
        for index, (label, key) in enumerate(
            (("Today", "today"), ("This month", "month"), ("Local lifetime", "lifetime"))
        ):
            block = tk.Frame(summary, bg=SURFACE_ALT, padx=16, pady=10)
            block.grid(row=0, column=index, sticky="nsew", padx=(0 if index == 0 else 5, 0))
            summary.columnconfigure(index, weight=1)
            tk.Label(block, text=label, bg=SURFACE_ALT, fg=MUTED, font=("Segoe UI", 8)).pack(anchor="w")
            tk.Label(
                block,
                text=f"{format_tokens(view.token_totals[key])} tokens",
                bg=SURFACE_ALT,
                fg=TEXT,
                font=("Segoe UI", 11, "bold"),
            ).pack(anchor="w", pady=(2, 0))

        if not view.providers:
            empty = ttk.Frame(self.content, style="Card.TFrame", padding=24)
            empty.pack(fill=tk.X)
            ttk.Label(empty, text="Waiting for provider data…", style="CardTitle.TLabel").pack(anchor=tk.W)
            ttk.Label(
                empty,
                text="Use Refresh now after signing in to Codex or opening Antigravity.",
                style="CardText.TLabel",
            ).pack(anchor=tk.W, pady=(6, 0))
            return

        for provider in view.providers:
            style = self.settings.provider_styles.get(provider.provider_id, {})
            provider_color = style.get("color", ACCENT)
            card = tk.Frame(
                self.content,
                bg=SURFACE,
                highlightbackground=provider_color,
                highlightthickness=1,
                padx=16,
                pady=14,
            )
            card.pack(fill=tk.X, pady=(0, 12))
            top = tk.Frame(card, bg=SURFACE)
            top.pack(fill=tk.X)
            tk.Label(
                top,
                text=provider.display_name,
                bg=SURFACE,
                fg=provider_color,
                font=("Segoe UI Variable Display", 13, "bold"),
            ).pack(side=tk.LEFT)
            status_color = TEXT if provider.status == "ok" else WARNING if provider.status == "stale" else CRITICAL
            tk.Label(
                top,
                text=provider.status.replace("_", " ").upper(),
                bg=SURFACE,
                fg=status_color,
                font=("Segoe UI", 8, "bold"),
            ).pack(side=tk.RIGHT)
            metadata = f"{provider.plan}  ·  {provider.source or 'no source'}  ·  confirmed {provider.age_text}"
            tk.Label(card, text=metadata, bg=SURFACE, fg=MUTED, font=("Segoe UI", 8)).pack(anchor="w", pady=(3, 10))

            if provider.windows:
                for window in provider.windows:
                    row = tk.Frame(card, bg=SURFACE)
                    row.pack(fill=tk.X, pady=4)
                    label_row = tk.Frame(row, bg=SURFACE)
                    label_row.pack(fill=tk.X)
                    tk.Label(label_row, text=window.label, bg=SURFACE, fg=TEXT, font=("Segoe UI", 9, "bold")).pack(side=tk.LEFT)
                    value_color = CRITICAL if window.severity == "critical" else WARNING if window.severity == "warning" else TEXT
                    tk.Label(
                        label_row,
                        text=f"{window.remaining_percent:.1f}% left  ·  resets {window.reset_in}",
                        bg=SURFACE,
                        fg=value_color,
                        font=("Segoe UI", 9),
                    ).pack(side=tk.RIGHT)
                    bar = tk.Canvas(row, height=8, bg=SURFACE, highlightthickness=0)
                    bar.pack(fill=tk.X, pady=(4, 0))

                    def draw_bar(event, canvas=bar, remaining=window.remaining_percent, color=value_color):
                        canvas.delete("all")
                        width = max(1, event.width)
                        canvas.create_rectangle(0, 1, width, 7, fill=SURFACE_ALT, outline="")
                        canvas.create_rectangle(0, 1, width * remaining / 100.0, 7, fill=color, outline="")

                    bar.bind("<Configure>", draw_bar)
            else:
                tk.Label(card, text="Quota is not available yet", bg=SURFACE, fg=MUTED, font=("Segoe UI", 9)).pack(anchor="w")

            if provider.message:
                tk.Label(
                    card,
                    text=provider.message,
                    bg=SURFACE,
                    fg=WARNING if provider.status == "stale" else CRITICAL,
                    font=("Segoe UI", 8),
                    wraplength=660,
                    justify=tk.LEFT,
                ).pack(anchor="w", pady=(8, 0))
