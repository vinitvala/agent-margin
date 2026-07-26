# Agent Margin

Agencies bill clients a fixed fee, then burn a variable, invisible amount of
AI coding-agent spend underneath. Clients now expect a discount because "you
use AI," and agencies concede without knowing what AI actually saved them.

Agent Margin reads Claude Code session transcripts, attributes every dollar
of agent spend to a specific Linear ticket, rolls it up to a project P&L,
and answers one question: **did the discount you gave break even?**

See [parser-spec.md](parser-spec.md) for the full technical spec (data
shapes, cost formula, join logic, failure modes, build order).

## Prerequisites -- read this before pointing at a new project

Agent Margin does **not** read a repo's code or clone anything from GitHub.
It reads Claude Code's own session transcripts, which live locally at
`~/.claude/projects/<encoded-cwd>/*.jsonl` -- one folder per local working
directory Claude Code has actually been run in. That means, for any project
you want to run this against:

1. **You need a local checkout of that project**, and Claude Code must have
   **already been used in it** (the transcript history has to exist before
   there's anything to attribute -- a bare GitHub URL gives this tool
   nothing to read).
2. **You must run `python -m agent_margin build` from inside that project's
   directory.** The tool infers which transcript folder to scan from your
   current working directory when you invoke it.
3. **That project's Linear tickets need branch names matching the
   `TEAM-123` pattern** (see `parser-spec.md` section 4) -- otherwise every
   session falls into the unmatched-branch bucket.
4. The `agent_margin/` package and a filled-in `config.yaml` need to be
   reachable from that directory. v0 isn't pip-installable yet, so in
   practice that means copying this repo's `agent_margin/` folder and a
   `config.yaml` into (or alongside) the target project -- see "Known
   limitations" below.

## Quickstart

```bash
pip install -r requirements.txt
cp config.example.yaml config.yaml   # fill in real values -- gitignored
python -m agent_margin build          # run from inside the target project's
                                      # own directory -- writes ledger.json there
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
  discount given, seat cost, client name, project name, Linear API key and
  team key, reporting period, and per-ticket `baseline_hours`. No settings
  UI -- edit the file.
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

## Cost basis: allocation, not a token price

Under a Claude subscription (Pro/Max) **no money is billed per token** — the
seat is a fixed cost, and the Anthropic Console shows zero usage regardless
of how much the agent actually did. Telling a client "your agent spend on
this project was $5,533" would therefore be false.

So token cost is not used as a price. It is used as an **allocation driver**
— ordinary activity-based costing over a real fixed cost:

```
allocated_seat_cost(ticket) =
    (ticket_notional / all_local_notional) x seat_cost_per_month x n_seats
```

The claim becomes "this ticket consumed 11% of that developer's agent
capacity, so 11% of their seat lands on it" — true under subscription and
metered billing alike. `notional_token_cost` is retained in the ledger as
the driver, explicitly not as money paid.

Two things this depends on:

- **The denominator spans every `~/.claude/projects/` directory**, not just
  this project's. Scoped per project, each project independently claims the
  full seat and the sum across projects exceeds what was actually paid.
- **`n_seats` must be 1** unless the denominator covers every seat's
  transcripts. This tool reads one machine, so a higher count spreads N
  seats of cost across one person's work; the build refuses it and forces 1.
  Team-wide allocation needs team-wide transcripts — a collection problem,
  not a config value.

Omit `seat_cost_per_month` and the ledger falls back to reporting notional
token cost only, labelled as such.

## Measured vs modelled vs inputs

`ledger.json` is split into three explicitly labelled zones so a fabricated
figure cannot be mistaken for an observed one:

| Zone | Contents |
|---|---|
| `measured` | Token counts, capacity share, allocated seat cost, event/session counts, attribution buckets, Linear cycle time |
| `modelled` | `baseline_hours`, `hours_saved`, `labour_cost`, `breakeven_hours`, `gap_hours`, `gap_value` — **null unless a human supplies a baseline** |
| `inputs` | `contract_value`, `discount_given`, `blended_cost_rate`, plus `verified` |

**Hours-based output requires a human-supplied baseline.** `baseline_hours`
in `config.yaml` maps ticket ID → "what would this have taken without AI".
There is deliberately **no** points-times-a-constant fallback: v0 shipped a
$13,560 headline built entirely out of one, and `points_to_hours_factor`
now raises on load rather than silently reappearing. With no baseline, the
break-even question is reported as unanswerable and the HTML hides the
savings and net-value columns rather than filling them with a guess.

Set `inputs_verified: true` only once the contract figures are confirmed
against a real engagement. While false, the HTML renders an explicit
UNVERIFIED banner and suppresses derived margin and gap figures.

## Known limitations (see parser-spec.md section 7 for the full list)

- A branch with multiple ticket IDs attributes to the first one found.
- A regex-matched ticket ID not present in Linear folds into
  `unattributed_cost` rather than appearing as a phantom ticket.
- `linear_cycle_time_hours` is wall-clock between Linear's `startedAt` and
  `completedAt` transitions. It is **neither human effort nor agent
  effort** — a ticket left "In Progress" over a weekend reads as days, and
  one closed quickly can read as seconds. Named for what it is so it can't
  be read as hours worked; nothing is derived from it without a baseline.
- The median-vs-mean distribution check has no statistical power below
  ~15 tickets. It reports `n` and explicitly declines to call the result a
  signal under that threshold, rather than warning on small-sample noise.
- Cache multipliers (1h write 2.0x, 5m write 1.25x, read 0.10x) were
  verified against published rates on 2026-07-26. `claude-sonnet-5` carries
  introductory pricing through 2026-08-31; the table uses list price, which
  shifts relative weight between Sonnet and Opus tickets in a mixed-model
  allocation. See the caveat in `agent_margin/cost.py`.
- Same repo, two clients is out of scope -- config assumes one project.
- **Not pip-installable.** There's no `pyproject.toml` / console-script
  entry point, so running this against another project means copying the
  `agent_margin/` folder and a `config.yaml` into (or alongside) it, rather
  than running a `agent-margin` command from anywhere.

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
