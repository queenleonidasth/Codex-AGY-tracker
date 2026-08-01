"""
AI Token Usage Tracker - Core Manager Module (Antigravity v2 Optimized Edition)
Provides Single Source of Truth (SSOT) data management with mtime caching.
"""

import json
import os
from datetime import datetime, date
from pathlib import Path

# Paths
DATA_DIR = Path(__file__).parent / "data"
DATA_FILE = DATA_DIR / "token_usage.json"
CONFIG_FILE = DATA_DIR / "config.json"

# Default provider configuration
DEFAULT_PROVIDERS = {
    "AGY": {"color": "#4FC3F7", "icon": "🤖", "monthly_budget": 1000000},
    "Codex": {"color": "#81C784", "icon": "💻", "monthly_budget": 500000},
    "DeepSeek": {"color": "#FFB74D", "icon": "🧠", "monthly_budget": 2000000},
    "Mimo": {"color": "#CE93D8", "icon": "🎯", "monthly_budget": 1000000},
}


class TokenTracker:
    """Core Token Usage Tracker with File Modification Time (mtime) Caching."""

    def __init__(self):
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        self._last_mtime = 0
        self.usage = self._load_usage()
        self.config = self._load_config()

    def _load_usage(self) -> dict:
        """Load usage data from disk only if the file has been modified."""
        if DATA_FILE.exists():
            try:
                mtime = DATA_FILE.stat().st_mtime
                if mtime > self._last_mtime:
                    self._last_mtime = mtime
                    with open(DATA_FILE, "r", encoding="utf-8") as f:
                        return json.load(f)
                return getattr(self, "usage", {"daily": {}, "monthly": {}, "total": {}})
            except Exception:
                pass
        return {"daily": {}, "monthly": {}, "total": {}}

    def reload(self):
        """Force check and reload usage data if modified."""
        self.usage = self._load_usage()

    def _save_usage(self):
        """Save usage data to disk and update cached mtime."""
        with open(DATA_FILE, "w", encoding="utf-8") as f:
            json.dump(self.usage, f, indent=2, ensure_ascii=False)
        if DATA_FILE.exists():
            self._last_mtime = DATA_FILE.stat().st_mtime

    def _load_config(self) -> dict:
        """Load configuration or create default if not exists."""
        if CONFIG_FILE.exists():
            try:
                with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        config = {
            "providers": DEFAULT_PROVIDERS,
            "display": {
                "font_size": 18,
                "font_name": "Segoe UI Variable Display",
                "separator_color": [180, 180, 200],
                "width": 620,
                "update_interval_ms": 3000,
                "show_percent_left": False
            }
        }
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2, ensure_ascii=False)
        return config

    def add_usage(self, provider: str, input_tokens: int = 0, output_tokens: int = 0):
        """Record token usage for a provider across daily, monthly, and total metrics."""
        today = date.today().isoformat()
        month = today[:7]
        total = input_tokens + output_tokens

        # Daily
        self.usage.setdefault("daily", {}).setdefault(today, {}).setdefault(
            provider, {"input": 0, "output": 0, "total": 0})
        self.usage["daily"][today][provider]["input"] += input_tokens
        self.usage["daily"][today][provider]["output"] += output_tokens
        self.usage["daily"][today][provider]["total"] += total

        # Monthly
        self.usage.setdefault("monthly", {}).setdefault(month, {}).setdefault(
            provider, {"input": 0, "output": 0, "total": 0})
        self.usage["monthly"][month][provider]["input"] += input_tokens
        self.usage["monthly"][month][provider]["output"] += output_tokens
        self.usage["monthly"][month][provider]["total"] += total

        # Total
        self.usage.setdefault("total", {}).setdefault(
            provider, {"input": 0, "output": 0, "total": 0})
        self.usage["total"][provider]["input"] += input_tokens
        self.usage["total"][provider]["output"] += output_tokens
        self.usage["total"][provider]["total"] += total

        self.usage["last_updated"] = datetime.now().isoformat()
        self._save_usage()

    def get_today_usage(self) -> dict:
        """Get today's usage dictionary."""
        self.reload()
        return self.usage.get("daily", {}).get(date.today().isoformat(), {})

    def get_month_usage(self) -> dict:
        """Get current month's usage dictionary."""
        self.reload()
        return self.usage.get("monthly", {}).get(date.today().isoformat()[:7], {})

    @staticmethod
    def _format_tokens(n: int) -> str:
        """Format token numbers to human-readable string (e.g. 1.2M, 45.0K)."""
        if n >= 1_000_000:
            return f"{n/1_000_000:.1f}M"
        if n >= 1_000:
            return f"{n/1_000:.1f}K"
        return str(n)


# Singleton Instance (Single Source of Truth)
tracker = TokenTracker()
