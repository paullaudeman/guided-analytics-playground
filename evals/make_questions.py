"""Build evals/questions.json: 20 questions with expected values computed by INDEPENDENT SQL (not the metric templates),
so the evals test the semantic layer's definitions, including the dedup and paid-month rules the traps are built to catch.
A human signs the file after reading it; the `signed_by` field stays empty until then.
Run: uv run --with duckdb python evals/make_questions.py
"""
import json, pathlib, duckdb
HERE = pathlib.Path(__file__).parent
con = duckdb.connect(str(HERE.parent / "data" / "northstar.duckdb"), read_only=True)
q = lambda sql: con.execute(sql).fetchone()[0]

Q = []
def add(text, metric, args, sql, note=""):
    Q.append({"id": f"q{len(Q)+1:02d}", "question": text, "metric": metric, "args": args, "expected": q(sql), "independent_sql": sql, "note": note, "signed_by": ""})

for pid, mf, mt in [(12, "2026-07", "2026-09"), (3, "2026-01", "2026-03"), (7, "2026-06", "2026-06")]:
    add(f"How many open care gaps does Practice {pid:02d} have, {mf} to {mt}?", "care_gaps_open",
        {"practice_id": pid, "month_from": mf, "month_to": mt},
        f"SELECT count(DISTINCT action_id) FROM actions WHERE status='open' AND practice_id={pid} AND action_date>=DATE '{mf}-01' AND action_date<DATE '{mt}-01'+INTERVAL 1 MONTH",
        "Practice 07 in June is the no-actions trap: expected 0, not an error" if pid == 7 else "dedup on action_id: the 60 duplicated rows must not count twice")
for pid, mf, mt, meas in [(12, "2026-07", "2026-09", "A1C"), (5, "2026-01", "2026-09", "AWV")]:
    add(f"Open {meas} gaps for Practice {pid:02d}, {mf} to {mt}", "care_gaps_open", {"practice_id": pid, "month_from": mf, "month_to": mt, "measure": meas},
        f"SELECT count(DISTINCT action_id) FROM actions WHERE status='open' AND practice_id={pid} AND measure='{meas}' AND action_date>=DATE '{mf}-01' AND action_date<DATE '{mt}-01'+INTERVAL 1 MONTH")
for pid, mf, mt in [(12, "2026-07", "2026-09"), (1, "2026-01", "2026-09")]:
    add(f"Gap closure rate for Practice {pid:02d}, {mf} to {mt}", "gap_closure_rate", {"practice_id": pid, "month_from": mf, "month_to": mt},
        f"SELECT ROUND(count(DISTINCT CASE WHEN status='completed' THEN action_id END)*1.0/NULLIF(count(DISTINCT action_id),0),4) FROM actions WHERE practice_id={pid} AND action_date>=DATE '{mf}-01' AND action_date<DATE '{mt}-01'+INTERVAL 1 MONTH")
for payer in ["Blue Harbor Health", "Meridian Plan", "Cascade Mutual"]:
    add(f"Gap closure rate across {payer} practices, Jan to Sep 2026", "gap_closure_rate", {"payer": payer, "month_from": "2026-01", "month_to": "2026-09"},
        f"SELECT ROUND(count(DISTINCT CASE WHEN status='completed' THEN action_id END)*1.0/NULLIF(count(DISTINCT action_id),0),4) FROM actions WHERE practice_id IN (SELECT practice_id FROM practices WHERE payer='{payer}') AND action_date>=DATE '2026-01-01' AND action_date<DATE '2026-10-01'")
for pid, m in [(3, "2026-04"), (3, "2026-05"), (12, "2026-08")]:
    add(f"How much was Practice {pid:02d} paid in {m}?", "actions_paid_usd", {"practice_id": pid, "month_from": m, "month_to": m},
        f"SELECT ROUND(COALESCE(sum(amount),0),2) FROM payments WHERE practice_id={pid} AND paid_month=DATE '{m}-01'",
        "paid_month, not action month: April is low and May is high because half of April's run landed in May" if pid == 3 else "")
add("Total paid to all practices, Jan to Sep 2026", "actions_paid_usd", {"month_from": "2026-01", "month_to": "2026-09"},
    "SELECT ROUND(COALESCE(sum(amount),0),2) FROM payments WHERE paid_month>=DATE '2026-01-01' AND paid_month<=DATE '2026-09-01'")
