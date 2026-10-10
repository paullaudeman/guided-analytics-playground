# ADR 0005 · The semantic layer is a YAML file first, a Snowflake Semantic View second

**Status:** accepted, 2026-10-07

**Context.** A typical production target defines metrics in a warehouse-native semantic layer (for example, Snowflake Semantic Views). The playground has to prove "defined once, asked by name" in an evening, and show the vendor path afterwards.

**Decision.** `metrics.yaml` carries each metric's owner, definition, grain roles, unit and SQL template. The server is the only reader. Tier 2 expresses the same metrics as a Semantic View and puts Snowflake's MCP server beside this one.

**Consequences.** The comparison in Tier 2 is the evaluation the VP asked for: the same questions, two routes, accuracy and cost per answer side by side.
