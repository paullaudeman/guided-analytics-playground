"""Capture every number the guided walkthrough shows, from the real server and the real data.
Run: uv run --with "mcp<2",duckdb,pyyaml python docs/walkthrough_capture.py [--traces DIR]
Writes docs/walkthrough-data.json. Nothing in the walkthrough HTML is typed by hand; it is all from here."""
import importlib, json, os, pathlib, sys, argparse
import duckdb, yaml
ROOT = pathlib.Path(__file__).parent.parent; sys.path.insert(0, str(ROOT))
ap = argparse.ArgumentParser(); ap.add_argument("--traces", default=str(ROOT / "traces")); a = ap.parse_args()

def load(role, practice=None):
    os.environ["ROLE"] = role; os.environ["PRINCIPAL"] = f"{role}.demo"; os.environ["TRACES"] = a.traces
    if practice is None: os.environ.pop("PRACTICE_ID", None)   # the unset case: must refuse
    else: os.environ["PRACTICE_ID"] = str(practice)
    import server; importlib.reload(server); return server

out = {"captured_at": __import__("datetime").datetime.now().isoformat(timespec="seconds"), "roles": {}}
out["metrics_yaml"] = yaml.safe_load((ROOT / "metrics.yaml").read_text())
out["prices_yaml"] = yaml.safe_load((ROOT / "prices.yaml").read_text())
out["skill_md"] = (ROOT / "skill" / "shape-my-question" / "SKILL.md").read_text()
out["project_instructions"] = (ROOT / "skill" / "project-instructions.md").read_text()

# --- the main journey, as admin (so nothing is refused)
s = load("admin", practice="all")
j = {}
j["whoami"] = s.whoami()
j["list_metrics"] = s.list_metrics()
j["explain_metric"] = s.explain_metric("care_gaps_open")
naive_args = dict(metric="care_gaps_open", grain="member", month_from="2026-01", month_to="2026-09", shaped_question="all member-level open gaps, every practice, all year")
shaped_args = dict(metric="care_gaps_open", grain="practice", practice_id=12, month_from="2026-07", month_to="2026-09", measure="A1C", shaped_question="Practice 12 open A1C gaps, Q3")
j["estimate_naive"] = {"args": naive_args, "result": s.estimate_cost(**naive_args)}
j["estimate_shaped"] = {"args": shaped_args, "result": s.estimate_cost(**shaped_args)}
ga = {**shaped_args, "estimate_trace_id": j["estimate_shaped"]["result"]["trace_id"]}
j["get_metric"] = {"args": ga, "result": s.get_metric(**ga)}
ra = dict(trace_id=j["get_metric"]["result"]["trace_id"], model="claude-sonnet", input_tokens_est=900, output_tokens_est=180, answer_summary="Practice 12 open A1C gaps Q3")
j["record_answer"] = {"args": ra, "result": s.record_answer(**ra)}
j["same_number_twice"] = {
  "a": {"args": dict(metric="gap_closure_rate", practice_id=12, month_from="2026-07", month_to="2026-09"), "result": s.get_metric("gap_closure_rate", practice_id=12, month_from="2026-07", month_to="2026-09", shaped_question="What share of Practice 12's care actions got done in Q3?")},
  "b": {"args": dict(metric="gap_closure_rate", practice_id=12, month_from="2026-07", month_to="2026-09", measure=None), "result": s.get_metric("gap_closure_rate", practice_id=12, month_from="2026-07", month_to="2026-09", measure=None, shaped_question="Practice 12 gap closure rate, July through September")}}
j["request_capability"] = {"args": dict(business_case="exec view: closure by payer with payments", data_needed="gap closure rate joined to actions_paid_usd by payer", owner="VP Analytics", review_date="2026-10-21"),
                           "result": s.request_capability("exec view: closure by payer with payments", "gap closure rate joined to actions_paid_usd by payer", "VP Analytics", "2026-10-21")}
j["unknown_measure"] = {"args": dict(metric="care_gaps_open", measure="HBA1C"), "result": s.estimate_cost("care_gaps_open", measure="HBA1C")}
j["cost_report"] = s.cost_report()
j["audit_log"] = s.audit_log(8)
out["roles"]["admin"] = j