for pid, mf, mt in [(12, "2026-03", "2026-03"), (12, "2026-07", "2026-09"), (20, "2026-01", "2026-09")]:
    add(f"Attributed members at Practice {pid:02d}, {mf} to {mt}", "attributed_members", {"practice_id": pid, "month_from": mf, "month_to": mt},
        f"SELECT count(DISTINCT member_id) FROM attribution WHERE practice_id={pid} AND month>=DATE '{mf}-01' AND month<=DATE '{mt}-01'",
        "March carries the double-attribution trap; a member attributed to two practices counts once per practice" if mf == "2026-03" else "")
add("Closed care gaps across all practices, Q3 2026", "care_gaps_closed", {"month_from": "2026-07", "month_to": "2026-09"},
    "SELECT count(DISTINCT action_id) FROM actions WHERE status='completed' AND action_date>=DATE '2026-07-01' AND action_date<DATE '2026-10-01'")
add("Closed SDOH screens, Cascade Mutual practices, all year", "care_gaps_closed", {"payer": "Cascade Mutual", "measure": "SDOH", "month_from": "2026-01", "month_to": "2026-09"},
    "SELECT count(DISTINCT action_id) FROM actions WHERE status='completed' AND measure='SDOH' AND practice_id IN (SELECT practice_id FROM practices WHERE payer='Cascade Mutual') AND action_date>=DATE '2026-01-01' AND action_date<DATE '2026-10-01'")
add("Gap closure rate, Practice 12, Q3, asked a second way (same expected value as q06)", "gap_closure_rate", {"practice_id": 12, "month_from": "2026-07", "month_to": "2026-09", "measure": None},
    "SELECT ROUND(count(DISTINCT CASE WHEN status='completed' THEN action_id END)*1.0/NULLIF(count(DISTINCT action_id),0),4) FROM actions WHERE practice_id=12 AND action_date>=DATE '2026-07-01' AND action_date<DATE '2026-10-01'",
    "the same-number-twice demonstration")
# the second fact table (8. Oct 2026): visits, one row per visit, with walk-ins at a practice the member is not attributed to
add("How many visits did Practice 12 have, Q3 2026?", "visit_count", {"practice_id": 12, "month_from": "2026-07", "month_to": "2026-09"},
    "SELECT count(*) FROM visits WHERE practice_id=12 AND visit_date>=DATE '2026-07-01' AND visit_date<DATE '2026-10-01'",
    "counted where the visit happened; walk-ins count at the practice visited")
add("Share of Practice 12's Q3 visits where the member had a completed action there that month", "visit_closure_rate", {"practice_id": 12, "month_from": "2026-07", "month_to": "2026-09"},
    "SELECT ROUND(sum(CASE WHEN EXISTS (SELECT 1 FROM actions a WHERE a.status='completed' AND a.member_id=v.member_id AND a.practice_id=v.practice_id AND date_trunc('month', a.action_date)=date_trunc('month', v.visit_date)) THEN 1 ELSE 0 END)*1.0/count(*),4) FROM visits v WHERE v.practice_id=12 AND v.visit_date>=DATE '2026-07-01' AND v.visit_date<DATE '2026-10-01'",
    "join key is member + practice + month; a join on member alone would let a walk-in borrow another practice's completed actions")
# the scorecard (8. Oct 2026): its quarter-to-date default for as_of 2026-09 must equal the Q3 closure rate asked by name (q06)
Q.append({"id": "q23", "question": "Practice 12 scorecard, as of 2026-09: the quarter-to-date gap closure rate must be the Q3 rate", "tool": "practice_scorecard", "metric": "gap_closure_rate",
          "args": {"practice_id": 12, "as_of": "2026-09"}, "pick": ["signals", "gap_closure_rate_qtd", "value"],
          "expected": q("SELECT ROUND(count(DISTINCT CASE WHEN status='completed' THEN action_id END)*1.0/NULLIF(count(DISTINCT action_id),0),4) FROM actions WHERE practice_id=12 AND action_date>=DATE '2026-07-01' AND action_date<DATE '2026-10-01'"),
          "independent_sql": "same as q06; the eval pins the default window, not the metric", "note": "the scorecard's defaults are a contract: quarter to date from the as-of month", "signed_by": ""})
assert len(Q) == 23, len(Q)
(HERE / "questions.json").write_text(json.dumps({"version": "2026-10-08.1", "signed": False, "questions": Q}, indent=1))
print("wrote", len(Q), "questions")
