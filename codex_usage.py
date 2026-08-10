"""Incremental Codex rollout scanner for automatic local token totals."""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone, tzinfo
from pathlib import Path
from typing import Any, Iterable, Optional


METRIC_KEYS = ("input", "cached_input", "output", "reasoning_output", "total")


def _empty_metrics() -> dict[str, int]:
    return {key: 0 for key in METRIC_KEYS}


def _add_metrics(target: dict[str, int], incoming: dict[str, int]) -> None:
    for key in METRIC_KEYS:
        target[key] = int(target.get(key, 0)) + int(incoming.get(key, 0))


def _to_non_negative_int(value: Any) -> int:
    if isinstance(value, bool) or value is None:
        return 0
    try:
        return max(0, int(float(value)))
    except (TypeError, ValueError, OverflowError):
        return 0


def _normalized_usage(raw: Any) -> Optional[dict[str, int]]:
    if not isinstance(raw, dict):
        return None
    input_tokens = _to_non_negative_int(
        raw.get("input_tokens", raw.get("prompt_tokens", raw.get("input")))
    )
    cached_input = _to_non_negative_int(
        raw.get(
            "cached_input_tokens",
            raw.get("cache_read_input_tokens", raw.get("cached_tokens")),
        )
    )
    output_tokens = _to_non_negative_int(
        raw.get("output_tokens", raw.get("completion_tokens", raw.get("output")))
    )
    reasoning = _to_non_negative_int(raw.get("reasoning_output_tokens"))
    supplied_total = _to_non_negative_int(raw.get("total_tokens"))
    computed_total = input_tokens + output_tokens
    total = computed_total if computed_total else supplied_total
    if not any((input_tokens, cached_input, output_tokens, reasoning, total)):
        return None
    return {
        "input": input_tokens,
        "cached_input": min(cached_input, input_tokens) if input_tokens else cached_input,
        "output": output_tokens,
        "reasoning_output": min(reasoning, output_tokens) if output_tokens else reasoning,
        "total": total,
    }


def _subtract_usage(current: dict[str, int], previous: Optional[dict[str, int]]) -> dict[str, int]:
    if previous is None:
        return dict(current)
    # A resumed/restarted session can reset cumulative counters. Treat that as a new baseline.
    if current["total"] < previous["total"]:
        return dict(current)
    delta = {key: max(0, current[key] - previous.get(key, 0)) for key in METRIC_KEYS}
    delta["total"] = delta["input"] + delta["output"]
    return delta


@dataclass(slots=True)
class ScanResult:
    daily: dict[str, dict[str, int]]
    monthly: dict[str, dict[str, int]]
    total: dict[str, int]
    models: dict[str, dict[str, int]]
    index: dict[str, Any]
    files_seen: int
    files_scanned: int
    malformed_lines: int


