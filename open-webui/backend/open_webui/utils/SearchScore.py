import re
from pathlib import Path
import tempfile
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse
from open_webui.utils.Scraping import scrape_url, table_to_text
from collections import deque
from open_webui.utils.WebRequest import get_top_link

# ============================================================
# CONFIG
# ============================================================

SCRAPER_DEBUG_DIR = Path(tempfile.gettempdir()) / "open_webui_deadline_scraper"
HTML_FILE = SCRAPER_DEBUG_DIR / "page.txt"
TEXT_FILE = SCRAPER_DEBUG_DIR / "page_text.txt"
TOP_K = 2
MIN_VALID_YEAR = 2025

# Pages that often match but are not useful for deadline scraping
NEGATIVE_KEYWORDS = {
    "undergraduate",
    "certificate",
    "certificates",
    "minor",
    "faculty",
    "staff",
    "news",
    "event",
    "events",
    "seminar",
    "seminars",
    "areas",
    "people",
    "alumni",
    "course",
    "courses",
    "bs/ms",
    "b.s./m.s.",
    "first-year",
    "transfer",
    "international",
    "b.s.",
    "frequently-asked",
    "questions",
    "data",
    "mail",
    "contact",
    "mailto:",
    "mailto",
    "facebook",
    "youtube",
    "twitter",
    "linkedin",
    "mba",
    "business",
    "instagram",
    "apply-now",
    "faq",
    "internships",
    "internship",
    "co-op",
    "outreach",
    "diploma",
    "law",
    "calendar",
    "civil",
    "mechanical",
    "chemical",
    "chemistry",
    "biology",
    "biological",
    "physics",
    "psychology",
    "sociology",
    "economics",
    "history",
    "philosophy",
    "english",
    "literature",
    "linguistics",
    "anthropology",
    "geology",
    "geography",
    "mathematics",
    "statistics",
    "nursing",
    "medicine",
    "medical",
    "pharmacy",
    "dental",
    "dentistry",
    "veterinary",
    "architecture",
    "art",
    "arts",
    "music",
    "theater",
    "theatre",
    "dance",
    "journalism",
    "communications",
    "agriculture",
    "environmental",
    "aerospace",
    "biomedical",
    "industrial",
    "materials",
    "nuclear",
    "petroleum",
    "finance",
    "accounting",
    "marketing",
    "management",
    "religion",
    "theology",
    "political",
    "government",
    "public-policy",
    "social-work",
    "kinesiology",
    "neuroscience",
    "bioengineering",
    "bridge",
    "accepting",
    "deferring",
    "reapplying",
}

BONUS_GROUPS = [
    # Program + admission-term pair bonuses (strongest signal for the pages we want)
    (125, {"doctoral", "applications"}),
    (125, {"doctoral", "admissions"}),
    (125, {"phd", "applications"}),
    (125, {"phd", "admissions"}),
    (125, {"masters", "applications"}),
    (125, {"masters", "admissions"}),
    (125, {"ms", "applications"}),
    (125, {"ms", "admissions"}),
    (125, {"admissions", "information"}),
    (125, {"admission", "information"}),
    (125, {"fields","study"}),
    (125, {"application-deadlines"}),
    (125, {"applying-for-admission"}),
    (125, {"application-requirements"}),
    (125, {"apply-to"}),
    (125, {"admission-process"}),
    (100, {"how-to-apply"}),
    (100, {"application-checklist"}),
    (100, {"prospective"}),
    (100, {"graduate"}),
    (100, {"research-programs"}),
    (75, {"apply","now"}),
    (50, {"deadlines"}),
    (35, {"application"}),
    (35, {"apply"}),
    (25, {"requirements"}),
]

DEADLINE_TERMS = [
    "deadline",
    "deadlines",
    "application deadline",
    "important dates",
    "due date",
    "application due",
    "submit by",
    "application timeline",
    "application enrollement & timeline",
    "application requirements",
]

MONTH_NAME_PATTERN = (
    r"(?:jan|january|feb|february|mar|march|apr|april|may|jun|june|jul|july|"
    r"aug|august|sep|sept|september|oct|october|nov|november|dec|december)"
)

DATE_PATTERNS = [
    re.compile(
        # Allow optional trailing "." after month name (e.g. "Aug. 1, 2026", "Dec. 1")
        rf"\b{MONTH_NAME_PATTERN}\.?\s*\d{{1,2}}(?:st|nd|rd|th)?(?:,\s*\d{{4}})?\b",
        re.IGNORECASE
    ),
    re.compile(r"\b\d{1,2}/\d{1,2}/\d{2,4}\b"),
    re.compile(r"\b\d{4}-\d{2}-\d{2}\b"),
]

YEAR_PATTERN = re.compile(r"\b(20\d{2})\b")

# Phrases that indicate a page is deferring to another page for deadline info
REDIRECT_PHRASES = [
    r"visit our",
    r"visit the",
    r"refer to",
    r"please refer",
    r"learn more",
    r"see the",
    r"check with",
    r"found on",
    r"listed on",
    r"available on",
    r"available at",
    r"on each program",
    r"on the program page",
    r"on your program",
    r"on their (website|page|site)",
    r"deadlines (may|will) vary",
    r"deadline information may vary",
    r"contact (your|the) (department|program|school)",
    # Strong "redirect to program page" phrases (common on grad-school top-level pages)
    r"consult (your|the) program",
    r"(your|the) program's page",
    r"vary by program",
    r"varies by program",
    r"depends on (the|your) program",
    r"specific to (each|your) program",
    r"most programs",
    r"individual programs",
    r"each (program|department) has",
]

REDIRECT_PHRASE_PATTERN = re.compile(
    "|".join(REDIRECT_PHRASES),
    re.IGNORECASE
)

