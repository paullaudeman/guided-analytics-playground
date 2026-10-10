# ADR 0007 · Priced first, above a line

**Status:** accepted, 2026-10-10.

**Context.** `estimate_cost` existed from Tier 0 and `get_metric` checked a claimed estimate (audit finding 3), but nothing required one. A live run in Claude Desktop surfaced it: the agent's own cost report showed two answers that "ran without a prior estimate" and concluded that "the 'price it first' step is not being enforced by the server." It was right. The skill asked for an estimate; the server only advised.

**Options.** (a) Require an estimate on every query: strict, but every cheap question pays a second round trip. (b) Require one above a cost line. (c) Leave it advisory and flag unpriced answers in the cost report.

**Decision.** (b). `metrics.yaml` carries `require_estimate_above_rows` (50.000). `get_metric` runs the same dry-run count that `estimate_cost` uses; above the line, a question without the `trace_id` of a matching estimate (same principal, same arguments) is refused, and the refusal says what to do. Below the line, one call is enough.

**Consequences.** Wide questions are always priced before they run, whatever the client does, so the rule no longer depends on the prompt or the skill being followed. Cheap questions stay cheap. The line is policy, so changing it is a commit to the versioned layer. The scorecard keeps its own bounded, single-practice path and is not gated. Checked in `tests/smoke.py` (three cases).
