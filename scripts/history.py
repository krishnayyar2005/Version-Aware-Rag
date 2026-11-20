"""History retrieval: find the document the question is about, then pull the most
relevant chunks from EVERY version of it so the LLM can compare versions."""
import re

from retrieve import connect, embed_query

STOP = {"what", "whats", "changed", "change", "changes", "in", "the", "of", "to", "a", "an",
        "is", "was", "how", "has", "have", "did", "between", "versions", "version", "history",
        "over", "time", "and", "for", "on", "about", "are", "were", "made", "since"}

BEST_DOC_SQL = """
select v.doc_id from chunks c join doc_versions v on v.version_id = c.version_id
where v.doc_id = any(%(ids)s)
group by v.doc_id order by max(1 - (c.embedding <=> %(q)s::vector)) desc limit 1
"""

SQL = """
select * from (
  select c.chunk_id, c.version_id, v.doc_id, d.title, v.version_label, v.effective_date,
         v.expiry_date, v.status, c.section, c.content, c.chunk_index,
         1 - (c.embedding <=> %(q)s::vector) as score,
         row_number() over (partition by c.version_id order by c.embedding <=> %(q)s::vector) as rn
  from chunks c
  join doc_versions v on v.version_id = c.version_id
  join documents d on d.doc_id = v.doc_id
  where v.doc_id = %(doc)s
) t
where rn <= %(n)s
order by effective_date, chunk_index
"""


def _tok(s):
    return re.findall(r"[a-z0-9]+", s.lower())


def candidates(docs, question):
    """docs = [(doc_id, title)]. Keep docs whose TITLE shares the most words with the question
    (company/product name). FAQ docs are skipped unless the question mentions FAQ."""
    q = set(_tok(question)) - STOP
    faq_ok = bool(q & {"faq", "faqs"})
    pool = [(i, t) for i, t in docs if faq_ok or "faq" not in _tok(t)] or list(docs)
    ov = {i: len(q & set(_tok(t))) for i, t in pool}
    best = max(ov.values())
    return [i for i, _ in pool if ov[i] == best]


def retrieve_history(question, per_version=4, conn=None):
    own = conn is None
    conn = conn or connect()
    try:
        qv = embed_query(question)
        with conn.cursor() as cur:
            cur.execute("select doc_id, title from documents")
            ids = candidates(cur.fetchall(), question)
            cur.execute(BEST_DOC_SQL, {"ids": ids, "q": qv})
            doc_id = cur.fetchone()[0]
            cur.execute(SQL, {"q": qv, "doc": doc_id, "n": per_version})
            cols = [c.name for c in cur.description]
            rows = [dict(zip(cols, r)) for r in cur.fetchall()]
    finally:
        if own:
            conn.close()
    return {"mode": "all", "as_of": None, "results": rows}