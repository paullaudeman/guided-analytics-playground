"""Guided analytics MCP server for Northstar Care (fictional). Local stdio, read-only, strict schema, deny by default.

Run (Claude Desktop config):  uv run --with "mcp<2",duckdb,pyyaml python server.py
Env: PRINCIPAL (who), ROLE (external|csm|analyst|admin), PRACTICE_ID (a practice number, or "all": an explicit grant; unset or junk refuses), TRACES (dir)
See docs/adr/ for why every tool is shaped the way it is. ADR 0006: nothing is allowed unless a policy statement allows it.
"""
from __future__ import annotations
import datetime as dt, fcntl, json, os, pathlib, re, time, uuid
from typing import Literal, Optional
import duckdb, yaml
from mcp.server.fastmcp import FastMCP

HERE = pathlib.Path(__file__).parent
CFG = yaml.safe_load((HERE / "metrics.yaml").read_text())
PRICES = yaml.safe_load((HERE / "prices.yaml").read_text())
DB = HERE / "data" / "northstar.duckdb"
TRACES = pathlib.Path(os.environ.get("TRACES", HERE / "traces")); TRACES.mkdir(exist_ok=True)
PRINCIPAL = os.environ.get("PRINCIPAL", "demo.user")
ROLE = os.environ.get("ROLE", "csm")
ROLES = ["external", "csm", "analyst", "admin"]
METRICS = CFG["metrics"]
CHANGELOG = CFG.get("changelog") or []
# ADR 0009: what this process loaded, so whoami can tell a stale server (Desktop not restarted) from a current one.
STARTED = {"at": dt.datetime.now().isoformat(timespec="seconds"), "layer_version": str(CFG["version"]),
           "files": {f: (HERE / f).stat().st_mtime for f in ("metrics.yaml", "server.py", "prices.yaml")}}
# ADR 0008: a version bump without a changelog entry does not load, so "what changed" can always be answered.
if not CHANGELOG or str(CHANGELOG[0]["version"]) != str(CFG["version"]):
    raise SystemExit(f"metrics.yaml: version {CFG['version']} has no changelog entry at the top; refusing to load (ADR 0008)")
for _e in CHANGELOG:
    for _mm in _e.get("metrics") or []:
        if _mm not in METRICS: raise SystemExit(f"metrics.yaml changelog {_e['version']} names unknown metric '{_mm}'")

def _defined_in(metric):
    """The layer version in which this metric's definition last changed (the newest changelog entry that names it)."""
    return next((str(e["version"]) for e in CHANGELOG if metric in (e.get("metrics") or [])), None)

def _since(metric):
    """Changelog entries newer than this metric's definition: what moved in the layer while this number stayed the same."""
    out = []
    for e in CHANGELOG:
        if metric in (e.get("metrics") or []): break
        out.append({"version": str(e["version"]), "change": e["change"]})
    return out
POLICY = CFG["policy"]
Metric = Literal[tuple(METRICS.keys())]          # ADR 0001: unknown metric is a schema error
Grain = Literal["practice", "payer", "month", "member", "total"]
MEASURES = ["A1C", "BP", "CCS", "COL", "AWV", "SDOH"]
VISIT_METRICS = {"visit_count", "visit_closure_rate"}      # the second fact table (8. Oct 2026): grain one row per visit
MONTH = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")   # the only shape a month field may have; anything else is refused, never interpolated
TOKEN_CAP = 2_000_000                            # record_answer: a token count above this is not an estimate, it is a typo or a forgery

mcp = FastMCP("northstar-guided-analytics")

def _con():
    return duckdb.connect(str(DB), read_only=True)   # read-only by construction

with _con() as _c:                                   # reference lists for validation, read once at start
    PRACTICES = {r[0] for r in _c.execute("SELECT practice_id FROM practices").fetchall()}
    PAYERS = {r[0] for r in _c.execute("SELECT DISTINCT payer FROM practices").fetchall()}

def _scope(v):
    """ADR 0002, amended: scope is explicit. A practice number that exists, or "all" (a deliberate grant). Anything else is None: unset, and every data tool refuses. Junk never crashes startup; it refuses."""
    v = (v or "").strip().lower()
    if not v: return None
    if v == "all": return "all"
    return int(v) if v.isdigit() and int(v) in PRACTICES else None
PRACTICE_SCOPE = _scope(os.environ.get("PRACTICE_ID"))

# PHI is enforced at load, not described: a metric whose SQL names a PHI column does not load (ADR 0006, explicit deny wins).
for _name, _m in METRICS.items():
    _hit = [c for c in CFG["phi_columns"] if re.search(rf"\b{re.escape(c)}\b", _m["sql"], re.I)]
    if _hit:
        raise SystemExit(f"metrics.yaml: metric '{_name}' selects PHI column(s) {_hit}; refusing to load (policy.deny.columns)")

