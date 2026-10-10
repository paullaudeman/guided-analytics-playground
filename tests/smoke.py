"""Smoke test every tool in-process, as four roles, with an assertion per audit finding (7. Oct 2026).
Run: uv run --with "mcp<2",duckdb,pyyaml python tests/smoke.py"""
import importlib, os, sys, json, pathlib, tempfile
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))
os.environ["TRACES"] = tempfile.mkdtemp(prefix="smoke-traces-")   # never the repo's trace file

def load(role, practice=None, principal=None):
    os.environ["ROLE"] = role; os.environ["PRINCIPAL"] = principal or f"{role}.demo"
    if practice is None: os.environ.pop("PRACTICE_ID", None)
    else: os.environ["PRACTICE_ID"] = str(practice)
    import server; importlib.reload(server); return server

def refused(r, why=""): assert r.get("refused"), f"expected a refusal {why}, got {json.dumps(r)[:200]}"; return r["rule"]
def answered(r, why=""): assert not r.get("refused"), f"expected an answer {why}, got {r.get('rule')}"; return r

checks = []
def ok(label, rule=None): checks.append(label); print(f"  ok  {label}" + (f"  ·  {rule}" if rule else ""))

# ---- external, practice 12
s = load("external", 12)
print("=== external, scope 12")
ok("member grain refused by policy", refused(s.estimate_cost("care_gaps_open", grain="member"), "member grain"))
ok("other practice refused by row policy", refused(s.get_metric("care_gaps_open", practice_id=3), "practice 3"))
ok("money metric refused by policy (not granted)", refused(s.get_metric("actions_paid_usd", practice_id=12), "actions_paid_usd"))
ok("payer grain refused by policy", refused(s.get_metric("care_gaps_open", grain="payer"), "payer grain"))
ok("cost_report refused by policy", refused(s.cost_report(), "cost_report"))
ok("audit_log refused by policy", refused(s.audit_log(3), "audit_log"))
own = answered(s.get_metric("care_gaps_open", grain="practice", practice_id=12, month_from="2026-07", month_to="2026-09", measure="A1C"), "own practice")
ok(f"own practice answered: {own['value']}")
vis = answered(s.get_metric("visit_closure_rate", grain="practice", practice_id=12, month_from="2026-07", month_to="2026-09"), "visits metric, own practice")
ok(f"visit_closure_rate answered: {vis['value']}")
ok("measure on a visits metric refused", refused(s.get_metric("visit_count", practice_id=12, measure="A1C"), "measure on visits"))
sc = answered(s.practice_scorecard(12), "scorecard, external"); assert sc["signals"]["paid_by_month_l3"].get("refused") and "actions_paid_usd" in sc["signals"]["paid_by_month_l3"]["rule"], sc["signals"]["paid_by_month_l3"]
assert not sc["signals"]["gap_closure_rate_qtd"].get("refused") and sc["defaults"]["quarter_to_date"] == {"from": "2026-07", "to": "2026-09"}
ok(f"scorecard for external: paid cell refused by policy, the rest answered; QTD {sc['defaults']['quarter_to_date']['from']} to {sc['defaults']['quarter_to_date']['to']}")
ok("scorecard for another practice refused by row policy", refused(s.practice_scorecard(3), "scorecard practice 3"))
# finding 1: injection through the month fields is refused, never interpolated
inj = refused(s.get_metric("care_gaps_open", month_from="2026-07-01' OR practice_id<>12 OR action_date>=DATE '2026-07"), "month injection")
assert "must be YYYY-MM" in inj, inj; ok("month injection refused", inj)
ok("bad month refused, no traceback", refused(s.get_metric("care_gaps_open", month_from="2026-13"), "2026-13"))
ok("month order checked", refused(s.get_metric("care_gaps_open", month_from="2026-09", month_to="2026-01"), "from after to"))
ok("unknown payer refused", refused(s.get_metric("care_gaps_open", payer="x') OR 1=1 --"), "payer"))
ok("bool practice_id refused", refused(s.get_metric("care_gaps_open", practice_id=True), "True"))
ok("unknown practice_id refused", refused(s.get_metric("care_gaps_open", practice_id=99), "99"))
# finding 3: forged trace links
ok("forged record_answer refused", refused(s.record_answer("t-doesnotexist", "claude-sonnet", 10, 10), "forged for_trace"))
ok("forged estimate_trace_id refused", refused(s.get_metric("care_gaps_open", practice_id=12, estimate_trace_id="t-forged"), "forged estimate"))
rec = answered(s.record_answer(own["trace_id"], "claude-sonnet", 900, 180), "own answer")
ok(f"own answer recorded ${rec['model_usd_est']}")
ok("double record refused", refused(s.record_answer(own["trace_id"], "claude-sonnet", 900, 180), "second record"))
r = refused(s.record_answer(own["trace_id"], "gpt-9", 1, 1), "model"); assert "unknown model" in r, r; ok("unknown model refused", r)
r = refused(s.record_answer(own["trace_id"], "claude-sonnet", 10**9, 1), "tokens"); assert "token estimates" in r, r; ok("absurd tokens refused", r)

