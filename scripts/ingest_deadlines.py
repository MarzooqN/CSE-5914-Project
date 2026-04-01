#!/usr/bin/env python3
"""
Grad Program Deadlines -> Elasticsearch ingestion

This script creates and populates the grad_program_deadlines index with
example deadline data for testing the filter_programs_by_deadline_and_degree tool.

Requirements:
  pip install elasticsearch python-dotenv

Environment Variables (put these in a .env file):
  ES_URL="http://localhost:9200"
  ES_API_KEY="<api_key>"

Run:
  python ingest_deadlines.py --create-index

Dry run (no ES needed):
  python scripts/ingest_deadlines.py --dry-run
"""

from __future__ import annotations

import argparse
import os
from typing import Any, Dict, List
import json
import re
from datetime import datetime
from typing import Optional

from dotenv import load_dotenv

load_dotenv()

# Elasticsearch is optional for dry-run
try:
    from elasticsearch import Elasticsearch, helpers
except ImportError:
    Elasticsearch = None
    helpers = None


# ----------------------------
# Example deadline data
# ----------------------------

EXAMPLE_DEADLINES: List[Dict[str, Any]] = [
    # PhD programs — varied deadline months
    {
        "school": "ohio state university",
        "program": "Computer Science",
        "degree_level": "phd",
        "deadline_date": "2025-11-30",
        "deadline_type": "priority",
        "term": "Fall 2026",
        "source_url": "https://cse.osu.edu/phd/admissions",
        "updated_at": "2025-10-01T00:00:00Z",
    },
    {
        "school": "ohio state university",
        "program": "Computer Science",
        "degree_level": "phd",
        "deadline_date": "2025-12-15",
        "deadline_type": "final",
        "term": "Fall 2026",
        "source_url": "https://cse.osu.edu/phd/admissions",
        "updated_at": "2025-10-01T00:00:00Z",
    },
    {
        "school": "carnegie mellon university",
        "program": "Computer Science",
        "degree_level": "phd",
        "deadline_date": "2025-12-01",
        "deadline_type": "final",
        "term": "Fall 2026",
        "source_url": "https://cs.cmu.edu/phd/admissions",
        "updated_at": "2025-10-01T00:00:00Z",
    },
    {
        "school": "stanford university",
        "program": "Computer Science",
        "degree_level": "phd",
        "deadline_date": "2025-12-05",
        "deadline_type": "final",
        "term": "Fall 2026",
        "source_url": "https://cs.stanford.edu/admissions/phd",
        "updated_at": "2025-10-01T00:00:00Z",
    },
    {
        "school": "university of michigan",
        "program": "Computer Science and Engineering",
        "degree_level": "phd",
        "deadline_date": "2025-12-15",
        "deadline_type": "final",
        "term": "Fall 2026",
        "source_url": "https://cse.umich.edu/phd/admissions",
        "updated_at": "2025-10-01T00:00:00Z",
    },
    {
        "school": "university of illinois urbana-champaign",
        "program": "Computer Science",
        "degree_level": "phd",
        "deadline_date": "2026-01-15",
        "deadline_type": "final",
        "term": "Fall 2026",
        "source_url": "https://cs.illinois.edu/admissions/phd",
        "updated_at": "2025-10-01T00:00:00Z",
    },
    {
        "school": "georgia institute of technology",
        "program": "Computer Science",
        "degree_level": "phd",
        "deadline_date": "2026-02-01",
        "deadline_type": "final",
        "term": "Fall 2026",
        "source_url": "https://scs.gatech.edu/phd/admissions",
        "updated_at": "2025-10-01T00:00:00Z",
    },
    {
        "school": "university of washington",
        "program": "Computer Science",
        "degree_level": "phd",
        "deadline_date": "2025-12-15",
        "deadline_type": "final",
        "term": "Fall 2026",
        "source_url": "https://cs.washington.edu/phd/admissions",
        "updated_at": "2025-10-01T00:00:00Z",
    },
    # MS programs — later deadline months
    {
        "school": "ohio state university",
        "program": "Computer Science",
        "degree_level": "ms",
        "deadline_date": "2026-02-15",
        "deadline_type": "final",
        "term": "Fall 2026",
        "source_url": "https://cse.osu.edu/ms/admissions",
        "updated_at": "2025-10-01T00:00:00Z",
    },
    {
        "school": "carnegie mellon university",
        "program": "Computer Science",
        "degree_level": "ms",
        "deadline_date": "2026-01-10",
        "deadline_type": "final",
        "term": "Fall 2026",
        "source_url": "https://cs.cmu.edu/ms/admissions",
        "updated_at": "2025-10-01T00:00:00Z",
    },
    {
        "school": "stanford university",
        "program": "Computer Science",
        "degree_level": "ms",
        "deadline_date": "2026-03-15",
        "deadline_type": "final",
        "term": "Fall 2026",
        "source_url": "https://cs.stanford.edu/admissions/ms",
        "updated_at": "2025-10-01T00:00:00Z",
    },
    {
        "school": "university of michigan",
        "program": "Computer Science and Engineering",
        "degree_level": "ms",
        "deadline_date": "2026-03-01",
        "deadline_type": "final",
        "term": "Fall 2026",
        "source_url": "https://cse.umich.edu/ms/admissions",
        "updated_at": "2025-10-01T00:00:00Z",
    },
    {
        "school": "georgia institute of technology",
        "program": "Computer Science",
        "degree_level": "ms",
        "deadline_date": "2026-04-01",
        "deadline_type": "final",
        "term": "Fall 2026",
        "source_url": "https://scs.gatech.edu/ms/admissions",
        "updated_at": "2025-10-01T00:00:00Z",
    },
    {
        "school": "university of illinois urbana-champaign",
        "program": "Computer Science",
        "degree_level": "ms",
        "deadline_date": "2026-05-01",
        "deadline_type": "rolling",
        "term": "Fall 2026",
        "source_url": "https://cs.illinois.edu/admissions/ms",
        "updated_at": "2025-10-01T00:00:00Z",
    },
]

