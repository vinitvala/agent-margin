from __future__ import annotations

from pathlib import Path

from collections import defaultdict

from .attribution import ATTRIBUTED, NO_BRANCH, UNMATCHED_BRANCH, bucket_for_event
from .config import Config
from .cost import cost_for_event, total_cost
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

    bucket_totals = defaultdict(float)
    bucket_counts = defaultdict(int)
    ticket_ids_seen = defaultdict(set)
    for event in events:
        bucket, ticket_id = bucket_for_event(event)
        bucket_totals[bucket] += cost_for_event(event).total
        bucket_counts[bucket] += 1
        if ticket_id:
            ticket_ids_seen[bucket].add(ticket_id)

    bucket_sum = sum(bucket_totals.values())
    print("\nGATE 2 -- attribution buckets (regex-matched; Linear existence checked in the next stage):")
    for bucket, label in (
        (ATTRIBUTED, "attributed"),
        (UNMATCHED_BRANCH, "unmatched branch"),
        (NO_BRANCH, "no branch"),
    ):
        pct = (bucket_totals[bucket] / breakdown.total * 100) if breakdown.total else 0.0
        print(
            f"  {label:18s} ${bucket_totals[bucket]:>8,.2f}  ({pct:5.1f}%)  "
            f"{bucket_counts[bucket]:>4} events"
            + (f"  tickets: {sorted(ticket_ids_seen[bucket])}" if ticket_ids_seen[bucket] else "")
        )
    print(f"  {'sum':18s} ${bucket_sum:>8,.2f}   vs total ${breakdown.total:,.2f}")
    if abs(bucket_sum - breakdown.total) > 0.005:
        print("  MISMATCH -- bucket totals do not sum to total cost. Records are being dropped.")
    else:
        print("  OK -- bucket totals reconcile against total cost.")

    print("\nLinear enrichment and rollup land in later tickets.")
