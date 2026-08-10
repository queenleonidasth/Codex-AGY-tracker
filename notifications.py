"""Quota threshold notifications deduplicated by provider reset window."""

from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import Any, Mapping

from quota_models import ProviderSnapshot, utc_now_iso


@dataclass(frozen=True, slots=True)
class NotificationEvent:
    key: str
    reserve_keys: tuple[str, ...]
    provider_id: str
    provider_name: str
    window_id: str
    window_label: str
    threshold: int
    remaining_percent: float
    reset_at: str
    title: str
    message: str


class NotificationPolicy:
    def __init__(self, thresholds: tuple[int, ...] | list[int] = (20, 10, 5)):
        self.thresholds = tuple(
            sorted(
                {int(value) for value in thresholds if 1 <= int(value) <= 99},
                reverse=True,
            )
        )

    @staticmethod
    def _sent(state: Mapping[str, Any]) -> Mapping[str, Any]:
        notifications = state.get("notifications")
        if not isinstance(notifications, Mapping):
            return {}
        sent = notifications.get("sent")
        return sent if isinstance(sent, Mapping) else {}

    def events(
        self,
        previous_state: Mapping[str, Any],
        snapshots: Mapping[str, ProviderSnapshot | Mapping[str, Any]],
    ) -> list[NotificationEvent]:
        sent = self._sent(previous_state)
        events: list[NotificationEvent] = []
        for provider_id, raw_snapshot in snapshots.items():
            try:
                snapshot = (
                    raw_snapshot
                    if isinstance(raw_snapshot, ProviderSnapshot)
                    else ProviderSnapshot.from_dict(dict(raw_snapshot))
                )
            except (TypeError, ValueError):
                continue
            for window_id, window in snapshot.windows.items():
                eligible = []
                reset_at = str(window.reset_at or "unknown-reset")
                for threshold in self.thresholds:
                    key = f"{provider_id}/{window_id}/{reset_at}/{threshold}"
                    if window.remaining_percent <= threshold and key not in sent:
                        eligible.append((threshold, key))
                if not eligible:
                    continue
                threshold, key = min(eligible, key=lambda value: value[0])
                events.append(
                    NotificationEvent(
                        key=key,
                        reserve_keys=tuple(value[1] for value in eligible),
                        provider_id=str(provider_id),
                        provider_name=snapshot.provider_name,
                        window_id=str(window_id),
                        window_label=window.label or str(window_id).replace("_", " ").title(),
                        threshold=threshold,
                        remaining_percent=window.remaining_percent,
                        reset_at=reset_at,
                        title=f"{snapshot.provider_name} quota is low",
                        message=(
                            f"{window.label or window_id}: {window.remaining_percent:.1f}% left "
                            f"(threshold {threshold}%)"
                        ),
                    )
                )
        return events

    def apply(
        self, previous_state: Mapping[str, Any], events: list[NotificationEvent]
    ) -> dict[str, Any]:
        state = copy.deepcopy(dict(previous_state))
        notifications = state.setdefault("notifications", {})
        if not isinstance(notifications, dict):
            notifications = {}
            state["notifications"] = notifications
        sent = notifications.setdefault("sent", {})
        if not isinstance(sent, dict):
            sent = {}
            notifications["sent"] = sent
        recorded_at = utc_now_iso()
        for event in events:
            for key in event.reserve_keys or (event.key,):
                sent[key] = recorded_at
        return state

    def claim(self, store: Any, snapshots: Mapping[str, Any]) -> list[NotificationEvent]:
        """Atomically reserve new notification keys before the tray displays them."""
        claimed: list[NotificationEvent] = []

        def update(state: dict[str, Any]) -> None:
            claimed.extend(self.events(state, snapshots))
            if not claimed:
                return
            updated = self.apply(state, claimed)
            state["notifications"] = updated["notifications"]

        store.mutate(update)
        return claimed