# ---- csm, all
s = load("csm", "all")
print("=== csm, scope all")
ok("member grain refused", refused(s.estimate_cost("care_gaps_open", grain="member")))
pay = answered(s.get_metric("care_gaps_open", grain="payer", month_from="2026-07", month_to="2026-09"), "payer grain")
est = answered(s.estimate_cost("care_gaps_open", grain="payer", month_from="2026-07", month_to="2026-09"))
assert est["result_rows"] == len(pay["value"]) == 3, (est["result_rows"], len(pay["value"]))
vp = answered(s.get_metric("visit_count", grain="payer", month_from="2026-07", month_to="2026-09"), "visits by payer"); assert len(vp["value"]) == 3
ok("visit_count at payer grain answered")
ok(f"payer grain answered, estimate groups == actual groups == {est['result_rows']}")
apr = answered(s.get_metric("actions_paid_usd", grain="practice", practice_id=3, month_from="2026-04", month_to="2026-04"))
ok(f"paid Apr practice 3 (late-run trap): {apr['value'][0]['value']}")
cr = answered(s.cost_report()); assert all(p["principal"] == "csm.demo" for p in cr["per_answer"]), "csm sees other principals"
ok(f"cost_report scoped to own principal: {cr['scope']}")
ok("audit_log refused", refused(s.audit_log(3)))

# ---- admin, all
s = load("admin", "all")
print("=== admin, scope all")
e1 = answered(s.estimate_cost("care_gaps_open", grain="member", month_from="2026-01", month_to="2026-09", shaped_question="everything"))
e2 = answered(s.estimate_cost("care_gaps_open", grain="practice", practice_id=12, month_from="2026-07", month_to="2026-09", measure="A1C", shaped_question="Practice 12 open A1C gaps, Q3"))
g = answered(s.get_metric("care_gaps_open", grain="practice", practice_id=12, month_from="2026-07", month_to="2026-09", measure="A1C", estimate_trace_id=e2["trace_id"]))
ok(f"naive {e1['rows_scanned']} rows vs shaped {e2['rows_scanned']} rows; answer {g['value'][0]['value']}")
mism = refused(s.get_metric("care_gaps_open", grain="practice", practice_id=12, month_from="2026-07", month_to="2026-08", measure="A1C", estimate_trace_id=e2["trace_id"]), "estimate for other args")
ok("estimate_trace_id for different arguments refused", mism)
a = answered(s.get_metric("gap_closure_rate", practice_id=12, month_from="2026-07", month_to="2026-09"))
b = answered(s.get_metric("gap_closure_rate", practice_id=12, month_from="2026-07", month_to="2026-09", measure=None))
assert a["value"] == b["value"]; ok(f"same number twice: {a['value']}")
assert answered(s.audit_log(3))["count"] == 3; ok("audit_log answered")
sc = answered(s.practice_scorecard(12, as_of="2026-09")); assert sc["actual"]["cells_refused"] == 0 and sc["signals"]["gap_closure_rate_qtd"]["value"] == a["value"]
ok(f"scorecard for admin: {sc['actual']['signals']} signals, 0 cells refused, QTD closure == the Q3 metric ({sc['signals']['gap_closure_rate_qtd']['value']}), peers {sc['signals']['gap_closure_rate_qtd']['peers']['value']}, {sc['actual']['rows_scanned']} rows")
ok("scorecard with a bad as_of refused", refused(s.practice_scorecard(12, as_of="Q3"), "as_of"))
cr = answered(s.cost_report()); ok(f"cost_report across principals: {cr['scope']}, {cr['answers']} answers")
ok("unknown measure refused", refused(s.estimate_cost("care_gaps_open", measure="HBA1C")))

# ---- scope: unset and junk refuse for every role, admin included (ADR 0002, amended)
for v in (None, "12,13", "0", "99", "abc"):
    s = load("admin", v); r = refused(s.get_metric("care_gaps_open", practice_id=12), f"scope {v!r}")
    assert s.PRACTICE_SCOPE is None
ok("unset or junk PRACTICE_ID refuses, never crashes", r)

# ---- default deny: a role with no statement gets nothing (ADR 0006)
# ---- priced first, above a line (ADR 0007)
s = load("admin", "all")
print("=== priced first, above the row line")
wide = dict(grain="total")                      # every paid action ever: scans past the line
r = refused(s.get_metric("actions_paid_usd", **wide), "wide, no estimate"); assert "row line" in r, r; ok("wide question without an estimate refused", r)
e = s.estimate_cost("actions_paid_usd", **wide)
w = answered(s.get_metric("actions_paid_usd", **wide, estimate_trace_id=e["trace_id"]), "wide, with its estimate")
ok(f"same question with its estimate answered ({e['rows_scanned']} rows priced first)")
n = answered(s.get_metric("attributed_members", grain="practice", month_from="2026-07", month_to="2026-09"), "narrow, no estimate")
ok(f"narrow question needs no estimate ({n['actual']['rows_scanned']} rows)")

s = load("intern", "all")
print("=== intern (no policy statement)")
ok("list_metrics refused", refused(s.list_metrics()))
ok("get_metric refused", refused(s.get_metric("care_gaps_open")))

print(f"\n{len(checks)} checks passed · traces in {os.environ['TRACES']}")
