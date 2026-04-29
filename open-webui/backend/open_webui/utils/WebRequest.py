import re
import requests
from urllib.parse import urlparse

from open_webui.config import SERPAPI_API_KEY

# ============================================================
# CS DEPARTMENT HOMEPAGE SCORING
# ============================================================

# Common words to strip from university names when extracting match tokens
UNIVERSITY_STOPWORDS = {
    "university", "college", "institute", "school", "of", "the", "at",
    "and", "&", "state", "system", "–", "-", "a", "an",
}

# Some universities have well-known abbreviations or alternate domain roots
# that don't directly match the words in their official name. Handle explicitly.
UNIVERSITY_ALIASES = {
    "massachusetts institute of technology": ["mit"],
    "california institute of technology": ["caltech"],
    "georgia institute of technology": ["gatech", "gt"],
    "university of california berkeley": ["berkeley", "ucberkeley", "ucb"],
    "university of california los angeles": ["ucla"],
    "university of california san diego": ["ucsd"],
    "university of california irvine": ["uci"],
    "university of california davis": ["ucdavis"],
    "university of california santa barbara": ["ucsb"],
    "university of california santa cruz": ["ucsc"],
    "university of california riverside": ["ucr"],
    "university of illinois at urbana-champaign": ["illinois", "uiuc"],
    "university of illinois urbana champaign": ["illinois", "uiuc"],
    "university of michigan": ["umich", "michigan"],
    "university of washington": ["uw", "washington"],
    "university of wisconsin madison": ["wisc", "wisconsin"],
    "university of maryland college park": ["umd", "maryland"],
    "university of texas at austin": ["utexas", "texas"],
    "university of pennsylvania": ["upenn", "penn"],
    "university of southern california": ["usc"],
    "university of minnesota": ["umn", "minnesota"],
    "university of chicago": ["uchicago"],
    "university of virginia": ["virginia"],
    "university of florida": ["ufl", "florida"],
    "university of north carolina chapel hill": ["unc"],
    "university of colorado boulder": ["colorado"],
    "university of massachusetts amherst": ["umass"],
    "carnegie mellon university": ["cmu"],
    "new york university": ["nyu"],
    "pennsylvania state university": ["psu"],
    "ohio state university": ["osu"],
    "north carolina state university": ["ncsu"],
    "virginia tech": ["vt"],
    "washington university in st louis": ["wustl", "washu"],
    "stony brook university": ["stonybrook"],
    "johns hopkins university": ["jhu"],
    "rensselaer polytechnic institute": ["rpi"],
    "rochester institute of technology": ["rit"],
    "texas a&m university": ["tamu"],
    "arizona state university": ["asu"],
    "princeton university": ["princeton"],
    "harvard university": ["harvard"],
    "yale university": ["yale"],
    "stanford university": ["stanford"],
    "duke university": ["duke"],
    "cornell university": ["cornell"],
    "brown university": ["brown"],
    "columbia university": ["columbia"],
    "dartmouth college": ["dartmouth"],
    "northeastern university": ["northeastern"],
    "northwestern university": ["northwestern"],
    "rice university": ["rice"],
    "vanderbilt university": ["vanderbilt"],
    "boston university": ["bu"],
    "emory university": ["emory"],
    "purdue university": ["purdue"],
}


def _university_match_tokens(university_name: str) -> set[str]:
    """
    Returns a set of lowercase tokens we expect to see in the host of a URL
    that actually belongs to this university.
    """
    name_lower = university_name.lower().strip()
    tokens = set()

    # Explicit aliases take priority
    if name_lower in UNIVERSITY_ALIASES:
        tokens.update(UNIVERSITY_ALIASES[name_lower])

    # Also include significant words from the name itself
    words = re.findall(r"[a-z]+", name_lower)
    for w in words:
        if w in UNIVERSITY_STOPWORDS:
            continue
        if len(w) < 3:
            continue
        tokens.add(w)

    return tokens

# Subdomain prefixes that strongly indicate a CS department
CS_SUBDOMAIN_PREFIXES = {
    "cs": 100,
    "cse": 100,
    "cis": 90,
    "eecs": 100,
    "ics": 90,
    "khoury": 100,
    "csd": 90,
    "cc": 70,           # "College of Computing"
    "computing": 90,
    "compsci": 90,
    "scs": 90,          # "School of Computer Science"
    "csail": 80,
    "informatics": 70,    # Some schools put CS under engineering subdomain
    "computerscience": 90,
}