def _trace(**row):
    row = {"trace_id": row.pop("trace_id", None) or f"t-{uuid.uuid4().hex[:10]}", "ts": dt.datetime.now().isoformat(timespec="seconds"),
           "principal": PRINCIPAL, "role": ROLE, **row}
    with (TRACES / f"{dt.date.today()}.jsonl").open("a") as f:     # three role processes append to one file: lock the append
        fcntl.flock(f, fcntl.LOCK_EX); f.write(json.dumps(row, default=str) + "\n"); fcntl.flock(f, fcntl.LOCK_UN)
    return row["trace_id"]

def _refuse(tool, rule, **args):
    tid = _trace(tool=tool, args=args, refused=rule)
    return {"refused": True, "rule": rule, "trace_id": tid}

def _authorize(tool, metric=None, grain=None):
    """ADR 0006, deny by default (the IAM shape): a role may use a tool, metric or grain only if a policy statement names it.
    Returns None when allowed, else the rule that denied. Explicit deny statements win over any allow."""
    stmt = POLICY["roles"].get(ROLE)
    if stmt is None:
        return f"policy: role '{ROLE}' has no policy statement; default is {POLICY['default']}"
    def allowed(kind, value):
        lst = stmt.get(kind, [])
        return "*" in lst or value in lst
    if not allowed("tools", tool):
        return f"policy: tool '{tool}' is not granted to role '{ROLE}' (no allow statement; default {POLICY['default']})"
    if metric is not None and not allowed("metrics", metric):
        return f"policy: metric '{metric}' is not granted to role '{ROLE}' (no allow statement; default {POLICY['default']})"
    if grain is not None and not allowed("grains", grain):
        return f"policy: grain '{grain}' is not granted to role '{ROLE}' (no allow statement; default {POLICY['default']})"
    return None

def _where(metric, practice_id, payer, month_from, month_to, measure, grain):
    """Build the predicate from typed, validated fields only. Returns ((where_actions, where_pay, where_attr), None) or (None, rule)."""
    if PRACTICE_SCOPE is None:   # fail closed: no scope is not "all" (ADR 0002, amended)
        return None, f"scope policy: no practice scope configured for principal '{PRINCIPAL}' (role '{ROLE}'); PRACTICE_ID must be an existing practice number or the explicit grant 'all'"
    if practice_id is not None:
        if isinstance(practice_id, bool) or not isinstance(practice_id, int) or practice_id not in PRACTICES:
            return None, f"unknown practice_id {practice_id!r}; practices are 1..{max(PRACTICES)}"
    if PRACTICE_SCOPE != "all":
        if practice_id not in (None, PRACTICE_SCOPE):
            return None, f"row policy: principal '{PRINCIPAL}' may only see practice {PRACTICE_SCOPE}"
        practice_id = PRACTICE_SCOPE
    for label, v in (("month_from", month_from), ("month_to", month_to)):
        if v is not None and not MONTH.match(v):
            return None, f"{label} must be YYYY-MM; got {v!r}"
    if month_from and month_to and month_from > month_to:
        return None, f"month_from {month_from} is after month_to {month_to}"
    if payer is not None and payer not in PAYERS:
        return None, f"unknown payer {payer!r}; known: {sorted(PAYERS)}"
    if measure is not None and measure not in MEASURES:
        return None, f"unknown measure {measure!r}; known: {MEASURES}"
    if measure is not None and metric in VISIT_METRICS:
        return None, f"measure does not apply to {metric}: visits are not per measure"
    w, wp, wa, wv = [], [], [], []
    if practice_id is not None:
        w.append(f"practice_id = {int(practice_id)}"); wp.append(f"p.practice_id = {int(practice_id)}"); wa.append(f"practice_id = {int(practice_id)}"); wv.append(f"v.practice_id = {int(practice_id)}")
    if payer:   # validated against PAYERS above, so the literal is one of three known strings
        w.append(f"practice_id IN (SELECT practice_id FROM practices WHERE payer = '{payer}')")
        wp.append(f"p.practice_id IN (SELECT practice_id FROM practices WHERE payer = '{payer}')")
        wa.append(f"practice_id IN (SELECT practice_id FROM practices WHERE payer = '{payer}')")
        wv.append(f"v.practice_id IN (SELECT practice_id FROM practices WHERE payer = '{payer}')")
    if month_from:   # validated by MONTH above
        w.append(f"action_date >= DATE '{month_from}-01'"); wp.append(f"p.paid_month >= DATE '{month_from}-01'"); wa.append(f"month >= DATE '{month_from}-01'"); wv.append(f"v.visit_date >= DATE '{month_from}-01'")
    if month_to:
        w.append(f"action_date < DATE '{month_to}-01' + INTERVAL 1 MONTH"); wp.append(f"p.paid_month <= DATE '{month_to}-01'"); wa.append(f"month <= DATE '{month_to}-01'"); wv.append(f"v.visit_date < DATE '{month_to}-01' + INTERVAL 1 MONTH")
    if measure:
        w.append(f"measure = '{measure}'"); wp.append(f"a.measure = '{measure}'")
    j = lambda parts: (" AND " + " AND ".join(parts)) if parts else ""
    return (j(w), j(wp), j(wa), j(wv)), None

