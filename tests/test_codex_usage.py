import json
import time
from datetime import timezone
from pathlib import Path

from codex_usage import CodexUsageScanner


def _usage(input_tokens, output_tokens, cached=0, reasoning=0):
    return {
        "input_tokens": input_tokens,
        "cached_input_tokens": cached,
        "output_tokens": output_tokens,
        "reasoning_output_tokens": reasoning,
        "total_tokens": input_tokens + output_tokens,
    }


def _token_event(timestamp, *, last=None, total=None, model="gpt-5.6-sol"):
    info = {"model": model}
    if last is not None:
        info["last_token_usage"] = last
    if total is not None:
        info["total_token_usage"] = total
    return {
        "timestamp": timestamp,
        "type": "event_msg",
        "payload": {"type": "token_count", "info": info},
    }


def _write_rollout(path: Path, events, malformed_lines=()):
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps(event) for event in events]
    lines.extend(malformed_lines)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_prefers_last_usage_and_falls_back_to_cumulative_delta(tmp_path):
    """Counting every cumulative sample would multiply the same tokens on each status event."""
    home = tmp_path / "codex"
    path = home / "sessions" / "2026" / "08" / "10" / "rollout-a.jsonl"
    _write_rollout(
        path,
        [
            _token_event(
                "2026-08-10T01:00:00Z",
                last=_usage(100, 10, cached=20, reasoning=3),
                total=_usage(100, 10, cached=20, reasoning=3),
            ),
            _token_event(
                "2026-08-10T02:00:00Z",
                total=_usage(180, 25, cached=30, reasoning=7),
            ),
        ],
    )

    result = CodexUsageScanner([home], timezone_info=timezone.utc).scan()

    assert result.daily["2026-08-10"] == {
        "input": 180,
        "cached_input": 30,
        "output": 25,
        "reasoning_output": 7,
        "total": 205,
    }
    assert result.monthly["2026-08"]["total"] == 205
    assert result.total["total"] == 205


def test_active_copy_wins_over_same_archived_relative_path(tmp_path):
    """Archived copies of an active rollout must not double count or replace newer usage."""
    home = tmp_path / "codex"
    relative = Path("2026/08/10/rollout-duplicate.jsonl")
    _write_rollout(
        home / "sessions" / relative,
        [_token_event("2026-08-10T01:00:00Z", last=_usage(120, 10))],
    )
    _write_rollout(
        home / "archived_sessions" / relative,
        [_token_event("2026-08-10T01:00:00Z", last=_usage(999, 100))],
    )

    result = CodexUsageScanner([home], timezone_info=timezone.utc).scan()

    assert result.total["input"] == 120
    assert result.total["output"] == 10
    assert result.files_seen == 1


def test_malformed_lines_are_skipped_and_reported(tmp_path):
    """One interrupted JSONL write must not make all historical usage unavailable."""
    home = tmp_path / "codex"
    _write_rollout(
        home / "sessions" / "rollout.jsonl",
        [_token_event("2026-08-10T01:00:00Z", last=_usage(50, 5))],
        malformed_lines=("{broken", "[]"),
    )

    result = CodexUsageScanner([home], timezone_info=timezone.utc).scan()

    assert result.total["total"] == 55
    assert result.malformed_lines == 2


def test_unchanged_files_are_reused_from_incremental_index(tmp_path):
    """A minute-level refresh must not reparse every historical rollout."""
    home = tmp_path / "codex"
    _write_rollout(
        home / "sessions" / "rollout.jsonl",
        [_token_event("2026-08-10T01:00:00Z", last=_usage(75, 5))],
    )
    scanner = CodexUsageScanner([home], timezone_info=timezone.utc)

    first = scanner.scan()
    second = scanner.scan(first.index)

    assert first.files_scanned == 1
    assert second.files_scanned == 0
    assert second.total == first.total


def test_changed_file_is_reparsed_and_replaces_cached_aggregate(tmp_path):
    """Appending a turn must update totals without adding the previous cached aggregate twice."""
    home = tmp_path / "codex"
    path = home / "sessions" / "rollout.jsonl"
    _write_rollout(
        path,
        [_token_event("2026-08-10T01:00:00Z", last=_usage(75, 5))],
    )
    scanner = CodexUsageScanner([home], timezone_info=timezone.utc)
    first = scanner.scan()
    time.sleep(0.002)
    _write_rollout(
        path,
        [
            _token_event("2026-08-10T01:00:00Z", last=_usage(75, 5)),
            _token_event("2026-08-10T02:00:00Z", last=_usage(25, 2)),
        ],
    )

    second = scanner.scan(first.index)

    assert second.files_scanned == 1
    assert second.total["input"] == 100
    assert second.total["output"] == 7


def test_replayed_token_event_across_subagent_rollouts_is_counted_once(tmp_path):
    """A child rollout replaying its parent's token event must not inflate daily usage."""
    home = tmp_path / "codex"
    replayed = _token_event("2026-08-10T01:00:00Z", last=_usage(200, 20), model="gpt-5.6-sol")
    _write_rollout(home / "sessions" / "root.jsonl", [replayed])
    _write_rollout(
        home / "sessions" / "child.jsonl",
        [
            replayed,
            _token_event("2026-08-10T02:00:00Z", last=_usage(30, 3), model="gpt-5.6-sol"),
        ],
    )

    result = CodexUsageScanner([home], timezone_info=timezone.utc).scan()

    assert result.total["input"] == 230
    assert result.total["output"] == 23


def test_turn_context_model_is_used_when_token_event_omits_model(tmp_path):
    """Older rollouts should be attributed to their real model instead of an invented default."""
    home = tmp_path / "codex"
    path = home / "sessions" / "rollout.jsonl"
    turn_context = {
        "timestamp": "2026-08-10T00:59:00Z",
        "type": "turn_context",
        "payload": {"model": "gpt-5.5-codex"},
    }
    event = _token_event("2026-08-10T01:00:00Z", last=_usage(40, 4), model=None)
    event["payload"]["info"].pop("model")
    _write_rollout(path, [turn_context, event])

    result = CodexUsageScanner([home], timezone_info=timezone.utc).scan()

    assert result.models["gpt-5.5-codex"]["total"] == 44


def test_multiple_codex_homes_are_aggregated_independently(tmp_path):
    """Work and personal CODEX_HOME values must both contribute without path-key collisions."""
    first_home = tmp_path / "work"
    second_home = tmp_path / "personal"
    relative = Path("sessions/rollout.jsonl")
    _write_rollout(first_home / relative, [_token_event("2026-08-10T01:00:00Z", last=_usage(10, 1))])
    _write_rollout(second_home / relative, [_token_event("2026-08-10T02:00:00Z", last=_usage(20, 2))])

    result = CodexUsageScanner([first_home, second_home], timezone_info=timezone.utc).scan()

    assert result.total["total"] == 33
    assert result.files_seen == 2
