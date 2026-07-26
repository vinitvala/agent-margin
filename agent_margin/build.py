from __future__ import annotations

import json
import statistics
from collections import defaultdict
from pathlib import Path

from .attribution import ATTRIBUTED, NO_BRANCH, UNMATCHED_BRANCH, bucket_for_event
from .config import Config
from .cost import cost_for_event, total_cost
from .linear import get_issues, index_by_identifier
from .rollup import build_project_ledger, build_ticket_ledgers, to_ledger_dict
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

    issues = get_issues(config.linear_api_key)
    issues_by_id = index_by_identifier(issues)
    print(f"\nLinear: {len(issues)} issues loaded (cached at .cache/linear_cache.json)")

    unresolved = sorted(ticket_ids_seen[ATTRIBUTED] - issues_by_id.keys())
    if unresolved:
        print(
            f"  WARNING: {len(unresolved)} regex-matched ticket ID(s) not found in "
            f"Linear -- will fold into unattributed at rollup: {unresolved}"
        )
    else:
        print("  All regex-matched ticket IDs resolved against Linear.")

    tickets = build_ticket_ledgers(events, issues_by_id, config.points_to_hours_factor)
    project = build_project_ledger(config, events, tickets)

    print(f"\nRollup: {len(tickets)} tickets attributed")
    print(
        f"  agent_cost=${project.agent_cost:,.2f}  labour_cost=${project.labour_cost:,.2f}  "
        f"total_cogs=${project.total_cogs:,.2f}"
    )
    print(
        f"  gross_profit=${project.gross_profit:,.2f}  gross_margin={project.gross_margin_pct:.1%}  "
        f"unattributed=${project.unattributed_cost:,.2f} ({project.unattributed_pct:.1%})"
    )
    print(
        f"  breakeven_hours={project.breakeven_hours:.2f}  hours_saved={project.hours_saved:.2f}  "
        f"gap_hours={project.gap_hours:.2f}  gap_value=${project.gap_value:,.2f}"
    )

    # Verification step 3: buckets + unattributed must equal the whole-project total.
    attributed_ticket_cost = sum(t.agent_cost for t in tickets)
    check_total = attributed_ticket_cost + project.unattributed_cost
    if abs(check_total - project.agent_cost) > 0.005:
        print(f"  MISMATCH: ticket costs + unattributed (${check_total:,.2f}) != agent_cost (${project.agent_cost:,.2f})")
    else:
        print("  OK -- ticket costs + unattributed reconcile against total agent_cost.")

    # Verification step 4: median should sit far below mean, or attribution is
    # smearing cost evenly across tickets instead of reflecting a real long tail.
    ticket_costs = [t.agent_cost for t in tickets]
    if len(ticket_costs) >= 2:
        median_cost = statistics.median(ticket_costs)
        mean_cost = statistics.mean(ticket_costs)
        print(f"  Distribution check: median=${median_cost:,.4f}  mean=${mean_cost:,.4f}")
        if mean_cost > 0 and median_cost / mean_cost > 0.8:
            print("  WARNING: median is close to mean -- cost may be smeared evenly, check attribution.")

    ledger = to_ledger_dict(project, tickets)
    ledger_path = Path("ledger.json")
    with ledger_path.open("w") as f:
        json.dump(ledger, f, indent=2)
    print(f"\nWrote {ledger_path}")
