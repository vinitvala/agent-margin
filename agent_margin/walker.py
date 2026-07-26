from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

CLAUDE_PROJECTS_ROOT = Path.home() / ".claude" / "projects"


@dataclass(frozen=True)
class CostEvent:
    uuid: str
    message_id: str
    session_id: str
    timestamp: datetime
    cwd: str
    git_branch: str | None
    model: str
    input_tokens: int
    output_tokens: int
    # cache_creation_input_tokens splits by TTL with different prices (see cost.py).
    # Older records may lack the ephemeral_* breakdown; when absent, the whole
    # amount is treated as 5m (Anthropic's default TTL) rather than silently dropped.
    cache_creation_1h_tokens: int
    cache_creation_5m_tokens: int
    cache_read_tokens: int
    is_sidechain: bool


@dataclass
class WalkStats:
    event_count: int = 0
    skipped_no_usage: int = 0
    malformed_lines: int = 0
    duplicate_records: int = 0
    earliest: datetime | None = None
    latest: datetime | None = None


def project_dir_for_cwd(cwd: Path, claude_root: Path = CLAUDE_PROJECTS_ROOT) -> Path:
    encoded = str(cwd).replace("/", "-")
    return claude_root / encoded


def _parse_ts(value: str) -> datetime:
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _session_files(project_dir: Path):
    if not project_dir.exists():
        return []
    return sorted(project_dir.glob("*.jsonl"))


def parse_events(
    project_dir: Path,
    period_start: datetime | None = None,
    period_end: datetime | None = None,
) -> tuple[list[CostEvent], WalkStats]:
    events: list[CostEvent] = []
    stats = WalkStats()
    seen_keys: set[str] = set()

    for path in _session_files(project_dir):
        with path.open(encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    stats.malformed_lines += 1
                    continue

                if record.get("type") != "assistant":
                    continue

                message = record.get("message") or {}
                usage = message.get("usage")
                if not usage:
                    stats.skipped_no_usage += 1
                    continue

                timestamp_raw = record.get("timestamp")
                if not timestamp_raw:
                    stats.skipped_no_usage += 1
                    continue
                timestamp = _parse_ts(timestamp_raw)

                if period_start is not None and timestamp < period_start:
                    continue
                if period_end is not None and timestamp > period_end:
                    continue

                # One logical API turn can be split across multiple JSONL lines
                # (one per content block, e.g. "thinking" + "text"), each with a
                # distinct top-level uuid but the same message.id and an identical
                # copy of that turn's usage. Deduping on uuid alone double-counts
                # these. message.id is the real per-API-call identity.
                dedup_key = message.get("id") or record.get("uuid")
                if dedup_key in seen_keys:
                    stats.duplicate_records += 1
                    continue
                seen_keys.add(dedup_key)

                cache_creation = usage.get("cache_creation")
                creation_total = usage.get("cache_creation_input_tokens") or 0
                if cache_creation:
                    tokens_1h = cache_creation.get("ephemeral_1h_input_tokens") or 0
                    tokens_5m = cache_creation.get("ephemeral_5m_input_tokens") or 0
                else:
                    tokens_1h = 0
                    tokens_5m = creation_total

                event = CostEvent(
                    uuid=record.get("uuid", ""),
                    message_id=message.get("id", ""),
                    session_id=record.get("sessionId", path.stem),
                    timestamp=timestamp,
                    cwd=record.get("cwd", ""),
                    git_branch=record.get("gitBranch") or None,
                    model=message.get("model", ""),
                    input_tokens=usage.get("input_tokens") or 0,
                    output_tokens=usage.get("output_tokens") or 0,
                    cache_creation_1h_tokens=tokens_1h,
                    cache_creation_5m_tokens=tokens_5m,
                    cache_read_tokens=usage.get("cache_read_input_tokens") or 0,
                    is_sidechain=bool(record.get("isSidechain", False)),
                )
                events.append(event)
                stats.event_count += 1
                if stats.earliest is None or timestamp < stats.earliest:
                    stats.earliest = timestamp
                if stats.latest is None or timestamp > stats.latest:
                    stats.latest = timestamp

    return events, stats