# Path segments that indicate the page is CS-related
CS_PATH_KEYWORDS = {
    "computer-science": 40,
    "computer_science": 40,
    "computer-sciences": 40,
    "computerscience": 40,
    "cs": 20,
    "cse": 20,
    "eecs": 30,
    "khoury": 30,
    "comp-sci": 30,
    "compsci": 30,
}

# Keywords in title/snippet that indicate a department homepage
TITLE_KEYWORDS = {
    "department of computer science": 50,
    "school of computer science": 50,
    "school of computing": 50,
    "college of computing": 50,
    "computer science department": 50,
    "computer science and engineering": 45,
    "electrical engineering and computer science": 45,
    "eecs": 30,
    "khoury college": 50,
    "department of computing": 40,
    "computer science": 25,
    "computing": 15,
}

# Subdomains that are explicitly NOT the CS department
BAD_SUBDOMAINS = {
    "admissions", "apply", "applications", "news", "events", "library",
    "alumni", "giving", "donate", "research", "jobs", "careers",
    "calendar", "directory", "store", "catalog", "catalogs",
}

# Path segments that suggest this is a sub-page, not the homepage
BAD_PATH_KEYWORDS = {
    "people": -30,
    "faculty": -30,
    "staff": -30,
    "students": -20,
    "courses": -20,
    "news": -30,
    "events": -30,
    "alumni": -30,
    "admissions": -40,
    "apply": -30,
    "giving": -40,
    "directory": -30,
    "contact": -20,
    "login": -40,
    "jobs": -40,
    "careers": -40,
    "undergraduate": -60,
    "undergrad": -60,
    "catalog": -60,
    "catalogs": -60,

}


def score_cs_department_result(result: dict, university_name: str = "") -> tuple[int, list[str]]:
    """
    Scores a single search result on how likely it is to be a CS department
    homepage for the given university. Returns (score, matched_labels).
    """
    url = result.get("url", "") or ""
    title = (result.get("title") or "").lower()
    snippet = (result.get("snippet") or "").lower()

    if not url:
        return -1000, ["NO_URL"]

    parsed = urlparse(url)
    host = parsed.netloc.lower()
    path = parsed.path.lower()

    score = 0
    labels = []

    # Hard filter: must be .edu
    if not (host.endswith(".edu") or ".edu." in host):
        return -1000, ["NOT_EDU"]

    # Hard filter: reject bad subdomains
    host_parts = host.split(".")
    if host_parts and host_parts[0] in BAD_SUBDOMAINS:
        return -1000, [f"BAD_SUBDOMAIN:{host_parts[0]}"]

    # University-match check: the URL's host must contain a token from the
    # university name or an alias. If not, this result belongs to some OTHER
    # institution and should be disqualified regardless of how CS-department
    # shaped it looks.
    if university_name:
        match_tokens = _university_match_tokens(university_name)
        host_no_edu = host.replace(".edu", "")
        title_snippet_blob = f"{title} {snippet}"
        matched_token = None
        for tok in match_tokens:
            if tok in host_no_edu:
                matched_token = tok
                break
        if matched_token:
            labels.append(f"UNIV_MATCH:{matched_token}(+0)")
        else:
            # Check if the university is mentioned in title/snippet as a
            # last-resort backup — but still penalize heavily since the host
            # belongs to some other institution.
            name_in_text = any(tok in title_snippet_blob for tok in match_tokens)
            if name_in_text:
                score -= 500
                labels.append(f"UNIV_MISMATCH:host_wrong_but_name_in_text(-500)")
            else:
                return -1000, [f"UNIV_MISMATCH:{host}_not_for_{university_name}"]

    # Subdomain-based scoring
    if host_parts:
        first_part = host_parts[0]
        if first_part in CS_SUBDOMAIN_PREFIXES:
            pts = CS_SUBDOMAIN_PREFIXES[first_part]
            score += pts
            labels.append(f"SUBDOMAIN:{first_part}(+{pts})")
        # Handle www.cs.school.edu pattern too
        elif first_part == "www" and len(host_parts) > 1 and host_parts[1] in CS_SUBDOMAIN_PREFIXES:
            pts = CS_SUBDOMAIN_PREFIXES[host_parts[1]] - 10
            score += pts
            labels.append(f"SUBDOMAIN:www.{host_parts[1]}(+{pts})")

    # Path-based scoring
    path_segments = [seg for seg in path.split("/") if seg]
    for seg in path_segments:
        if seg in CS_PATH_KEYWORDS:
            pts = CS_PATH_KEYWORDS[seg]
            score += pts
            labels.append(f"PATH:{seg}(+{pts})")
        if seg in BAD_PATH_KEYWORDS:
            pts = BAD_PATH_KEYWORDS[seg]
            score += pts
            labels.append(f"BAD_PATH:{seg}({pts})")

    # Homepage-shape bonus: shorter paths are more likely to be homepages
    if len(path_segments) == 0:
        score += 30
        labels.append("ROOT_PATH(+30)")
    elif len(path_segments) == 1:
        score += 15
        labels.append("SHALLOW_PATH(+15)")
    elif len(path_segments) >= 4:
        score -= 10
        labels.append("DEEP_PATH(-10)")

    # Title / snippet scoring — at most one bonus to avoid double-counting
    text_blob = f"{title} {snippet}"
    for keyword, pts in TITLE_KEYWORDS.items():
        if keyword in text_blob:
            score += pts
            labels.append(f"TITLE:{keyword!r}(+{pts})")
            break

    return score, labels