MS_CONFIG = {
    "name": "MS",
    "target_keywords": {"ms", "m.s.", "master", "masters"},
    "positive_keywords": {
        "admissions",
        "ms",
        "masters",
        "computer science",
        "cse",
        "cs",
        "program-info",
        "steps",
        "academic-planning",
    },
    # Target-program keywords: gentle +25 boost to surface MS-related links above generic CS
    "target_boost_keywords": {"ms", "masters"},
    # Wrong-program keywords: -100 penalty to drop PhD-only pages from MS results
    "anti_keywords": {"phd", "doctoral", "doctorate"},
    "priority_groups": [
        # (180, {"ms", "computer science", "cs","application", "requirements"}),
        # (180, {"ms", "computer science", "cs","how","apply"}),
        # (150, {"ms", "how","apply"}),
        # (140, {"ms", "admissions", "cs"}),
        # (140, {"ms", "admissions", "cse"}),
        # (130, {"master", "admissions"}),
        # (130, {"masters", "admissions"}),
        # (110, {"graduate", "admissions", "cs"}),
        # (110, {"graduate", "admissions", "cse"}),
        # (100, {"graduate", "admissions"}),
        # (70, {"admissions"}),
        # (40, {"academics"}),
    ],
    "program_pattern": re.compile(
        r"\b(ms|m\.s\.|master'?s|masters)\b",
        re.IGNORECASE
    ),
}

PHD_CONFIG = {
    "name": "PhD",
    "target_keywords": {"phd", "ph.d.", "doctoral", "doctorate"},
    "positive_keywords": {
        "admissions",
        "phd",
        "doctorate",
        "computer science",
        "cse",
        "cs",
        "program-info",
        "steps",
    },
    # Target-program keywords: gentle +25 boost to surface PhD-related links above generic CS
    "target_boost_keywords": {"phd", "doctoral", "doctorate"},
    # Wrong-program keywords: -100 penalty to drop MS-only pages from PhD results
    "anti_keywords": {"ms", "masters"},
    "priority_groups": [
        # (180, {"phd", "computer science", "cs","application", "requirements"}),
        # (180, {"phd", "computer science", "cs","how","apply"}),
        # (150, {"phd", "how","apply"}),
        # (140, {"phd", "admissions", "cs"}),
        # (140, {"phd", "admissions", "cse"}),
        # (130, {"doctoral", "admissions"}),
        # (130, {"doctorate", "admissions"}),
        # (110, {"graduate", "admissions", "cs"}),
        # (110, {"graduate", "admissions", "cse"}),
        # (100, {"graduate", "admissions"}),
        # (70, {"admissions"}),
        # (40, {"academics"}),
    ],
    "program_pattern": re.compile(
        r"\b(phd|ph\.d\.|doctoral|doctorate)\b",
        re.IGNORECASE
    ),
}

DEADLINE_HEADING_PATTERNS = [
    re.compile(r"\bdeadlines?\b", re.IGNORECASE),
    re.compile(r"\bapplication deadlines?\b", re.IGNORECASE),
    re.compile(r"\bimportant dates\b", re.IGNORECASE),
    re.compile(r"\badmissions deadlines?\b", re.IGNORECASE),
    re.compile(r"\bgraduate admissions deadlines?\b", re.IGNORECASE),
]

# ============================================================
# NORMALIZATION / TOKENIZATION
# ============================================================

