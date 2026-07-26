from __future__ import annotations

from pathlib import Path

from .config import Config
from .cost import total_cost
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

    breakdown = total_cost(events)
    cache_write = breakdown.cache_write_1h_cost + breakdown.cache_write_5m_cost
    print(f"\nTotal computed spend (this project dir): ${breakdown.total:,.2f}")
    print(
        f"  input=${breakdown.input_cost:,.2f}  "
        f"cache_write_1h=${breakdown.cache_write_1h_cost:,.2f}  "
        f"cache_write_5m=${breakdown.cache_write_5m_cost:,.2f}  "
        f"cache_read=${breakdown.cache_read_cost:,.2f}  "
        f"output=${breakdown.output_cost:,.2f}"
    )
    if breakdown.total > 0:
        print(
            f"  cache_read is {breakdown.cache_read_cost / breakdown.total:.1%} of cost, "
            f"cache_write is {cache_write / breakdown.total:.1%} of cost"
        )

    print("\nAttribution and rollup land in later tickets.")
