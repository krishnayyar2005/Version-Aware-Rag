"""Phase 4: version-aware answer generation.

Usage: python scripts\\answer.py "What is the meal allowance at Crestline Financial?"
Importable: from answer import answer
"""
import argparse
import sys

from llm import generate
from history import retrieve_history
from retrieve import detect_intent, retrieve

SYSTEM = """You answer questions about company policies and terms using ONLY the numbered sources provided.
Rules:
1. Every source shows its document version label, effective date and status. Always state which version and effective date your answer is based on, e.g. "(Travel Policy v3, effective 2024-02-27)".
2. Cite sources inline as [1], [2].
3. If sources from different documents or versions give conflicting values, say so explicitly, name each source's version/date, and say which one is current.
4. For a history question, compare consecutive versions and list what changed (old value -> new value) with each version label and date. Ignore sections that did not change.
5. If the sources do not contain the answer, say so. Never guess or use outside knowledge.
6. Be concise: 2-5 sentences unless a history answer needs more."""


def build_context(results, mode):
    rows = list(results)
    if mode == "all":
        rows.sort(key=lambda r: (r["title"], r["effective_date"]))
    lines = []
    for i, r in enumerate(rows, 1):
        lines.append(f"[{i}] {r['title']} | version {r['version_label']} | "
                     f"effective {r['effective_date']} | status {r['status']}\n{r['content']}")
    return rows, "\n\n".join(lines)


def answer(question, k=8, mode=None, as_of=None):
    if mode is None:
        mode, as_of = detect_intent(question)
    if mode == "all":
        out = retrieve_history(question)
    else:
        out = retrieve(question, mode=mode, as_of=as_of, k=k)
    rows, context = build_context(out["results"], out["mode"])
    note = {"current": "Only CURRENT versions were searched.",
            "as_of": f"Only versions in force on {out['as_of']} were searched.",
            "all": "History question: the most relevant passages from EVERY version of one document are included, oldest first."}[out["mode"]]
    prompt = f"{note}\n\nSources:\n{context}\n\nQuestion: {question}"
    text = generate(prompt, system=SYSTEM)
    return {"question": question, "mode": out["mode"], "as_of": out["as_of"],
            "answer": text, "sources": rows}


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("question", nargs="+")
    a = ap.parse_args()
    res = answer(" ".join(a.question))
    print(f"mode={res['mode']} as_of={res['as_of']}\n")
    print(res["answer"])
    print("\nSources:")
    for i, r in enumerate(res["sources"], 1):
        print(f"  [{i}] {r['title']} | {r['version_label']} | {r['effective_date']} | {r['status']}")


if __name__ == "__main__":
    main()
