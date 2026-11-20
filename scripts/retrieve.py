"""Phase 3: version-aware hybrid retrieval.

Usage (from project root, venv active):
  python scripts\\retrieve.py --apply-sql            # create the SQL function once
  python scripts\\retrieve.py "What is the meal allowance?"
  python scripts\\retrieve.py "Meal allowance as of March 2025?"
  python scripts\\retrieve.py "What changed in the leave policy?"
  python scripts\\retrieve.py --test-intent          # check intent detector on questions.json
Importable: from retrieve import retrieve, detect_intent
"""
import argparse
import calendar
import json
import os
import re
import sys
from datetime import date
from pathlib import Path

MODEL = "BAAI/bge-small-en-v1.5"
PREFIX = "Represent this sentence for searching relevant passages: "
SQL_FILE = Path(__file__).with_name("phase3_search.sql")
ROOT = Path(__file__).resolve().parent.parent

MON = (r"(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|"
       r"aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)")
MONTHS = ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"]
HISTORY = re.compile(
    r"what (?:has |have )?changed|history|over time|(?:previous|earlier|older|past|prior) versions?"
    r"|all versions|changes? (?:to|in|between|made)|differences? between"
    r"|how (?:has|have|did) .{0,40}change", re.I)


def _mnum(s):
    return MONTHS.index(s[:3].lower()) + 1


def parse_date(q):
    """Find an explicit date in the question. Month-only -> last day of month; year-only -> Dec 31."""
    ql = q.lower()
    try:
        if m := re.search(r"\b(\d{4})-(\d{2})-(\d{2})\b", ql):
            return date(int(m[1]), int(m[2]), int(m[3]))
        if m := re.search(rf"\b{MON}\.?\s+(\d{{1,2}})(?:st|nd|rd|th)?,?\s+(\d{{4}})\b", ql):
            return date(int(m[3]), _mnum(m[1]), int(m[2]))
        if m := re.search(rf"\b(\d{{1,2}})(?:st|nd|rd|th)?\s+(?:of\s+)?{MON}\.?,?\s+(\d{{4}})\b", ql):
            return date(int(m[3]), _mnum(m[2]), int(m[1]))
        if m := re.search(rf"\b{MON}\.?,?\s+(\d{{4}})\b", ql):
            y, mo = int(m[2]), _mnum(m[1])
            return date(y, mo, calendar.monthrange(y, mo)[1])
        if m := re.search(r"\b(?:in|as of|during|by|for|of|back in)\s+((?:19|20)\d\d)\b", ql):
            return date(int(m[1]), 12, 31)
    except ValueError:
        return None
    return None


def detect_intent(q):
    """Return (mode, as_of): 'all' (history), 'as_of' (date), or 'current'."""
    if HISTORY.search(q) and not re.search(r"\bas of\b", q, re.I):
        return "all", None
    d = parse_date(q)
    if d:
        return "as_of", d
    return "current", None


_model = None


def embed_query(q):
    global _model
    if _model is None:
        from fastembed import TextEmbedding
        _model = TextEmbedding(MODEL)
    v = next(iter(_model.embed([PREFIX + q])))
    return "[" + ",".join(f"{x:.6f}" for x in v) + "]"


def tsq(q):
    words = dict.fromkeys(re.findall(r"[a-z0-9]+", q.lower()))
    return " | ".join(w for w in words if len(w) > 1)


def connect():
    import psycopg
    from dotenv import load_dotenv
    load_dotenv()
    return psycopg.connect(os.environ["DATABASE_URL"])


def retrieve(question, mode=None, as_of=None, k=8, conn=None):
    if mode is None:
        mode, as_of = detect_intent(question)
    if mode == "as_of" and as_of is None:
        raise ValueError("as_of mode needs a date")
    own = conn is None
    conn = conn or connect()
    try:
        with conn.cursor() as cur:
            cur.execute("select * from search_chunks(%s::vector, %s, %s, %s::date, %s)",
                        (embed_query(question), tsq(question), mode, as_of, k))
            cols = [c.name for c in cur.description]
            rows = [dict(zip(cols, r)) for r in cur.fetchall()]
    finally:
        if own:
            conn.close()
    return {"mode": mode, "as_of": as_of, "results": rows}


def test_intent():
    data = json.loads((ROOT / "data/synthetic/questions.json").read_text(encoding="utf-8"))
    if isinstance(data, dict):
        data = next(v for v in data.values() if isinstance(v, list))
    print("question keys:", list(data[0].keys()))
    ok, bad = 0, []
    for q in data:
        text = q.get("question") or q.get("text")
        want = q.get("type")
        got, _ = detect_intent(text)
        if got == want:
            ok += 1
        else:
            bad.append((want, got, text))
    print(f"intent accuracy: {ok}/{len(data)}")
    for want, got, text in bad[:8]:
        print(f"  want={want} got={got} :: {text}")


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("question", nargs="*")
    ap.add_argument("--apply-sql", action="store_true")
    ap.add_argument("--test-intent", action="store_true")
    ap.add_argument("--mode", choices=["current", "as_of", "all"])
    ap.add_argument("--as-of")
    ap.add_argument("-k", type=int, default=8)
    a = ap.parse_args()

    if a.apply_sql:
        conn = connect()
        conn.execute(SQL_FILE.read_text(encoding="utf-8"))
        conn.commit()
        conn.close()
        print("search_chunks() created.")
        return
    if a.test_intent:
        test_intent()
        return
    q = " ".join(a.question)
    if not q:
        ap.error("give a question")
    as_of = date.fromisoformat(a.as_of) if a.as_of else None
    out = retrieve(q, a.mode, as_of, a.k)
    print(f"mode={out['mode']} as_of={out['as_of']}")
    for r in out["results"]:
        print(f"[{r['score']:.4f}] {r['title']} | {r['version_label']} | "
              f"{r['effective_date']} | {r['status']}")
        print(f"    {(r['section'] or '')[:60]} :: {r['content'][:150].replace(chr(10), ' ')}")


if __name__ == "__main__":
    main()
