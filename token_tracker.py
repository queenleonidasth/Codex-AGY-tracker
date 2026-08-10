"""Token-usage facade backed exclusively by :mod:`state_store` transactions."""

from __future__ import annotations

from datetime import date
from typing import Any, Optional

from app_paths import settings_path
from settings import Settings
from state_store import AtomicStateStore, get_store


def _provider_id(name: str) -> str:
    value = str(name).strip().lower()
    if value == "antigravity":
        return "agy"
    return value


class TokenTracker:
    def __init__(
        self,
        store: Optional[AtomicStateStore] = None,
        settings: Optional[Settings] = None,
    ):
        self.store = store or get_store()
        self.settings = settings or Settings.load(settings_path())
        self.config = self.settings.to_dict()
        self.usage: dict[str, Any] = {}
        self.reload()

    def reload(self) -> None:
        self.usage = self.store.load().get("usage", {})

    def add_usage(self, provider: str, input_tokens: int = 0, output_tokens: int = 0) -> None:
        if (
            isinstance(input_tokens, bool)
            or isinstance(output_tokens, bool)
            or not isinstance(input_tokens, int)
            or not isinstance(output_tokens, int)
            or input_tokens < 0
            or output_tokens < 0
        ):
            raise ValueError("Token counts must be non-negative integers")

        provider_id = _provider_id(provider)
        today = date.today().isoformat()
        month = today[:7]
        total = input_tokens + output_tokens

        def add(state: dict[str, Any]) -> None:
            usage = state["usage"]
            for bucket_name, period in (("daily", today), ("monthly", month)):
                record = (
                    usage[bucket_name]
                    .setdefault(period, {})
                    .setdefault(provider_id, {"input": 0, "output": 0, "total": 0})
                )
                record["input"] += input_tokens
                record["output"] += output_tokens
                record["total"] += total

            lifetime = usage["total"].setdefault(
                provider_id, {"input": 0, "output": 0, "total": 0}
            )
            lifetime["input"] += input_tokens
            lifetime["output"] += output_tokens
            lifetime["total"] += total

            if provider_id == "codex":
                adjustment = usage["scanner"].setdefault(
                    "codex_adjustment",
                    {"daily": {}, "monthly": {}, "total": {}},
                )
                if not isinstance(adjustment, dict):
                    adjustment = {"daily": {}, "monthly": {}, "total": {}}
                    usage["scanner"]["codex_adjustment"] = adjustment
                for key in ("daily", "monthly", "total"):
                    if not isinstance(adjustment.get(key), dict):
                        adjustment[key] = {}
                for bucket_name, period in (("daily", today), ("monthly", month)):
                    record = adjustment[bucket_name].setdefault(
                        period, {"input": 0, "output": 0, "total": 0}
                    )
                    record["input"] += input_tokens
                    record["output"] += output_tokens
                    record["total"] += total
                adjusted_total = adjustment["total"]
                adjusted_total["input"] = adjusted_total.get("input", 0) + input_tokens
                adjusted_total["output"] = adjusted_total.get("output", 0) + output_tokens
                adjusted_total["total"] = adjusted_total.get("total", 0) + total

        state = self.store.mutate(add)
        self.usage = state["usage"]

    def get_today_usage(self) -> dict[str, Any]:
        self.reload()
        return self.usage.get("daily", {}).get(date.today().isoformat(), {})

    def get_month_usage(self) -> dict[str, Any]:
        self.reload()
        return self.usage.get("monthly", {}).get(date.today().isoformat()[:7], {})

    def get_total_usage(self) -> dict[str, Any]:
        self.reload()
        return self.usage.get("total", {})

    @staticmethod
    def _format_tokens(value: int) -> str:
        if value >= 1_000_000:
            return f"{value / 1_000_000:.1f}M"
        if value >= 1_000:
            return f"{value / 1_000:.1f}K"
        return str(value)


tracker = TokenTracker()
