# ADR 0008 · A version carries its changelog

**Status:** accepted, 2026-10-10.

**Context.** The layer was versioned from Tier 0, and every answer cited the version. A live run in Claude Desktop showed what a version alone cannot do: after the layer moved from 2026-10-08.1 to 2026-10-10.1, the agent said "I don't know what changed, so if you compare this figure with one pulled earlier, check that the definition was the same." A version tells a consumer *that* something changed, never *what*, so everyone downstream has to guess or ask.

**Decision.** `metrics.yaml` carries a `changelog`, newest first: version, date, what changed, and which metric definitions it touched (an empty list means policy or plumbing only). The server refuses to load when the top entry does not name the current version, or when an entry names an unknown metric. `get_metric` and `explain_metric` return `definition_changed_in` (the version in which that metric last changed) and `layer_changes_since_definition` (what moved in the layer while the number stayed the same); `explain_metric` adds the metric's own history; `list_metrics` leads with the latest change.

**Consequences.** "Is this number comparable with last week's?" has an answer in the payload: compare `definition_changed_in`, not the layer version. A version bump cannot ship silently, because the load check fails first. The entries were written from the git history of `metrics.yaml` (four versions), not reconstructed. Checked in `tests/smoke.py` (three cases, one of them the load refusal).