# --- refusals, as external (practice 12) and csm
e = load("external", practice=12); r = {}
r["whoami"] = e.whoami()
r["member_grain"] = {"args": dict(metric="care_gaps_open", grain="member", month_from="2026-01", month_to="2026-09"), "result": e.estimate_cost("care_gaps_open", grain="member", month_from="2026-01", month_to="2026-09")}
r["other_practice"] = {"args": dict(metric="care_gaps_open", grain="practice", practice_id=3, month_from="2026-07", month_to="2026-09"), "result": e.get_metric("care_gaps_open", grain="practice", practice_id=3, month_from="2026-07", month_to="2026-09")}
r["own_practice"] = {"args": dict(metric="care_gaps_open", grain="practice", practice_id=12, month_from="2026-07", month_to="2026-09", measure="A1C"), "result": e.get_metric("care_gaps_open", grain="practice", practice_id=12, month_from="2026-07", month_to="2026-09", measure="A1C")}
r["money_metric"] = {"args": dict(metric="actions_paid_usd", grain="practice", practice_id=12, month_from="2026-07", month_to="2026-09"), "result": e.get_metric("actions_paid_usd", grain="practice", practice_id=12, month_from="2026-07", month_to="2026-09")}
r["audit_log"] = e.audit_log(3)
out["roles"]["external"] = r
c = load("csm", practice="all"); cs = {}
cs["whoami"] = c.whoami()
cs["member_grain"] = {"args": dict(metric="care_gaps_open", grain="member"), "result": c.estimate_cost("care_gaps_open", grain="member")}
cs["payer_grain"] = {"args": dict(metric="care_gaps_open", grain="payer", month_from="2026-07", month_to="2026-09"), "result": c.get_metric("care_gaps_open", grain="payer", month_from="2026-07", month_to="2026-09")}
cs["paid_apr_p3"] = {"args": dict(metric="actions_paid_usd", grain="practice", practice_id=3, month_from="2026-04", month_to="2026-04"), "result": c.get_metric("actions_paid_usd", grain="practice", practice_id=3, month_from="2026-04", month_to="2026-04")}
cs["paid_may_p3"] = {"args": dict(metric="actions_paid_usd", grain="practice", practice_id=3, month_from="2026-05", month_to="2026-05"), "result": c.get_metric("actions_paid_usd", grain="practice", practice_id=3, month_from="2026-05", month_to="2026-05")}
out["roles"]["csm"] = cs
u = load("admin", practice=None); un = {"whoami": u.whoami()}
un["get_metric"] = {"args": dict(metric="care_gaps_open", practice_id=12), "result": u.get_metric("care_gaps_open", practice_id=12)}
out["roles"]["admin_unset"] = un

# --- the trace lines this capture produced (the journey's receipts)
tf = pathlib.Path(a.traces) / f"{__import__('datetime').date.today()}.jsonl"
out["trace_lines"] = [json.loads(l) for l in tf.read_text().splitlines() if l.strip()] if tf.exists() else []

# --- the data underneath: counts and the four traps, by independent SQL
con = duckdb.connect(str(ROOT / "data" / "northstar.duckdb"), read_only=True)
q = lambda sql: con.execute(sql).fetchall()
d = {"tables": {t: q(f"SELECT count(*) FROM {t}")[0][0] for t in ("practices", "members", "attribution", "actions", "payments", "visits")}}
d["columns"] = {t: [r[0] for r in q(f"DESCRIBE {t}")] for t in ("practices", "members", "attribution", "actions", "payments", "visits")}
d["traps"] = {
 "double_attribution": {"sql": "SELECT count(*) FROM (SELECT member_id FROM attribution WHERE month=DATE '2026-03-01' GROUP BY member_id HAVING count(DISTINCT practice_id)>1)", "value": q("SELECT count(*) FROM (SELECT member_id FROM attribution WHERE month=DATE '2026-03-01' GROUP BY member_id HAVING count(DISTINCT practice_id)>1)")[0][0]},
 "silent_june_p7": {"sql": "SELECT date_trunc('month',action_date) m, count(*) FROM actions WHERE practice_id=7 AND action_date BETWEEN DATE '2026-05-01' AND DATE '2026-07-31' GROUP BY 1 ORDER BY 1",
                    "rows": [[str(x[0])[:7], x[1]] for x in q("SELECT date_trunc('month',action_date) m, count(*) FROM actions WHERE practice_id=7 AND action_date BETWEEN DATE '2026-05-01' AND DATE '2026-07-31' GROUP BY 1 ORDER BY 1")]},
 "late_april_payments": {"sql": "SELECT paid_month, round(sum(amount),2) FROM payments WHERE paid_month BETWEEN DATE '2026-03-01' AND DATE '2026-06-01' GROUP BY 1 ORDER BY 1",
                         "rows": [[str(x[0])[:7], float(x[1])] for x in q("SELECT paid_month, round(sum(amount),2) FROM payments WHERE paid_month BETWEEN DATE '2026-03-01' AND DATE '2026-06-01' GROUP BY 1 ORDER BY 1")]},
 "duplicate_actions": {"sql": "SELECT count(*) - count(DISTINCT action_id) FROM actions", "value": q("SELECT count(*) - count(DISTINCT action_id) FROM actions")[0][0]},
}
# q14: the naive join (payments joined to raw actions, duplicates paid twice) vs the deduplicated join
d["q14"] = {"naive_sql": "SELECT ROUND(SUM(amount),2) FROM payments p JOIN actions a USING(action_id) WHERE p.paid_month BETWEEN DATE '2026-01-01' AND DATE '2026-09-01'",
            "naive_value": float(q("SELECT ROUND(SUM(amount),2) FROM payments p JOIN actions a USING(action_id) WHERE p.paid_month BETWEEN DATE '2026-01-01' AND DATE '2026-09-01'")[0][0]),
            "dedup_value": float(q("SELECT ROUND(SUM(amount),2) FROM payments p JOIN (SELECT DISTINCT action_id FROM actions) a USING(action_id) WHERE p.paid_month BETWEEN DATE '2026-01-01' AND DATE '2026-09-01'")[0][0]),
            "independent_sql": "SELECT ROUND(COALESCE(sum(amount),0),2) FROM payments WHERE paid_month>=DATE '2026-01-01' AND paid_month<=DATE '2026-09-01'",
            "independent_value": float(q("SELECT ROUND(COALESCE(sum(amount),0),2) FROM payments WHERE paid_month>=DATE '2026-01-01' AND paid_month<=DATE '2026-09-01'")[0][0])}
