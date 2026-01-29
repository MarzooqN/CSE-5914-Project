#!/usr/bin/env python3
"""
CSRankings -> Elasticsearch ingestion

What this script does
1) Downloads:
   - csrankings.csv (author metadata: affiliation, homepage, scholarid, orcid; sometimes name has [NOTE])
   - generated-author-info.csv (author x venue x year with counts and adjustedcount)
2) Loads venue -> parent-area mapping (parentMap) from src/config.ts if provided, otherwise uses a fallback map.
3) Aggregates generated-author-info.csv into ONE document per (author, dept):
   - by_parent: adjustedcount summed by parent area (mlmining, sec, robotics, etc.)
   - by_venue:  adjustedcount summed by venue (nips, icra, ccs, etc.)
   - first_year, last_year, total_adjusted, venues list
4) Enriches each doc with csrankings.csv metadata:
   - homepage, scholarid (+ scholar_url), orcid (+ orcid_url)
   - parses bracket notes like: "Alex Conway 0001 [Tech]"
     and stores name_note = "Tech" plus note_url if known (noteMap)
5) Bulk indexes into Elasticsearch.

Requirements
  pip install elasticsearch requests

Run (local ES)
  export ES_URL="http://localhost:9200"
  python ingest_csrankings_es.py --create-index --index csrankings_authors

Run (Elastic Cloud)
  export ES_URL="https://<cluster>.es.<region>.aws.cloud.es.io:443"
  export ES_API_KEY="<api_key>"
  python ingest_csrankings_es.py --create-index --index csrankings_authors

Dry run (no ES needed)
  python ingest_csrankings_es.py --dry-run --dry-run-count 5

"""

from __future__ import annotations

import argparse
import csv
import io
import json
import os
import re
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Tuple

import requests

# Elasticsearch is optional for dry-run
try:
    from elasticsearch import Elasticsearch, helpers  # type: ignore
except Exception:
    Elasticsearch = None  # type: ignore
    helpers = None  # type: ignore

# ----------------------------
# Data sources
# ----------------------------

CSRANKINGS_CSV_URL = "https://raw.githubusercontent.com/emeryberger/CSrankings/gh-pages/csrankings.csv"
AUTHOR_INFO_URL = "https://raw.githubusercontent.com/emeryberger/CSrankings/gh-pages/generated-author-info.csv"

# ----------------------------
# Name note parsing (matches CSRankings nameMatcher)
# Example: "Alex Conway 0001 [Tech]" -> ("Alex Conway 0001", "Tech")
# ----------------------------

NAME_NOTE_RE = re.compile(r"^(.*)\s+\[(.*)\]\s*$")

# ----------------------------
# noteMap from src/config.ts
# ----------------------------

NOTE_MAP: Dict[str, str] = {
    "Tech": "https://tech.cornell.edu/",
    "CBG": "https://www.cis.mpg.de/cbg/",
    "INF": "https://www.cis.mpg.de/mpi-inf/",
    "IS": "https://www.cis.mpg.de/is/",
    "MG": "https://www.cis.mpg.de/molgen/",
    "SP": "https://www.cis.mpg.de/mpi-for-security-and-privacy/",
    "SWS": "https://www.cis.mpg.de/mpi-sws/",
}

# ----------------------------
# Fallback parentMap (venue -> parent area)
# Prefer parsing src/config.ts via --config-ts
# ----------------------------

