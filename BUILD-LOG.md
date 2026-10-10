# Build log

Rolling, newest at the bottom. Each entry: what was built or decided, why, and how it rolls into the five-minute demo. ADRs in `docs/adr/`. Side notes are the thinking that shaped a decision; they stay here so the repo explains itself.

## 2026-10-07 · planning and Tier 0 start

**Why this exists.** A common shape in analytics teams adopting AI: Claude over a cloud warehouse, business users asking questions in Claude Desktop, and "accurate answers" as the goal, while the data model under the agents and the evals are still open questions. This playground is that evaluation, built small on synthetic data so it can be shown instead of talked about. The setting is fictional: Northstar Care.

**Decisions D1 to D13** taken in one sitting (see `decisions.md`). The ones that shape everything: DuckDB before Snowflake, a YAML semantic layer before a Semantic View, our own strict-schema MCP server before the vendor's, Claude Desktop as the surface, generated data with deliberate fuzziness, one Desktop entry per role for identity, cost estimated before every query and measured after.

**Four dimensions added by request** before any code: identity and security, governance, tracing, model and token cost. The honest limits are in the README table: a local stdio server has no login and cannot see the model's tokens. Both are stated on screen, not hidden.

**Side note: identity in a real business** (mixed Windows and Mac laptops). The laptop login is not the identity to the data. Three layers: who you are (IdP, OIDC token with subject and groups), what you are on (MDM posture and conditional access, Jamf or Intune), what you may see (row and column policies at the warehouse keyed on the token's user). Claude Desktop reaches a remote MCP connector over OAuth; the admin configures it once; the connector passes the user through to the warehouse. The playground fakes layer one with a role in the server config and says so in `whoami`; Tier 2 replaces it with a real OIDC provider. The demo fakes the login; the design does not. → ADR 0002.

**Side note: the cost loop.** The pattern from a prior production decision: benchmark first, optimise, measure after. Here it is a tool, `estimate_cost`, that prices a question before it runs (rows scanned, warehouse rate, token estimate from the projected result), the skill narrows the question, prices again, and `get_metric` returns the actual beside the estimate. The delta the guidance produced is the demonstration. → ADR 0003.

**Built today.**
- `data/generate.py`: 24 practices, 8,178 members, 73,642 attribution rows, 79,864 actions, 57,359 payments, Jan to Sep 2026. Four deliberate traps: 40 members attributed to two practices in March, Practice 07 with no actions in June, half of April's payments run in May, 60 duplicated action rows. An agent that does not deduplicate on `action_id` or that joins payments by action month will be wrong, visibly.
- `metrics.yaml`: five metrics across four domains, each with owner, definition, unit and SQL with a `{where}` slot; grains with the lowest role allowed; PHI columns listed so no tool can select them.
- `prices.yaml`: dated placeholder prices for three model tiers, shown as the source on every cost line.
- Leak gate `tools/leak-scan.sh`, whole-word, blocklist outside the repo. Clean.

**Rolls into the demo as:** demonstration 2 (same number twice) depends on the dedup in the metric SQL; demonstration 3 (refusal) depends on the grain roles and PHI list; demonstration 4 (cost before and after) depends on the traps making the naive question expensive.

**Next:** `server.py` with the eight tools and the trace; Desktop config with one entry per role; smoke test every tool from Python, then from Desktop.

## 2026-10-07 · Tier 0 built and smoke-tested

**Built.** `server.py` on the MCP Python SDK (pinned `mcp<2`; 2.x renamed FastMCP). Eight tools: `whoami`, `list_metrics`, `explain_metric`, `estimate_cost`, `get_metric`, `request_capability`, `record_answer`, `cost_report`, `audit_log`. Two MCP prompts: practice performance, care-gap trend. Read-only DuckDB connection; `metric` is a `Literal` from `metrics.yaml` (ADR 0001); role and practice scope from env (ADR 0002); one JSONL trace line per call with the id returned (ADR 0004); estimate before, actual after (ADR 0003).

**Smoke test, three roles** (`tests/smoke.py`):
- external (practice 12): member grain refused by the grain policy; practice 3 refused by the row policy; own practice answered; `audit_log` refused.
- csm: member grain refused; practice 3 payments answered ($4,837.50 for April, the late-run trap showing as a lower April).
- admin: the naive question "all member-level open gaps, every practice, all year" priced at 79,864 rows scanned, 8,178 result rows, about $0.18 warehouse and about $1.72 estimated model; the shaped question "Practice 12, A1C, Q3" at 164 rows, $0.0004 and $0.003. **About 500 to 1 from the guidance alone.** Same metric asked two ways returned the same value (0.6995). `audit_log` answered.

**Also.** Claude Desktop config now carries three servers, `northstar-as-external`, `northstar-as-csm`, `northstar-as-admin` (one per role, ADR 0002). The Desktop skill `skill/shape-my-question/SKILL.md` and project instructions written; install steps in `skill/README.md`. Tier 3 added to the plan: the same server and skill in Claude Code, and an Agent SDK runner for exact tokens and evals as a CI gate.

**Rolls into the demo as:** all four demonstrations now have working tool calls behind them. What is missing is the Desktop run itself (restart Desktop, upload the skill, run the three roles) and the 20 signed questions for the evals.

**Next:** Desktop run and screenshots; `evals/questions.json` and `evals/run.py`; first commit.

**Article.** A write-up in the author's voice is kept alongside, unpublished for now. The spine: build it first to see what is possible, price every question from day one, decide later when to care.

## 2026-10-07 · Tier 1, part one: the evals, and what they caught

**Built.** `evals/make_questions.py` writes twenty questions whose expected values come from **independent SQL**, not from the metric templates, so the evals test the layer's definitions rather than repeat them. `evals/run.py` runs each question through `estimate_cost` and `get_metric` in-process, scores the value, and prints estimate beside actual for rows and warehouse cost, plus the estimated model cost. Exit 1 on any miss, so it can gate a commit. `signed_by` is empty on every question until a human signs the file; the report prints `signed: False` until then.

**What the first run found.** Nineteen of twenty passed. `q14`, total paid to all practices, came back $1,655,182.50 against an expected $1,654,002.00. The cause: `actions_paid_usd` joined payments to actions on `action_id`, and the sixty duplicated action rows (trap four) made the join pay those actions twice. The metric now joins to a deduplicated action set; the layer version moved to 2026-10-07.2 and the definition says so. **The evals caught a wrong number in the semantic layer before any user saw it, which is exactly the argument for having them.** Twenty of twenty after the fix.

**Rolls into the demo as:** the eval run is the evidence behind demonstration 2. The q14 story is the one to tell when someone says "the semantic layer makes it correct": no, the semantic layer makes it *correctable*, and the evals are what make it correct.

**Next:** the Desktop run (restart, upload the skill, three roles, screenshots); then a human signs `questions.json`.

## 2026-10-07 · The guided walkthrough, and a payer-grain bug

**Built.** `docs/walkthrough.html`, a fifteen-step stepper that starts at "How's Practice 12 doing?" and follows the one question through whoami, list_metrics, explain_metric, the three analyst questions, estimate_cost naive and shaped, get_metric, record_answer, the trace, the refusals by role, the same number twice, the four data traps, the q14 eval story, and what is next. A spine diagram at the top lights the part of the system each step touches. Every number on the page comes from `docs/walkthrough_capture.py`, which runs the server in-process as admin, external and csm and writes `docs/walkthrough-data.json`; `docs/build_walkthrough.py` splices the theme kit and the data into `docs/walkthrough.src.html`. Nothing on the page is typed by hand. Notes, progress and the chosen role persist in localStorage.

**What the capture found.** The payer grain never worked: `_group("payer")` compared `pr.practice_id` to an unqualified `practice_id`, which resolves to `pr` inside the subquery, so every practice matched and DuckDB refused the scalar subquery. No smoke test and no eval asks at payer grain. Fixed by qualifying the outer table; the CSM payer-grain answer in walkthrough step 10 is the first the server has returned. Twenty of twenty evals still pass, which is the point: the evals have no payer-grain question, so a missing eval, not a passing one.

**Rolls into the demo as:** the walkthrough is the rehearsal script for the Desktop run, one step per thing to show. The payer-grain story joins q14 as evidence that coverage, not the layer, is what makes a number correct.

**Next:** add a payer-grain eval; the Desktop run; sign `evals/questions.json`. `*.html` is gitignored, so the walkthrough stays local unless that changes.

## 2026-10-08 · The audit, the policy model, and the walkthrough's framing

**Challenged.** Paul read the walkthrough's step 1 and stopped at `practice_scope: none (admin sees all)`: *"this seems fast and loose."* Right: absence of a scope behaved as a grant. Then: *"explicitly permissions deny unless explicitly granted (AWS model)."* Both are recorded in `decisions.md` under Challenged, with the originals.

**Audited.** A read-only adversarial pass over the whole repo (report kept locally; 14 findings: 1 critical, 2 high, 6 medium, 5 low). The critical one: `month_from` and `month_to` were interpolated unvalidated into `DATE '...'`, inside the same function that enforces row scope, so an external user scoped to practice 12 could read every practice with a quote in a month field (verified: 88 rows scoped, 77,605 injected). The two highs: `cost_report` had no gate and read every principal's trace; `record_answer` and `estimate_trace_id` accepted any id, so costs could be attached to anyone's answer and the estimate-vs-actual story forged. Also found: the PHI list was never enforced; a one-line regression from the day before had put the evals' `TRACES` setting inside a comment; the page embedded JSON into a script tag without escaping `</`; several page interpolations bypassed `esc()`; the docs said "20 signed" with none signed; the unlocked trace append; junk `PRACTICE_ID` crashed startup; unknown models priced silently; payer-grain group count hardcoded to 3.

**Fixed, all of it.** `server.py` rewritten: a `policy` block in `metrics.yaml` (ADR 0006, deny by default, `"*"` explicit, PHI deny enforced at load) and one `_authorize()` first in every tool; months validated against `YYYY-MM`, payers and practice ids against the data, measures against the list, nothing interpolated that was not validated; query errors returned as refusals; `estimate_trace_id` must be this principal's estimate for these exact arguments; `record_answer` must name this principal's own unrecorded answer, a priced model, and bounded tokens; `cost_report` gated by policy and scoped to the caller's principal unless the policy grants `trace_scope: "*"`; locked trace appends; `_scope()` refuses junk instead of crashing; payer groups counted. `tests/smoke.py` now carries 33 checks, one per finding, each asserting the refusal's reason. `evals/run.py --require-signed` exits 3 until a person signs. README, plan and D6 say signed-pending.

**The walkthrough** now opens with an overview of the parts and how they interact, and every step has an intro paragraph (what, why, how it connects, what to expect), a checkpoint (what to inspect, what it means) and an explicit implemented / simulated line, so a passing demo is never read as production readiness. Every page interpolation goes through `esc()`; the embedded JSON escapes `</`. Theme kit v1.4 draws checkboxes and radios so they stop following the OS scheme.

**Rolls into the demo as:** the refusals in step 10 now include the policy refusals (external asking for money), and the injection attempt is a smoke-test line to show. The q14 and payer-grain stories gain a third: a critical injection in the row-scope function, found by an audit, not by the evals.

**Next:** sign `evals/questions.json`; add a payer-grain eval; the Desktop run; decide whether `docs/walkthrough.html` ships (gitignored today, carries the kit's comments).

## 2026-10-08 · See it run: the animated walkthrough

**Built.** A self-playing animated walkthrough of the build, generated from `docs/walkthrough-data.json` so every number on screen is the server's: the question, the semantic layer, the strict schema, the evals and the cost loop, scene by scene. The film's builder is kept local.

## 2026-10-08 · The second fact table, and the join key

**Built.** `visits` in `data/generate.py` (one row per visit, drawn after the seeded stream so the original tables and the first twenty expected values are unchanged), with a fifth trap: about 2 % of visits are walk-ins at a practice the member is not attributed to that month. Two metrics in `metrics.yaml`: `visit_count` and `visit_closure_rate` (share of visits where the same member had a completed action at the same practice in the same month). The server gained a fourth predicate slot, `{where_visits}`, a refusal for a measure on a visits metric, and payer / month / member grouping for the new table. Granted to external (own practice), csm, analyst, admin. Evals q21 and q22 with independent SQL (an EXISTS, not a join). Smoke: 36 checks. Layer version 2026-10-08.1.

**What the join key showed, by SQL (practice 12, Q3).** Member only: 1,0, every member had a completed action somewhere, sometime, so the number is empty. Member + month: 0,5163, the nine walk-ins borrow other practices' completed actions. Member + practice + month: 0,5121, the metric. Same question, three keys, three answers; the definition names the key. The film carries it as scene 13; the capture computes the three numbers so nothing is typed.

**Next:** sign `evals/questions.json` (22 now); a payer-grain eval; the Desktop run.

## 2026-10-08 · The scorecard tool, and margin notes on the film

**Built.** `practice_scorecard(practice_id, as_of)`: the conventional answer to "how is practice X doing" in one call, defaults named (quarter to date from the as-of month, the payer's peer practices beside the closure rate, open gaps by measure, visits per attributed member over three months, paid by month for the last three), one trace, one actual, a cell that names its rule wherever the role was not granted a metric. The MCP prompt invokes it; the Desktop skill now answers that question with the scorecard first and uses the three analyst questions as the adjustment menu. Policy grants updated. Eval q23 pins the default window to the Q3 metric. Smoke: 40 checks, including the partial scorecard an external role gets and the row-policy refusal for another practice.

**What the smoke test caught, before any user did.** The first version checked scope only inside each cell: an external principal asking for practice 3 got a scorecard shell with every cell refused and the header filled in, including that practice's payer. Scope is now checked at the top of the tool, before any lookup. Same lesson as 7. Oct: a control that exists only where someone remembered to write it.

**The film.** Margin contextuals on every scene (left: where this lives; right: in the room), flying in after the last reveal, outside the 980 px stage, hidden under 1400 px. The other session's five modeling scenes (The test, Grain, Double count, The star, From OLTP) are in the same generator; 21 scenes, 5:57 before the outro.

**Next:** sign `evals/questions.json` (23); the Desktop run, which is now the scorecard prompt first; a payer-grain eval.

**Addendum, 8. Oct 2026 · the visual pass.** Paul's eye found what the first detector did not: a 9 px rust shadow with 7 px of box-model clearance reads as touching. Every shadowed block now owns 10 px below it; `docs/tests_see_it_shadows.py` flags any shadowed element whose next solid sibling is closer than 12 px, at two viewport sizes, and runs beside the layout check. The "From OLTP" scene was rebuilt as the same two real rows twice (member 3809 at practice 12, actions in January and April, through `walkthrough_capture.py`): the app's four tables with PHI present, then the star with the payment folded into the fact and the PHI columns marked not loaded. Dense scenes carry `class="dense"` and scale to 0,7 under 680 px. Captions name the layout they sit under; the terrain questions on the start screen have collapsible answers.
