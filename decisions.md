# Decisions

| # | Decision | Chosen | Why |
|---|---|---|---|
| D1 | Where the data lives | DuckDB first, Snowflake second | a demo tonight, the real target later; the MCP layer is the same |
| D2 | Semantic layer | `metrics.yaml` now, Snowflake Semantic View later | "defined once, asked by name" is provable in hours |
| D3 | MCP server | our own strict-schema server, then the vendor's beside it | only our own can make the metric an enum and show a refusal |
| D4 | Surface | Claude Desktop skill plus a Project | the users are in Desktop |
| D5 | Data | generated, domain-shaped, fuzzy on purpose | actions and payments per practice exist in no public set |
| D6 | Evals | 20 questions in JSON, signed by a person before they gate (signed-pending today), a runner scoring numbers and cost | legible on a screen |
| D7 | Demo | three demonstrations, nothing more | five minutes |
| D8 | Repo | public, synthetic only | the link is the receipt |
| D9 | Identity simulation | one Desktop MCP entry per role, principal in the env | a `set_role` tool is the hole the demo exists to show |
| D10 | Trace store | JSONL, then a DuckDB table | so audit and cost reports can query it |
| D11 | Prices | `prices.yaml`, hand-filled and dated | the date is a drift watch |
| D12 | Token accounting | estimated and labelled, exact via the Agent SDK later | a local server cannot see the model's tokens |
| D13 | Cost before and after | `estimate_cost` dry run on every question; actual on the trace; the skill re-estimates after narrowing | the FPL pattern: benchmark first, optimise, measure after; the delta is the demo |

| D14 | A second fact table (8. Oct) | `visits`, one row per visit, drawn after the seeded stream; `visit_count` and `visit_closure_rate`, the latter joined on member + practice + month | the join key is the modeling lesson: member only gives 1,0, member + month borrows other practices' actions through walk-ins, the full key gives the metric; evals q21 and q22 use EXISTS so they can disagree |

## Challenged

Design choices Paul challenged after the build, where the challenge was right. Recorded so the original reasoning and the correction both stay visible.

| Date | First design | Paul's challenge | Outcome |
|---|---|---|---|
| 7. Oct 2026 | `PRACTICE_ID` read only for the external role; unset scope meant "all" for csm, analyst, admin. `whoami` printed `none (admin sees all)`. | *"this seems fast and loose: 'none' versus an explicit admin-all"* | Agreed. Fail-open: absence of a grant behaved as a grant. Scope is now a number or the literal `all`; unset refuses for every role. ADR 0002 amended; the evals runner was caught by it (20 refused until it declared `all`). |
| 7. Oct 2026 | Per-check `if` statements: grains allow-listed, `audit_log` hardcoded admin, `cost_report` open to all roles, no per-role metric list. | *"explicitly permissions deny unless explicitly granted (AWS model)"* | Agreed. One `policy` block in `metrics.yaml` (default deny, per-role tools / metrics / grains, explicit deny wins for PHI), one `_authorize()` at the top of every tool. Built 8. Oct, ADR 0006; the audit had found `cost_report` open and the PHI list unenforced, both closed by the same block. |
| 7. Oct 2026 | Checkbox left native in the walkthrough page; house style 3.8 required drawing it but only in one script's CSS. | *"checkbox appearance is still globally fucked"* | Agreed, and the fix moved up a level: the kit CSS slab now draws every checkbox and radio (kit v1.4), so no page has to remember. |
| 8. Oct 2026 | The skill asks the three analyst questions before any query: interrogate, then answer. | *"my reflex would be there's a common thread to unpack in that query ... how do we give enough to give something and let them adjust further"* | Agreed. "How's practice 12 doing?" has a conventional shape (the scorecard at standard windows). Answer that with stated defaults first; the three questions become the adjustment menu. Build pending: `practice_scorecard` tool, an MCP prompt, a 23rd eval. |