FALLBACK_PARENT_MAP: Dict[str, str] = {
    "aaai": "ai",
    "ijcai": "ai",
    "cvpr": "vision",
    "eccv": "vision",
    "iccv": "vision",
    "icml": "mlmining",
    "iclr": "mlmining",
    "kdd": "mlmining",
    "nips": "mlmining",
    "acl": "nlp",
    "emnlp": "nlp",
    "naacl": "nlp",
    "sigir": "inforet",
    "www": "inforet",
    "asplos": "arch",
    "isca": "arch",
    "micro": "arch",
    "hpca": "arch",
    "ccs": "sec",
    "oakland": "sec",
    "usenixsec": "sec",
    "ndss": "sec",
    "pets": "sec",
    "vldb": "mod",
    "sigmod": "mod",
    "icde": "mod",
    "pods": "mod",
    "dac": "da",
    "iccad": "da",
    "emsoft": "bed",
    "rtas": "bed",
    "rtss": "bed",
    "sc": "hpc",
    "hpdc": "hpc",
    "ics": "hpc",
    "mobicom": "mobile",
    "mobisys": "mobile",
    "sensys": "mobile",
    "imc": "metrics",
    "sigmetrics": "metrics",
    "osdi": "ops",
    "sosp": "ops",
    "eurosys": "ops",
    "fast": "ops",
    "usenixatc": "ops",
    "popl": "plan",
    "pldi": "plan",
    "oopsla": "plan",
    "icfp": "plan",
    "fse": "soft",
    "icse": "soft",
    "ase": "soft",
    "issta": "soft",
    "nsdi": "comm",
    "sigcomm": "comm",
    "siggraph": "graph",
    "siggraph-asia": "graph",
    "eurographics": "graph",
    "focs": "act",
    "soda": "act",
    "stoc": "act",
    "crypto": "crypt",
    "eurocrypt": "crypt",
    "cav": "log",
    "lics": "log",
    "ismb": "bio",
    "recomb": "bio",
    "ec": "ecom",
    "wine": "ecom",
    "chiconf": "chi",
    "ubicomp": "chi",
    "uist": "chi",
    "icra": "robotics",
    "iros": "robotics",
    "rss": "robotics",
    "vis": "visualization",
    "vr": "visualization",
    "sigcse": "csed",
}

KNOWN_PARENT_AREAS = sorted(
    {
        "ai",
        "vision",
        "mlmining",
        "nlp",
        "inforet",
        "arch",
        "comm",
        "sec",
        "mod",
        "da",
        "bed",
        "hpc",
        "mobile",
        "metrics",
        "ops",
        "plan",
        "soft",
        "act",
        "crypt",
        "log",
        "bio",
        "graph",
        "csed",
        "ecom",
        "chi",
        "robotics",
        "visualization",
    }
)

# ----------------------------
# Helpers
# ----------------------------


def fetch_text(url: str, timeout: int = 180) -> str:
    r = requests.get(url, timeout=timeout)
    r.raise_for_status()
    return r.text


def safe_float(s: str) -> float:
    try:
        return float(s)
    except Exception:
        return 0.0


def safe_int(s: str) -> Optional[int]:
    try:
        return int(s)
    except Exception:
        return None


def normalize_key(s: str) -> str:
    return (s or "").strip().lower()


def parse_name_and_note(raw_name: str) -> Tuple[str, str]:
    raw_name = (raw_name or "").strip()
    m = NAME_NOTE_RE.match(raw_name)
    if not m:
        return raw_name, ""
    return m.group(1).strip(), m.group(2).strip()


def parse_parent_map_from_ts(ts_path: str) -> Dict[str, str]:
    with open(ts_path, "r", encoding="utf-8") as f:
        txt = f.read()

    m = re.search(r"export\s+const\s+parentMap[^=]*=\s*\{(.*?)\};", txt, flags=re.S)
    if not m:
        raise ValueError("Could not find parentMap block in config.ts")

    block = m.group(1)
    pairs = re.findall(r"['\"]([^'\"]+)['\"]\s*:\s*['\"]([^'\"]+)['\"]", block)
    if not pairs:
        raise ValueError("Found parentMap block, but no pairs were parsed")

    return {k.strip(): v.strip() for k, v in pairs}


def make_doc_id(name: str, dept: str) -> str:
    return f"{name}|{dept}".lower()


def scholar_url(scholarid: str) -> str:
    return f"https://scholar.google.com/citations?user={scholarid}" if scholarid else ""


def orcid_url(orcid: str) -> str:
    return f"https://orcid.org/{orcid}" if orcid else ""


# ----------------------------
# CSV models and loaders
# ----------------------------

@dataclass(frozen=True)
class AuthorMeta:
    name: str
    affiliation: str
    homepage: str
    scholarid: str
    orcid: str
    name_note: str