def normalize_degree_level(value: str) -> str:
    v = value.strip().lower()
    if v in {"phd", "ph.d", "ph.d."}:
        return "phd"
    if v in {"masters", "master's", "ms", "m.s.", "m.eng", "meng"}:
        return "ms"
    return v

def normalize_deadline_date(raw: str, term: str) -> Optional[str]:
    """
    Convert common deadline strings to YYYY-MM-DD.
    Returns None if parsing fails.
    """
    if not raw:
        return None

    s = raw.strip()

    # Already ISO-like
    for fmt in ("%Y-%m-%d", "%Y/%m/%d"):
        try:
            return datetime.strptime(s, fmt).strftime("%Y-%m-%d")
        except ValueError:
            pass

    # Remove ordinal suffixes: 23rd -> 23
    s = re.sub(r'(\d+)(st|nd|rd|th)', r'\1', s, flags=re.IGNORECASE)

    # Remove time / timezone suffixes
    s = re.sub(r',?\s*\d{1,2}:\d{2}\s*[APMapm]{2}\s*[A-Z]{0,4}', '', s).strip()

    # If year missing, infer from term
    inferred_year = None
    term_lower = (term or "").lower()
    if "fall 2026" in term_lower:
        inferred_year = 2025   # fall admissions deadlines are usually in prior year
    elif "spring 2026" in term_lower:
        inferred_year = 2025   # may vary, but still better than leaving blank

    # Try formats with year
    for fmt in ("%B %d, %Y", "%b %d, %Y"):
        try:
            return datetime.strptime(s, fmt).strftime("%Y-%m-%d")
        except ValueError:
            pass

    # Try formats without year
    if inferred_year is not None:
        for fmt in ("%B %d", "%b %d"):
            try:
                dt = datetime.strptime(s, fmt)
                return dt.replace(year=inferred_year).strftime("%Y-%m-%d")
            except ValueError:
                pass

    return None

def load_deadlines_from_jsonl(path: str) -> list[dict]:
    deadlines = []
    skipped = 0

    with open(path, "r", encoding="utf-8") as f:
        for line_num, line in enumerate(f, start=1):
            line = line.strip()
            if not line:
                continue

            try:
                row = json.loads(line)
            except json.JSONDecodeError as e:
                print(f"Skipping line {line_num}: invalid JSON ({e})")
                skipped += 1
                continue

            school = row.get("school", "").strip().lower()
            program = row.get("program", "").strip()
            degree_level = normalize_degree_level(row.get("degree_level", ""))
            term = row.get("term", "").strip()
            source_url = row.get("source_url", "").strip()
            deadline_date = normalize_deadline_date(row.get("deadline_date", ""), term)

            if not all([school, program, degree_level, term, source_url, deadline_date]):
                print(f"Skipping line {line_num}: missing/invalid required field(s)")
                skipped += 1
                continue

            deadlines.append({
                "school": school,
                "program": program,
                "degree_level": degree_level,
                "deadline_date": deadline_date,
                "term": term,
                "source_url": source_url,
            })

    print(f"Loaded {len(deadlines)} records from JSONL, skipped {skipped}")
    return deadlines


