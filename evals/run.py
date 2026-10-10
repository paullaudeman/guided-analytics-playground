"""Run the signed questions against the server in-process: score the value, record estimate and actual cost per answer.
Exit 1 on any miss, 3 if the file is unsigned and --require-signed is given, so this can gate a commit. Run: uv run --with "mcp<2" --with duckdb --with pyyaml python evals/run.py
"""
import json, os, pathlib, sys, time
HERE = pathlib.Path(__file__).parent
sys.path.insert(0, str(HERE.parent))
os.environ.setdefault("ROLE", "analyst"); os.environ.setdefault("PRINCIPAL", "evals")
os.environ.setdefault("PRACTICE_ID", "all")   # explicit grant: the evals ask across practices (ADR 0002, amended)
os.environ.setdefault("TRACES", str(HERE / "traces"))
import server as s

def close(a, b):
    if a is None or b is None: return a == b
    try: return abs(float(a) - float(b)) < 1e-6
    except Exception: return a == b

def main():
    qs = json.loads((HERE / "questions.json").read_text())
    miss, rows, t0 = 0, [], time.time()
    for q in qs["questions"]:
        args = {k: v for k, v in q["args"].items() if v is not None}
        if q.get("tool") == "practice_scorecard":   # the scorecard: one call, pick one cell by path
            got = s.practice_scorecard(**args); est = {}
            val = got
            for key in q["pick"]: val = val.get(key) if isinstance(val, dict) else None
            if got.get("refused"): val = f"REFUSED: {got.get('rule')}"
        else:
            est = s.estimate_cost(q["metric"], **args, shaped_question=q["question"])
            got = s.get_metric(q["metric"], **args, estimate_trace_id=est.get("trace_id"))
            val = got.get("value") if not got.get("refused") else f"REFUSED: {got.get('rule')}"
        ok = close(val, q["expected"])
        miss += 0 if ok else 1
        rows.append((q["id"], "ok" if ok else "MISS", q["metric"], str(q["expected"]), str(val), est.get("rows_scanned"), got.get("actual", {}).get("rows_scanned"),
                     est.get("warehouse_usd"), got.get("actual", {}).get("warehouse_usd"), est.get("model_usd_est")))
    w = [max(len(str(r[i])) for r in rows + [("id","res","metric","expected","got","est_rows","act_rows","est_wh$","act_wh$","est_model$")]) for i in range(10)]
    hdr = ("id","res","metric","expected","got","est_rows","act_rows","est_wh$","act_wh$","est_model$")
    print("  ".join(str(h).ljust(w[i]) for i, h in enumerate(hdr)))
    for r in rows: print("  ".join(str(c).ljust(w[i]) for i, c in enumerate(r)))
    tot_wh = sum(r[8] or 0 for r in rows); tot_model = sum(r[9] or 0 for r in rows)
    print(f"\n{len(rows)} questions, {miss} miss, {time.time()-t0:.1f}s · warehouse ${tot_wh:.5f} actual · model ${tot_model:.4f} ESTIMATED (prices {s.PRICES['as_of']}) · signed: {qs['signed']}")
    if miss: sys.exit(1)
    if "--require-signed" in sys.argv and not qs["signed"]:
        print("UNSIGNED: evals/questions.json has no human signature; refusing to pass the gate"); sys.exit(3)
    sys.exit(0)

if __name__ == "__main__":
    main()