def load_csrankings_meta(csv_text: str) -> Dict[Tuple[str, str], AuthorMeta]:
    f = io.StringIO(csv_text)
    reader = csv.DictReader(f)

    expected = {"name", "affiliation", "homepage", "scholarid", "orcid"}
    if set(reader.fieldnames or []) != expected:
        raise ValueError(f"Unexpected csrankings.csv columns: {reader.fieldnames}")

    out: Dict[Tuple[str, str], AuthorMeta] = {}
    for row in reader:
        raw_name = (row.get("name") or "").strip()
        affiliation = (row.get("affiliation") or "").strip()
        if not raw_name or not affiliation:
            continue

        clean_name, note = parse_name_and_note(raw_name)

        out[(normalize_key(clean_name), normalize_key(affiliation))] = AuthorMeta(
            name=clean_name,
            affiliation=affiliation,
            homepage=(row.get("homepage") or "").strip(),
            scholarid=(row.get("scholarid") or "").strip(),
            orcid=(row.get("orcid") or "").strip(),
            name_note=note,
        )

    return out


def iter_author_info_rows(csv_text: str) -> Iterable[Dict[str, str]]:
    f = io.StringIO(csv_text)
    reader = csv.DictReader(f)

    expected = {"name", "dept", "area", "count", "adjustedcount", "year"}
    if set(reader.fieldnames or []) != expected:
        raise ValueError(f"Unexpected generated-author-info.csv columns: {reader.fieldnames}")

    for row in reader:
        yield row


# ----------------------------
# Elasticsearch mapping
# ----------------------------

def make_index_mapping(parent_areas: List[str]) -> Dict[str, Any]:
    by_parent_props = {a: {"type": "float"} for a in parent_areas}

    return {
        "settings": {
            "analysis": {
                "normalizer": {
                    "lowercase_normalizer": {
                        "type": "custom",
                        "filter": ["lowercase", "asciifolding"],
                    }
                }
            }
        },
        "mappings": {
            "dynamic": False,
            "properties": {
                "name": {
                    "type": "text",
                    "fields": {"keyword": {"type": "keyword", "normalizer": "lowercase_normalizer"}},
                },
                "dept": {
                    "type": "text",
                    "fields": {"keyword": {"type": "keyword", "normalizer": "lowercase_normalizer"}},
                },
                "name_note": {"type": "keyword"},
                "note_url": {"type": "keyword"},
                "homepage": {"type": "keyword"},
                "scholarid": {"type": "keyword"},
                "scholar_url": {"type": "keyword"},
                "orcid": {"type": "keyword"},
                "orcid_url": {"type": "keyword"},
                "by_parent": {"properties": by_parent_props},
                "by_venue": {"type": "flattened"},
                "venues": {"type": "keyword"},
                "first_year": {"type": "integer"},
                "last_year": {"type": "integer"},
                "total_adjusted": {"type": "float"},
                "ingested_at": {"type": "date"},
                "name_suggest": {"type": "completion"},
                "dept_suggest": {"type": "completion"},
            },
        },
    }


# ----------------------------
# Aggregation logic
# ----------------------------

