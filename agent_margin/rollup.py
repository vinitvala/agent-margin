from __future__ import annotations

from collections import defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime

from .attribution import ATTRIBUTED, bucket_for_event
from .config import Config
from .cost import cost_for_event
from .walker import CostEvent


@dataclass
class TicketLedger:
    ticket_id: str
    title: str
    assignee: str | None
    state: str
    agent_cost: float
    session_count: int
    event_count: int
    first_seen: str
    last_seen: str
    estimate_points: float | None
    estimate_hours: float | None
    actual_hours: float | None
    hours_saved: float | None


@dataclass
class ProjectLedger:
    project: str
    client: str
    contract_value: float
    blended_cost_rate: float
    labour_cost: float
    agent_cost: float
    total_cogs: float
    gross_profit: float
    gross_margin_pct: float
    unattributed_cost: float
    unattributed_pct: float
    discount_given: float
    breakeven_hours: float
    hours_saved: float
    gap_hours: float
    gap_value: float


def _parse_dt(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def build_ticket_ledgers(
    events: list[CostEvent],
    issues_by_id: dict[str, dict],
    points_to_hours_factor: float,
) -> list[TicketLedger]:
    """Groups ATTRIBUTED events by ticket_id. A regex match whose ticket_id
    isn't in issues_by_id is excluded here -- it folds into unattributed_cost
    at the project level (VIN-10's honesty rule: don't silently pass through
    a ticket ID Linear doesn't recognise)."""
    per_ticket: dict[str, list[CostEvent]] = defaultdict(list)
    for event in events:
        bucket, ticket_id = bucket_for_event(event)
        if bucket == ATTRIBUTED and ticket_id in issues_by_id:
            per_ticket[ticket_id].append(event)

    tickets: list[TicketLedger] = []
    for ticket_id, ticket_events in per_ticket.items():
        issue = issues_by_id[ticket_id]
        agent_cost = sum(cost_for_event(e).total for e in ticket_events)
        session_ids = {e.session_id for e in ticket_events}
        timestamps = [e.timestamp for e in ticket_events]

        estimate_points = issue.get("estimate")
        estimate_hours = (
            estimate_points * points_to_hours_factor if estimate_points is not None else None
        )

        # actual_hours: real Linear state-transition duration (In Progress ->
        # Done), not a manual guess -- see linear.py's startedAt field.
        actual_hours = None
        started_at, completed_at = issue.get("startedAt"), issue.get("completedAt")
        if started_at and completed_at:
            actual_hours = (_parse_dt(completed_at) - _parse_dt(started_at)).total_seconds() / 3600

        hours_saved = None
        if estimate_hours is not None and actual_hours is not None:
            hours_saved = estimate_hours - actual_hours

        tickets.append(
            TicketLedger(
                ticket_id=ticket_id,
                title=issue.get("title") or "",
                assignee=(issue.get("assignee") or {}).get("name"),
                state=(issue.get("state") or {}).get("name") or "",
                agent_cost=agent_cost,
                session_count=len(session_ids),
                event_count=len(ticket_events),
                first_seen=min(timestamps).isoformat(),
                last_seen=max(timestamps).isoformat(),
                estimate_points=estimate_points,
                estimate_hours=estimate_hours,
                actual_hours=actual_hours,
                hours_saved=hours_saved,
            )
        )

    tickets.sort(key=lambda t: t.ticket_id)
    return tickets


def build_project_ledger(
    config: Config,
    events: list[CostEvent],
    tickets: list[TicketLedger],
) -> ProjectLedger:
    total_agent_cost = sum(cost_for_event(e).total for e in events)
    attributed_cost = sum(t.agent_cost for t in tickets)
    unattributed_cost = total_agent_cost - attributed_cost
    unattributed_pct = (unattributed_cost / total_agent_cost) if total_agent_cost else 0.0

    total_actual_hours = sum(t.actual_hours for t in tickets if t.actual_hours is not None)
    labour_cost = total_actual_hours * config.blended_cost_rate
    total_cogs = labour_cost + total_agent_cost
    gross_profit = config.contract_value - total_cogs
    gross_margin_pct = (gross_profit / config.contract_value) if config.contract_value else 0.0

    hours_saved = sum(t.hours_saved for t in tickets if t.hours_saved is not None)
    breakeven_hours = (config.discount_given + total_agent_cost) / config.blended_cost_rate
    gap_hours = breakeven_hours - hours_saved
    gap_value = gap_hours * config.blended_cost_rate

    return ProjectLedger(
        project=config.project_name,
        client=config.client_name,
        contract_value=config.contract_value,
        blended_cost_rate=config.blended_cost_rate,
        labour_cost=labour_cost,
        agent_cost=total_agent_cost,
        total_cogs=total_cogs,
        gross_profit=gross_profit,
        gross_margin_pct=gross_margin_pct,
        unattributed_cost=unattributed_cost,
        unattributed_pct=unattributed_pct,
        discount_given=config.discount_given,
        breakeven_hours=breakeven_hours,
        hours_saved=hours_saved,
        gap_hours=gap_hours,
        gap_value=gap_value,
    )


def to_ledger_dict(project: ProjectLedger, tickets: list[TicketLedger]) -> dict:
    return {
        "project": asdict(project),
        "tickets": [asdict(t) for t in tickets],
    }