def _group(grain):
    return {"practice": "practice_id", "payer": "(SELECT payer FROM practices pr WHERE pr.practice_id = actions.practice_id)",
            "month": "date_trunc('month', action_date)", "member": "member_id", "total": None}[grain]

def _table_and_where(metric, wheres):
    table = {"actions_paid_usd": "payments p JOIN (SELECT DISTINCT action_id, member_id, practice_id, measure FROM actions) a USING(action_id)",
             "attributed_members": "attribution", "visit_count": "visits v", "visit_closure_rate": "visits v"}.get(metric, "actions")
    w = {"actions_paid_usd": wheres[1], "attributed_members": wheres[2], "visit_count": wheres[3], "visit_closure_rate": wheres[3]}.get(metric, wheres[0])
    return table, w

def _group_for(metric, grain):
    if grain == "total": return None
    g = _group(grain)
    if metric == "actions_paid_usd":
        g = {"practice": "p.practice_id", "payer": "(SELECT payer FROM practices pr WHERE pr.practice_id = p.practice_id)",
             "month": "p.paid_month", "member": "a.member_id"}[grain]
    if metric == "attributed_members":
        g = {"practice": "practice_id", "payer": "(SELECT payer FROM practices pr WHERE pr.practice_id = attribution.practice_id)",
             "month": "month", "member": "member_id"}[grain]
    if metric in VISIT_METRICS:
        g = {"practice": "v.practice_id", "payer": "(SELECT payer FROM practices pr WHERE pr.practice_id = v.practice_id)",
             "month": "date_trunc('month', v.visit_date)", "member": "v.member_id"}[grain]
    return g

def _sql(metric, grain, wheres):
    tpl = METRICS[metric]["sql"]
    w, wp, wa, wv = wheres
    base = tpl.format(where=w, where_pay=wp, where_attr=wa, where_visits=wv)
    g = _group_for(metric, grain)
    if g is None:
        return base
    return base.replace("SELECT ", f"SELECT {g} AS grain_key, ", 1) + f" GROUP BY {g} ORDER BY {g}"

def _price_tokens(in_tok, out_tok, model):
    m = PRICES["models"][model]
    return round(in_tok / 1e6 * m["input_per_mtok_usd"] + out_tok / 1e6 * m["output_per_mtok_usd"], 6)

def _load_traces(days=1):
    out = []
    for i in reversed(range(days)):   # oldest day first, so the list is chronological and [-n:] is the most recent (ADR 0004 fix, 10. Oct 2026)
        f = TRACES / f"{dt.date.today() - dt.timedelta(days=i)}.jsonl"
        if f.exists():
            for l in f.read_text().splitlines():
                if l.strip():
                    try: out.append(json.loads(l))
                    except json.JSONDecodeError: out.append({"tool": "corrupt_line", "raw": l[:80]})
    return out

def _find_trace(trace_id, tool, days=1):
    """A trace line this principal produced with this tool, or None. Caller-supplied ids are claims; this is the check (audit finding 3)."""
    for r in _load_traces(days):
        if r.get("trace_id") == trace_id and r.get("tool") == tool and r.get("principal") == PRINCIPAL and not r.get("refused"):
            return r
    return None

# ------------------------------------------------------------------ tools
def _health(skill_version):
    """Is the server current with the files on disk, and is the client's skill the one this layer expects (ADR 0009)?"""
    changed = [f for f, mt in STARTED["files"].items() if (HERE / f).stat().st_mtime != mt]
    server = {"status": "stale" if changed else "current", "started": STARTED["at"], "layer_version_loaded": STARTED["layer_version"]}
    if changed:
        server["fix"] = f"{', '.join(changed)} changed on disk after this server started: restart the MCP client (Claude Desktop: quit fully, then reopen)"
    expected = str(CFG.get("skill_expected") or "")
    if not skill_version:
        skill = {"status": "undeclared", "expected": expected,
                 "fix": "no skill version declared: either the shape-my-question skill was not used for this call (fine for a direct question), or it is missing, or it is an upload older than this check (then re-upload it). Run the skill to tell which"}
    elif str(skill_version) != expected:
        skill = {"status": "outdated" if str(skill_version) < expected else "newer than this layer", "declared": str(skill_version), "expected": expected,
                 "fix": "re-upload the shape-my-question skill from the repo" if str(skill_version) < expected else "restart the MCP client so the server loads the newer layer"}
    else:
        skill = {"status": "current", "declared": str(skill_version)}
    return {"server": server, "skill": skill, "ok": not changed and skill["status"] == "current"}