def aggregate_author_docs(
    author_info_csv: str,
    meta_by_name_dept: Dict[Tuple[str, str], AuthorMeta],
    parent_map: Dict[str, str],
) -> Dict[Tuple[str, str], Dict[str, Any]]:
    by_parent: Dict[Tuple[str, str], Dict[str, float]] = defaultdict(lambda: defaultdict(float))
    by_venue: Dict[Tuple[str, str], Dict[str, float]] = defaultdict(lambda: defaultdict(float))
    venues: Dict[Tuple[str, str], set] = defaultdict(set)
    total_adj: Dict[Tuple[str, str], float] = defaultdict(float)
    min_year: Dict[Tuple[str, str], int] = {}
    max_year: Dict[Tuple[str, str], int] = {}

    for row in iter_author_info_rows(author_info_csv):
        name = (row.get("name") or "").strip()
        dept = (row.get("dept") or "").strip()
        venue = (row.get("area") or "").strip()
        year = safe_int((row.get("year") or "").strip())
        adj = safe_float((row.get("adjustedcount") or "").strip())

        if not name or not dept or not venue or year is None:
            continue

        key = (name, dept)

        by_venue[key][venue] += adj
        venues[key].add(venue)
        total_adj[key] += adj

        parent = parent_map.get(venue)
        if parent:
            by_parent[key][parent] += adj

        if key not in min_year or year < min_year[key]:
            min_year[key] = year
        if key not in max_year or year > max_year[key]:
            max_year[key] = year

    now = datetime.now(timezone.utc).isoformat()

    docs: Dict[Tuple[str, str], Dict[str, Any]] = {}
    for (name, dept) in by_venue.keys():
        meta = meta_by_name_dept.get((normalize_key(name), normalize_key(dept)))

        name_note = meta.name_note if meta else ""
        note_url = NOTE_MAP.get(name_note, "") if name_note else ""

        docs[(name, dept)] = {
            "name": name,
            "dept": dept,
            "name_note": name_note,
            "note_url": note_url,
            "homepage": meta.homepage if meta else "",
            "scholarid": meta.scholarid if meta else "",
            "scholar_url": scholar_url(meta.scholarid) if meta else "",
            "orcid": meta.orcid if meta else "",
            "orcid_url": orcid_url(meta.orcid) if meta else "",
            "by_parent": dict(by_parent.get((name, dept), {})),
            "by_venue": dict(by_venue.get((name, dept), {})),
            "venues": sorted(venues.get((name, dept), set())),
            "first_year": min_year.get((name, dept)),
            "last_year": max_year.get((name, dept)),
            "total_adjusted": float(total_adj.get((name, dept), 0.0)),
            "ingested_at": now,
            "name_suggest": {"input": [name]},
            "dept_suggest": {"input": [dept]},
        }

    return docs


# ----------------------------
# Dry run output
# ----------------------------

def doc_preview(doc: Dict[str, Any], top_n: int = 5) -> Dict[str, Any]:
    """
    Create a compact preview:
    - top N parent areas by score
    - top N venues by score
    """
    by_parent = doc.get("by_parent") or {}
    by_venue = doc.get("by_venue") or {}

    top_parent = sorted(by_parent.items(), key=lambda kv: kv[1], reverse=True)[:top_n]
    top_venue = sorted(by_venue.items(), key=lambda kv: kv[1], reverse=True)[:top_n]

    return {
        "name": doc.get("name"),
        "dept": doc.get("dept"),
        "name_note": doc.get("name_note"),
        "homepage": doc.get("homepage"),
        "scholar_url": doc.get("scholar_url"),
        "orcid_url": doc.get("orcid_url"),
        "first_year": doc.get("first_year"),
        "last_year": doc.get("last_year"),
        "total_adjusted": doc.get("total_adjusted"),
        "top_parent_areas": top_parent,
        "top_venues": top_venue,
    }


def run_dry_mode(docs: Dict[Tuple[str, str], Dict[str, Any]], count: int, top_n: int) -> None:
    """
    Print a small sample of docs in a human-readable format.
    """
    items = list(docs.items())

    # Show docs with bracket notes first (useful sanity check)
    items.sort(key=lambda kv: (0 if (kv[1].get("name_note") or "") else 1, kv[0][0]))

    print("\n=== DRY RUN PREVIEW ===")
    print(f"Total aggregated docs: {len(items)}")
    print(f"Showing {min(count, len(items))} documents\n")

    for i, (_, doc) in enumerate(items[:count], start=1):
        preview = doc_preview(doc, top_n=top_n)
        print(f"[{i}] {preview['name']} — {preview['dept']}")
        if preview.get("name_note"):
            print(f"    note: {preview['name_note']} (url: {NOTE_MAP.get(preview['name_note'], '')})")
        if preview.get("homepage"):
            print(f"    homepage: {preview['homepage']}")
        if preview.get("scholar_url"):
            print(f"    scholar: {preview['scholar_url']}")
        if preview.get("orcid_url"):
            print(f"    orcid: {preview['orcid_url']}")
        print(f"    years: {preview.get('first_year')}..{preview.get('last_year')}  total_adjusted={preview.get('total_adjusted')}")
        print(f"    top parent areas: {preview.get('top_parent_areas')}")
        print(f"    top venues:       {preview.get('top_venues')}")
        print("")


