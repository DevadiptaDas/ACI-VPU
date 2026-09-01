"""
E1 — measure extraction quality on REAL store content (read-only).

We can't auto-know "all facts present" (that needs human judgment), so this script
does the measurable, transparent half and prints raw samples for adjudication:

  COVERAGE  — over a random real sample, what fraction yields ANY triple
  PRECISION — of the triples produced, print them so genuine-vs-junk can be judged
  RECALL    — print the source text beside each triple so misses are visible

Default extractor (spaCy) is used. READ-ONLY: only SELECTs against aci_data.db.
"""
import os
import sqlite3
import sys

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "uqrt-mca-nlp"))
from uqrt_mca_nlp.extract import get_extractor   # noqa: E402

DB = os.path.join(os.path.dirname(__file__), "..", "aci_data.db")
SAMPLE = 120
SEED = 7


def find_text_table(con):
    """Locate the table/column holding monad content."""
    for t in [r[0] for r in con.execute("select name from sqlite_master where type='table'")]:
        cols = [r[1] for r in con.execute(f"PRAGMA table_info({t})")]
        for cand in ("value", "summary", "content", "text", "raw", "body"):
            if cand in cols:
                return t, cand, cols
    return None, None, None


def main():
    con = sqlite3.connect(DB)
    t, col, cols = find_text_table(con)
    print(f"store table={t} col={col}")
    print(f"columns={cols}\n")
    if not t:
        print("no text column found; dumping table schemas:")
        for tt in [r[0] for r in con.execute("select name from sqlite_master where type='table'")]:
            print("  ", tt, [r[1] for r in con.execute(f"PRAGMA table_info({tt})")])
        return

    rows = con.execute(
        f"select {col} from {t} where {col} is not null and length({col}) > 15 "
        f"order by abs(random() % 100000) limit {SAMPLE}"
    ).fetchall()
    ex = get_extractor()
    print(f"extractor={ex.name}  sample={len(rows)}\n")

    yielded = 0
    samples = []
    for (txt,) in rows:
        txt = str(txt).strip().replace("\n", " ")
        out = ex.extract(txt)
        has = bool(out.get("subject") and out.get("object"))
        if has:
            yielded += 1
        samples.append((txt, out, has))

    print("=" * 100)
    print(f"COVERAGE: {yielded}/{len(rows)} = {yielded/len(rows)*100:.0f}% of real entries produced a triple")
    print("=" * 100)
    # print the first 30 WITH a triple (precision adjudication) ...
    print("\n----- TRIPLES PRODUCED (judge precision: is each a genuine fact?) -----")
    shown = 0
    for txt, out, has in samples:
        if has and shown < 30:
            shown += 1
            s, p, o = out["subject"], out["predicate"], out.get("object", "")
            print(f"\n[{shown}] TEXT: {txt[:160]}")
            print(f"     TRIPLE: ({s}) -[{p}]-> ({o})")
    # ... and the first 20 WITHOUT (recall adjudication: did real facts get missed?)
    print("\n\n----- NO TRIPLE (judge recall: was there a real fact to catch?) -----")
    shown = 0
    for txt, out, has in samples:
        if not has and shown < 20:
            shown += 1
            print(f"\n[{shown}] TEXT: {txt[:160]}")
            print(f"     entities={out.get('entities', [])[:5]}")


if __name__ == "__main__":
    main()