def whoami(skill_version: Optional[str] = None) -> dict:
    """Who the server believes is asking, and where that belief comes from (ADR 0002). Pass skill_version (from the skill's own text)
    to have the server check that the skill and the server are both current (ADR 0009)."""
    return {"principal": PRINCIPAL, "role": ROLE, "practice_scope": PRACTICE_SCOPE, "health": _health(skill_version),
            "scope_meaning": {None: "UNSET or invalid: every data tool will refuse", "all": "explicit grant: every practice"}.get(PRACTICE_SCOPE, f"one practice: {PRACTICE_SCOPE}"),
            "policy": POLICY["roles"].get(ROLE, {"note": f"no statement for role '{ROLE}': everything denied"}),
            "source": "role and scope from server config; production: OIDC token subject and groups via a remote MCP connector",
            "trace_id": _trace(tool="whoami")}

def list_metrics() -> dict:
    """Every metric the layer defines, with domain, owner and unit, and which of them this role may ask for. The only numbers an agent may ask for."""
    if (r := _authorize("list_metrics")): return _refuse("list_metrics", r)
    stmt = POLICY["roles"][ROLE]
    return {"version": CFG["version"], "latest_change": {"version": str(CHANGELOG[0]["version"]), "change": CHANGELOG[0]["change"]},
            "metrics": {k: {"domain": v["domain"], "owner": v["owner"], "unit": v["unit"], "definition_changed_in": _defined_in(k),
                                                        "granted_to_you": "*" in stmt["metrics"] or k in stmt["metrics"]} for k, v in METRICS.items()},
            "grains_by_role": {g: [ro for ro in ROLES if "*" in POLICY["roles"][ro]["grains"] or g in POLICY["roles"][ro]["grains"]] for g in ("practice", "payer", "month", "member", "total")},
            "trace_id": _trace(tool="list_metrics")}

def explain_metric(metric: Metric) -> dict:
    """The definition, owner, version and SQL of one metric, so an answer can cite where its number came from."""
    if (r := _authorize("explain_metric", metric)): return _refuse("explain_metric", r, metric=metric)
    m = METRICS[metric]
    return {"metric": metric, **{k: m[k] for k in ("domain", "owner", "description", "unit")}, "version": CFG["version"],
            "definition_changed_in": _defined_in(metric), "layer_changes_since_definition": _since(metric),
            "history": [{"version": str(e["version"]), "date": str(e["date"]), "change": e["change"]} for e in CHANGELOG if metric in (e.get("metrics") or [])],
            "sql_template": m["sql"], "trace_id": _trace(tool="explain_metric", args={"metric": metric})}

def _count(metric, grain, wheres):
    """Rows scanned and result groups under the exact predicate the answer will use. Query errors become refusals, never tracebacks."""
    table, w = _table_and_where(metric, wheres)
    g = _group_for(metric, grain)
    with _con() as c:
        rows = c.execute(f"SELECT count(*) FROM {table} WHERE 1=1 {w}").fetchone()[0]
        groups = 1 if g is None else c.execute(f"SELECT count(DISTINCT {g}) FROM {table} WHERE 1=1 {w}").fetchone()[0]
    return rows, groups

def estimate_cost(metric: Metric, grain: Grain = "total", practice_id: Optional[int] = None, payer: Optional[str] = None,
                  month_from: Optional[str] = None, month_to: Optional[str] = None, measure: Optional[str] = None,
                  shaped_question: Optional[str] = None) -> dict:
    """Price a question BEFORE running it (ADR 0003): rows scanned, warehouse cost, estimated model tokens. Dry run, no result."""
    args = dict(metric=metric, grain=grain, practice_id=practice_id, payer=payer, month_from=month_from, month_to=month_to, measure=measure)
    if (r := _authorize("estimate_cost", metric, grain)): return _refuse("estimate_cost", r, **args)
    wheres, err = _where(metric, practice_id, payer, month_from, month_to, measure, grain)
    if err:
        return _refuse("estimate_cost", err, **args)
    t0 = time.time()
    try:
        rows, groups = _count(metric, grain, wheres)
    except duckdb.Error as e:
        return _refuse("estimate_cost", f"query error: {type(e).__name__}", **args)
    wh_usd = round(rows / 1000 * CFG["rate_per_1k_rows_usd"], 6)
    in_tok, out_tok = 350 + len(shaped_question or "") // 4, 120 + 14 * groups
    est = {"rows_scanned": rows, "result_rows": groups, "warehouse_usd": wh_usd, "model_tokens_est": {"input": in_tok, "output": out_tok},
           "model_usd_est": _price_tokens(in_tok, out_tok, PRICES["default_model"]), "prices_as_of": PRICES["as_of"],
           "label": "ESTIMATE (dry run; tokens are estimated, see ADR 0003)"}
    tid = _trace(tool="estimate_cost", args=args, shaped_question=shaped_question, estimate=est, latency_ms=int((time.time()-t0)*1000))
    return {**est, "trace_id": tid}

def get_metric(metric: Metric, grain: Grain = "total", practice_id: Optional[int] = None, payer: Optional[str] = None,
               month_from: Optional[str] = None, month_to: Optional[str] = None, measure: Optional[str] = None,
               shaped_question: Optional[str] = None, estimate_trace_id: Optional[str] = None) -> dict:
    """Answer a metric by name from the semantic layer. Returns the value(s), the definition, and the ACTUAL cost beside the estimate."""
    args = dict(metric=metric, grain=grain, practice_id=practice_id, payer=payer, month_from=month_from, month_to=month_to, measure=measure)
    if (r := _authorize("get_metric", metric, grain)): return _refuse("get_metric", r, **args)
    wheres, err = _where(metric, practice_id, payer, month_from, month_to, measure, grain)
    if err:
        return _refuse("get_metric", err, **args)
    if estimate_trace_id is not None:   # a claimed estimate must exist, be mine, and be for this exact question (audit finding 3)
        e = _find_trace(estimate_trace_id, "estimate_cost")
        if e is None or e.get("args") != args:
            return _refuse("get_metric", f"estimate_trace_id {estimate_trace_id!r} is not an estimate this principal made for these arguments", **args)
    limit = CFG.get("require_estimate_above_rows")
    if limit is not None and estimate_trace_id is None:   # priced first, above a line (ADR 0007): the dry-run count decides
        try:
            pre_rows, _ = _count(metric, grain, wheres)
        except duckdb.Error as e:
            return _refuse("get_metric", f"query error: {type(e).__name__}", **args)
        if pre_rows > limit:
            return _refuse("get_metric", f"policy: this question scans {pre_rows} rows, above the {limit}-row line; "
                           f"call estimate_cost with the same arguments and pass its trace_id as estimate_trace_id", **args)
    sql = _sql(metric, grain, wheres)
    t0 = time.time()
    try:
        with _con() as c:
            res = c.execute(sql).fetchall()
        rows, _ = _count(metric, grain, wheres)
    except duckdb.Error as e:
        return _refuse("get_metric", f"query error: {type(e).__name__}", **args)
    ms = int((time.time() - t0) * 1000)
    values = res[0][0] if grain == "total" else [{"grain_key": str(r[0]), "value": r[1]} for r in res]
    actual = {"rows_scanned": rows, "result_rows": len(res), "warehouse_usd": round(rows / 1000 * CFG["rate_per_1k_rows_usd"], 6), "latency_ms": ms,
              "label": "ACTUAL warehouse; model tokens arrive via record_answer"}
    m = METRICS[metric]
    # the audit line carries what was answered and under which definition, so "was this comparable?" can be settled later (ADR 0008)
    answered = {"layer_version": str(CFG["version"]), "definition_changed_in": _defined_in(metric),
                **({"value": values} if grain == "total" else {"result_rows": len(res)})}
    tid = _trace(tool="get_metric", args=args, shaped_question=shaped_question, sql=sql, actual=actual, estimate_trace_id=estimate_trace_id, answered=answered)
    return {"metric": metric, "value": values, "unit": m["unit"], "definition": m["description"], "owner": m["owner"], "version": CFG["version"],
            "definition_changed_in": _defined_in(metric), "layer_changes_since_definition": _since(metric),
            "window": {"from": month_from, "to": month_to}, "filters": {"practice_id": practice_id, "payer": payer, "measure": measure},
            "actual": actual, "estimate_trace_id": estimate_trace_id, "trace_id": tid, "cite_as": f"{metric} v{CFG['version']} · trace {tid}"}

def _signal(metric, grain="total", **kw):
    """One signal of the scorecard: authorise, build the predicate, count and run, like get_metric but returning a compact cell.
    A refusal becomes a cell that names its rule, so a role with a narrower grant still gets the rest of the scorecard."""
    if (r := _authorize("practice_scorecard", metric, grain)): return {"refused": True, "rule": r}
    wheres, err = _where(metric, kw.get("practice_id"), kw.get("payer"), kw.get("month_from"), kw.get("month_to"), kw.get("measure"), grain)
    if err: return {"refused": True, "rule": err}
    try:
        with _con() as c:
            res = c.execute(_sql(metric, grain, wheres)).fetchall()
        rows, _ = _count(metric, grain, wheres)
    except duckdb.Error as e:
        return {"refused": True, "rule": f"query error: {type(e).__name__}"}
    value = res[0][0] if grain == "total" else [{"grain_key": str(x[0]), "value": x[1]} for x in res]
    return {"value": value, "unit": METRICS[metric]["unit"], "definition": METRICS[metric]["description"], "owner": METRICS[metric]["owner"],
            "rows_scanned": rows, "warehouse_usd": round(rows / 1000 * CFG["rate_per_1k_rows_usd"], 6)}

def _month_add(ym, n):
    y, m = int(ym[:4]), int(ym[5:7]); m += n; y += (m - 1) // 12; m = (m - 1) % 12 + 1
    return f"{y:04d}-{m:02d}"

def practice_scorecard(practice_id: int, as_of: Optional[str] = None) -> dict:
    """The conventional answer to "how is practice X doing": four signals at their standard windows, in one call, with the defaults named.
    Gap closure rate quarter to date (with the payer's peer practices beside it); open gaps by measure, now; visits per attributed member,
    trailing three months; paid, last three paid months. One estimate, one trace, four cited numbers. Change any knob with get_metric."""
    if (r := _authorize("practice_scorecard")): return _refuse("practice_scorecard", r, practice_id=practice_id)
    if as_of is not None and not MONTH.match(as_of): return _refuse("practice_scorecard", f"as_of must be YYYY-MM; got {as_of!r}", practice_id=practice_id)
    # scope first, at the tool level (smoke test, 8. Oct 2026): without this an out-of-scope practice returned a scorecard shell
    # with every cell refused but the header filled in, which leaked that practice's payer. Fail closed before any lookup.
    if PRACTICE_SCOPE is None:
        return _refuse("practice_scorecard", f"scope policy: no practice scope configured for principal '{PRINCIPAL}' (role '{ROLE}')", practice_id=practice_id)
    if isinstance(practice_id, bool) or practice_id not in PRACTICES:
        return _refuse("practice_scorecard", f"unknown practice_id {practice_id!r}; practices are 1..{max(PRACTICES)}", practice_id=practice_id)
    if PRACTICE_SCOPE != "all" and practice_id != PRACTICE_SCOPE:
        return _refuse("practice_scorecard", f"row policy: principal '{PRINCIPAL}' may only see practice {PRACTICE_SCOPE}", practice_id=practice_id)
    with _con() as c:
        latest = c.execute("SELECT strftime(max(action_date), '%Y-%m') FROM actions").fetchone()[0]
    as_of = as_of or latest
    q_start = f"{as_of[:4]}-{((int(as_of[5:7]) - 1) // 3) * 3 + 1:02d}"
    t3_start = _month_add(as_of, -2)
    with _con() as c:
        payer = c.execute("SELECT payer FROM practices WHERE practice_id = ?", [practice_id]).fetchone() if practice_id in PRACTICES else None
    payer = payer[0] if payer else None
    t0 = time.time()
    sig = {}
    sig["gap_closure_rate_qtd"] = {"window": {"from": q_start, "to": as_of}, "compared_with": "the payer's peer practices, same window",
        **_signal("gap_closure_rate", practice_id=practice_id, month_from=q_start, month_to=as_of)}
    peers = _signal("gap_closure_rate", payer=payer, month_from=q_start, month_to=as_of) if payer else {"refused": True, "rule": "no payer for this practice"}
    sig["gap_closure_rate_qtd"]["peers"] = {k: peers.get(k) for k in ("value", "refused", "rule", "rows_scanned", "warehouse_usd")} | {"payer": payer, "note": "all practices of the payer, this one included"}
    sig["gap_closure_rate_qtd"]["same_quarter_last_year"] = {"value": None, "note": "no data: the synthetic set covers 2026 only"}
    by_measure = {}
    for m in MEASURES:
        cell = _signal("care_gaps_open", practice_id=practice_id, month_from=q_start, month_to=as_of, measure=m)
        by_measure[m] = {k: cell.get(k) for k in ("value", "refused", "rule", "rows_scanned", "warehouse_usd")}
    sig["open_gaps_by_measure"] = {"window": {"from": q_start, "to": as_of}, "compared_with": "year end: quality programs close on 31. Dec", "unit": "actions",
        "definition": METRICS["care_gaps_open"]["description"], "owner": METRICS["care_gaps_open"]["owner"], "values": by_measure}
    v = _signal("visit_count", practice_id=practice_id, month_from=t3_start, month_to=as_of)
    a = _signal("attributed_members", practice_id=practice_id, month_from=t3_start, month_to=as_of)
    sig["visits_per_attributed_member_t3m"] = {"window": {"from": t3_start, "to": as_of}, "compared_with": "the prior three months (ask: get_metric, same two metrics)",
        "visits": {k: v.get(k) for k in ("value", "refused", "rule", "rows_scanned", "warehouse_usd")},
        "attributed_members": {k: a.get(k) for k in ("value", "refused", "rule", "rows_scanned", "warehouse_usd")},
        "value": (round(v["value"] / a["value"], 4) if not v.get("refused") and not a.get("refused") and a.get("value") else None), "unit": "visits per member"}
    sig["paid_by_month_l3"] = {"window": {"from": t3_start, "to": as_of}, "compared_with": "the run before each month, so a late run is visible",
        **_signal("actions_paid_usd", grain="month", practice_id=practice_id, month_from=t3_start, month_to=as_of)}
    cells = [sig["gap_closure_rate_qtd"], sig["gap_closure_rate_qtd"]["peers"], *by_measure.values(), sig["visits_per_attributed_member_t3m"]["visits"],
             sig["visits_per_attributed_member_t3m"]["attributed_members"], sig["paid_by_month_l3"]]
    rows = sum(c.get("rows_scanned") or 0 for c in cells); refused = sum(1 for c in cells if c.get("refused"))
    actual = {"rows_scanned": rows, "warehouse_usd": round(rows / 1000 * CFG["rate_per_1k_rows_usd"], 6), "latency_ms": int((time.time() - t0) * 1000),
              "signals": len(sig), "cells_refused": refused, "label": "ACTUAL warehouse; model tokens arrive via record_answer"}
    defaults = {"as_of": as_of, "quarter_to_date": {"from": q_start, "to": as_of}, "trailing_3_months": {"from": t3_start, "to": as_of}, "peers": f"practices of {payer}" if payer else None,
                "say_to_change": "any of: a month or quarter ('Q2'), one measure ('A1C only'), a grain ('by month'), a payer; each knob is one get_metric call"}
    tid = _trace(tool="practice_scorecard", args={"practice_id": practice_id, "as_of": as_of}, defaults=defaults, actual=actual,
                 cells_refused=[c["rule"] for c in cells if c.get("refused")])
    return {"practice_id": practice_id, "defaults": defaults, "signals": sig, "version": CFG["version"], "actual": actual, "trace_id": tid,
            "cite_as": f"practice_scorecard v{CFG['version']} · trace {tid}", "label": "the conventional reading; every number is one of the named metrics at its stated window"}

def request_capability(business_case: str, data_needed: str, owner: str, review_date: str) -> dict:
    """Governance intake. Records a request for a new metric, grain or access; never grants it. A human edits metrics.yaml after review."""
    if (r := _authorize("request_capability")): return _refuse("request_capability", r)
    tid = _trace(tool="request_capability", request={"business_case": business_case, "data_needed": data_needed, "owner": owner, "review_date": review_date})
    return {"status": "logged for review", "granted": False, "next": f"reviewed by the metric owner before {review_date}; a grant is a commit to metrics.yaml", "trace_id": tid}

def record_answer(trace_id: str, model: str, input_tokens_est: int, output_tokens_est: int, answer_summary: Optional[str] = None) -> dict:
    """The skill reports the model side of an answer (estimated tokens; exact only via the Agent SDK) so cost_report can price it.
    The answer must be one this principal received, not yet recorded; the model must be a priced one; the counts must be plausible."""
    if (r := _authorize("record_answer")): return _refuse("record_answer", r, trace_id=trace_id)
    if model not in PRICES["models"]:
        return _refuse("record_answer", f"unknown model {model!r}; priced models: {sorted(PRICES['models'])}", trace_id=trace_id, model=model)
    if not (0 <= input_tokens_est <= TOKEN_CAP and 0 <= output_tokens_est <= TOKEN_CAP):
        return _refuse("record_answer", f"token estimates must be between 0 and {TOKEN_CAP}", trace_id=trace_id)
    if _find_trace(trace_id, "get_metric") is None:
        return _refuse("record_answer", f"trace_id {trace_id!r} is not an answer this principal received", trace_id=trace_id)
    if any(t.get("tool") == "record_answer" and t.get("for_trace") == trace_id for t in _load_traces()):
        return _refuse("record_answer", f"trace_id {trace_id!r} already has a model record", trace_id=trace_id)
    usd = _price_tokens(input_tokens_est, output_tokens_est, model)
    tid = _trace(tool="record_answer", for_trace=trace_id, model=model, tokens_est={"input": input_tokens_est, "output": output_tokens_est}, model_usd_est=usd, answer_summary=answer_summary)
    return {"recorded": True, "model_usd_est": usd, "prices_as_of": PRICES["as_of"], "label": "ESTIMATED tokens (ADR 0003)", "trace_id": tid}