class CodexUsageScanner:
    """Parse active and archived Codex JSONL logs without counting snapshots repeatedly."""

    INDEX_VERSION = 1

    def __init__(
        self,
        codex_homes: Optional[Iterable[Path]] = None,
        timezone_info: Optional[tzinfo] = None,
    ):
        self.codex_homes = [Path(path).expanduser().resolve() for path in (codex_homes or self._default_homes())]
        self.timezone_info = timezone_info or datetime.now().astimezone().tzinfo or timezone.utc

    @staticmethod
    def _default_homes() -> list[Path]:
        configured = os.environ.get("CODEX_HOME")
        if configured:
            homes = [Path(value.strip()) for value in configured.split(",") if value.strip()]
            if homes:
                return homes
        return [Path.home() / ".codex"]

    def scan(self, previous_index: Optional[dict[str, Any]] = None) -> ScanResult:
        timezone_key = str(self.timezone_info)
        valid_previous = (
            previous_index
            if isinstance(previous_index, dict)
            and previous_index.get("version") == self.INDEX_VERSION
            and previous_index.get("timezone") == timezone_key
            else {}
        )
        previous_files = valid_previous.get("files") if isinstance(valid_previous.get("files"), dict) else {}
        new_files: dict[str, Any] = {}
        files_scanned = 0

        for key, path in self._collect_files():
            try:
                stat = path.stat()
            except OSError:
                continue
            signature = [stat.st_mtime_ns, stat.st_size]
            cached = previous_files.get(key)
            if isinstance(cached, dict) and cached.get("signature") == signature:
                events = cached.get("events") if isinstance(cached.get("events"), list) else []
                malformed = _to_non_negative_int(cached.get("malformed_lines"))
            else:
                events, malformed = self._parse_file(path)
                files_scanned += 1
            new_files[key] = {
                "signature": signature,
                "events": events,
                "malformed_lines": malformed,
            }

        daily: dict[str, dict[str, int]] = {}
        monthly: dict[str, dict[str, int]] = {}
        total = _empty_metrics()
        models: dict[str, dict[str, int]] = {}
        fingerprints: set[str] = set()
        malformed_lines = 0

        for cached in new_files.values():
            malformed_lines += _to_non_negative_int(cached.get("malformed_lines"))
            for event in cached.get("events", []):
                if not isinstance(event, dict):
                    continue
                fingerprint = str(event.get("fingerprint") or "")
                if not fingerprint or fingerprint in fingerprints:
                    continue
                fingerprints.add(fingerprint)
                metrics = event.get("metrics")
                if not isinstance(metrics, dict):
                    continue
                normalized_metrics = {key: _to_non_negative_int(metrics.get(key)) for key in METRIC_KEYS}
                day = str(event.get("day") or "")
                month = day[:7]
                model = str(event.get("model") or "unknown")
                if len(day) != 10:
                    continue
                _add_metrics(daily.setdefault(day, _empty_metrics()), normalized_metrics)
                _add_metrics(monthly.setdefault(month, _empty_metrics()), normalized_metrics)
                _add_metrics(total, normalized_metrics)
                _add_metrics(models.setdefault(model, _empty_metrics()), normalized_metrics)

        index = {
            "version": self.INDEX_VERSION,
            "timezone": timezone_key,
            "files": new_files,
        }
        return ScanResult(
            daily=daily,
            monthly=monthly,
            total=total,
            models=models,
            index=index,
            files_seen=len(new_files),
            files_scanned=files_scanned,
            malformed_lines=malformed_lines,
        )

    def _collect_files(self) -> list[tuple[str, Path]]:
        collected: list[tuple[str, Path]] = []
        for home in self.codex_homes:
            seen_relative: set[str] = set()
            source_directories = [home / "sessions", home / "archived_sessions"]
            if not any(directory.is_dir() for directory in source_directories) and home.is_dir():
                source_directories = [home]
            for directory in source_directories:
                if not directory.is_dir():
                    continue
                try:
                    files = sorted(directory.rglob("*.jsonl"))
                except OSError:
                    continue
                for path in files:
                    try:
                        relative = path.relative_to(directory).as_posix()
                    except ValueError:
                        relative = path.name
                    if relative in seen_relative:
                        continue
                    seen_relative.add(relative)
                    key = f"{home.as_posix()}::{relative}"
                    collected.append((key, path))
        return collected

    def _parse_file(self, path: Path) -> tuple[list[dict[str, Any]], int]:
        events: list[dict[str, Any]] = []
        malformed = 0
        current_model = "unknown"
        previous_cumulative: Optional[dict[str, int]] = None

        try:
            handle = path.open("r", encoding="utf-8", errors="replace")
        except OSError:
            return events, 1

        with handle:
            for line in handle:
                if not line.strip():
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    malformed += 1
                    continue
                if not isinstance(entry, dict):
                    malformed += 1
                    continue

                payload = entry.get("payload")
                if not isinstance(payload, dict):
                    continue
                if entry.get("type") == "turn_context":
                    model = payload.get("model") or payload.get("model_name")
                    if isinstance(model, str) and model.strip():
                        current_model = model.strip()
                    continue
                if entry.get("type") != "event_msg" or payload.get("type") != "token_count":
                    continue

                info = payload.get("info")
                if not isinstance(info, dict):
                    malformed += 1
                    continue
                day = self._day_for_timestamp(entry.get("timestamp"))
                if day is None:
                    malformed += 1
                    continue

                model_value = (
                    info.get("model")
                    or info.get("model_name")
                    or payload.get("model")
                    or payload.get("model_name")
                    or current_model
                )
                model = str(model_value).strip() if model_value else "unknown"
                current_model = model

                last_usage = _normalized_usage(info.get("last_token_usage"))
                cumulative = _normalized_usage(info.get("total_token_usage"))
                metrics = last_usage or _subtract_usage(cumulative, previous_cumulative) if cumulative else last_usage
                if cumulative is not None:
                    previous_cumulative = cumulative
                if metrics is None or metrics["total"] <= 0:
                    continue

                timestamp_text = self._canonical_timestamp(entry.get("timestamp"))
                fingerprint_input = (
                    timestamp_text,
                    model,
                    *(metrics[key] for key in METRIC_KEYS),
                )
                fingerprint = hashlib.sha256(
                    json.dumps(fingerprint_input, separators=(",", ":")).encode("utf-8")
                ).hexdigest()[:32]
                events.append(
                    {
                        "day": day,
                        "model": model,
                        "metrics": metrics,
                        "fingerprint": fingerprint,
                    }
                )
        return events, malformed

    def _day_for_timestamp(self, value: Any) -> Optional[str]:
        parsed = self._parse_timestamp(value)
        if parsed is None:
            return None
        return parsed.astimezone(self.timezone_info).date().isoformat()

    def _canonical_timestamp(self, value: Any) -> str:
        parsed = self._parse_timestamp(value)
        if parsed is None:
            return str(value or "")
        return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")

    @staticmethod
    def _parse_timestamp(value: Any) -> Optional[datetime]:
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            seconds = float(value)
            if seconds > 10_000_000_000:
                seconds /= 1_000.0
            try:
                return datetime.fromtimestamp(seconds, tz=timezone.utc)
            except (OSError, OverflowError, ValueError):
                return None
        if not isinstance(value, str) or not value.strip():
            return None
        try:
            parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except ValueError:
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed
