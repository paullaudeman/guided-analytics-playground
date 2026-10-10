"""Synthetic value-based-care data for Northstar Care, a fictional company. No real person, practice or payer.

Shape: practices receive care actions for attributed members; completed actions are paid monthly by a payer.
Deliberate fuzziness (so an agent that assumes clean data is caught): one practice with no actions in a month,
one month with a late payment run, duplicated action ids from a double-submit, members attributed to two
practices in the same month, and walk-in visits at a practice the member is not attributed to. Run: `uv run --with duckdb python data/generate.py` -> data/northstar.duckdb
"""
import random, datetime as dt, pathlib, duckdb

random.seed(20261007)
HERE = pathlib.Path(__file__).parent
DB = HERE / "northstar.duckdb"
PAYERS = ["Blue Harbor Health", "Meridian Plan", "Cascade Mutual"]
MEASURES = [("A1C", "Diabetes: HbA1c test"), ("BP", "Hypertension: blood pressure recorded"),
            ("CCS", "Cervical cancer screening"), ("COL", "Colorectal cancer screening"),
            ("AWV", "Annual wellness visit"), ("SDOH", "Social needs screen")]
MONTHS = [dt.date(2026, m, 1) for m in range(1, 10)]  # Jan..Sep 2026

def gen():
    practices = [(i, f"Practice {i:02d}", random.choice(["IN", "OH", "KY", "TN"]), random.choice(PAYERS)) for i in range(1, 25)]
    members, attrib, actions, payments = [], [], [], []
    mid = 1
    for pid, _, _, payer in practices:
        n = random.randint(180, 520)
        for _ in range(n):
            dob = dt.date(1940 + random.randint(0, 65), random.randint(1, 12), random.randint(1, 28))
            members.append((mid, f"MBR{mid:06d}", f"Member {mid}", dob, random.choice(["F", "M"]), payer))
            for m in MONTHS:
                attrib.append((mid, pid, m))
            mid += 1
    # fuzz 1: 40 members attributed to two practices in Mar 2026
    for mm in random.sample(range(1, mid), 40):
        attrib.append((mm, random.randint(1, 24), dt.date(2026, 3, 1)))
    aid = 1
    for (mmid, pid, m) in attrib:
        if pid == 7 and m == dt.date(2026, 6, 1):  # fuzz 2: Practice 07 has no actions in June
            continue
        for code, _ in MEASURES:
            if random.random() < 0.18:
                status = "completed" if random.random() < 0.72 else "open"
                day = m + dt.timedelta(days=random.randint(0, 27))
                actions.append((aid, mmid, pid, code, status, day))
                if status == "completed":
                    paid_month = m if not (m == dt.date(2026, 4, 1) and random.random() < 0.5) else dt.date(2026, 5, 1)  # fuzz 3: late April run
                    payments.append((aid, pid, paid_month, round(random.choice([18.0, 22.5, 30.0, 45.0]), 2)))
                aid += 1
    # fuzz 4: 60 duplicated action rows (double submit) with the same action_id
    actions += random.sample(actions, 60)
    # visits (added 8. Oct 2026): one row per visit, the second fact table. Drawn AFTER everything above so the
    # seeded stream for the original tables is untouched and the first twenty evals keep their expected values.
    # fuzz 5: about 2% of visits are walk-ins at a practice the member is NOT attributed to that month. A metric
    # that joins visits to actions on member alone, or on member and month, counts them; member + practice + month does not.
    visits, vid = [], 1
    for (mmid, pid, m) in attrib:
        for _ in range(random.choice([0, 0, 1, 1, 1, 2])):
            where = pid if random.random() > 0.02 else random.randint(1, 24)
            visits.append((vid, mmid, where, m + dt.timedelta(days=random.randint(0, 27)))); vid += 1
    return practices, members, attrib, actions, payments, visits

def main():
    if DB.exists():
        DB.unlink()
    con = duckdb.connect(str(DB))
    practices, members, attrib, actions, payments, visits = gen()
    con.execute("CREATE TABLE practices(practice_id INT, practice_name TEXT, state TEXT, payer TEXT)")
    con.execute("CREATE TABLE members(member_id INT, member_number TEXT, member_name TEXT, dob DATE, sex TEXT, payer TEXT)")
    con.execute("CREATE TABLE attribution(member_id INT, practice_id INT, month DATE)")
    con.execute("CREATE TABLE actions(action_id INT, member_id INT, practice_id INT, measure TEXT, status TEXT, action_date DATE)")
    con.execute("CREATE TABLE payments(action_id INT, practice_id INT, paid_month DATE, amount DOUBLE)")
    con.execute("CREATE TABLE visits(visit_id INT, member_id INT, practice_id INT, visit_date DATE)")
    con.execute("CREATE TABLE measures(measure TEXT, description TEXT)")
    con.executemany("INSERT INTO practices VALUES (?,?,?,?)", practices)
    con.executemany("INSERT INTO members VALUES (?,?,?,?,?,?)", members)
    con.executemany("INSERT INTO attribution VALUES (?,?,?)", attrib)
    con.executemany("INSERT INTO actions VALUES (?,?,?,?,?,?)", actions)
    con.executemany("INSERT INTO payments VALUES (?,?,?,?)", payments)
    con.executemany("INSERT INTO visits VALUES (?,?,?,?)", visits)
    con.executemany("INSERT INTO measures VALUES (?,?)", MEASURES)
    for t in ["practices", "members", "attribution", "actions", "payments", "visits"]:
        print(t, con.execute(f"SELECT count(*) FROM {t}").fetchone()[0])
    con.close()
    print("wrote", DB)

if __name__ == "__main__":
    main()