def cost_report(days: int = 1) -> dict:
    """Estimate versus actual, per answer, per role and per metric, from the trace. Your own answers unless you are admin. Model lines are estimates until the SDK path exists."""
    if (r := _authorize("cost_report")): return _refuse("cost_report", r, days=days)
    rows = _load_traces(days)
    if "*" not in POLICY["roles"][ROLE].get("trace_scope", ["own"]):
        rows = [x for x in rows if x.get("principal") == PRINCIPAL]
    answers = [x for x in rows if x.get("tool") == "get_metric" and not x.get("refused")]
    ests = {x["trace_id"]: x for x in rows if x.get("tool") == "estimate_cost"}
    model = {x.get("for_trace"): x for x in rows if x.get("tool") == "record_answer"}
    per = []
    for a in answers:
        e = ests.get(a.get("estimate_trace_id") or "")
        m = model.get(a["trace_id"])
        per.append({"trace_id": a["trace_id"], "principal": a["principal"], "metric": a["args"]["metric"], "grain": a["args"]["grain"], "role": a["role"],
                    "estimate_warehouse_usd": e["estimate"]["warehouse_usd"] if e else None, "actual_warehouse_usd": a["actual"]["warehouse_usd"],
                    "estimate_rows": e["estimate"]["rows_scanned"] if e else None, "actual_rows": a["actual"]["rows_scanned"],
                    "model_usd_est": m["model_usd_est"] if m else None})
    by_role, by_metric = {}, {}
    for p in per:
        by_role[p["role"]] = round(by_role.get(p["role"], 0) + p["actual_warehouse_usd"] + (p["model_usd_est"] or 0), 6)
        by_metric[p["metric"]] = round(by_metric.get(p["metric"], 0) + p["actual_warehouse_usd"] + (p["model_usd_est"] or 0), 6)
    return {"days": days, "scope": "all principals" if "*" in POLICY["roles"][ROLE].get("trace_scope", ["own"]) else f"principal {PRINCIPAL} only",
            "answers": len(per), "refusals": sum(1 for x in rows if x.get("refused")), "per_answer": per, "by_role_usd": by_role, "by_metric_usd": by_metric,
            "prices_as_of": PRICES["as_of"], "warehouse_rate_per_1k_rows": CFG["rate_per_1k_rows_usd"], "label": "model costs are ESTIMATES (ADR 0003)",
            "trace_id": _trace(tool="cost_report", args={"days": days})}

def audit_log(n: int = 20) -> dict:
    """The last n trace lines, all principals. Granted by policy (admin) only (ADR 0004)."""
    if (r := _authorize("audit_log")): return _refuse("audit_log", r, n=n)
    rows = _load_traces(7)[-n:]
    return {"count": len(rows), "lines": rows, "trace_id": _trace(tool="audit_log", args={"n": n})}

TOOLS = (whoami, list_metrics, explain_metric, estimate_cost, get_metric, practice_scorecard, request_capability, record_answer, cost_report, audit_log)
for fn in TOOLS:
    mcp.tool()(fn)

# Every policy statement may only name tools that exist; a typo in metrics.yaml must fail loudly, not grant nothing silently.
for _role, _stmt in POLICY["roles"].items():
    for _t in _stmt.get("tools", []):
        if _t != "*" and _t not in {f.__name__ for f in TOOLS}:
            raise SystemExit(f"metrics.yaml policy.roles.{_role}.tools names unknown tool '{_t}'")

@mcp.prompt()
def practice_performance(practice: str = "Practice 12") -> str:
    """A pre-shaped start: how a practice is doing. The scorecard first, with its defaults named; then the knobs."""
    return (f"How is {practice} doing? Call practice_scorecard for it first and show me the four signals as a table, with the defaults "
            f"it chose (as-of month, quarter to date, trailing three months, peer payer) in the caption. Then offer the knobs in one line: "
            f"a different window, one measure, a grain, a payer; each is one get_metric call. Cite the scorecard's trace id and the metric definitions.")

@mcp.prompt()
def care_gap_trend(months: str = "2026-01 to 2026-09") -> str:
    """A pre-shaped start: open care gaps by month, deduplicated, with the definition attached."""
    return (f"Show open care gaps by month for {months}. Ask which measure first if I did not say. Call estimate_cost before get_metric, "
            f"use grain 'month', and cite care_gaps_open's definition and the trace id in the answer.")

if __name__ == "__main__":
    mcp.run()
