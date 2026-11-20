"""Download real versioned documents from the Open Terms Archive 'contrib' dataset.

Dataset layout inside the zip:  <Service>/<Terms type>/<YYYY-MM-DDTHH-MM-SSZ>.md
We stream the zip to disk, read it WITHOUT extracting everything (avoids Windows
long-path problems), pick documents with enough version history, and write only
the selected ones to data/raw/selected/ plus a manifest.json.

Usage:  python scripts/download_real.py
        python scripts/download_real.py --zip path/to/dataset.zip   # use a manual download
Data license: ODbL (Open Terms Archive contributors) - keep attribution in the README.
"""
import argparse
import json
import re
import sys
import zipfile
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
SELECTED = RAW / "selected"
API = "https://api.github.com/repos/OpenTermsArchive/contrib-versions/releases"

# ---- selection knobs --------------------------------------------------------
MIN_VERSIONS = 3          # a doc needs at least this many versions
MIN_SPAN_DAYS = 180       # ...spread over at least this long
MIN_CHARS = 2000          # ignore tiny / broken versions
MAX_VERSIONS = 6          # keep at most this many versions per doc (evenly spaced)
MAX_TYPES_PER_SERVICE = 2
TARGET_DOCS = 40

FNAME = re.compile(r"^(\d{4})-(\d{2})-(\d{2})T(\d{2})-(\d{2})-(\d{2})Z\.md$")


def find_zip_url():
    r = requests.get(API, params={"per_page": 10}, timeout=30)
    if r.status_code == 403:
        sys.exit("GitHub API rate limit hit. Download the .zip manually from the "
                 "contrib-versions Releases page, then run with --zip <path>.")
    r.raise_for_status()
    for rel in r.json():
        for a in rel.get("assets", []):
            if a["name"].endswith(".zip"):
                print(f"Release: {rel['tag_name']}  asset: {a['name']}  "
                      f"({a['size'] / 1e6:.0f} MB)")
                return a["browser_download_url"]
    sys.exit("No .zip asset found in the latest releases. Use --zip with a manual download.")


def download(url, dest):
    dest.parent.mkdir(parents=True, exist_ok=True)
    with requests.get(url, stream=True, timeout=60) as r:
        r.raise_for_status()
        total = int(r.headers.get("content-length", 0))
        done = 0
        with open(dest, "wb") as f:
            for chunk in r.iter_content(1 << 20):
                f.write(chunk)
                done += len(chunk)
                if total:
                    print(f"\r  {done / 1e6:.0f}/{total / 1e6:.0f} MB", end="")
    print()


def index_zip(zf):
    """-> {(service, type): [(datetime, member_name), ...]} sorted by date"""
    docs = defaultdict(list)
    for name in zf.namelist():
        parts = [p for p in name.split("/") if p]
        if len(parts) < 3 or not parts[-1].endswith(".md"):
            continue
        m = FNAME.match(parts[-1])
        if not m:
            continue
        ts = datetime(*map(int, m.groups()))
        docs[(parts[-3], parts[-2])].append((ts, name))
    for v in docs.values():
        v.sort()
    return docs


def spaced(items, k):
    """Pick k items evenly spaced, always keeping first and last."""
    if len(items) <= k:
        return items
    idx = sorted({round(i * (len(items) - 1) / (k - 1)) for i in range(k)})
    return [items[i] for i in idx]


def safe(s):
    return re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", s).strip(" .")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--zip", help="path to an already-downloaded dataset zip")
    args = ap.parse_args()

    zpath = Path(args.zip) if args.zip else RAW / "contrib-dataset.zip"
    if not zpath.exists():
        print("Finding latest dataset release...")
        download(find_zip_url(), zpath)

    with zipfile.ZipFile(zpath) as zf:
        docs = index_zip(zf)
        print(f"Found {len(docs)} (service, terms-type) documents in the dataset.")

        # candidates: enough versions over a long enough time span
        cands = []
        for (svc, typ), vers in docs.items():
            if len(vers) < MIN_VERSIONS:
                continue
            if (vers[-1][0] - vers[0][0]).days < MIN_SPAN_DAYS:
                continue
            cands.append((len(vers), svc, typ))
        cands.sort(reverse=True)

        # diversify: cap doc types per service, prefer richer histories
        per_service, chosen = defaultdict(int), []
        for n, svc, typ in cands:
            if per_service[svc] >= MAX_TYPES_PER_SERVICE:
                continue
            chosen.append((svc, typ))
            per_service[svc] += 1

        manifest, kept = [], 0
        for svc, typ in chosen:
            if kept >= TARGET_DOCS:
                break
            versions = []
            for ts, name in docs[(svc, typ)]:
                text = zf.read(name).decode("utf-8", errors="replace")
                if len(text) >= MIN_CHARS:
                    versions.append((ts, text))
            if len(versions) < MIN_VERSIONS:
                continue
            versions = spaced(versions, MAX_VERSIONS)
            out_dir = SELECTED / safe(svc) / safe(typ)
            out_dir.mkdir(parents=True, exist_ok=True)
            entries = []
            for ts, text in versions:
                fname = ts.strftime("%Y-%m-%d") + ".md"
                (out_dir / fname).write_text(text, encoding="utf-8")
                entries.append({"effective_date": ts.strftime("%Y-%m-%d"),
                                "file": str((out_dir / fname).relative_to(ROOT)).replace("\\", "/")})
            manifest.append({"title": f"{svc} - {typ}", "service": svc,
                             "doc_family": typ, "versions": entries})
            kept += 1

    (RAW / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    total_versions = sum(len(d["versions"]) for d in manifest)
    print(f"Selected {len(manifest)} documents, {total_versions} versions.")
    print(f"Files: {SELECTED}\nManifest: {RAW / 'manifest.json'}")


if __name__ == "__main__":
    main()
