"""
Grad-school discovery assistant: Elasticsearch helpers for CSRankings faculty/program data.

Index schema matches scripts/ingestion.py (csrankings_authors):
- One document per (author, dept) with by_parent (area -> score), by_venue, name, dept, etc.
"""

import logging
import re as _re
from typing import Any, Optional

from open_webui.config import (
    ELASTICSEARCH_API_KEY,
    ELASTICSEARCH_PASSWORD,
    ELASTICSEARCH_URL,
    ELASTICSEARCH_USERNAME,
    GRAD_SCHOOL_ES_INDEX,
    GRAD_SCHOOL_DEADLINES_ES_INDEX,
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

    buckets = (resp.get("aggregations") or {}).get("by_dept", {}).get("buckets", [])
    return [
        {"dept": b["key"], "score": b.get("total", {}).get("value", 0)}
        for b in buckets
    ]


def query_programs_by_deadline(
    school: Optional[str] = None,
    degree_level: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """
    Filter programs by school, degree level, and/or deadline date range.
    Queries the grad_program_deadlines index.

    :param school: University name to filter by (optional)
    :param degree_level: Degree level to filter by ("phd" or "ms")
    :param start_date: Only include deadlines on or after this date (YYYY-MM-DD)
    :param end_date: Only include deadlines on or before this date (YYYY-MM-DD)
    :param limit: Maximum number of results to return
    :return: List of dicts with school, program, degree_level, deadline_date, term, source_url
    """
    es = _get_es_client()
    index = GRAD_SCHOOL_DEADLINES_ES_INDEX

    # Build bool filter
    must = []

    # Add school filter if provided
    if school:
        must.append({"term": {"school": school.strip().lower()}})

    # Add degree level filter if provided
    if degree_level:
        must.append({"term": {"degree_level": degree_level.strip().lower()}})

    # Add date range filter if provided
    if start_date or end_date:
        date_range = {}
        if start_date:
            date_range["gte"] = start_date
        if end_date:
            date_range["lte"] = end_date
        must.append({"range": {"deadline_date": date_range}})

    # If no filters, match all
    if must:
        query = {"query": {"bool": {"must": must}}, "size": limit}
    else:
        query = {"query": {"match_all": {}}, "size": limit}

    query["_source"] = ["school", "program", "degree_level", "deadline_date", "term", "source_url"]
    query["sort"] = [{"deadline_date": "asc"}]

    try:
        resp = es.search(index=index, body=query)
    except Exception as e:
        log.exception("grad_school query_programs_by_deadline: %s", e)
        return []

    out = []
    for hit in resp.get("hits", {}).get("hits", []):
        src = hit.get("_source", {})
        out.append({
            "school": src.get("school", ""),
            "program": src.get("program", ""),
            "degree_level": src.get("degree_level", ""),
            "deadline_date": src.get("deadline_date", ""),
            "term": src.get("term", ""),
            "source_url": src.get("source_url", ""),
        })
    return out


# ---------------------------------------------------------------------------
# Resume Fit Checker
# ---------------------------------------------------------------------------
# No new Elasticsearch index needed — scoring is done locally via keyword
# matching against the area taxonomy below.
# ---------------------------------------------------------------------------

# Keyword taxonomy: area name -> keywords found in resumes + section tags
_AREA_KEYWORDS: dict[str, dict] = {
    "nlp": {
        "keywords": [
            "nlp", "natural language processing", "text classification",
            "named entity recognition", "ner", "sentiment analysis",
            "language model", "llm", "transformer", "bert", "gpt",
            "seq2seq", "tokenization", "embeddings", "word2vec", "glove",
            "question answering", "machine translation", "summarization",
            "information extraction", "coreference", "dependency parsing",
            "huggingface", "spacy", "nltk",
        ],
    },
    "mlmining": {
        "keywords": [
            "machine learning", "ml", "deep learning", "dl",
            "neural network", "nn", "cnn",
            "rnn", "lstm", "reinforcement learning", "rl",
            "supervised learning",
            "unsupervised learning", "gradient descent", "backpropagation",
            "pytorch", "tensorflow", "keras", "scikit-learn", "sklearn",
            "feature engineering", "hyperparameter", "classification",
            "regression", "clustering", "random forest", "xgboost", "svm",
            "support vector", "generative model", "gan", "diffusion model",
            "fine-tuning", "transfer learning",
        ],
    },
    "sec": {
        "keywords": [
            "security", "cybersecurity", "penetration testing", "pen test",
            "vulnerability", "exploit", "malware", "reverse engineering",
            "network security", "web security", "sql injection", "xss",
            "ctf", "capture the flag", "forensics", "intrusion detection",
            "firewall", "zero-day", "threat modeling", "secure coding",
            "owasp", "kali", "metasploit", "burp suite",
        ],
    },
    "crypt": {
        "keywords": [
            "cryptography", "encryption", "decryption", "tls", "ssl", "pki",
            "hash function", "public key", "private key", "rsa", "aes",
            "elliptic curve", "zero knowledge", "homomorphic",
        ],
    },
    "arch": {
        "keywords": [
            "computer architecture", "cpu", "gpu", "fpga", "cache",
            "pipeline", "microarchitecture", "memory hierarchy",
            "instruction set", "isa", "verilog", "hdl", "risc", "x86",
            "hardware design", "chip design",
        ],
    },
    "ops": {
        "keywords": [
            "operating systems", "kernel", "process", "thread", "scheduler",
            "memory management", "virtual memory", "file system",
            "concurrency", "synchronization", "mutex", "semaphore",
            "linux", "unix", "posix", "system calls",
        ],
    },
    "comm": {
        "keywords": [
            "networking", "network protocol", "tcp", "ip", "udp", "http",
            "dns", "routing", "switching", "socket", "packet", "bandwidth",
            "latency", "wireless", "5g", "sdn", "network simulation",
        ],
    },
    "vision": {
        "keywords": [
            "computer vision", "cv", "image classification", "object detection",
            "segmentation", "ocr", "optical flow", "3d reconstruction",
            "point cloud", "lidar", "yolo", "faster rcnn", "resnet",
            "image processing", "opencv", "pose estimation",
            "depth estimation", "video understanding", "tracking",
        ],
    },
    "robotics": {
        "keywords": [
            "robotics", "ros", "robot operating system", "kinematics",
            "motion planning", "path planning", "sensor fusion", "imu",
            "localization", "mapping", "slam", "manipulation",
            "autonomous", "drone", "uav", "control system", "pid",
            "gazebo",
        ],
    },
    "act": {
        "keywords": [
            "algorithm", "complexity", "np-hard", "np-complete",
            "approximation algorithm", "graph theory", "combinatorics",
            "probability theory", "computational geometry", "automata",
            "formal methods", "proof", "theorem", "online algorithm",
            "streaming algorithm", "data structure",
        ],
    },
    "mod": {
        "keywords": [
            "database", "sql", "nosql", "query optimization", "indexing",
            "transactions", "acid", "relational", "postgresql", "mysql",
            "mongodb", "data modeling", "schema design", "data warehouse",
        ],
    },
    "hpc": {
        "keywords": [
            "high performance computing", "parallel computing", "mpi",
            "openmp", "cuda", "gpu programming", "cluster", "supercomputer",
            "distributed computing", "mapreduce", "spark", "hadoop",
            "job scheduler", "slurm",
        ],
    },
"ai": {
        "keywords": [
            "artificial intelligence", "ai", "knowledge representation",
            "expert system", "planning", "search algorithm", "heuristic",
            "bayesian", "probabilistic reasoning", "constraint satisfaction",
            "multi-agent", "game playing",
        ],
    },
    "inforet": {
        "keywords": [
            "information retrieval", "search engine", "web search", "indexing",
            "ranking", "tf-idf", "bm25", "inverted index", "crawling",
            "web scraping", "recommendation system", "collaborative filtering",
            "content-based filtering", "knowledge graph", "semantic search",
        ],
    },
    "da": {
        "keywords": [
            "design automation", "eda", "electronic design automation",
            "vlsi", "synthesis", "place and route", "timing analysis",
            "logic synthesis", "circuit design", "cadence", "synopsys",
        ],
    },
    "bed": {
        "keywords": [
            "embedded systems", "real-time systems", "rtos", "microcontroller",
            "arduino", "raspberry pi", "firmware", "bare metal", "interrupt",
            "embedded c", "arm", "iot", "internet of things", "sensor",
            "actuator", "real-time scheduling",
        ],
    },
    "mobile": {
        "keywords": [
            "mobile computing", "android", "ios", "swift", "kotlin",
            "react native", "flutter", "mobile app", "mobile development",
            "location services", "push notifications", "mobile security",
        ],
    },
    "metrics": {
        "keywords": [
            "performance analysis", "benchmarking", "profiling", "tracing",
            "monitoring", "observability", "latency", "throughput",
            "performance modeling", "simulation", "queueing theory",
            "workload characterization",
        ],
    },
    "plan": {
        "keywords": [
            "programming languages", "compiler", "type system", "type theory",
            "static analysis", "program analysis", "formal verification",
            "llvm", "interpreter", "garbage collection", "memory safety",
            "rust", "functional programming", "haskell", "ocaml",
            "program synthesis", "language design",
        ],
    },
    "soft": {
        "keywords": [
            "software engineering", "agile", "scrum", "devops", "ci/cd",
            "testing", "unit test", "integration test", "code review",
            "refactoring", "design pattern", "software architecture",
            "microservices", "software quality", "debugging",
            "version control", "requirements engineering",
        ],
    },
    "log": {
        "keywords": [
            "logic", "formal verification", "model checking", "theorem proving",
            "satisfiability", "sat solver", "smt", "coq", "isabelle",
            "temporal logic", "program verification", "automated reasoning",
        ],
    },
    "bio": {
        "keywords": [
            "bioinformatics", "computational biology", "genomics", "sequencing",
            "dna", "rna", "protein structure", "phylogenetics", "blast",
            "sequence alignment", "gene expression", "metagenomics",
            "biopython", "r bioconductor",
        ],
    },
    "graph": {
        "keywords": [
            "computer graphics", "rendering", "opengl", "webgl", "vulkan",
            "ray tracing", "rasterization", "shading", "texture mapping",
            "3d modeling", "animation", "blender", "unity", "unreal",
            "game engine", "physically based rendering",
        ],
    },
    "csed": {
        "keywords": [
            "cs education", "computer science education", "curriculum design",
            "pedagogy", "tutoring", "teaching assistant", "course design",
            "learning outcomes", "educational technology", "mooc",
            "broadening participation", "k-12",
        ],
    },
    "ecom": {
        "keywords": [
            "economics and computation", "algorithmic game theory",
            "mechanism design", "auction theory", "market design",
            "computational economics", "game theory", "nash equilibrium",
            "social choice", "pricing algorithm",
        ],
    },
    "chi": {
        "keywords": [
            "human-computer interaction", "hci", "user interface", "ui",
            "ux", "user experience", "usability", "accessibility",
            "user study", "a/b testing", "figma", "prototyping",
            "interaction design", "cognitive load", "eye tracking",
        ],
    },
    "visualization": {
        "keywords": [
            "visualization", "data visualization", "d3", "tableau",
            "visual analytics", "scientific visualization", "information visualization",
            "dashboard", "charting", "geospatial visualization",
            "matplotlib", "plotly", "vega",
        ],
    },
}

# Generic research signals (boost any area)
_RESEARCH_SIGNALS = [
    "research", "publication", "paper", "conference", "journal",
    "arxiv", "ieee", "acm", "thesis", "dissertation", "lab",
    "undergraduate research", "graduate research", "research assistant",
    "research intern", "phd", "ms", "master", "bachelor",
]

# Coding / tooling depth signals
_CODING_SIGNALS = [
    "python", "java", "c++", "c#", "javascript", "typescript",
    "sql", "bash", "r", "matlab", "scala", "rust", "go",
    "git", "github", "linux", "api", "rest", "docker",
]


def _normalize_text(text: str) -> str:
    return _re.sub(r"\s+", " ", text.lower())


def _keyword_hits(text_lower: str, keywords: list[str]) -> list[str]:
    found = []
    for kw in keywords:
        escaped = _re.escape(kw)
        # Use lookaround boundaries that work for non-word chars like c++, c#, ci/cd
        pattern = r"(?<!\w)" + escaped + r"(?!\w)"
        if _re.search(pattern, text_lower):
            found.append(kw)
    return found


def _resolve_area_for_resume(raw_area: str) -> tuple[str, dict | None]:
    """
    Map user-supplied area string to an _AREA_KEYWORDS entry.
    Reuses the existing AREA_ALIASES dict so the same synonyms work here.
    """
    area_lower = raw_area.lower().strip()

    # First check our resume taxonomy directly
    if area_lower in _AREA_KEYWORDS:
        return area_lower, _AREA_KEYWORDS[area_lower]

    # Then check AREA_ALIASES (already defined above in this file) to get
    # the parent key(s), and use the first one that exists in _AREA_KEYWORDS
    mapped_keys = normalize_area(raw_area)  # uses AREA_ALIASES defined above
    for key in mapped_keys:
        if key in _AREA_KEYWORDS:
            return key, _AREA_KEYWORDS[key]

    # Substring fallback
    for key in _AREA_KEYWORDS:
        if key in area_lower or area_lower in key:
            return key, _AREA_KEYWORDS[key]

    return area_lower, None


def score_resume_for_area(resume_text: str, research_area: str) -> dict:
    """
    Score a plain-text resume against a CS research area.

    Returns a dict with:
      overall_score   int  0-100
      letter_grade    str  A/B/C/D/F
      category_scores dict
      matched_keywords list[str]
      missing_keywords list[str]  (top 10 missing area keywords)
      summary         str
    """
    text = _normalize_text(resume_text)
    resolved_area, area_data = _resolve_area_for_resume(research_area)

    # ---- 1. Area keyword score (0–50 pts) ----
    area_kws = area_data["keywords"] if area_data else [research_area.lower()]
    matched_area = _keyword_hits(text, area_kws)
    missing_area = [kw for kw in area_kws if kw not in matched_area]
    area_ratio = min(len(matched_area) / max(len(area_kws) * 0.4, 1), 1.0)
    area_score = round(area_ratio * 50)

    # ---- 2. Research experience signals (0–30 pts) ----
    matched_research = _keyword_hits(text, _RESEARCH_SIGNALS)
    research_ratio = min(len(matched_research) / max(len(_RESEARCH_SIGNALS) * 0.35, 1), 1.0)
    research_score = round(research_ratio * 30)

    # ---- 3. Coding / tooling depth (0–20 pts) ----
    matched_coding = _keyword_hits(text, _CODING_SIGNALS)
    coding_ratio = min(len(matched_coding) / max(len(_CODING_SIGNALS) * 0.4, 1), 1.0)
    coding_score = round(coding_ratio * 20)

    overall = area_score + research_score + coding_score  # 0–100

    if overall >= 85:
        grade = "A"
    elif overall >= 70:
        grade = "B"
    elif overall >= 55:
        grade = "C"
    elif overall >= 40:
        grade = "D"
    else:
        grade = "F"

    top_missing = sorted(missing_area, key=len)[:10]

    strength = "strong" if area_score >= 35 else "moderate" if area_score >= 20 else "limited"
    research_str = (
        "solid research background" if research_score >= 20
        else "some research exposure" if research_score >= 10
        else "little research experience highlighted"
    )
    summary = (
        f"Your resume shows {strength} alignment with {resolved_area} "
        f"({len(matched_area)} of {len(area_kws)} area keywords found) and "
        f"{research_str}. "
    )
    if top_missing:
        summary += f"Consider adding experience related to: {', '.join(top_missing[:5])}. "
    if overall >= 70:
        summary += "Overall, you appear to be a competitive candidate for this area."
    elif overall >= 50:
        summary += "With targeted projects or coursework, you could strengthen your profile."
    else:
        summary += "Gaining hands-on projects or coursework in this area would significantly improve your fit."

    return {
        "research_area": resolved_area,
        "overall_score": overall,
        "letter_grade": grade,
        "category_scores": {
            "area_keywords":        {"score": area_score,    "max": 50, "matched": len(matched_area),    "total": len(area_kws)},
            "research_experience":  {"score": research_score,"max": 30, "matched": len(matched_research),"total": len(_RESEARCH_SIGNALS)},
            "coding_and_tools":     {"score": coding_score,  "max": 20, "matched": len(matched_coding),  "total": len(_CODING_SIGNALS)},
        },
        "matched_keywords": matched_area,
        "missing_keywords": top_missing,
        "summary": summary,
    }
