"""
Grad-school discovery assistant: Elasticsearch helpers for CSRankings faculty/program data.

Index schema matches scripts/ingestion.py (csrankings_authors):
- One document per (author, dept) with by_parent (area -> score), by_venue, name, dept, etc.
"""

import logging
from typing import Any, Optional

from open_webui.config import (
    ELASTICSEARCH_API_KEY,
    ELASTICSEARCH_PASSWORD,
    ELASTICSEARCH_URL,
    ELASTICSEARCH_USERNAME,
    GRAD_SCHOOL_ES_INDEX,
)

log = logging.getLogger(__name__)

# User-facing area names / synonyms -> parent area keys (from ingestion.py FALLBACK_PARENT_MAP / KNOWN_PARENT_AREAS)
AREA_ALIASES: dict[str, list[str]] = {
    "ai": ["ai"],
    "artificial intelligence": ["ai"],
    "vision": ["vision"],
    "computer vision": ["vision"],
    "cv": ["vision"],
    "ml": ["mlmining"],
    "machine learning": ["mlmining"],
    "mlmining": ["mlmining"],
    "mining": ["mlmining"],
    "nlp": ["nlp"],
    "natural language processing": ["nlp"],
    "language": ["nlp"],
    "security": ["sec", "crypt"],
    "sec": ["sec"],
    "crypto": ["crypt"],
    "cryptography": ["crypt"],
    "systems": ["arch", "ops", "comm", "hpc"],
    "systems research": ["arch", "ops", "comm", "hpc"],
    "architecture": ["arch"],
    "arch": ["arch"],
    "operating systems": ["ops"],
    "os": ["ops"],
    "ops": ["ops"],
    "networking": ["comm"],
    "networks": ["comm"],
    "comm": ["comm"],
    "hpc": ["hpc"],
    "high performance computing": ["hpc"],
    "databases": ["mod"],
    "db": ["mod"],
    "mod": ["mod"],
    "software engineering": ["soft"],
    "software": ["soft"],
    "soft": ["soft"],
    "programming languages": ["plan"],
    "pl": ["plan"],
    "plan": ["plan"],
    "robotics": ["robotics"],
    "theory": ["act", "log"],
    "theory of computing": ["act"],
    "graphics": ["graph"],
    "graph": ["graph"],
    "information retrieval": ["inforet"],
    "ir": ["inforet"],
    "inforet": ["inforet"],
    "human computer interaction": ["chi"],
    "hci": ["chi"],
    "chi": ["chi"],
    "bioinformatics": ["bio"],
    "bio": ["bio"],
    "visualization": ["visualization"],
    "vis": ["visualization"],
    "mobile": ["mobile"],
    "embedded": ["bed"],
    "bed": ["bed"],
    "metrics": ["metrics"],
    "ecom": ["ecom"],
    "economics": ["ecom"],
    "cs education": ["csed"],
    "csed": ["csed"],
}

# All known parent area keys (for validation / fallback)
KNOWN_PARENT_AREAS = frozenset(
    {
        "ai", "vision", "mlmining", "nlp", "inforet", "arch", "comm", "sec",
        "mod", "da", "bed", "hpc", "mobile", "metrics", "ops", "plan", "soft",
        "act", "crypt", "log", "bio", "graph", "csed", "ecom", "chi",
        "robotics", "visualization",
    }
)


def normalize_area(user_text: str) -> list[str]:
    """
    Map user-facing area name (e.g. 'NLP', 'security', 'systems') to a list of
    parent area keys used in the CSRankings index (by_parent).
    """
    if not user_text or not isinstance(user_text, str):
        return []
    key = user_text.strip().lower()
    if not key:
        return []
    if key in AREA_ALIASES:
        return list(AREA_ALIASES[key])
    if key in KNOWN_PARENT_AREAS:
        return [key]
    for alias, areas in AREA_ALIASES.items():
        if key in alias or alias in key:
            return list(areas)
    return []


