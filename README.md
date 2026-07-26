# Agent Margin

Agencies bill clients a fixed fee, then burn a variable, invisible amount of
AI coding-agent spend underneath. Clients now expect a discount because "you
use AI," and agencies concede without knowing what AI actually saved them.

Agent Margin reads Claude Code session transcripts, attributes every dollar
of agent spend to a specific Linear ticket, rolls it up to a project P&L,
and answers one question: **did the discount you gave break even?**

See [parser-spec.md](parser-spec.md) for the full technical spec (data
shapes, cost formula, join logic, failure modes, build order).

## Quickstart

```bash
pip install -r requirements.txt
cp config.example.yaml config.yaml   # fill in real values -- gitignored
python -m agent_margin build          # writes ledger.json
```

Open `agent-margin-mvp.html` over a local HTTP server (fetch() of local
JSON is blocked over `file://`):

```bash
python -m http.server 8000
```

`python -m agent_margin reconcile` sums cost across **all** local
`~/.claude/projects/` directories, for comparison against the Anthropic
Console usage page (see "Cost basis" below for when that comparison is
meaningful).

## Constraints

These are fixed for this build, not defaults to be revisited mid-session:

- **Python, standard library plus `requests` and `pyyaml`.** No framework,
  no database, no ORM.
- **Output is a single `ledger.json`.** `agent-margin-mvp.html` reads it;
  there is no other frontend.
- **Config lives in one `config.yaml`**: contract value, blended cost rate,
  discount given, points-to-hours factor, client name, project name, Linear
  API key and team key, reporting period. No settings UI -- edit the file.
- **Single project, single client.** No auth, no database, no accounts,
  no multi-tenancy.
- **CLI entry point:** `python -m agent_margin build` writes `ledger.json`.

## Non-goals

Deliberately out of scope. If a future request asks for one of these, the
answer is "that's on the cut list," not a rebuild:

- Auth, a database, a web server.
- GitHub, Jira, Stripe, or Zendesk integrations.
- Real-time updates, charts, a landing page.
- A settings UI for `config.yaml`.
- Automated tests beyond the four verification steps in `parser-spec.md`.
- Anything that isn't on the path to `ledger.json`.

## Cost basis: notional, not necessarily metered

Costs are computed as token counts priced at Anthropic's **published API
rates**. If Claude Code is authenticated via a subscription (Pro/Max)
rather than a metered API key, nothing is actually billed per token, and
the Anthropic Console usage page will show zero regardless of real usage.
In that case every `agent_cost` figure here is a **shadow cost** -- a proxy
for AI effort per ticket, useful for comparing against the discount given,
but not literal money paid out. This was confirmed against a real Console
usage page during this build's Gate 1; see git history on `master` for
specifics.

## Known limitations (see parser-spec.md section 7 for the full list)

- A branch with multiple ticket IDs attributes to the first one found.
- A regex-matched ticket ID not present in Linear folds into
  `unattributed_cost` rather than appearing as a phantom ticket.
- `actual_hours` comes from Linear's own `startedAt` -> `completedAt`
  state-transition timestamps, not a hand-entered number. A ticket left
  "In Progress" for reasons unrelated to active work (e.g. over a
  weekend) will inflate its `actual_hours`.
- Same repo, two clients is out of scope -- config assumes one project.

## Pipeline

```
walker.py       walk ~/.claude/projects/*.jsonl, dedup on message.id, emit CostEvent rows
cost.py         price events (cache-write TTL aware), unknown model raises
attribution.py  regex-extract ticket ID from git_branch, bucket attributed/unmatched/no-branch
linear.py       pull issues via GraphQL, cache to .cache/linear_cache.json
rollup.py       join events -> tickets -> TicketLedger / ProjectLedger
build.py        orchestrates the above, writes ledger.json
reconcile.py    Gate-1-style cost total across all local sessions
```