# ----------------------------
# Elasticsearch indexing
# ----------------------------

def ensure_es_available() -> None:
    if Elasticsearch is None or helpers is None:
        raise RuntimeError(
            "Elasticsearch libraries not available. Install with: pip install elasticsearch"
        )


def bulk_index_docs(es: Any, index: str, docs: Dict[Tuple[str, str], Dict[str, Any]]) -> Tuple[int, int]:
    ensure_es_available()

    actions = (
        {
            "_op_type": "index",
            "_index": index,
            "_id": make_doc_id(name, dept),
            "_source": doc,
        }
        for (name, dept), doc in docs.items()
    )

    success = 0
    failed = 0
    for ok, _ in helpers.streaming_bulk(es, actions, chunk_size=2000, request_timeout=180):
        if ok:
            success += 1
        else:
            failed += 1
    return success, failed


# ----------------------------
# Main
# ----------------------------

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--es-url", default=os.getenv("ES_URL", "http://localhost:9200"))
    parser.add_argument("--es-api-key", default=os.getenv("ES_API_KEY", ""))
    parser.add_argument("--index", default="csrankings_authors")
    parser.add_argument("--create-index", action="store_true", help="Delete existing index and recreate mapping.")
    parser.add_argument("--config-ts", default="", help="Path to src/config.ts to parse parentMap.")
    parser.add_argument("--csrankings-url", default=CSRANKINGS_CSV_URL)
    parser.add_argument("--authorinfo-url", default=AUTHOR_INFO_URL)

    # Dry run controls
    parser.add_argument("--dry-run", action="store_true", help="Do not connect to ES; print sample aggregated docs.")
    parser.add_argument("--dry-run-count", type=int, default=5, help="How many docs to print in dry-run mode.")
    parser.add_argument("--dry-run-top", type=int, default=5, help="Top N parent areas/venues to show per doc.")
    args = parser.parse_args()

    # Parent map
    if args.config_ts:
        parent_map = parse_parent_map_from_ts(args.config_ts)
        print(f"Loaded parentMap from {args.config_ts} ({len(parent_map)} venues)")
    else:
        parent_map = dict(FALLBACK_PARENT_MAP)
        print(f"Using fallback parentMap ({len(parent_map)} venues). Tip: pass --config-ts for exact mapping.")

    # Download data
    print("Downloading csrankings.csv ...")
    csrankings_text = fetch_text(args.csrankings_url)

    print("Downloading generated-author-info.csv ...")
    author_info_text = fetch_text(args.authorinfo_url)

    # Load + aggregate
    meta = load_csrankings_meta(csrankings_text)
    print(f"Loaded {len(meta)} metadata records from csrankings.csv (names normalized, notes parsed)")

    docs = aggregate_author_docs(author_info_text, meta, parent_map)
    print(f"Built {len(docs)} aggregated author+dept documents")

    # Dry run mode: no ES required
    if args.dry_run:
        run_dry_mode(docs, count=max(1, args.dry_run_count), top_n=max(1, args.dry_run_top))
        return

    # ES mode
    ensure_es_available()
    es = Elasticsearch(args.es_url, api_key=args.es_api_key) if args.es_api_key else Elasticsearch(args.es_url)

    if args.create_index:
        mapping = make_index_mapping(KNOWN_PARENT_AREAS)
        if es.indices.exists(index=args.index):
            es.indices.delete(index=args.index)
            print(f"Deleted index {args.index}")
        es.indices.create(index=args.index, body=mapping)
        print(f"Created index {args.index}")

    success, failed = bulk_index_docs(es, args.index, docs)
    print(f"Indexed documents: success={success}, failed={failed}")


if __name__ == "__main__":
    main()
