# Plan

**Why:** most "chat with your data" demos skip the four things that decide whether the answer can be trusted and paid for: who asked, who owns the metric, what happened, and what it cost. This playground builds those in from the first line.

**Example setting:** Northstar Care, a fictional value-based-care company. Primary-care practices receive a checklist of care actions and are paid per completed action; health plans fund it. Four analytics domains: practice performance, care gaps, payments, membership.

## Build ladder

- **Tier 0:** `data/generate.py` → DuckDB; `metrics.yaml` with owners, grains and roles; `prices.yaml` (dated); `server.py` (FastMCP) with `whoami`, `list_metrics`, `explain_metric`, `estimate_cost` (dry run: rows scanned via a COUNT over the same predicate, warehouse rate, token estimate from the projected result size), `get_metric` (enum, role-gated, returns actual beside estimate), `request_capability`, `record_answer`, `cost_report`, `audit_log`; JSONL trace with trace ids; refusals that name the rule. Tested from Claude Desktop with one server entry per role.
- **Tier 1:** the Desktop skill "shape my question"; Project instructions; two MCP prompts; `evals/questions.json` (20, signed-pending; `run.py --require-signed` refuses until signed) and `evals/run.py`; trace store moves to a DuckDB table so `audit_log` and `cost_report` query it.
- **Tier 2:** the same metrics as a Snowflake Semantic View behind Snowflake's MCP server, side by side; a short comparison write-up.
- **Tier 3, Claude Code (added 7. Oct):** the same server registered in Claude Code (`claude mcp add northstar -- uv run ... server.py`); the same skill as a Claude Code skill; an Agent SDK runner that drives the flow headless, returns **exact** token usage per answer (closing D12), and runs `evals/questions.json` on every change as a CI step. That is where the eval harness becomes a gate rather than a report, and where an analyst's "run this for all 24 practices" becomes a background job with a budget and a kill switch.

## Identity, the real design (added 7. Oct)

Three layers, none of them the laptop login:

```
 who you are              what you're on                what you may see
 IdP (Okta / Entra),      device trust: MDM posture     data policy at the warehouse:
 OIDC token with          (Jamf on macOS, Intune on     row access and masking keyed on
 subject and groups       Windows), conditional access  the token's user and groups
```

- Claude Desktop reaches a **remote MCP connector** over OAuth 2.1; the token's subject and groups are the principal. The org admin configures the connector once; no user edits a config file.
- The connector passes the user through to the warehouse (external OAuth, or a service role carrying a session tag), and the warehouse's own row and column policies decide. The server is never a shared superuser.
- Device trust is the second factor: only a managed device gets a token. The local account on the laptop is irrelevant to the data.

**In this playground:** Tier 0 simulates layer one with a role in the server config (one Desktop entry per role) and says so in `whoami`. Tier 2 runs the same server as a remote connector behind a real OIDC provider, so `whoami` returns the token's subject. The demo fakes the login; the design does not.

**Plan check, resolved 7. Oct:** Claude Desktop on a Max subscription supports local MCP servers, skills and Cowork; the config file already carries an empty `mcpServers` list.

## The cost loop (added 7. Oct)

```
ask ──▶ estimate_cost ──▶ guide (skill narrows: grain, window, filters) ──▶ estimate_cost ──▶ get_metric ──▶ actual
         before: rows, $, tokens                                              after: rows, $, tokens          on the trace
```

Benchmark first, then optimise, then measure after. Every trace line carries estimate and actual so `cost_report` can show the delta the guidance produced.

## Decisions

See `decisions.md`. The ones that shape everything: DuckDB first, YAML semantic layer first, our own strict-schema server before the vendor's, Desktop as the surface, generated data with deliberate fuzziness, one Desktop entry per role for identity, estimates labelled as estimates until the SDK path exists.

## Leak gate

`tools/leak-scan.sh` runs before any push and fails on any real company, person or client name. The list it checks lives outside this repository.
