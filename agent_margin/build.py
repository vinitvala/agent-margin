from __future__ import annotations

import json
import statistics
from collections import defaultdict
from pathlib import Path

from .attribution import ATTRIBUTED, NO_BRANCH, UNMATCHED_BRANCH, bucket_for_event
from .config import Config
from .cost import cost_for_event, total_cost
from .linear import get_issues, index_by_identifier
from .rollup import Allocation, build_project_ledger, build_ticket_ledgers, to_ledger_dict
from .walker import all_project_dirs, parse_events, parse_events_multi, project_dir_for_cwd


def _build_allocation(config: Config) -> Allocation | None:
    """Denominator is ALL local agent usage for the period, not just this
    project's -- scoped to one project, every project independently claims the
    full seat and the sum across projects exceeds what was actually paid."""
    if config.seat_cost_per_month is None:
        print("\nAllocation: skipped (no seat_cost_per_month configured).")
        return None

    dirs = all_project_dirs()
    all_events, _ = parse_events_multi(dirs, config.period_start, config.period_end)
    denominator = total_cost(all_events).total

    n_seats = config.n_seats
    if n_seats != 1:
        # This tool reads one machine's transcripts, so the denominator covers
        # one person's usage. Allocating N seats across it inflates every ticket
        # N-fold. Team-wide allocation needs team-wide transcripts -- a
        # collection problem, not a config value.
        print(f"\nAllocation: n_seats={n_seats} ignored -- the denominator covers only "
              f"this machine's transcripts, so allocating {n_seats} seats across one "
              f"person's usage would overstate every ticket. Forcing n_seats=1.")
        n_seats = 1

    print(f"\nAllocation: denominator ${denominator:,.2f} notional across "
          f"{len(dirs)} project dir(s), pool ${config.seat_cost_per_month * n_seats:,.2f}")
    return Allocation(
        seat_cost_per_month=config.seat_cost_per_month,
        n_seats=n_seats,
        denominator_notional=denominator,
    )


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

    allocation = _build_allocation(config)

    tickets = build_ticket_ledgers(
        events, issues_by_id, config.baseline_hours, config.blended_cost_rate, allocation
    )
    project = build_project_ledger(config, events, tickets, dict(bucket_totals), allocation)

    m = project.measured
    print(f"\nRollup: {len(tickets)} tickets attributed")
    print(f"  MEASURED  notional_token_cost=${m.notional_token_cost:,.2f}  "
          f"unattributed=${m.unattributed_cost:,.2f} ({m.unattributed_pct:.1%})")
    if m.allocated_seat_cost is not None:
        print(f"            project_capacity_share={m.project_capacity_share_pct:.1%}  "
              f"allocated_seat_cost=${m.allocated_seat_cost:,.2f}")
    else:
        print("            allocated_seat_cost=None (no seat_cost_per_month in config)")

    mod = project.modelled
    if mod.hours_saved is None:
        print(f"  MODELLED  all hours-based figures null "
              f"({project.tickets_with_baseline}/{project.tickets_total} tickets have a baseline)")
    else:
        print(f"  MODELLED  hours_saved={mod.hours_saved:.2f}  breakeven_hours={mod.breakeven_hours:.2f}  "
              f"gap_hours={mod.gap_hours:.2f}  gap_value=${mod.gap_value:,.2f}")
    print(f"  INPUTS    verified={project.inputs.verified}"
          + ("" if project.inputs.verified else "  <- derived figures are illustrative only"))

    # Verification step 3: ticket costs + unattributed must equal the project total.
    attributed_ticket_cost = sum(t.measured.notional_token_cost for t in tickets)
    check_total = attributed_ticket_cost + m.unattributed_cost
    if abs(check_total - m.notional_token_cost) > 0.005:
        print(f"  MISMATCH: ticket costs + unattributed (${check_total:,.2f}) "
              f"!= total (${m.notional_token_cost:,.2f})")
    else:
        print("  OK -- ticket costs + unattributed reconcile against the project total.")

    # Verification step 4: median should sit far below mean, or attribution is
    # smearing cost evenly across tickets instead of reflecting a real long tail.
    # Underpowered below ~15 tickets -- reported, but not treated as a signal.
    ticket_costs = [t.measured.notional_token_cost for t in tickets]
    if len(ticket_costs) >= 2:
        median_cost = statistics.median(ticket_costs)
        mean_cost = statistics.mean(ticket_costs)
        ratio = median_cost / mean_cost if mean_cost else 0.0
        print(f"  Distribution: median=${median_cost:,.4f}  mean=${mean_cost:,.4f}  ratio={ratio:.2f}")
        if len(ticket_costs) < 15:
            print(f"    n={len(ticket_costs)} -- too few tickets for this check to have power; "
                  f"not a signal either way.")
        elif ratio > 0.8:
            print("    WARNING: median close to mean -- cost may be smeared evenly, check attribution.")

    if allocation is not None:
        cost_basis = "allocated_seat_cost"
        cost_basis_note = (
            "Real seat cost apportioned by measured token share. True under both "
            "subscription and metered billing. notional_token_cost is retained as "
            "the allocation driver, not as a price paid."
        )
    else:
        cost_basis = "notional"
        cost_basis_note = (
            "Token counts priced at published API rates. Under a subscription no "
            "money is billed per token, so this is a proxy for agent effort, not "
            "spend. Set seat_cost_per_month in config to allocate real seat cost."
        )

    ledger = to_ledger_dict(config, project, tickets, cost_basis, cost_basis_note)
    ledger_path = Path("ledger.json")
    with ledger_path.open("w") as f:
        json.dump(ledger, f, indent=2)
    print(f"\nWrote {ledger_path}")