def normalize_text(text: str) -> str:
    text = text.lower()
    text = text.replace("&", " and ")
    text = re.sub(r"[_/\\\-]+", " ", text)
    text = re.sub(r"[^a-z0-9.+ ]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text

def build_token_set(text: str) -> set[str]:
    """
    Creates a token set from anchor text + URL/path.
    Also adds phrase-aware aliases like:
    - 'computer science' -> 'computer science', 'cs'
    - 'ph.d.' -> 'phd'
    - 'm.s.' -> 'ms'

    Each concept is represented by a SINGLE canonical form to avoid
    double-scoring (e.g. 'deadlines' alone is added, not both 'deadline'
    and 'deadlines').
    """
    norm = normalize_text(text)
    tokens = set(norm.split())

    if "computer science" in norm:
        tokens.add("computer science")
        tokens.add("cs")

    if "phd" in norm or "ph.d." in text.lower() or "ph d" in norm:
        tokens.add("phd")

    # MS - must match as a whole word, not as substring of "programs", "systems", etc.
    norm_words = set(norm.split())
    if "ms" in norm_words or "m.s." in text.lower() or "m s" in norm:
        tokens.add("ms")

    # Deadline - use plural as canonical form
    if "deadline" in norm:
        tokens.add("deadlines")
    tokens.discard("deadline")

    # Admissions - use plural as canonical form
    if "admission" in norm:
        tokens.add("admissions")
    tokens.discard("admission")

    # Masters - use plural as canonical form
    if "master" in norm or "master's" in text.lower():
        tokens.add("masters")
    tokens.discard("master")

    if "doctoral" in norm:
        tokens.add("doctoral")
    if "doctorate" in norm:
        tokens.add("doctorate")

    if "how" in norm and "apply" in norm:
        tokens.add("how-to-apply")
    if "application" in norm and "requirements" in norm:
        tokens.add("application-requirements")
    if "program" in norm and "info" in norm:
        tokens.add("program-info")
    if "apply" in norm and "now" in norm:
        tokens.add("apply-now")
    if "apply" in norm and "to" in norm:
        tokens.add("apply-to")
    if "research" in norm and "programs" in norm:
        tokens.add("research-programs")
    if "applying" in norm and "admissions" in tokens:
        tokens.add("applying-for-admission")
    if "application" in norm and "checklist" in norm:
        tokens.add("application-checklist")
    if "admission" in norm and "process" in norm:
        tokens.add("admission-process")
    if "application" in norm and "deadlines" in norm:
        tokens.add("application-deadlines")

    return tokens

# ============================================================
# DATE FILTERING
# ============================================================

def extract_years_from_text(text: str) -> list[int]:
    years = []
    for match in YEAR_PATTERN.finditer(text):
        year = int(match.group(1))
        years.append(year)
    return years

def has_recent_year(text: str, min_valid_year: int = MIN_VALID_YEAR) -> bool:
    years = extract_years_from_text(text)
    return any(year >= min_valid_year for year in years)

def snippet_has_recent_year(snippet: str, min_valid_year: int = MIN_VALID_YEAR) -> bool:
    return has_recent_year(snippet, min_valid_year)

def text_has_dates(text: str) -> bool:
    """Returns True if any date pattern matches in the given text."""
    return any(p.search(text) for p in DATE_PATTERNS)

# ============================================================
# SCORING
# ============================================================

def score_link(anchor_text: str, full_url: str, config: dict) -> tuple[int, list[str], list[str]]:
    parsed = urlparse(full_url)

    scoring_blob = f"{anchor_text} {full_url} {parsed.path}"
    tokens = build_token_set(scoring_blob)

    score = 0
    matched_labels = []

    # for pts, group in config["priority_groups"]:
    #     if group.issubset(tokens):
    #         score += pts
    #         matched_labels.append(f"PRIORITY:{sorted(group)}")

    for pts, group in BONUS_GROUPS:
        if group.issubset(tokens):
            score += pts
            matched_labels.append(f"BONUS:{sorted(group)}")

    # if "graduate" in tokens:
    #     score += 12
    # if "admissions" in tokens or "admission" in tokens:
    #     score += 18
    # if "cs" in tokens or "cse" in tokens or "computer science" in tokens:
    #     score += 15
    # if "how-to-apply" in tokens:
    #     score += 60
    # if "application-requirements" in tokens:
    #     score += 60
    # if "apply-to" in tokens:
    #     score += 60

    for kw in config["positive_keywords"]:
        if kw in tokens:
          score += 20
          matched_labels.append(f"POSITIVE:{kw}")

    # Target-program boost: +25 per match to surface our program's links above generic CS
    for kw in config.get("target_boost_keywords", set()):
        if kw in tokens:
            score += 25
            matched_labels.append(f"TARGET:{kw}(+25)")

    # Anti-program penalty: -100 per match to drop wrong-program pages
    for kw in config.get("anti_keywords", set()):
        if kw in tokens:
            score -= 100
            matched_labels.append(f"ANTI:{kw}(-100)")

    # Program-specific boosts
    # if config["name"] == "MS":
    #     if "ms" in tokens or "master" in tokens or "masters" in tokens:
    #         score += 35
    #         matched_labels.append("TARGET:MS")
    # elif config["name"] == "PhD":
    #     if "phd" in tokens or "doctoral" in tokens or "doctorate" in tokens:
    #         score += 35
    #         matched_labels.append("TARGET:PHD")

    path_norm = normalize_text(parsed.path)

    # if "deadline" in path_norm or "deadlines" in path_norm:
    #     score += 40
    #     matched_labels.append("PATH:deadline")
    # if "admission" in path_norm or "admissions" in path_norm:
    #     score += 25
    #     matched_labels.append("PATH:admissions")
    # if "prospective" in path_norm:
    #     score += 18
    #     matched_labels.append("PATH:prospective")
    # if "graduate" in path_norm:
    #     score += 15
    #     matched_labels.append("PATH:graduate")
    # if "apply" in path_norm or "application" in path_norm:
    #     score += 20
    #     matched_labels.append("PATH:apply/application")

    negative_hits = []
    anchor_norm = normalize_text(anchor_text)

    for neg in NEGATIVE_KEYWORDS:
        neg_norm = normalize_text(neg)
        if neg_norm in path_norm or neg_norm in anchor_norm or neg_norm in tokens:
            negative_hits.append(neg)

    # for neg in negative_hits:
    #     if neg in {"first-year", "undergraduate", "transfer", "international","data science", "electrical engineering", "civil engineering"}:
    #         score -= 100
    #     elif neg in {"bs/ms", "b.s./m.s."}:
    #         score -= 50
    #     elif neg in {"certificate", "certificates", "minor"}:
    #         score -= 40
    #     elif neg in {"faculty", "staff", "people", "alumni"}:
    #         score -= 30
    #     elif neg in {"research", "areas"}:
    #         score -= 20
    #     else:
    #         score -= 15

    #     matched_labels.append(f"PENALTY:{neg}")

    for neg in negative_hits:
        score -= 1000
        matched_labels.append(f"PENALTY:{neg}")

    return score, matched_labels, sorted(tokens)

# ============================================================
# LINK EXTRACTION
# ============================================================

def extract_ranked_links(html: str, base_url: str, config: dict) -> list[dict]:
    soup = BeautifulSoup(html, "lxml")
    seen = set()
    results = []

    for i, a in enumerate(soup.find_all("a", href=True), start=1):
        href = a["href"].strip()
        if not href:
            continue

        full_url = urljoin(base_url, href)
        anchor_text = " ".join(a.stripped_strings).strip()

        if not anchor_text:
            anchor_text = "[NO TEXT]"

        url_key = full_url
        if url_key in seen:
            continue
        seen.add(url_key)

        score, matched_labels, tokens = score_link(anchor_text, full_url, config)

        if score > 0:
            results.append({
                "original_index": i,
                "score": score,
                "text": anchor_text,
                "url": full_url,
                "matched_labels": matched_labels,
                "tokens": tokens,
            })

    results.sort(
        key=lambda x: (-x["score"], len(x["url"]), x["original_index"])
    )
    return results

# ============================================================
# DEADLINE PAGE DETECTION
# ============================================================

def extract_heading_info(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "lxml")
    headings = []

    for tag_name in ["h1", "h2", "h3", "h4", "h5"]:
        for tag in soup.find_all(tag_name):
            heading_text = " ".join(tag.stripped_strings).strip()
            if heading_text:
                headings.append({
                    "tag": tag_name,
                    "text": heading_text
                })

    return headings

def find_deadline_headings(headings: list[dict], config: dict) -> list[dict]:
    matches = []

    for heading in headings:
        heading_text = heading["text"]

        has_deadline_heading = any(
            pattern.search(heading_text) for pattern in DEADLINE_HEADING_PATTERNS
        )
        has_program_term = bool(config["program_pattern"].search(heading_text))

        if has_deadline_heading:
            matches.append({
                "tag": heading["tag"],
                "text": heading_text,
                "has_program_term": has_program_term,
            })

    return matches

def get_sibling_content_after_heading(html: str, heading_tag: dict, char_limit: int = 600) -> tuple[str, list[str]]:
    """
    Given a heading dict (with 'tag' and 'text'), finds that heading in the HTML
    and returns all text content between it and the next heading of equal or
    higher rank, plus any href links inside that section.

    Uses position-based slicing on the rendered DOM text rather than DOM-walk
    deduplication. This reliably captures tables, nested divs, and other
    complex layouts without double-counting or missing content.
    """
    soup = BeautifulSoup(html, "lxml")
    heading_tags = ["h1", "h2", "h3", "h4", "h5"]

    for tag in soup.find_all(heading_tag["tag"]):
        if " ".join(tag.stripped_strings).strip() != heading_tag["text"]:
            continue

        # Walk forward collecting siblings/descendants until we hit the next heading
        # Using find_all_next() gives us document order
        collected_chunks = []
        collected_links = []
        total_chars = 0
        # Track descendants of already-rendered tables so we don't re-capture their
        # <th>/<td> cells individually after table_to_text already rendered them.
        table_descendants = set()

        for element in tag.find_all_next():
            # Stop at the next heading of equal or higher rank
            if element.name in heading_tags:
                break

            # Skip elements that are descendants of a table we already rendered
            if id(element) in table_descendants:
                continue

            # When we encounter a <table>, render it structurally via table_to_text
            # (which produces "row_label | column_header: value" format) instead of
            # walking its cells individually. Then mark all descendants as seen.
            if element.name == "table":
                rendered = table_to_text(element)
                if rendered:
                    collected_chunks.append(rendered)
                    total_chars += len(rendered)
                for descendant in element.find_all():
                    table_descendants.add(id(descendant))
                # Collect links from inside the table too
                for a in element.find_all("a", href=True):
                    href = a["href"].strip()
                    if href and not href.startswith("#"):
                        collected_links.append(href)
                if total_chars >= char_limit:
                    break
                continue

            # We only care about leaf-ish text nodes — paragraphs, list items, table cells
            # This avoids re-capturing the same text via both parent container and its children
            if element.name not in ["p", "li", "td", "th"]:
                # Still collect hrefs from anchors we encounter at any depth
                if element.name == "a":
                    href = element.get("href", "").strip()
                    if href and not href.startswith("#"):
                        collected_links.append(href)
                continue

            element_text = " ".join(element.stripped_strings).strip()
            if not element_text:
                continue

            collected_chunks.append(element_text)
            total_chars += len(element_text)

            for a in element.find_all("a", href=True):
                href = a["href"].strip()
                if href and not href.startswith("#"):
                    collected_links.append(href)

            if total_chars >= char_limit:
                break

        return "\n".join(collected_chunks), list(dict.fromkeys(collected_links))

    return "", []

def detect_hollow_deadline_section(html: str, base_url: str, matched_headings: list[dict]) -> dict:
    """
    For each matched deadline heading, checks whether the content beneath it
    contains actual date information or is instead a hollow redirect section.

    Redirect URLs are filtered through NEGATIVE_KEYWORDS to drop links pointing
    to social media, mailto:, faculty pages, etc. — these would never lead to
    a real deadline page.

    Returns:
        {
            "is_hollow": bool,
            "redirect_urls": list[str],   # absolute URLs found near hollow sections
            "reason": str                 # human-readable explanation
        }
    """
    hollow_sections = 0
    total_sections = len(matched_headings)
    all_redirect_urls = []
    filtered_negative_count = 0

    for heading in matched_headings:
        section_text, raw_links = get_sibling_content_after_heading(html, heading)

        has_dates = text_has_dates(section_text)
        redirect_matches = REDIRECT_PHRASE_PATTERN.findall(section_text)
        has_redirect_phrase = bool(redirect_matches)
        # A section with MULTIPLE redirect phrases is highly likely to be a
        # "consult your program's page" redirect, even if it happens to include
        # a single example date (e.g. "For spring admission, the deadline for
        # most programs is October 1st"). Treat as hollow when 2+ redirect
        # phrases are present.
        heavily_redirects = len(redirect_matches) >= 2

        section_is_hollow = (
            (not has_dates and (has_redirect_phrase or raw_links))
            or heavily_redirects
        )

        if section_is_hollow:
            hollow_sections += 1
            for href in raw_links:
                full_url = urljoin(base_url, href)

                # Filter out links containing negative keywords (mailto, facebook, etc.)
                url_norm = normalize_text(full_url)
                neg_hit = None
                for neg in NEGATIVE_KEYWORDS:
                    neg_norm = normalize_text(neg)
                    if neg_norm in url_norm:
                        neg_hit = neg
                        break

                if neg_hit:
                    filtered_negative_count += 1
                    print(f"    [FILTERED] Redirect URL dropped (neg keyword '{neg_hit}'): {full_url}")
                    continue

                all_redirect_urls.append(full_url)

            reason_tag = "heavy-redirect" if heavily_redirects and has_dates else "no-dates+redirect"
            print(f"  [HOLLOW SECTION DETECTED - {reason_tag}] Heading: '{heading['text']}'")
            print(f"    Section text: {section_text[:200]!r}")
            print(f"    Redirect phrase matches: {len(redirect_matches)}")
            print(f"    Redirect links kept: {all_redirect_urls}")

    if filtered_negative_count > 0:
        print(f"  [HOLLOW FILTER] Dropped {filtered_negative_count} redirect URL(s) matching negative keywords")

    is_hollow = hollow_sections > 0 and hollow_sections == total_sections

    reason = ""
    if is_hollow:
        reason = (
            f"All {total_sections} deadline section(s) lacked date info and "
            f"contained redirect phrases or links."
        )
    elif hollow_sections > 0:
        reason = (
            f"{hollow_sections}/{total_sections} deadline section(s) appeared hollow; "
            f"page may still contain some real deadline info."
        )

    return {
        "is_hollow": is_hollow,
        "redirect_urls": list(dict.fromkeys(all_redirect_urls)),  # deduplicated, order-preserved
        "reason": reason,
    }

# Closure phrases that UNAMBIGUOUSLY indicate applications are closed.
# If any of these are found, the snippet is treated as a closure notice.
STRONG_CLOSURE_PHRASES = [
    "is now closed",
    "application is closed",
    "applications are closed",
    "applications closed",
    "currently closed",
    "not accepting applications",
    "no longer accepting",
    "reopen in",
    "will reopen",
    "next available application cycle",
    "next application cycle",
    "applications open in",
    "applications will open",
]

# Weak closure phrases — common in legitimate deadline pages too (e.g. "check back
# for information on how to apply for Fall 2027" next to a past deadline). These
# are ONLY treated as closure signals if combined with a STRONG phrase.
WEAK_CLOSURE_PHRASES = [
    "check back",
]

# Legacy alias used by existing code
CLOSURE_PHRASES = STRONG_CLOSURE_PHRASES + WEAK_CLOSURE_PHRASES

CS_TERMS = [
    "computer science",
    "computing",
    " cs ",
    " cse ",
    "comp sci",
]

# If a page produces more than this many snippets, it's likely a multi-program
# portal page. In that case, apply a stricter CS-relevance filter.
MULTI_PROGRAM_THRESHOLD = 10

def extract_deadline_snippets(text: str, window: int = 300) -> tuple[int, list[str]]:
    """
    Finds every date pattern that appears within `window` characters of a
    deadline-related term in the plain text. Returns both the count and the
    actual text snippets so they can be passed directly to the LLM instead
    of the full page text.

    Filters out snippets that contain closure phrases (e.g. "application is now
    closed", "will reopen in September") since these refer to when the portal
    reopens, not actual application deadlines.

    If the number of snippets exceeds MULTI_PROGRAM_THRESHOLD, the page is
    assumed to be a multi-program portal (e.g. gradapp.gatech.edu) and a
    stricter filter is applied requiring each snippet to mention a CS-related
    term. This prevents the LLM from being flooded with deadlines for
    unrelated programs.
    """
    lower = text.lower()
    snippets = []
    # Track (start, end) of each kept snippet. A new match is a duplicate if
    # its window overlaps significantly with an existing one.
    kept_spans = []
    filtered_closures = 0

    def _is_duplicate(new_start: int, new_end: int) -> bool:
        """A new window is a duplicate if it overlaps >50% with any kept window."""
        new_len = new_end - new_start
        for s, e in kept_spans:
            overlap = max(0, min(new_end, e) - max(new_start, s))
            if overlap > new_len * 0.5 or overlap > (e - s) * 0.5:
                return True
        return False

    for pattern in DATE_PATTERNS:
        for date_match in pattern.finditer(text):
            start = max(0, date_match.start() - window)
            end = min(len(text), date_match.end() + window)
            snippet_lower = lower[start:end]
            snippet_text = text[start:end]

            if any(term in snippet_lower for term in DEADLINE_TERMS):
                # Deduplicate overlapping windows by checking content overlap
                if _is_duplicate(start, end):
                    continue

                # Filter out snippets where STRONG closure language dominates. We only drop
                # the snippet if BOTH conditions are true:
                #   1. The snippet contains a STRONG closure phrase (e.g. "applications
                #      are closed", "no longer accepting", "will reopen").
                #      Weak phrases like "check back" alone do NOT trigger this filter,
                #      because they commonly appear in legit deadline pages that say
                #      "The deadline was X. Check back for next year's info."
                #   2. The snippet contains very few dates (suggesting the closure
                #      notice is the main content, not a side-note next to real deadlines)
                # Snippets that contain closure language alongside multiple dates are
                # most likely tables where one row/cell is "closed" but others still
                # have valid deadlines — we want to keep those.
                if any(phrase in snippet_lower for phrase in STRONG_CLOSURE_PHRASES):
                    date_count_in_snippet = sum(
                        len(list(p.finditer(snippet_text))) for p in DATE_PATTERNS
                    )
                    if date_count_in_snippet < 2:
                        filtered_closures += 1
                        continue

                snippets.append(snippet_text.strip())
                kept_spans.append((start, end))

    if filtered_closures > 0:
        print(f"  [CLOSURE FILTER] Dropped {filtered_closures} snippet(s) matching closure/reopen phrases")

    # Multi-program portal filtering: if too many snippets, keep only CS-relevant ones
    if len(snippets) > MULTI_PROGRAM_THRESHOLD:
        cs_filtered = []
        for snippet in snippets:
            snippet_lower = snippet.lower()
            if any(term in snippet_lower for term in CS_TERMS):
                cs_filtered.append(snippet)

        print(f"  [MULTI-PROGRAM FILTER] {len(snippets)} snippets exceeds threshold ({MULTI_PROGRAM_THRESHOLD})")
        print(f"    Filtered down to {len(cs_filtered)} CS-relevant snippet(s)")

        # Only use CS-filtered results if we actually found CS snippets
        # Otherwise fall back to all snippets so the page isn't silently discarded
        if cs_filtered:
            snippets = cs_filtered
        else:
            print(f"    No CS-relevant snippets found, keeping all {len(snippets)}")

    return len(snippets), snippets

def _relaxed_cooccurrence_count(text: str, window: int = 800) -> int:
    """
    Count date + deadline-term co-occurrences with a RELAXED window (800 chars
    by default vs the strict 300-char window used for snippet extraction).

    This is used as a SECONDARY signal to catch pages like Princeton where the
    sentence structure puts the date and the word "deadline" in a legitimate
    deadline context but slightly further apart than the strict window allows,
    or where the strict-window version would be filtered out by heuristics.
    """
    lower = text.lower()
    count = 0
    for pattern in DATE_PATTERNS:
        for m in pattern.finditer(text):
            start = max(0, m.start() - window)
            end = min(len(text), m.end() + window)
            snippet_lower = lower[start:end]
            if any(term in snippet_lower for term in DEADLINE_TERMS):
                count += 1
    return count


def score_page_deadline_content(html: str, text: str, base_url: str, config: dict, min_valid_year: int = MIN_VALID_YEAR) -> dict:
    """
    Scores a page on how likely it contains deadline information for the given
    program. Replaces the binary found/not-found logic with a numeric score.

    Score tiers:
      - 300+    → HIGH confidence (clear deadline page, crawler stops here)
      - 150-299 → MEDIUM confidence (looks like a real deadline page, worth using)
      - 50-149  → LOW confidence (some signal, use as fallback if nothing better)
      - 1-49    → MINIMAL (barely anything, keep as last resort)
      - 0       → hollow/empty (skip)

    Returns dict with score, all supporting signals, and snippets.
    """
    program_pattern = config["program_pattern"]

    # --- Heading-based signals ---
    headings = extract_heading_info(html)
    matched_headings = find_deadline_headings(headings, config)
    has_deadline_heading = len(matched_headings) > 0

    # --- Supporting signals ---
    has_program_term = bool(program_pattern.search(text))
    has_recent_year_flag = has_recent_year(text, min_valid_year)

    # --- Build scanning text: prefer heading-localized content, fall back to full page ---
    if has_deadline_heading:
        heading_sections = []
        for heading in matched_headings:
            section_text, _ = get_sibling_content_after_heading(html, heading, char_limit=2000)
            if section_text:
                heading_sections.append(f"{heading['text']}\n{section_text}")

        if heading_sections:
            scan_text = "\n\n".join(heading_sections)
            scan_source = f"deadline heading section(s): {len(heading_sections)} heading(s), {len(scan_text)} chars"
        else:
            scan_text = text
            scan_source = "full page (headings matched but produced empty sections)"
    else:
        scan_text = text
        scan_source = "full page (no deadline headings found)"

    print(f"  [SNIPPET SOURCE] {scan_source}")

    # --- Strict co-occurrence (date within 300 chars of deadline term) ---
    cooccurrence_count, deadline_snippets = extract_deadline_snippets(scan_text)

    # Fallback: if we scanned a deadline heading section but found zero co-occurrences,
    # retry against full page text.
    if cooccurrence_count == 0 and has_deadline_heading and scan_text != text:
        print(f"  [FALLBACK] Heading-localized scan found 0 co-occurrences, retrying against full page text")
        scan_text = text
        scan_source = "full page (fallback after heading scan found nothing)"
        cooccurrence_count, deadline_snippets = extract_deadline_snippets(scan_text)

    # --- Relaxed co-occurrence (800-char window on FULL page text) ---
    # This is a secondary signal. Catches pages where:
    #   - Date and "deadline" are in the same sentence but slightly spread apart
    #   - The strict 300-char snippet got filtered by closure/dedup heuristics
    #     but the underlying signal is real
    relaxed_count = _relaxed_cooccurrence_count(text, window=800)

    # --- Date presence signal (any date on the page at all) ---
    date_matches = 0
    for pattern in DATE_PATTERNS:
        date_matches += len(list(pattern.finditer(text)))

    # --- Deadline-term presence signal (any deadline-related word on the page) ---
    lower = text.lower()
    deadline_term_count = sum(
        lower.count(term) for term in DEADLINE_TERMS
    )

    print(f"  [DEADLINE CHECK] strict_cooccurrence={cooccurrence_count}, "
          f"relaxed_cooccurrence={relaxed_count}, "
          f"dates_on_page={date_matches}, "
          f"deadline_terms_on_page={deadline_term_count}, "
          f"has_program_term={has_program_term}, "
          f"has_recent_year={has_recent_year_flag}, "
          f"has_deadline_heading={has_deadline_heading}")

    # --- SCORING ---
    score = 0
    reasons = []

    # Strict co-occurrences are the strongest signal (100 per, capped)
    strict_contrib = min(cooccurrence_count, 5) * 100
    if strict_contrib > 0:
        score += strict_contrib
        reasons.append(f"strict_cooccurrence x{cooccurrence_count} (+{strict_contrib})")

    # Relaxed co-occurrences beyond what strict caught (50 per "extra")
    extra_relaxed = max(0, relaxed_count - cooccurrence_count)
    relaxed_contrib = min(extra_relaxed, 5) * 50
    if relaxed_contrib > 0:
        score += relaxed_contrib
        reasons.append(f"extra_relaxed_cooccurrence x{extra_relaxed} (+{relaxed_contrib})")

    # Supporting signals
    if has_deadline_heading:
        score += 50
        reasons.append("deadline_heading (+50)")
    if has_program_term:
        score += 30
        reasons.append("program_term (+30)")
    if has_recent_year_flag:
        score += 20
        reasons.append("recent_year (+20)")

    # "Page has dates AND mentions deadline" — baseline medium-low signal.
    # This catches pages like Princeton where date/deadline are in same sentence
    # but the primary co-occurrence got filtered. Only award this bonus if strict
    # co-occurrence is 0 (otherwise double-counting).
    if cooccurrence_count == 0 and date_matches > 0 and deadline_term_count > 0:
        score += 40
        reasons.append(f"date+deadline_word_on_page (+40)")

    # --- Hollow detection (only if no direct co-occurrence signal) ---
    hollow_info = {"is_hollow": False, "redirect_urls": [], "reason": ""}
    if has_deadline_heading and cooccurrence_count == 0:
        hollow_info = detect_hollow_deadline_section(html, base_url, matched_headings)
        if hollow_info["is_hollow"]:
            # Hollow pages get zeroed regardless of other signals
            score = 0
            reasons.append("HOLLOW (score=0)")

    # Derive a confidence label from the score
    if score >= 300:
        confidence = "high"
    elif score >= 150:
        confidence = "medium"
    elif score >= 50:
        confidence = "low"
    elif score > 0:
        confidence = "minimal"
    else:
        confidence = "none"

    print(f"  [SCORE] total={score}, confidence={confidence}")
    print(f"    reasons: {', '.join(reasons) if reasons else '(no signals)'}")

    # --- If strict co-occurrences found zero snippets but we still have a positive
    # score (i.e. date+deadline_word signal fired), build a fallback snippet by
    # extracting the area around each date on the page. This gives the LLM something
    # to chew on for Princeton-style pages.
    if not deadline_snippets and score > 0 and date_matches > 0:
        deadline_snippets = _build_fallback_snippets(text, window=400)
        if deadline_snippets:
            print(f"  [FALLBACK SNIPPETS] Built {len(deadline_snippets)} snippet(s) "
                  f"around date mentions (no strict co-occurrence found)")

    return {
        "score": score,
        "confidence": confidence,
        "reasons": reasons,
        "cooccurrence_count": cooccurrence_count,
        "relaxed_count": relaxed_count,
        "deadline_snippets": deadline_snippets,
        "has_deadline_heading": has_deadline_heading,
        "has_program_term": has_program_term,
        "has_recent_year": has_recent_year_flag,
        "matched_headings": matched_headings[:10],
        "is_hollow": hollow_info["is_hollow"],
        "hollow_redirect_urls": hollow_info["redirect_urls"],
        "hollow_reason": hollow_info["reason"],
    }


def _build_fallback_snippets(text: str, window: int = 400) -> list[str]:
    """
    Build snippets by extracting windows around each date mention. Used when
    the strict co-occurrence check found nothing but the page still scored
    positive (meaning there's likely a date+deadline-word pattern that didn't
    quite fit the strict filter).

    Deduplicates overlapping windows.
    """
    snippets = []
    kept_spans = []

    def _is_duplicate(new_start: int, new_end: int) -> bool:
        new_len = new_end - new_start
        for s, e in kept_spans:
            overlap = max(0, min(new_end, e) - max(new_start, s))
            if overlap > new_len * 0.5 or overlap > (e - s) * 0.5:
                return True
        return False

    for pattern in DATE_PATTERNS:
        for m in pattern.finditer(text):
            start = max(0, m.start() - window)
            end = min(len(text), m.end() + window)
            if _is_duplicate(start, end):
                continue
            snippets.append(text[start:end].strip())
            kept_spans.append((start, end))

    return snippets

# ============================================================
# HELPER PRINTS
# ============================================================

def print_ranked_links(ranked_links: list[dict], program_name: str):
    print("=" * 90)
    print(f"Top {min(TOP_K, len(ranked_links))} ranked candidate links for {program_name}")
    print("=" * 90)
    print()

    for idx, item in enumerate(ranked_links[:TOP_K], start=1):
        print(f"RANK #{idx}")
        print(f"SCORE: {item['score']}")
        print(f"ORIG#: {item['original_index']}")
        print("TEXT :", item["text"])
        print("URL  :", item["url"])
        print("WHY  :", ", ".join(item["matched_labels"]) if item["matched_labels"] else "None")
        print()

def print_queue(queue: deque):
    print("----------------------------------------")
    print("Updated URLs to follow:")
    print("----------------------------------------")
    for url in queue:
        print(url)

# ============================================================
# PROGRAM-SPECIFIC CRAWLER
# ============================================================

def crawl_for_program(university: str, base_url: str, config: dict) -> dict:
    """
    Crawl starting from base_url looking for a deadline page for the given program.

    New behavior vs SearchUpdatedBulk:
      - Every visited page gets a score from score_page_deadline_content
      - Early-exit on HIGH confidence (score >= HIGH_CONFIDENCE_THRESHOLD)
      - At end of crawl, if no HIGH page found, pick the best MEDIUM/LOW page
        that was visited and use it. Only return empty if NO page had any
        positive signal at all.
    """
    HIGH_CONFIDENCE_THRESHOLD = 300  # score >= 300 → stop crawling, use this page
    MINIMUM_USABLE_SCORE = 50        # anything below this is not worth running LLM on

    print("\n" + "=" * 100)
    print(f"STARTING {config['name']} CRAWL")
    print("=" * 100)

    scrape_url(base_url)

    with open(HTML_FILE, "r", encoding="utf-8") as f:
        html = f.read()

    ranked_links = extract_ranked_links(html, base_url, config)
    print_ranked_links(ranked_links, config["name"])

    best_urls = [item["url"] for item in ranked_links[:TOP_K]]

    print("=" * 90)
    print(f"Top URLs to follow for {config['name']}:")
    print("=" * 90)
    for url in best_urls:
        print(url)

    url_queue = deque(best_urls)
    checked_urls = set()
    queued_urls = set(best_urls)

    # Track all pages we score so we can pick the best one at the end.
    # Each entry: {"url": str, "score": int, "deadline_info": dict}
    scored_pages = []

    while url_queue:
        url = url_queue.popleft()
        queued_urls.discard(url)

        if url in checked_urls:
            continue

        print(f"\n\n=== Crawling {config['name']} page: {url} ===")
        scrape_url(url)
        checked_urls.add(url)

        with open(HTML_FILE, "r", encoding="utf-8") as f:
            page_html = f.read()

        with open(TEXT_FILE, "r", encoding="utf-8") as f:
            page_text = f.read()

        deadline_info = score_page_deadline_content(page_html, page_text, url, config, MIN_VALID_YEAR)

        # Handle hollow pages: deadline heading found but content just redirects elsewhere
        if deadline_info["is_hollow"]:
            print(f"  [HOLLOW PAGE] Deadline section found but contains no dates.")
            print(f"  Reason: {deadline_info['hollow_reason']}")
            redirect_urls = deadline_info["hollow_redirect_urls"]

            if redirect_urls:
                print(f"  Queueing {len(redirect_urls)} redirect URL(s) from hollow section:")
                for r_url in redirect_urls:
                    print(f"    -> {r_url}")
                    if r_url not in checked_urls and r_url not in queued_urls:
                        url_queue.appendleft(r_url)  # prioritize — insert at front
                        queued_urls.add(r_url)
            else:
                print("  No redirect URLs found in hollow section. Continuing normal crawl.")

            print_queue(url_queue)
            continue

        # Track this page in the scored list (even score=0 pages, for debugging)
        scored_pages.append({
            "url": url,
            "score": deadline_info["score"],
            "deadline_info": deadline_info,
        })

        # Early exit: this page is clearly a deadline page, use it immediately
        if deadline_info["score"] >= HIGH_CONFIDENCE_THRESHOLD:
            print(f"{config['name']} HIGH-confidence deadline page found (score={deadline_info['score']}).")

            return {
                "program": config["name"],
                "found": True,
                "url": url,
                "deadline_info": deadline_info,
                "reason": "high_confidence_early_exit",
            }

        # Not high confidence — keep crawling but remember this page's score
        print(f"  [NOT HIGH CONFIDENCE] Keeping page as candidate (score={deadline_info['score']}). Continuing crawl.")

        with open(HTML_FILE, "r", encoding="utf-8") as f:
            html = f.read()

        ranked_links = extract_ranked_links(html, url, config)
        additional_urls = [item["url"] for item in ranked_links[:TOP_K]]

        for idx, item in enumerate(ranked_links[:TOP_K], start=1):
            print(f"RANK #{idx}")
            print(f"SCORE: {item['score']}")
            print(f"ORIG#: {item['original_index']}")
            print("TEXT :", item["text"])
            print("URL  :", item["url"])
            print("WHY  :", ", ".join(item["matched_labels"]) if item["matched_labels"] else "None")
            print()

        print("----------------------------------------")
        print(f"Additional candidate URLs found on this {config['name']} page:")
        print("----------------------------------------")
        for found_url in additional_urls:
            print(found_url)

        for next_url in additional_urls:
            if next_url not in checked_urls and next_url not in queued_urls:
                url_queue.append(next_url)
                queued_urls.add(next_url)

        print()
        print_queue(url_queue)

    # --- End of crawl: pick the best-scored page if we have one ---
    print("\n" + "=" * 90)
    print(f"CRAWL COMPLETE for {config['name']}. All visited pages ranked by score:")
    print("=" * 90)
    scored_pages.sort(key=lambda p: p["score"], reverse=True)
    for i, p in enumerate(scored_pages, start=1):
        print(f"  #{i}: score={p['score']:>4} confidence={p['deadline_info']['confidence']:<8} {p['url']}")

    if scored_pages and scored_pages[0]["score"] >= MINIMUM_USABLE_SCORE:
        best = scored_pages[0]
        print(f"\n  [FALLBACK SELECTION] No HIGH-confidence page found. "
              f"Using best candidate (score={best['score']}, confidence={best['deadline_info']['confidence']}): {best['url']}")

        return {
            "program": config["name"],
            "found": True,
            "url": best["url"],
            "deadline_info": best["deadline_info"],
            "reason": "fallback_best_score",
        }

    print(f"\n  [NO USABLE PAGE] No visited page scored above {MINIMUM_USABLE_SCORE}. "
          f"Returning empty result.")
    return {
        "program": config["name"],
        "found": False,
        "url": None,
        "deadline_info": None,
        "reason": "no_page_found",
    }

# ============================================================
# PUBLIC API — importable function for use in other scripts
# ============================================================

# Degree-type input normalization. Accepts loose user input like
# "ms", "M.S.", "Masters", "Master's", "master of science", etc. for MS;
# "phd", "Ph.D.", "doctorate", "doctoral", "DPhil", etc. for PhD.
_MS_ALIASES = {
    "ms", "m s", "master", "masters", "mastersdegree", "masterofscience",
    "mastersofscience", "msdegree", "mscs", "msincs", "mscomputerscience",
    "msincomputerscience", "msc",
}
_PHD_ALIASES = {
    "phd", "ph d", "doctorate", "doctoral", "doctor", "doctorofphilosophy",
    "phdincs", "phdcomputerscience", "phdincomputerscience", "dphil",
}


def _normalize_degree(raw: str) -> str:
    """Normalize a user-provided degree string to 'MS' or 'PhD'.

    Raises ValueError if the input cannot be recognized.
    """
    if not raw or not isinstance(raw, str):
        raise ValueError(f"degree must be a non-empty string, got {raw!r}")

    # Lowercase, strip all non-alphanumeric (handles 'M.S.', "Master's", 'Ph.D.', etc.)
    cleaned = re.sub(r"[^a-z0-9 ]+", "", raw.lower()).strip()
    cleaned = re.sub(r"\s+", " ", cleaned)
    compact = cleaned.replace(" ", "")

    if cleaned in _MS_ALIASES or compact in _MS_ALIASES:
        return "MS"
    if cleaned in _PHD_ALIASES or compact in _PHD_ALIASES:
        return "PhD"

    raise ValueError(
        f"Could not recognize degree {raw!r}. "
        f"Accepted: MS/Masters/Master's/M.S./etc. or PhD/Ph.D./Doctorate/Doctoral/etc."
    )


def find_deadline_url(university: str, degree: str) -> dict:
    """Find the best-scoring deadline page URL for a given university + degree.

    Parameters
    ----------
    university : str
        University name (e.g. "Princeton University"). Used with SerpAPI to
        find the CS department root URL.
    degree : str
        Loosely-formatted degree type. Accepted forms include:
          MS / Masters / Master's / M.S. / Master of Science / MSc / ...
          PhD / Ph.D. / Doctorate / Doctoral / Doctor of Philosophy / DPhil / ...
        Raises ValueError if the input can't be normalized.

    Returns
    -------
    dict
        {
            "found": bool,         # True if any page scored >= minimum threshold
            "url": str | None,     # best-scoring page URL (or None if nothing found)
            "score": int,          # score of the winning page
            "confidence": str,     # 'high' | 'medium' | 'low' | 'minimal' | 'none'
            "university": str,
            "degree": str,         # canonical 'MS' or 'PhD'
            "reason": str,         # how/why this page was picked (or why nothing was)
            "base_url": str | None,
        }
    """
    if not university or not isinstance(university, str):
        raise ValueError(f"university must be a non-empty string, got {university!r}")
    university = university.strip()

    degree_canonical = _normalize_degree(degree)
    config = MS_CONFIG if degree_canonical == "MS" else PHD_CONFIG

    base_url = get_top_link(university)
    if base_url is None:
        return {
            "found": False,
            "url": None,
            "score": 0,
            "confidence": "none",
            "university": university,
            "degree": degree_canonical,
            "reason": "could_not_find_university_root",
            "base_url": None,
        }

    result = crawl_for_program(university, base_url, config)

    if result["found"] and result["deadline_info"] is not None:
        return {
            "found": True,
            "url": result["url"],
            "score": result["deadline_info"]["score"],
            "confidence": result["deadline_info"]["confidence"],
            "university": university,
            "degree": degree_canonical,
            "reason": result["reason"],
            "base_url": base_url,
        }

    return {
        "found": False,
        "url": None,
        "score": 0,
        "confidence": "none",
        "university": university,
        "degree": degree_canonical,
        "reason": result.get("reason", "no_page_found"),
        "base_url": base_url,
    }


# ============================================================
# MAIN (CLI entry point for quick single-university testing)
# ============================================================

def main():
    """Simple CLI: prompts for a university and degree, runs find_deadline_url,
    prints the result. Use this for debugging; for bulk processing, import
    find_deadline_url from another script."""
    print("=" * 60)
    print("SearchScored — single-university URL finder")
    print("=" * 60)
    university = input("\nUniversity name: ").strip()
    degree = input("Degree (MS / PhD / Masters / Doctorate / etc.): ").strip()

    try:
        result = find_deadline_url(university, degree)
    except ValueError as e:
        print(f"\nERROR: {e}")
        return

    print("\n" + "=" * 60)
    print("RESULT")
    print("=" * 60)
    for k, v in result.items():
        print(f"  {k}: {v}")


if __name__ == "__main__":
    main()