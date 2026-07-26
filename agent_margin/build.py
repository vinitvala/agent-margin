from __future__ import annotations

from pathlib import Path

from .config import Config
from .walker import parse_events, project_dir_for_cwd


def run(config: Config) -> None:
    print(f"Config OK: {config.project_name} / {config.client_name}")
    print(f"Period: {config.period_start.isoformat()} .. {config.period_end.isoformat()}")

    project_dir = project_dir_for_cwd(Path.cwd())
    events, stats = parse_events(project_dir, config.period_start, config.period_end)

    print(f"\nProject dir: {project_dir}")
    print(f"Events parsed: {stats.event_count}")
    if stats.earliest and stats.latest:
        print(f"Date range: {stats.earliest.isoformat()} .. {stats.latest.isoformat()}")
    print(
        f"Skipped (no usage/timestamp): {stats.skipped_no_usage}  "
        f"Duplicate records collapsed: {stats.duplicate_records}  "
        f"Malformed lines: {stats.malformed_lines}"
    )
    print("\nCost engine, attribution, and rollup land in later tickets.")
