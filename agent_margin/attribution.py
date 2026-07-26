from __future__ import annotations

import re

from .walker import CostEvent

# Linear's default branch format is username/eng-123-short-title, so the ID
# sits after the first "/". Uppercase the captured group.
TICKET_ID_RE = re.compile(r"(?:^|[/_-])([A-Z][A-Z0-9]{1,9}-\d+)", re.IGNORECASE)

ATTRIBUTED = "attributed"
UNMATCHED_BRANCH = "unmatched_branch"
NO_BRANCH = "no_branch"


def extract_ticket_id(git_branch: str | None) -> str | None:
    if not git_branch:
        return None
    match = TICKET_ID_RE.search(git_branch)
    if not match:
        return None
    return match.group(1).upper()


def bucket_for_event(event: CostEvent) -> tuple[str, str | None]:
    """Regex-only classification. "attributed" here means the branch matched
    the ticket pattern -- whether that ticket ID actually exists in Linear is
    confirmed later once the Linear pull (VIN-10) has run, per the spec's own
    build order (attribution before Linear pull)."""
    if not event.git_branch:
        return NO_BRANCH, None
    ticket_id = extract_ticket_id(event.git_branch)
    if ticket_id is None:
        return UNMATCHED_BRANCH, None
    return ATTRIBUTED, ticket_id