def serpapi_google_search(query: str, num_results: int = 1) -> list[dict]:
    """
    Uses SerpAPI's Google Search engine to search for given query and returns the .edu of the top three links
    """
    url = "https://serpapi.com/search.json"
    params = {
        "engine": "google",
        "q": query,
        "api_key": SERPAPI_API_KEY,
        "num": min(max(num_results, 1), 10),
        "hl": "en",
        "gl": "us",
    }

    r = requests.get(url, params=params, timeout=30)
    r.raise_for_status()
    data = r.json()

    results = []
    for item in data.get("organic_results", []):
        results.append({
            "title": item.get("title"),
            "url": item.get("link"),
            "snippet": item.get("snippet"),
        })
    return results

def get_top_link(university_name: str) -> str | None:
    search_query = f"{university_name} Computer Science Department"

    print("Search query:")
    print(search_query)
    print("=" * 60)

    hits = serpapi_google_search(search_query, num_results=10)

    if not hits:
        print("No results found.")
        return None

    # Score each hit for how likely it is to be the CS department homepage
    scored_hits = []
    for i, h in enumerate(hits, start=1):
        score, labels = score_cs_department_result(h, university_name=university_name)
        scored_hits.append({
            "original_rank": i,
            "score": score,
            "labels": labels,
            "title": h.get("title", "N/A"),
            "url": h.get("url", "N/A"),
            "snippet": h.get("snippet", "N/A"),
        })

    print("Top Results (scored):")
    print("=" * 60)
    for h in scored_hits:
        print(f"ORIG#{h['original_rank']}  SCORE: {h['score']}")
        print(f"  TITLE : {h['title']}")
        print(f"  URL   : {h['url']}")
        print(f"  WHY   : {', '.join(h['labels']) if h['labels'] else 'None'}")
        print("-" * 60)

    # Sort by score descending, break ties by original rank (Google's ranking)
    scored_hits.sort(key=lambda x: (-x["score"], x["original_rank"]))

    best = scored_hits[0]

    # Require at least a modest positive score to trust the scored winner.
    # If nothing scores well enough, fall back to Google's top result.
    MIN_ACCEPTABLE_SCORE = 40

    if best["score"] >= MIN_ACCEPTABLE_SCORE:
        print(f"Top CS department link selected (score={best['score']}):")
        print(best["url"])
        return best["url"]
    else:
        # Fallback: no result scored high enough to be confident
        fallback = hits[0].get("url")
        print(f"No result met threshold ({MIN_ACCEPTABLE_SCORE}). "
              f"Top candidate scored only {best['score']}.")
        print(f"Falling back to Google's top result: {fallback}")
        return fallback