def _get_es_client():
    """Build Elasticsearch client from config (same URL/auth as RAG vector DB)."""
    from elasticsearch import Elasticsearch

    kwargs = {"hosts": [ELASTICSEARCH_URL]}
    if ELASTICSEARCH_API_KEY:
        kwargs["api_key"] = ELASTICSEARCH_API_KEY
    elif ELASTICSEARCH_USERNAME and ELASTICSEARCH_PASSWORD:
        kwargs["basic_auth"] = (ELASTICSEARCH_USERNAME, ELASTICSEARCH_PASSWORD)
    return Elasticsearch(**kwargs)


def search_faculty_by_school_and_areas(
    school: str,
    area_keys: list[str],
    limit: int = 30,
) -> list[dict[str, Any]]:
    """
    Find faculty at a given school (dept) with non-zero strength in any of the given
    parent areas. Returns list of dicts with name, dept, homepage, scholar_url,
    top parent areas, top venues, total_adjusted.
    """
    if not area_keys or not school or not school.strip():
        return []

    dept_normalized = school.strip().lower()
    es = _get_es_client()
    index = GRAD_SCHOOL_ES_INDEX

    # Build bool filter: dept matches + at least one by_parent[area] > 0
    must = [{"term": {"dept.keyword": dept_normalized}}]
    should = []
    for area in area_keys:
        should.append({"range": {f"by_parent.{area}": {"gt": 0}}})
    if should:
        must.append({"bool": {"should": should, "minimum_should_match": 1}})

    query = {
        "query": {"bool": {"filter": must}},
        "size": limit,
        "_source": [
            "name", "dept", "homepage", "scholar_url", "orcid_url",
            "by_parent", "by_venue", "venues", "first_year", "last_year", "total_adjusted",
        ],
        "sort": [{"total_adjusted": "desc"}],
    }

    try:
        resp = es.search(index=index, body=query)
    except Exception as e:
        log.exception("grad_school search_faculty_by_school_and_areas: %s", e)
        return []

    out = []
    for hit in resp.get("hits", {}).get("hits", []):
        src = hit.get("_source", {})
        by_parent = src.get("by_parent") or {}
        top_areas = sorted(
            [k for k, v in by_parent.items() if v and float(v) > 0],
            key=lambda k: by_parent[k],
            reverse=True,
        )[:5]
        by_venue = src.get("by_venue") or {}
        top_venues = sorted(
            by_venue.keys(),
            key=lambda k: by_venue.get(k, 0),
            reverse=True,
        )[:5]
        out.append({
            "name": src.get("name", ""),
            "dept": src.get("dept", ""),
            "homepage": src.get("homepage", ""),
            "scholar_url": src.get("scholar_url", ""),
            "orcid_url": src.get("orcid_url", ""),
            "top_areas": top_areas,
            "top_venues": top_venues,
            "first_year": src.get("first_year"),
            "last_year": src.get("last_year"),
            "total_adjusted": src.get("total_adjusted"),
        })
    return out


def rank_programs_by_area(
    area_key: str,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """
    Rank programs (depts) by total strength in the given parent area.
    Uses ES terms aggregation on dept.keyword, sum by_parent.<area_key>.
    """
    if not area_key or area_key not in KNOWN_PARENT_AREAS:
        return []

    es = _get_es_client()
    index = GRAD_SCHOOL_ES_INDEX

    agg_field = f"by_parent.{area_key}"
    query = {
        "size": 0,
        "query": {"range": {agg_field: {"gt": 0}}},
        "aggs": {
            "by_dept": {
                "terms": {"field": "dept.keyword", "size": limit, "order": {"total": "desc"}},
                "aggs": {"total": {"sum": {"field": agg_field}}},
            },
        },
    }

    try:
        resp = es.search(index=index, body=query)
    except Exception as e:
        log.exception("grad_school rank_programs_by_area: %s", e)
        return []

    buckets = (resp.get("aggs") or {}).get("by_dept", {}).get("buckets", [])
    return [
        {"dept": b["key"], "score": b.get("total", {}).get("value", 0)}
        for b in buckets
    ]
