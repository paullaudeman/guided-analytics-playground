# ADR 0001 · The metric is an enum, never free text

**Status:** accepted, 2026-10-07

**Context.** "Chat with your data" agents write their own SQL, so two people asking the same question get two numbers. The semantic layer exists to define a metric once. Advising the agent to use it is not enough; it has to be unable not to.

**Decision.** `get_metric` and `estimate_cost` take `metric` as a `Literal[...]` built from `metrics.yaml` at startup. An unknown metric is a schema error before any code runs. No tool accepts SQL. Filters are a fixed set of typed fields (practice, payer, month window, measure).

**Consequences.** Cross-domain questions the layer cannot express are refused with a message that names the gap, which is the signal that the layer needs a new metric. Adding a metric is a commit to `metrics.yaml`, reviewed like code. The agent cannot be clever; that is the point.
