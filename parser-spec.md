# Agent Margin — parser spec

*Paste into Claude Code in the repo. Build against real files in `~/.claude/projects/`.*

Turns Claude Code session transcripts into a per-ticket cost ledger joined to Linear issues and a project P&L.

---

## 0. The one thing that makes this easy

Every record in a Claude Code transcript carries `gitBranch` as a **top-level field**. No git reflog reconstruction, no timestamp correlation with branch history. The branch is stamped on the event itself.

Consequence, and it matters: **attribute at the record level, not the session level.** One session routinely spans several branches — you switch tickets without restarting Claude. Session-level attribution would smear cost across tickets and produce numbers you cannot defend. Record-level attribution is both more accurate and less code.

---

## 1. Input

```
~/.claude/projects/<url-encoded-project-path>/<session-uuid>.jsonl
```

Directory name is the cwd with `/` → `-` (`/Users/you/code/my-app` → `-Users-you-code-my-app`). Files are append-only, one JSON object per line, not pretty-printed.

Relevant fields on every record:

| Field | Use |
|---|---|
| `type` | `"user"` \| `"assistant"` \| `"system"` — cost lives on `assistant` |
| `uuid` | Dedup key |
| `timestamp` | ISO 8601, for period filtering |
| `sessionId` | Session UUID |
| `cwd` | Working directory — maps to repo |
| `gitBranch` | **The join key.** May be absent |
| `version` | Claude Code version |
| `message.model` | Model string — pricing is per model |
| `message.usage` | `input_tokens`, `output_tokens`, `cache_creation_input_tokens`, `cache_read_input_tokens` |
| `isSidechain` | Subagent work. Real cost — include it |

Verify all of this against your own files before writing logic. Fields are optional and vary by version:

```bash
ls ~/.claude/projects/
jq -c 'select(.type=="assistant") | {ts:.timestamp, br:.gitBranch, m:.message.model, u:.message.usage}' \
  ~/.claude/projects/<dir>/<session>.jsonl | head -20
```

---

## 2. Stage 1 — walk and normalise

Emit one row per **assistant record** (only assistant records carry `usage`).

```
CostEvent {
  uuid, session_id, timestamp, cwd, git_branch, model,
  input_tokens, output_tokens, cache_creation_tokens, cache_read_tokens,
  is_sidechain
}
```

Rules:

- Skip non-`assistant` records for costing. They're needed only if you later want tool-call detail.
- **Dedup on `uuid`.** Files are append-only but can be replayed or copied between machines.
- Missing `usage` → skip the record, count it in a `skipped` tally, report the tally. Never silently drop.
- Treat every `usage` field as optional; default to `0`.
- Filter by `timestamp` to the reporting period. Compaction and summary records may fall outside it — that's fine, they carry no usage.

---

## 3. Stage 2 — the cost engine

**This is the part most likely to be silently wrong.** Cached tokens are not priced like fresh ones, and Claude Code is cache-heavy by design. Sum `input_tokens` naively and you will overstate cost by a large multiple.

```
cost = (input_tokens          / 1e6) * price_in
     + (cache_creation_tokens / 1e6) * price_in * CACHE_WRITE_MULT
     + (cache_read_tokens     / 1e6) * price_in * CACHE_READ_MULT
     + (output_tokens         / 1e6) * price_out
```

Config — verify against current published rates before you trust a number:

```python
CACHE_WRITE_MULT = 1.25
CACHE_READ_MULT  = 0.10

PRICES = {                     # USD per 1M tokens, (input, output)
    "claude-sonnet-5":   (3.00, 15.00),
    "claude-haiku-4-5":  (1.00,  5.00),
    "claude-opus-4-8":   (5.00, 25.00),
}
```

- Match `message.model` by prefix — the field carries version suffixes.
- **Unknown model must raise, not default.** A silent fallback price is how you end up presenting a wrong number to a customer.
- Keep the four components on the row, not just the total. You will want to show that cache reads were 70% of tokens and 12% of cost.

---

## 4. Stage 3 — attribution

```
ticket_id = first match of /(?:^|[\/_-])([A-Z][A-Z0-9]{1,9}-\d+)/i against git_branch
```

Linear's default branch format is `username/eng-123-short-title`, so the ID sits after the first `/`. Uppercase the captured group.

Three buckets, and **all three must appear in the output**:

| Bucket | Condition |
|---|---|
| Attributed | Branch matched a ticket ID that exists in Linear |
| Unmatched branch | Branch present, no ticket pattern (`main`, `spike/foo`) |
| No branch | `gitBranch` absent or empty |

