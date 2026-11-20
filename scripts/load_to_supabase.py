"""Load versioned documents into Supabase (tables: documents, doc_versions).

Reads data/raw/manifest.json (real) and data/synthetic/manifest.json (synthetic, if present).
For each document it:
  - inserts the document, then its versions in date order
  - sets expiry_date of each version = effective_date of the NEXT version
  - marks the latest version 'current' (expiry NULL), all earlier ones 'superseded'
  - links supersedes_version_id to the previous version

Usage:
  python scripts/load_to_supabase.py            # load, skipping titles already present
  python scripts/load_to_supabase.py --reset    # wipe all tables first, then load
"""
import argparse
import json
import os
import sys
from datetime import date
from pathlib import Path

import psycopg
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
MANIFESTS = [
    (ROOT / "data" / "raw" / "manifest.json", False),
    (ROOT / "data" / "synthetic" / "manifest.json", True),
]
SOURCE_URL = "https://github.com/OpenTermsArchive/contrib-versions"


def clean(text: str) -> str:
    return text.replace("\x00", "")  # Postgres text cannot contain NUL


def load_manifest(path: Path, synthetic: bool):
    if not path.exists():
        print(f"(skip) {path.relative_to(ROOT)} not found")
        return []
    docs = json.loads(path.read_text(encoding="utf-8"))
    for d in docs:
        d.setdefault("is_synthetic", synthetic)
    print(f"Read {len(docs)} documents from {path.relative_to(ROOT)}")
    return docs


def insert_document(cur, doc):
    versions = {}
    for v in doc["versions"]:              # one version per date (keep the last)
        versions[v["effective_date"]] = v
    ordered = [versions[k] for k in sorted(versions)]
    if len(ordered) < 2:
        return None

    cur.execute(
        """insert into documents (title, doc_family, source_url, is_synthetic)
           values (%s, %s, %s, %s)
           on conflict (title) do nothing returning doc_id""",
        (doc["title"], doc.get("doc_family"),
         doc.get("source_url") or (None if doc["is_synthetic"] else SOURCE_URL),
         doc["is_synthetic"]),
    )
    row = cur.fetchone()
    if row is None:
        return None                         # title already loaded
    doc_id = row[0]

    prev_id = None
    for i, v in enumerate(ordered):
        is_last = i == len(ordered) - 1
        expiry = None if is_last else date.fromisoformat(ordered[i + 1]["effective_date"])
        text = clean((ROOT / v["file"]).read_text(encoding="utf-8"))
        cur.execute(
            """insert into doc_versions
               (doc_id, version_label, effective_date, expiry_date, status,
                supersedes_version_id, source_file, raw_text)
               values (%s, %s, %s, %s, %s, %s, %s, %s) returning version_id""",
            (doc_id, f"v{i + 1}", v["effective_date"], expiry,
             "current" if is_last else "superseded", prev_id, v["file"], text),
        )
        prev_id = cur.fetchone()[0]
    return len(ordered)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--reset", action="store_true", help="delete everything first")
    args = ap.parse_args()

    load_dotenv(ROOT / ".env")
    url = os.getenv("DATABASE_URL")
    if not url:
        sys.exit("DATABASE_URL missing in .env")

    docs = []
    for path, synthetic in MANIFESTS:
        docs += load_manifest(path, synthetic)
    if not docs:
        sys.exit("Nothing to load. Run download_real.py first.")

    loaded = skipped = n_versions = 0
    with psycopg.connect(url) as conn:
        with conn.cursor() as cur:
            if args.reset:
                cur.execute("truncate documents restart identity cascade")
                print("Reset: all tables cleared.")
            for doc in docs:
                n = insert_document(cur, doc)
                if n is None:
                    skipped += 1
                else:
                    loaded += 1
                    n_versions += n
                    print(f"  + {doc['title']} ({n} versions)")
        conn.commit()

    print(f"\nDone. Loaded {loaded} documents / {n_versions} versions; skipped {skipped}.")


if __name__ == "__main__":
    main()