def make_index_mapping() -> Dict[str, Any]:
    """Create the Elasticsearch index mapping for grad program deadlines."""
    return {
        "settings": {
            "number_of_shards": 1,
            "analysis": {
                "normalizer": {
                    "lowercase_normalizer": {
                        "type": "custom",
                        "filter": ["lowercase", "asciifolding"],
                    }
                }
            },
        },
        "mappings": {
            "dynamic": False,
            "properties": {
                "school": {
                    "type": "keyword",
                    "normalizer": "lowercase_normalizer",
                },
                "program": {
                    "type": "text",
                    "fields": {
                        "keyword": {
                            "type": "keyword",
                            "normalizer": "lowercase_normalizer",
                        }
                    },
                },
                "degree_level": {
                    "type": "keyword",
                },
                "deadline_date": {
                    "type": "date",
                    "format": "strict_date_optional_time||yyyy-MM-dd||epoch_millis",
                },
                "term": {
                    "type": "keyword",
                },
                "source_url": {
                    "type": "keyword",
                    "index": False,
                },
            },
        },
    }


def get_es_client(es_url: str, api_key: str) -> Any:
    """Build Elasticsearch client."""
    if Elasticsearch is None:
        raise RuntimeError("elasticsearch package not installed. Run: pip install elasticsearch")

    kwargs = {"hosts": [es_url]}
    if api_key:
        kwargs["api_key"] = api_key
    return Elasticsearch(**kwargs)


def create_index(es: Any, index: str) -> None:
    """Create the deadline index with mapping."""
    if es.indices.exists(index=index):
        print(f"Index '{index}' already exists. Deleting and recreating...")
        es.indices.delete(index=index)

    mapping = make_index_mapping()
    es.indices.create(index=index, body=mapping)
    print(f"Created index '{index}' with mapping.")


def bulk_index_deadlines(es: Any, index: str, deadlines: List[Dict[str, Any]]) -> tuple:
    """Bulk index deadline documents."""
    if helpers is None:
        raise RuntimeError("elasticsearch helpers not available")

    actions = [
        {
            "_op_type": "index",
            "_index": index,
            "_id": f"{d['school']}_{d['program']}_{d['degree_level']}_{d['deadline_date']}".replace(" ", "_").lower(),
            "_source": d,
        }
        for d in deadlines
    ]

    success = 0
    failed = 0
    for ok, _ in helpers.streaming_bulk(es, actions, chunk_size=100, request_timeout=60):
        if ok:
            success += 1
        else:
            failed += 1

    return success, failed


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest grad program deadlines into Elasticsearch")
    parser.add_argument("--es-url", default=os.getenv("ES_URL", "http://localhost:9200"),
                        help="Elasticsearch URL")
    parser.add_argument("--es-api-key", default=os.getenv("ES_API_KEY", ""),
                        help="Elasticsearch API key")
    parser.add_argument("--index", default=os.getenv("GRAD_SCHOOL_DEADLINES_ES_INDEX", "grad_program_deadlines"),
                        help="Index name (default: grad_program_deadlines)")
    parser.add_argument("--create-index", action="store_true",
                        help="Create/recreate the index before ingesting")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print documents without indexing")

    args = parser.parse_args()

    print(f"Deadline ingestion script")
    print(f"  ES URL: {args.es_url}")
    print(f"  Index: {args.index}")
    print(f"  Documents: {len(EXAMPLE_DEADLINES)}")
    print()

    if args.dry_run:
        print("=== DRY RUN MODE ===")
        print()
        for d in EXAMPLE_DEADLINES:
            print(f"  School: {d['school']}")
            print(f"  Program: {d['program']}")
            print(f"  Degree: {d['degree_level']}")
            print(f"  Deadline: {d['deadline_date']} ({d.get('deadline_type', '')})")
            print(f"  Term: {d.get('term', '')}")
            print(f"  URL: {d.get('source_url', '')}")
            print()

        print(f"Total: {len(EXAMPLE_DEADLINES)} documents")
        return

    # Connect to Elasticsearch
    es = get_es_client(args.es_url, args.es_api_key)

    # Verify connection
    if not es.ping():
        print("ERROR: Could not connect to Elasticsearch")
        return
    print("Connected to Elasticsearch")

    # Create index if requested
    if args.create_index:
        create_index(es, args.index)

    # Bulk index documents
    deadlines_data_path = "data/deadlines.jsonl"
    deadlines = load_deadlines_from_jsonl(deadlines_data_path)
    print(f"Indexing {len(deadlines)} deadline documents...")
    success, failed = bulk_index_deadlines(es, args.index, deadlines)

    print(f"Indexing complete: {success} succeeded, {failed} failed")

    # Refresh index
    es.indices.refresh(index=args.index)

    # Show count
    count = es.count(index=args.index)["count"]
    print(f"Total documents in index: {count}")


if __name__ == "__main__":
    main()
