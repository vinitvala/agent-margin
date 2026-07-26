from __future__ import annotations

from .config import Config
from .cost import total_cost
from .walker import CLAUDE_PROJECTS_ROOT, all_project_dirs, parse_events_multi


def run(config: Config) -> None:
    dirs = all_project_dirs()
    print(f"Scanning {len(dirs)} project director{'y' if len(dirs) == 1 else 'ies'} under {CLAUDE_PROJECTS_ROOT}")
    for d in dirs:
        print(f"  - {d.name}")

    events, stats = parse_events_multi(dirs, config.period_start, config.period_end)

    print(f"\nEvents parsed: {stats.event_count}")
    if stats.earliest and stats.latest:
        print(f"Date range: {stats.earliest.isoformat()} .. {stats.latest.isoformat()}")
    print(
        f"Skipped (no usage/timestamp): {stats.skipped_no_usage}  "
        f"Duplicate records collapsed: {stats.duplicate_records}  "
        f"Malformed lines: {stats.malformed_lines}"
    )

    breakdown = total_cost(events)
    cache_write = breakdown.cache_write_1h_cost + breakdown.cache_write_5m_cost
    print(f"\nTOTAL COMPUTED SPEND (all local sessions, this machine): ${breakdown.total:,.2f}")
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

    print(
        "\nCompare this total against the Anthropic Console usage page for the "
        "same window (https://console.anthropic.com/settings/usage). Should land "
        "within a few percent. Off by ~5x means the cache multipliers are wrong.\n"
        "\n"
        "NOTE: if Claude Code is authenticated via a Claude subscription (Pro/Max) "
        "rather than a metered Console API key, the Console usage page will show "
        "zero regardless of real token usage -- subscription spend isn't billed "
        "per-token. In that case there is nothing to reconcile against, and every "
        "cost figure this tool produces is a NOTIONAL cost: what the tokens would "
        "have cost at Anthropic's published pay-as-you-go rates, not money actually "
        "billed. Still a valid proxy for AI effort per ticket against the discount "
        "given -- just not literal metered spend."
    )
