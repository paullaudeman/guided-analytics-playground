# ADR 0004 · One trace line per tool call, and the id goes back to the user

**Status:** accepted, 2026-10-07

**Context.** "Why did it say that?" is the support burden the VP named. An answer without provenance cannot be defended.

**Decision.** Every tool call appends one JSONL line: trace id, timestamp, principal, role, tool, arguments, SQL executed, rows, latency, refusal reason, estimate and actual cost. The trace id is returned in every result so the skill can end the answer with "trace: <id>". `audit_log` (admin only) lists recent lines.

**Consequences.** The server logs tool calls, not the chat; what the user typed is on the trace only if the skill passes the shaped question in. Tier 1 moves the store to a DuckDB table so the reports query it.
