from __future__ import annotations

from collections import defaultdict
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone

from .attribution import ATTRIBUTED, bucket_for_event
from .config import Config
from .cost import cost_for_event
from .walker import CostEvent

# The ledger is split into three zones so a consumer cannot mistake a
# fabricated figure for an observed one:
#
#   measured  -- derived only from transcript records and Linear timestamps
#   modelled  -- rests on human-supplied assumptions; null when none supplied
#   inputs    -- config constants, flagged verified/unverified
#
# v0 emitted these interleaved and shipped a $13,560 headline built from
# story points multiplied by an arbitrary constant. Hence the separation.


@dataclass
class Allocation:
    """Under a subscription the real cost is the seat, not the tokens. Token
    spend becomes the usage driver that allocates that fixed cost across
    tickets -- ordinary activity-based costing.

    denominator_notional MUST be total agent usage across every local session
    for the period, not just this project's. Scoped to one project, every
    project independently claims the full seat and the sum across projects
    exceeds what was actually paid."""

    seat_cost_per_month: float
    n_seats: int
    denominator_notional: float

    @property
    def pool(self) -> float:
        return self.seat_cost_per_month * self.n_seats


@dataclass
class ProjectDirUsage:
    """One Claude Code project directory = one working tree. Across a real
    agency these stand in for separate clients, which is what makes the
    allocation mechanism legible: the seat is shared, and this is the split."""

    dir_name: str
    notional_token_cost: float
    capacity_share_pct: float
    allocated_seat_cost: float
    event_count: int
    is_current_project: bool


@dataclass
class TicketMeasured:
    notional_token_cost: float
    # Share of all agent capacity consumed on this machine for the period.
    # Purely measured: a ratio of token spend, no price assumption survives it.
    capacity_share_pct: float | None
    # capacity_share_pct x (seat cost x seats). Real money, apportioned -- the
    # figure that is true under subscription and metered billing alike.
    allocated_seat_cost: float | None
    session_count: int
    event_count: int
    first_seen: str
    last_seen: str
    # Wall-clock between Linear's "In Progress" and "Done" transitions. NOT
    # human effort and NOT agent effort -- a ticket left open over a weekend
    # reads as days. Named for what it is so it can't be read as hours worked.
    linear_cycle_time_hours: float | None


@dataclass
class TicketModelled:
    estimate_points: float | None
    baseline_hours: float | None
    hours_saved: float | None
    net_value: float | None


@dataclass
class TicketLedger:
    ticket_id: str
    title: str
    assignee: str | None
    state: str
    measured: TicketMeasured
    modelled: TicketModelled


@dataclass
class ProjectMeasured:
    notional_token_cost: float
    attributed_cost: float
    unattributed_cost: float
    unattributed_pct: float
    # Share of this machine's total agent capacity that went to this project,
    # and the seat cost that share claims. None when no seat cost is configured.
    project_capacity_share_pct: float | None
    allocated_seat_cost: float | None
    seat_cost_basis: str | None
    # Every project directory on this machine, not just the current one.
    capacity_by_project_dir: list[dict]
    ticket_count: int
    event_count: int
    session_count: int
    buckets: dict


@dataclass
class ProjectModelled:
    baseline_hours_total: float | None
    hours_saved: float | None
    labour_cost: float | None
    total_cogs: float | None
    gross_profit: float | None
    gross_margin_pct: float | None
    breakeven_hours: float | None
    gap_hours: float | None
    gap_value: float | None
    basis: str


@dataclass
class ProjectInputs:
    project: str
    client: str
    contract_value: float
    discount_given: float
    blended_cost_rate: float
    verified: bool
    note: str


@dataclass
class ProjectLedger:
    inputs: ProjectInputs
    measured: ProjectMeasured
    modelled: ProjectModelled
    tickets_with_baseline: int = 0
    tickets_total: int = 0


@dataclass
class LedgerMeta:
    generated_at: str
    period_start: str
    period_end: str
    cost_basis: str
    cost_basis_note: str
    zones: dict = field(default_factory=dict)