d["p12_sample"] = [dict(zip(["action_id","member_id","measure","status","action_date"], map(str, x))) for x in q("SELECT action_id, member_id, measure, status, action_date FROM actions WHERE practice_id=12 AND measure='A1C' AND status='open' AND action_date>=DATE '2026-07-01' ORDER BY action_date LIMIT 5")]
# the second fact table (8. Oct 2026): the same question under three join keys, and the walk-ins that explain the gap
w = "v.practice_id=12 AND v.visit_date>=DATE '2026-07-01' AND v.visit_date<DATE '2026-10-01'"
keys = [("member only", "a.member_id=v.member_id"), ("member + month", "a.member_id=v.member_id AND a.m=date_trunc('month', v.visit_date)"),
        ("member + practice + month", "a.member_id=v.member_id AND a.practice_id=v.practice_id AND a.m=date_trunc('month', v.visit_date)")]
d["join_key"] = {"question": "share of Practice 12's Q3 visits where the member had a completed action there that month",
  "keys": [{"key": k, "value": float(q(f"SELECT ROUND(COUNT(DISTINCT v.visit_id) FILTER (WHERE a.member_id IS NOT NULL)*1.0/COUNT(DISTINCT v.visit_id),4) FROM visits v LEFT JOIN (SELECT DISTINCT member_id, practice_id, date_trunc('month', action_date) AS m FROM actions WHERE status='completed') a ON {on} WHERE {w}")[0][0])} for k, on in keys],
  "visits": q(f"SELECT count(*) FROM visits v WHERE {w}")[0][0],
  "walk_ins": q(f"SELECT count(*) FROM visits v WHERE {w} AND NOT EXISTS (SELECT 1 FROM attribution t WHERE t.member_id=v.member_id AND t.practice_id=v.practice_id AND t.month=date_trunc('month', v.visit_date))")[0][0]}
# OLTP versus the star (8. Oct 2026): one member at practice 12 with two completed, paid actions in one month, every table they touch
mid = q("SELECT a.member_id FROM actions a JOIN payments p USING(action_id) WHERE a.practice_id=12 AND a.status='completed' GROUP BY a.member_id, date_trunc('month', a.action_date) HAVING count(DISTINCT a.action_id)>=2 ORDER BY a.member_id LIMIT 1")[0][0]
acts = q(f"SELECT DISTINCT a.action_id, a.member_id, a.practice_id, a.measure, a.status, a.action_date FROM actions a JOIN payments p USING(action_id) WHERE a.practice_id=12 AND a.member_id={mid} AND a.status='completed' ORDER BY a.action_date LIMIT 2")
ids = ",".join(str(x[0]) for x in acts)
d["oltp_star"] = {
  "members": [dict(zip(["member_id","member_number","member_name","dob","sex","payer"], map(str, r))) for r in q(f"SELECT * FROM members WHERE member_id={mid}")],
  "practices": [dict(zip(["practice_id","practice_name","state","payer"], map(str, r))) for r in q("SELECT * FROM practices WHERE practice_id=12")],
  "actions": [dict(zip(["action_id","member_id","practice_id","measure","status","action_date"], map(str, r))) for r in acts],
  "payments": [dict(zip(["action_id","practice_id","paid_month","amount"], map(str, r))) for r in q(f"SELECT * FROM payments WHERE action_id IN ({ids}) ORDER BY action_id")],
}
out["data"] = d

# --- evals summary
ev = json.loads((ROOT / "evals" / "questions.json").read_text())
out["evals"] = {"version": ev.get("version"), "signed": ev.get("signed"), "count": len(ev["questions"]),
                "signed_count": sum(1 for x in ev["questions"] if x.get("signed_by")),
                "questions": [{k: x.get(k) for k in ("id", "question", "metric", "expected")} for x in ev["questions"]]}
(ROOT / "docs" / "walkthrough-data.json").write_text(json.dumps(out, indent=1, default=str))
print("wrote docs/walkthrough-data.json", len(json.dumps(out, default=str)), "bytes;", len(out["trace_lines"]), "trace lines")
