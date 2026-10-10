# Guided analytics playground

A small, runnable demonstration of **governed, guided analytics on Claude Desktop**: a business user asks a vague question, a skill shapes it, a strict MCP server answers it from a semantic layer, and every answer carries its definition, its trace id and what it cost.

Built as a public example against a **fictional value-based-care company, Northstar Care**, on fully synthetic data. No real company, person, patient or payer appears anywhere in this repository.

## What it shows, in five minutes

1. **A vague question becomes a shaped one.** "How's Practice 12 doing?" becomes measure set, attribution window, payer, grain.
2. **Two differently worded questions return the same number**, with the metric's definition, owner and version attached, and the cost of each answer.
3. **A refusal that names the rule.** Unknown metric, member-level data below the analyst role, or a cross-domain question the layer cannot serve yet.
4. **Measure before, guide, measure after.** "I want all member-level data for every practice this year" is priced before it runs: rows scanned, warehouse cost, estimated tokens. The skill guides the user to the question they actually have, prices that, runs it, and shows the actual cost beside both estimates.

## The shape

```
Claude Desktop (business user)
   │  Project instructions: domains, vocabulary, "ask before you query"
   │  Skill "shape my question": intent → three analyst questions → then data
   ▼
MCP server (this repo, local stdio)
   ├─ prompts: practice performance · care-gap trend
   ├─ estimate_cost(metric, grain, window, filters)      dry run: rows, warehouse $, est. tokens
   ├─ get_metric(metric: ENUM, grain, window, filters)   strict schema; returns actual cost beside the estimate
   ├─ explain_metric · list_metrics · whoami
   ├─ request_capability (intake, never a grant) · record_answer · cost_report · audit_log
   └─ guards: read-only, PHI never leaves the server, role-gated grain, one trace line per call
   ▼
Semantic layer: metrics.yaml (defined once; owner, grain, version, allowed roles)
   ▼
Synthetic data: practices, members, measures, actions, payments (DuckDB)
   ▼
Evals: 20 questions (signed-pending until a person signs the file), accuracy and cost per answer, run on every change
```

## The four dimensions most demos skip

| Dimension | Here | Honest limit |
|---|---|---|
| **Identity and security** | principal and role on every call; row access by practice; PHI columns never exposed; read-only by construction | a local stdio server has no login; the role comes from the server's config, one Desktop entry per role. Production: an authenticated remote MCP connector |
| **Governance** | each metric has an owner and a definition; the layer file is versioned; a deny-by-default policy names which role may use which tool, metric and grain; changing one is a commit; `request_capability` logs a request instead of granting it | approval is a human editing a file |
| **Tracing** | JSONL trace per tool call with trace id, principal, SQL, rows, latency, refusal reason; the id is returned so the answer can cite it | the server sees tool calls, not the chat |
| **Cost** | `estimate_cost` before any query (rows × rate, token estimate), actual cost on every `get_metric`, both on the trace; `cost_report` shows estimate versus actual per answer, per role, per metric | a local MCP server cannot see Claude's tokens; counts are estimates until the same flow runs through the Agent SDK, and every line says so |

## Run it in Claude Desktop

You need macOS or Windows with [Claude Desktop](https://claude.ai/download), and [uv](https://docs.astral.sh/uv/) (it fetches Python and the three dependencies on first run).

**1. Clone and generate the data** (synthetic and seeded, so every clone gets the same numbers):

```bash
git clone https://github.com/paullaudeman/guided-analytics-playground.git
cd guided-analytics-playground
uv run --with duckdb python data/generate.py        # writes data/northstar.duckdb
uv run --with "mcp<2",duckdb,pyyaml python tests/smoke.py   # 40 checks should pass
```

**2. Register the server, once per role.** Claude Desktop → Settings → Developer → Edit Config opens `claude_desktop_config.json`. Add these entries under `mcpServers`, with your clone's absolute path, and the full path to `uv` if Desktop cannot find it (`which uv`):

```json
{
  "mcpServers": {
    "northstar-as-external": {
      "command": "uv",
      "args": ["run", "-q", "--with", "mcp<2", "--with", "duckdb", "--with", "pyyaml",
               "python", "/ABSOLUTE/PATH/guided-analytics-playground/server.py"],
      "env": { "ROLE": "external", "PRINCIPAL": "practice12.office@northstar.example", "PRACTICE_ID": "12" }
    },
    "northstar-as-csm": {
      "command": "uv",
      "args": ["run", "-q", "--with", "mcp<2", "--with", "duckdb", "--with", "pyyaml",
               "python", "/ABSOLUTE/PATH/guided-analytics-playground/server.py"],
      "env": { "ROLE": "csm", "PRINCIPAL": "csm.demo@northstar.example", "PRACTICE_ID": "all" }
    },
    "northstar-as-admin": {
      "command": "uv",
      "args": ["run", "-q", "--with", "mcp<2", "--with", "duckdb", "--with", "pyyaml",
               "python", "/ABSOLUTE/PATH/guided-analytics-playground/server.py"],
      "env": { "ROLE": "admin", "PRINCIPAL": "admin.demo@northstar.example", "PRACTICE_ID": "all" }
    }
  }
}
```

The role comes from the config, not from a login: a local stdio server has none (see `docs/adr/0002`).

**3. Add the skill and the Project.** Zip the `skill/shape-my-question` folder (the folder, not its contents) and upload it under Settings → Capabilities → Skills. Create a Project, for example "Northstar analytics", and paste `skill/project-instructions.md` into its instructions.

**4. Restart Claude Desktop,** open a chat in the Project, and turn on **one** `northstar-as-*` server in the tools menu. That server is the role you are playing.

| Server | Plays | Can see |
|---|---|---|
| `northstar-as-external` | a practice office (practice 12) | its own practice; care-gap and visit metrics; no payments |
| `northstar-as-csm` | customer success | every practice, plus payments and membership |
| `northstar-as-admin` | admin | everything, plus the cost and audit reports |

**5. Try these, in order:**

1. As **external**: *"How's Practice 12 doing?"* The skill asks three shaping questions (measures, months, grain) before any data is touched.
2. Still **external**: *"How much were we paid in March?"* Refused, and the refusal names the policy rule.
3. As **csm**: *"Show me member names for practice 12's open care gaps."* Refused: PHI columns are not reachable from any tool.
4. As **csm**: *"All member-level data for every practice this year."* Priced before it runs: rows scanned, warehouse cost, estimated tokens.
5. As **admin**: *"Show me the cost report."* Estimate versus actual for every answer so far.

Menu names in Claude Desktop move between versions; if a label differs, the setting is still there. Server logs: `~/Library/Logs/Claude/mcp-server-northstar-as-*.log` on macOS. The same server also runs in Claude Code: `claude mcp add northstar -e ROLE=csm -e PRINCIPAL=csm.demo@northstar.example -e PRACTICE_ID=all -- uv run -q --with "mcp<2" --with duckdb --with pyyaml python /ABSOLUTE/PATH/guided-analytics-playground/server.py`.

## See it run

A self-playing animated walkthrough of the build: 21 scenes with sound, every number captured from the server. [Watch the film](https://paullaudeman.github.io/guided-analytics-playground/film.html) (`docs/film.html`).

## Status

Tier 0 (strict-schema MCP server over the YAML layer) and Tier 1 (twenty evals with independent SQL) are built, 7. Oct 2026; deny-by-default policy and a second fact table followed on 8. Oct. The evals are written and run; their sign-off is still pending. See `plan.md` for the build ladder and `decisions.md` for the choices made and why.

## Licence

MIT. Synthetic data generated by `data/generate.py`.
