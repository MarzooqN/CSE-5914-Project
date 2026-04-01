#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
from datetime import datetime, timezone

import pandas as pd
from dotenv import load_dotenv

load_dotenv()

try:
    from elasticsearch import Elasticsearch, helpers  # type: ignore
except Exception:
    Elasticsearch = None  # type: ignore
    helpers = None  # type: ignore


DEFAULT_INDEX = os.environ.get("USNEWS_RANKINGS_INDEX", "usnews_rankings")
ES_URL = os.environ.get("ES_URL") or os.environ.get("ELASTICSEARCH_URL", "http://localhost:9200")
ES_API_KEY = os.environ.get("ES_API_KEY") or os.environ.get("ELASTICSEARCH_API_KEY")
ES_USERNAME = os.environ.get("ELASTICSEARCH_USERNAME")
ES_PASSWORD = os.environ.get("ELASTICSEARCH_PASSWORD")


MAPPING = {
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
            "school": {"type": "keyword", "normalizer": "lowercase_normalizer"},
            "display_school": {"type": "keyword"},
            "state": {"type": "keyword"},
            "ipeds": {"type": "integer"},
            "year": {"type": "integer"},
            "rank": {"type": "integer"},
            "rank_source": {"type": "keyword"},
            "updated_at": {"type": "date", "format": "strict_date_optional_time||epoch_millis"},
        },
    },
}


def get_es_client() -> Elasticsearch:
    if Elasticsearch is None:
        raise RuntimeError("elasticsearch package not installed. pip install elasticsearch")
    if ES_API_KEY:
        return Elasticsearch(ES_URL, api_key=ES_API_KEY)
    if ES_USERNAME and ES_PASSWORD:
        return Elasticsearch(ES_URL, basic_auth=(ES_USERNAME, ES_PASSWORD))
    return Elasticsearch(ES_URL)


def ensure_index(es: Elasticsearch, index_name: str):
    if es.indices.exists(index=index_name):
        return
    es.indices.create(index=index_name, body=MAPPING)


def normalize_school(s: str) -> str:
    return (s or "").strip().lower()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True, help="Path to long CSV: columns [University Name, State, IPEDS, year, rank]")
    ap.add_argument("--index", default=DEFAULT_INDEX)
    ap.add_argument("--source", default="usnews_national_universities", help="rank_source value")
    ap.add_argument("--create-index", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--dry-run-count", type=int, default=10)
    args = ap.parse_args()

    df = pd.read_csv(args.input)

    required = {"University Name", "State", "IPEDS", "year", "rank"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"Missing required columns: {sorted(missing)}")

    df["year"] = pd.to_numeric(df["year"], errors="coerce").astype("Int64")
    df["rank"] = pd.to_numeric(df["rank"], errors="coerce").astype("Int64")
    df["IPEDS"] = pd.to_numeric(df["IPEDS"], errors="coerce").astype("Int64")
    df = df.dropna(subset=["University Name", "year", "rank"])

    now = datetime.now(timezone.utc).isoformat()

    docs = []
    for _, row in df.iterrows():
        display_school = str(row["University Name"])
        docs.append(
            {
                "_index": args.index,
                "_source": {
                    "school": normalize_school(display_school),
                    "display_school": display_school,
                    "state": str(row["State"]) if not pd.isna(row["State"]) else None,
                    "ipeds": int(row["IPEDS"]) if not pd.isna(row["IPEDS"]) else None,
                    "year": int(row["year"]),
                    "rank": int(row["rank"]),
                    "rank_source": args.source,
                    "updated_at": now,
                },
            }
        )

    if args.dry_run:
        for d in docs[: args.dry_run_count]:
            print(d["_source"])
        print(f"Dry run: prepared {len(docs)} docs")
        return

    es = get_es_client()
    if args.create_index:
        ensure_index(es, args.index)

    ok, errs = helpers.bulk(es, docs, raise_on_error=False)
    print(f"Indexed {ok} docs into {args.index}")
    if errs:
        print("Errors (first 5):")
        print(errs[:5])


if __name__ == "__main__":
    main()