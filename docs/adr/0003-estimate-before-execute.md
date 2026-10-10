# ADR 0003 · Every question is priced before it runs, and measured after

**Status:** accepted, 2026-10-07

**Context.** AI on data is cheap to ask and expensive to answer. A prior production decision held a workload out at 150 times the cost of the SQL it replaced until the economics crossed; the method was benchmark first, optimise, measure after. Analytics agents need the same loop per question, visibly.

**Decision.** `estimate_cost` runs a COUNT over the same predicate the metric would use, prices rows at the dated warehouse rate in `metrics.yaml`, and estimates model tokens from the projected result size at the dated prices in `prices.yaml`. `get_metric` records actual rows, latency and warehouse cost on the trace and returns them beside the estimate. The skill re-estimates after narrowing the question.

**Consequences.** `cost_report` can show estimate versus actual per answer, per role, per metric, and the delta the guidance produced. Token figures are estimates until the same flow runs through the Agent SDK with exact usage; every line is labelled "estimated" until then.
