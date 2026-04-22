from pathlib import Path
import tempfile

import shutil
from selenium import webdriver
from selenium.webdriver.firefox.options import Options
from selenium.webdriver.firefox.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from bs4 import BeautifulSoup


def _get_firefox_driver(options: Options):
    """
    Create a Firefox webdriver. Prefers an explicit geckodriver path from PATH
    (e.g. homebrew install) to avoid relying on selenium-manager, which has
    been crashing with SIGKILL on macOS.
    """
    gecko_path = shutil.which("geckodriver")
    if gecko_path:
        service = Service(executable_path=gecko_path)
        return webdriver.Firefox(options=options, service=service)
    # Fallback to selenium-manager auto-download
    return webdriver.Firefox(options=options)


def fetch_rendered_html(url: str, wait_seconds: int = 15) -> str:
    options = Options()
    options.add_argument("--headless")

    try:
        driver = _get_firefox_driver(options)
    except Exception as e:
        print(f"Error launching Firefox for {url}: {e}")
        return "Not a valid webpage url"

    try:
        driver.get(url)

        # Better than time.sleep: wait until the page has a body element
        WebDriverWait(driver, wait_seconds).until(
            EC.presence_of_element_located((By.TAG_NAME, "body"))
        )

        return driver.page_source
    except Exception as e:
        print(f"Error fetching {url}: {e}")
        return "Not a valid webpage url"
    finally:
        try:
            driver.quit()
        except Exception:
            pass

def _normalize_cell_text(cell) -> str:
    """
    Returns clean single-line text from a cell.

    Strips elements marked aria-hidden="true" before extracting text. Many
    responsive tables include a hidden "mobile label" span inside each cell
    (e.g. "<span class='vt-table-headerTitle' aria-hidden='true'>Program</span>")
    that duplicates the column header. We don't want to surface those into
    the LLM as content — they'd produce garbage like "Program: Program M.S."
    """
    # Work on a fresh parse of the cell's HTML so we don't mutate the caller's tree
    cell_copy = BeautifulSoup(str(cell), "html.parser")
    for hidden in cell_copy.find_all(attrs={"aria-hidden": "true"}):
        hidden.decompose()
    return cell_copy.get_text(" ", strip=True)


def _expand_table_grid(table) -> list[list[dict]]:
    """
    Parses a <table> into a fully-expanded 2D grid where rowspan/colspan cells
    are duplicated into every grid position they occupy. This makes it safe to
    reason about rows and columns without dealing with HTML span attributes.

    Each cell in the grid is a dict: {"text": str, "is_th": bool}
    Empty positions (rare edge case) get {"text": "", "is_th": False}.
    """
    rows = table.find_all("tr")
    if not rows:
        return []

    # Build the grid row by row, respecting rowspan/colspan
    grid = []
    # pending_rowspans[col_index] = (cell_dict, remaining_rows_to_fill)
    pending_rowspans: dict[int, tuple[dict, int]] = {}

    for row in rows:
        row_out = []
        col_idx = 0
        cells = row.find_all(["th", "td"], recursive=False)
        # Some pages nest cells in tbody/thead; if recursive=False missed them, retry
        if not cells:
            cells = row.find_all(["th", "td"])

        cell_iter = iter(cells)

        while True:
            # Fill any pending rowspan cells first at the current column
            while col_idx in pending_rowspans:
                cell_data, remaining = pending_rowspans[col_idx]
                row_out.append(cell_data)
                if remaining - 1 <= 0:
                    del pending_rowspans[col_idx]
                else:
                    pending_rowspans[col_idx] = (cell_data, remaining - 1)
                col_idx += 1

            try:
                cell = next(cell_iter)
            except StopIteration:
                break

            text = _normalize_cell_text(cell)
            is_th = cell.name == "th"
            cell_data = {"text": text, "is_th": is_th}

            try:
                colspan = int(cell.get("colspan", 1))
            except (TypeError, ValueError):
                colspan = 1
            try:
                rowspan = int(cell.get("rowspan", 1))
            except (TypeError, ValueError):
                rowspan = 1

            for c in range(colspan):
                row_out.append(cell_data)
                if rowspan > 1:
                    pending_rowspans[col_idx] = (cell_data, rowspan - 1)
                col_idx += 1

        # Flush remaining pending rowspans at the tail (if any)
        while col_idx in pending_rowspans:
            cell_data, remaining = pending_rowspans[col_idx]
            row_out.append(cell_data)
            if remaining - 1 <= 0:
                del pending_rowspans[col_idx]
            else:
                pending_rowspans[col_idx] = (cell_data, remaining - 1)
            col_idx += 1

        grid.append(row_out)

    # Pad short rows to uniform width for safety
    max_cols = max((len(r) for r in grid), default=0)
    for r in grid:
        while len(r) < max_cols:
            r.append({"text": "", "is_th": False})

    return grid


