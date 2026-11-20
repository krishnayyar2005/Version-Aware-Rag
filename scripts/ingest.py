"""Phase 2: chunk + embed every doc version that has no chunks yet, store in Supabase.

Pipeline per version:  raw_text -> markdown-aware chunks -> bge-small embeddings -> chunks table
Chunks do NOT store version/date themselves: they point to doc_versions via version_id,
so version metadata lives in one place (update a version row, never thousands of chunks).

Usage:
  python scripts/ingest.py --dry-run         # chunk only, print stats, write nothing
  python scripts/ingest.py --limit 5         # process only 5 pending versions (smoke test)
  python scripts/ingest.py                   # process everything pending (safe to re-run / resume)
  python scripts/ingest.py --reset           # delete all chunks (and conflicts), then re-ingest
"""
import argparse
import os
import re
import sys
import time
from pathlib import Path

import psycopg
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
MODEL_NAME = "BAAI/bge-small-en-v1.5"   # 384-dim, matches vector(384) in the schema

# chunk sizing, in words (bge-small handles 512 tokens; ~200 words is comfortably inside)
MIN_WORDS = 50      # start a new chunk at a heading only if the current one has >= this
TARGET_WORDS = 200  # flush when adding the next block would exceed this
MAX_WORDS = 300     # hard cap for a single block (split by sentence beyond this)

HEADING = re.compile(r"^(#{1,6})\s+(.*\S)\s*$")
SENTENCE = re.compile(r"(?<=[.!?])\s+")


def wc(s):
    return len(s.split())


def split_long(text):
    """Split an oversized block into pieces of <= TARGET_WORDS, on sentence boundaries."""
    pieces, cur, cur_w = [], [], 0
    for sent in SENTENCE.split(text):
        w = wc(sent)
        if w > MAX_WORDS:                      # one monster sentence: cut by words
            if cur:
                pieces.append(" ".join(cur)); cur, cur_w = [], 0
            words = sent.split()
            for i in range(0, len(words), TARGET_WORDS):
                pieces.append(" ".join(words[i:i + TARGET_WORDS]))
            continue
        if cur and cur_w + w > TARGET_WORDS:
            pieces.append(" ".join(cur)); cur, cur_w = [], 0
        cur.append(sent); cur_w += w
    if cur:
        pieces.append(" ".join(cur))
    return pieces


def parse_blocks(text):
    """Markdown -> list of blocks {path, head, body}. Headings attach to the paragraph after them."""
    blocks, stack, para, pending = [], [], [], []

    def flush():
        if para:
            blocks.append({"path": " > ".join(t for _, t in stack),
                           "head": "\n".join(pending) if pending else None,
                           "body": "\n".join(para).strip()})
            para.clear(); pending.clear()

    for line in text.replace("\r\n", "\n").split("\n"):
        m = HEADING.match(line)
        if m:
            flush()
            level, title = len(m.group(1)), m.group(2).strip("# ").strip()
            while stack and stack[-1][0] >= level:
                stack.pop()
            stack.append((level, title))
            pending.append(line.strip())
        elif not line.strip():
            flush()
        else:
            para.append(line.rstrip())
    flush()
    return [b for b in blocks if b["body"]]


def chunk_markdown(text):
    """-> list of (section, content). Packs blocks up to TARGET_WORDS, prefers heading boundaries."""
    chunks, cur, cur_w = [], [], 0

    def flush():
        nonlocal cur, cur_w
        if cur:
            content = "\n\n".join(t for _, t in cur)
            chunks.append((cur[0][0][:200] or None, content))
        cur, cur_w = [], 0

    for b in parse_blocks(text):
        full = (b["head"] + "\n\n" if b["head"] else "") + b["body"]
        w = wc(full)
        if w > MAX_WORDS:
            flush()
            for i, piece in enumerate(split_long(b["body"])):
                piece = (b["head"] + "\n\n" if (b["head"] and i == 0) else "") + piece
                chunks.append((b["path"][:200] or None, piece))
            continue
        starts_section = b["head"] is not None
        if cur and (cur_w + w > TARGET_WORDS or (starts_section and cur_w >= MIN_WORDS)):
            flush()
        cur.append((b["path"], full)); cur_w += w
    flush()
    return chunks


def vec_literal(v):
    return "[" + ",".join(f"{float(x):.6f}" for x in v) + "]"


def connect(url):
    return psycopg.connect(url)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--reset", action="store_true")
    args = ap.parse_args()

    load_dotenv(ROOT / ".env")
    url = os.getenv("DATABASE_URL")
    if not url:
        sys.exit("DATABASE_URL missing in .env")

    conn = connect(url)
    if args.reset and not args.dry_run:
        with conn.cursor() as cur:
            cur.execute("truncate chunks restart identity cascade")
        conn.commit()
        print("Reset: all chunks (and conflicts) deleted.")

    with conn.cursor() as cur:
        cur.execute("""select v.version_id, d.title, v.version_label, v.raw_text
                       from doc_versions v join documents d using (doc_id)
                       where not exists (select 1 from chunks c where c.version_id = v.version_id)
                       order by v.version_id""")
        pending = cur.fetchall()
    conn.commit()
    if args.limit:
        pending = pending[: args.limit]
    print(f"{len(pending)} versions to process.")
    if not pending:
        return

    model = None
    if not args.dry_run:
        from fastembed import TextEmbedding
        print(f"Loading embedding model {MODEL_NAME} (first run downloads ~130 MB)...")
        model = TextEmbedding(model_name=MODEL_NAME)

    cache, total_chunks, total_words, t0 = {}, 0, [], time.time()
    for i, (version_id, title, label, raw) in enumerate(pending, 1):
        chunks = chunk_markdown(raw or "")
        total_chunks += len(chunks)
        total_words += [wc(c) for _, c in chunks]
        if args.dry_run:
            if i <= 5 or i % 50 == 0:
                print(f"  [{i}/{len(pending)}] {title} {label}: {len(chunks)} chunks")
            continue

        # embed with a contextual header (doc title + section); identical texts are embedded once
        texts = [f"{title}\n{sec or ''}\n{c}" for sec, c in chunks]
        todo = list(dict.fromkeys(t for t in texts if t not in cache))
        if todo:
            for t, v in zip(todo, model.embed(todo, batch_size=32)):
                cache[t] = vec_literal(v)
        rows = [(version_id, idx, sec, c, cache[t])
                for idx, ((sec, c), t) in enumerate(zip(chunks, texts))]

        for attempt in (1, 2):               # one reconnect attempt if the pooler dropped us
            try:
                with conn.cursor() as cur:
                    cur.executemany(
                        "insert into chunks (version_id, chunk_index, section, content, embedding) "
                        "values (%s, %s, %s, %s, %s::vector)", rows)
                conn.commit()
                break
            except psycopg.OperationalError:
                if attempt == 2:
                    raise
                conn = connect(url)
        print(f"  [{i}/{len(pending)}] {title} {label}: {len(chunks)} chunks "
              f"({len(todo)} newly embedded)  {time.time() - t0:.0f}s")

    conn.close()
    avg = sum(total_words) / max(len(total_words), 1)
    print(f"\n{'DRY RUN: ' if args.dry_run else 'Done. '}{total_chunks} chunks from {len(pending)} versions; "
          f"avg {avg:.0f} words, max {max(total_words, default=0)} words.")


if __name__ == "__main__":
    main()