def _parse_dt(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def build_ticket_ledgers(
    events: list[CostEvent],
    issues_by_id: dict[str, dict],
    baseline_hours: dict[str, float],
    blended_cost_rate: float,
    allocation: Allocation | None = None,
) -> list[TicketLedger]:
    """Groups ATTRIBUTED events by ticket_id. A regex match whose ticket_id
    isn't in issues_by_id is excluded here -- it folds into unattributed_cost
    at the project level rather than appearing as a phantom ticket."""
    per_ticket: dict[str, list[CostEvent]] = defaultdict(list)
    for event in events:
        bucket, ticket_id = bucket_for_event(event)
        if bucket == ATTRIBUTED and ticket_id in issues_by_id:
            per_ticket[ticket_id].append(event)

    tickets: list[TicketLedger] = []
    for ticket_id, ticket_events in per_ticket.items():
        issue = issues_by_id[ticket_id]
        agent_cost = sum(cost_for_event(e).total for e in ticket_events)
        timestamps = [e.timestamp for e in ticket_events]

        cycle_time_hours = None
        started_at, completed_at = issue.get("startedAt"), issue.get("completedAt")
        if started_at and completed_at:
            cycle_time_hours = (
                _parse_dt(completed_at) - _parse_dt(started_at)
            ).total_seconds() / 3600

        # Only a human-supplied baseline produces hours-based output. No
        # points-times-factor fallback: that is what manufactured v0's headline.
        capacity_share = None
        allocated_seat_cost = None
        if allocation is not None and allocation.denominator_notional > 0:
            capacity_share = agent_cost / allocation.denominator_notional
            allocated_seat_cost = capacity_share * allocation.pool

        baseline = baseline_hours.get(ticket_id)
        hours_saved = None
        net_value = None
        if baseline is not None and cycle_time_hours is not None:
            hours_saved = baseline - cycle_time_hours
            # Net against allocated seat cost when available -- that's the real
            # money. Falls back to notional only when no seat cost is supplied.
            cost_basis = allocated_seat_cost if allocated_seat_cost is not None else agent_cost
            net_value = hours_saved * blended_cost_rate - cost_basis

        tickets.append(
            TicketLedger(
                ticket_id=ticket_id,
                title=issue.get("title") or "",
                assignee=(issue.get("assignee") or {}).get("name"),
                state=(issue.get("state") or {}).get("name") or "",
                measured=TicketMeasured(
                    notional_token_cost=agent_cost,
                    capacity_share_pct=capacity_share,
                    allocated_seat_cost=allocated_seat_cost,
                    session_count=len({e.session_id for e in ticket_events}),
                    event_count=len(ticket_events),
                    first_seen=min(timestamps).isoformat(),
                    last_seen=max(timestamps).isoformat(),
                    linear_cycle_time_hours=cycle_time_hours,
                ),
                modelled=TicketModelled(
                    estimate_points=issue.get("estimate"),
                    baseline_hours=baseline,
                    hours_saved=hours_saved,
                    net_value=net_value,
                ),
            )
        )

    tickets.sort(key=lambda t: t.ticket_id)
    return tickets


def build_project_ledger(
    config: Config,
    events: list[CostEvent],
    tickets: list[TicketLedger],
    bucket_totals: dict[str, float],
    allocation: Allocation | None = None,
    dir_usage: list[ProjectDirUsage] | None = None,
) -> ProjectLedger:
    total_agent_cost = sum(cost_for_event(e).total for e in events)
    attributed_cost = sum(t.measured.notional_token_cost for t in tickets)
    unattributed_cost = total_agent_cost - attributed_cost
    unattributed_pct = (unattributed_cost / total_agent_cost) if total_agent_cost else 0.0

    project_share = None
    project_allocated = None
    seat_basis = None
    if allocation is not None and allocation.denominator_notional > 0:
        project_share = total_agent_cost / allocation.denominator_notional
        project_allocated = project_share * allocation.pool
        seat_basis = (
            f"${allocation.seat_cost_per_month:,.2f}/month x {allocation.n_seats} seat(s) "
            f"allocated by share of all local agent usage for the period. This is real "
            f"money apportioned by a measured usage driver, not a token price."
        )

    with_baseline = [t for t in tickets if t.modelled.hours_saved is not None]

    if with_baseline:
        baseline_total = sum(t.modelled.baseline_hours for t in with_baseline)
        hours_saved = sum(t.modelled.hours_saved for t in with_baseline)
        labour_cost = sum(
            t.measured.linear_cycle_time_hours * config.blended_cost_rate
            for t in with_baseline
            if t.measured.linear_cycle_time_hours is not None
        )
        # Real money where we have it: allocated seat cost, else notional.
        ai_cost_basis = project_allocated if project_allocated is not None else total_agent_cost
        total_cogs = labour_cost + ai_cost_basis
        gross_profit = config.contract_value - total_cogs
        gross_margin_pct = (
            (gross_profit / config.contract_value) if config.contract_value else None
        )
        breakeven_hours = (
            config.discount_given + ai_cost_basis
        ) / config.blended_cost_rate
        gap_hours = breakeven_hours - hours_saved
        gap_value = gap_hours * config.blended_cost_rate
        basis = (
            f"{len(with_baseline)} of {len(tickets)} tickets have a human-supplied "
            f"baseline_hours figure. Hours-based output covers only those tickets. "
            f"Labour cost uses Linear cycle time, which is wall-clock, not effort."
        )
    else:
        baseline_total = hours_saved = labour_cost = None
        total_cogs = gross_profit = gross_margin_pct = None
        breakeven_hours = gap_hours = gap_value = None
        basis = (
            "No baseline_hours supplied in config, so no hours-based figure is "
            "computed. Break-even against the discount cannot be answered without "
            "a human standing behind an estimate of what the work would have taken "
            "without AI. Measured agent cost and attribution below are unaffected."
        )

    inputs_note = (
        "Confirmed against a real engagement."
        if config.inputs_verified
        else (
            "UNVERIFIED -- contract_value, discount_given and blended_cost_rate are "
            "config constants that no one has confirmed correspond to a real "
            "engagement. Any figure derived from them is illustrative only."
        )
    )

    return ProjectLedger(
        inputs=ProjectInputs(
            project=config.project_name,
            client=config.client_name,
            contract_value=config.contract_value,
            discount_given=config.discount_given,
            blended_cost_rate=config.blended_cost_rate,
            verified=config.inputs_verified,
            note=inputs_note,
        ),
        measured=ProjectMeasured(
            notional_token_cost=total_agent_cost,
            attributed_cost=attributed_cost,
            unattributed_cost=unattributed_cost,
            unattributed_pct=unattributed_pct,
            project_capacity_share_pct=project_share,
            allocated_seat_cost=project_allocated,
            seat_cost_basis=seat_basis,
            capacity_by_project_dir=[asdict(d) for d in (dir_usage or [])],
            ticket_count=len(tickets),
            event_count=len(events),
            session_count=len({e.session_id for e in events}),
            buckets=dict(bucket_totals),
        ),
        modelled=ProjectModelled(
            baseline_hours_total=baseline_total,
            hours_saved=hours_saved,
            labour_cost=labour_cost,
            total_cogs=total_cogs,
            gross_profit=gross_profit,
            gross_margin_pct=gross_margin_pct,
            breakeven_hours=breakeven_hours,
            gap_hours=gap_hours,
            gap_value=gap_value,
            basis=basis,
        ),
        tickets_with_baseline=len(with_baseline),
        tickets_total=len(tickets),
    )


def to_ledger_dict(
    config: Config,
    project: ProjectLedger,
    tickets: list[TicketLedger],
    cost_basis: str,
    cost_basis_note: str,
) -> dict:
    meta = LedgerMeta(
        generated_at=datetime.now(timezone.utc).isoformat(),
        period_start=config.period_start.isoformat(),
        period_end=config.period_end.isoformat(),
        cost_basis=cost_basis,
        cost_basis_note=cost_basis_note,
        zones={
            "measured": "Derived only from Claude Code transcript records and Linear timestamps.",
            "modelled": "Rests on human-supplied assumptions. Null when none supplied.",
            "inputs": "Config constants. Check inputs.verified before quoting anything derived from them.",
        },
    )
    return {
        "meta": asdict(meta),
        "project": asdict(project),
        "tickets": [asdict(t) for t in tickets],
    }