Report unattributed spend as a first-class figure on the screen. An honest *"18% unattributed"* is more credible than a suspiciously clean 100%, and it is itself a finding — it means work happened outside the ticketing system.

---

## 5. Stage 4 — Linear

GraphQL at `https://api.linear.app/graphql`, personal API key in the `Authorization` header (raw key, no `Bearer`).

```graphql
query($after: String) {
  issues(first: 100, after: $after) {
    pageInfo { hasNextPage endCursor }
    nodes {
      identifier title estimate
      state { name type }
      assignee { name }
      project { id name }
      completedAt createdAt
    }
  }
}
```

Join `CostEvent.ticket_id` → `issue.identifier`. Paginate. Cache the response to a local JSON file so you aren't re-querying on every run while iterating.

Note `estimate` is usually **story points, not hours**. Converting needs a points-to-hours factor from the team — make it explicit config, never a silent assumption.

---

## 6. Stage 5 — rollup

```
TicketLedger {
  ticket_id, title, assignee, state,
  agent_cost, session_count, event_count, first_seen, last_seen,
  estimate_points, estimate_hours, actual_hours          # actual_hours = manual input for v0
}

ProjectLedger {
  project, client, contract_value, blended_cost_rate,    # config
  labour_cost, agent_cost, total_cogs, gross_profit, gross_margin_pct,
  unattributed_cost, unattributed_pct,
  discount_given,                                        # config
  breakeven_hours = (discount_given + agent_cost) / blended_cost_rate,
  hours_saved,                                           # from estimate vs actual
  gap_hours = breakeven_hours - hours_saved,
  gap_value = gap_hours * blended_cost_rate
}
```

Config lives in one `config.yaml` — contract value, blended cost rate, discount given, points-to-hours factor, client name. None of these come from an API. Don't build a settings UI.

Output a single `ledger.json` the existing HTML reads. Keep the data layer general — do not shape it toward one screen, because the screen is the layer most likely to change.

---

## 7. Failure modes to handle explicitly

| Failure | Handling |
|---|---|
| Session spans multiple branches | Solved by record-level attribution. Do not aggregate to session first. |
| Branch merged and deleted | Ticket ID is in the historic record; Linear lookup still resolves. Fine. |
| Multiple tickets on one branch | Attributes to the first ID in the branch name. Note it as a known limitation. |
| Work on `main` | Unmatched bucket. Expected and reportable. |
| Subagent / `isSidechain` records | Include. It is real spend. Tag it so you can split it out. |
| Compaction events | Carry no `usage`. Skipped naturally. But they *cause* large `cache_creation` on the next turn — expect spikes and don't treat them as bugs. |
| Same repo, two clients | Out of scope for v0. Config assumes one project. |

---

## 8. Verification — do this before trusting any output

1. **Reconcile against the console.** Sum `agent_cost` across all sessions for a period and compare to the Anthropic Console usage for the same window. Should land within a few percent. If it's off by ~5×, your cache multipliers are wrong.
2. **Spot-check one session by hand.** Pick a short one, `jq` its usage blocks, compute cost with a calculator, compare.
3. **Check the buckets sum.** Attributed + unmatched + no-branch must equal total. If not, you're dropping records.
4. **Sanity-check the distribution.** Median ticket cost should be far below the mean. If they're close, attribution is probably smearing cost evenly, which means the join isn't working.

Point 4 is the real tell. The long tail is the product — if it isn't there, something upstream is wrong.

---

## 9. Build order

1. Walk + parse + dedup → print event count and date range
2. Cost engine → reconcile against console **before going further**
3. Branch regex → print the three bucket totals
4. Linear pull → cache to disk
5. Rollup → emit `ledger.json`
6. Point the HTML at it

Stop after step 2 until reconciliation passes. Everything downstream inherits that error.

---

## Sources

- [Claude Code JSONL transcript format explained](https://claude-dev.tools/docs/jsonl-format)
- [Inside Claude Code: the session file format](https://databunny.medium.com/inside-claude-code-the-session-file-format-and-how-to-inspect-it-b9998e66d56b)
- [token-dashboard](https://github.com/nateherkai/token-dashboard) · [claude-usage](https://github.com/phuryn/claude-usage) — existing parsers worth reading first
- [Anthropic API pricing 2026](https://www.finout.io/blog/anthropic-api-pricing)