def _row_is_header(row: list[dict]) -> bool:
    """Row is a header row if most cells are <th>."""
    if not row:
        return False
    th_count = sum(1 for c in row if c["is_th"])
    return th_count >= max(1, len(row) // 2 + 1)  # majority


def table_to_text(table):
    """
    Converts an HTML table to structured text optimized for LLM consumption.

    Strategy:
      - Expand rowspan/colspan so the table is a clean 2D grid
      - Detect header row (majority-th or first row)
      - Detect row-label column (first column mostly-th or sensibly labeled)
      - Emit each data cell on its own line:
          row_label | column_header: value
        (or just column_header: value when no row label column exists)
      - Fall back to pipe-joined format if the table doesn't have a clear
        header row (e.g. layout tables).
    """
    grid = _expand_table_grid(table)
    if not grid:
        return ""

    # Identify header row: first row with majority <th>, else first row
    header_row_idx = None
    for i, row in enumerate(grid):
        if _row_is_header(row):
            header_row_idx = i
            break

    if header_row_idx is None:
        # No obvious header - fall back to simple pipe-joined output
        lines = []
        for row in grid:
            texts = [c["text"] for c in row if c["text"]]
            if texts:
                lines.append(" | ".join(texts))
        return "\n".join(lines)

    headers = [c["text"] for c in grid[header_row_idx]]
    data_rows = grid[header_row_idx + 1:]

    if not data_rows:
        # Header only, nothing to structure - emit as-is
        return " | ".join(h for h in headers if h)

    # Decide if the first column acts as a row label.
    # Heuristic: first column's data cells are majority <th>, or first column
    # values repeat/span (suggesting they label the row).
    first_col_data = [row[0] for row in data_rows if row]
    first_col_is_label = False
    if first_col_data:
        th_ratio = sum(1 for c in first_col_data if c["is_th"]) / len(first_col_data)
        if th_ratio >= 0.5:
            first_col_is_label = True

    lines = []
    for row in data_rows:
        if not row or all(not c["text"] for c in row):
            continue

        if first_col_is_label:
            row_label = row[0]["text"]
            for col_idx in range(1, len(row)):
                value = row[col_idx]["text"]
                if not value:
                    continue
                col_header = headers[col_idx] if col_idx < len(headers) else ""
                if col_header:
                    lines.append(f"{row_label} | {col_header}: {value}")
                else:
                    lines.append(f"{row_label} | {value}")
        else:
            for col_idx, cell in enumerate(row):
                value = cell["text"]
                if not value:
                    continue
                col_header = headers[col_idx] if col_idx < len(headers) else ""
                if col_header and col_header != value:
                    lines.append(f"{col_header}: {value}")
                else:
                    lines.append(value)

    return "\n".join(lines)

def html_to_llm_text(html):
    soup = BeautifulSoup(html, "lxml")

    # Remove junk tags completely
    for tag in soup(["script", "style", "noscript", "iframe", "svg"]):
        tag.decompose()

    # Remove common junk sections
    for tag in soup.find_all(["nav", "footer", "aside"]):
        tag.decompose()

    output = []

    # Walk only meaningful tags in document order
    for tag in soup.find_all([
        "h1", "h2", "h3", "h4", "h5", "h6",
        "p",
        "ul", "ol",
        "table"
    ]):
        name = tag.name.lower()

        if name in ["h1", "h2", "h3", "h4", "h5", "h6"]:
            level = int(name[1])
            text = tag.get_text(" ", strip=True)
            if text:
                output.append(f"\n{'#' * level} {text}\n")

        elif name == "p":
            text = tag.get_text(" ", strip=True)
            if text:
                output.append(text + "\n")

        elif name == "ul":
            for li in tag.find_all("li", recursive=False):
                text = li.get_text(" ", strip=True)
                if text:
                    output.append(f"- {text}")
            output.append("")

        elif name == "ol":
            for i, li in enumerate(tag.find_all("li", recursive=False), start=1):
                text = li.get_text(" ", strip=True)
                if text:
                    output.append(f"{i}. {text}")
            output.append("")

        elif name == "table":
            table_text = table_to_text(tag)
            if table_text:
                output.append(table_text + "\n")

    # Clean repeated blank lines
    cleaned = []
    prev_blank = False

    for line in output:
        line = line.strip()
        if line == "":
            if not prev_blank:
                cleaned.append("")
            prev_blank = True
        else:
            cleaned.append(line)
            prev_blank = False

    return "\n".join(cleaned)

def scrape_url(url: str):
    rendered_html = fetch_rendered_html(url)

    debug_dir = Path(tempfile.gettempdir()) / "open_webui_deadline_scraper"
    debug_dir.mkdir(parents=True, exist_ok=True)

    rendered_html_path = debug_dir / "page_rendered.html"
    html_path = debug_dir / "page.txt"
    text_path = debug_dir / "page_text.txt"

    # 1) Save the fully rendered HTML (useful for debugging)
    with open(rendered_html_path, "w", encoding="utf-8") as f:
        f.write(rendered_html)

    #2) Save the html page
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(rendered_html)

    # 2) Save cleaned text (useful for LLM / keyword search)
    cleaned_text = html_to_llm_text(rendered_html)
    with open(text_path, "w", encoding="utf-8") as f:
        f.write(cleaned_text)

    print(f"Saved scraper debug files to: {debug_dir}")