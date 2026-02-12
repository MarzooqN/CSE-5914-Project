# Runbook: Adding and Improving Tools for the Grad-School Assistant

This runbook is a step-by-step, all-in-one guide for adding new tools (or implementing stubs like deadlines) so the model can answer a wider range of questions. It explains where tools live in the code, how they are registered, how Elasticsearch is used, and exactly what to add or change. It is written so that a human or an AI can follow it to implement a new tool or a new index-backed feature.

---

## Table of contents

1. [Overview: How tools work end-to-end](#1-overview-how-tools-work-end-to-end)
2. [Exact code locations (map of the codebase)](#2-exact-code-locations-map-of-the-codebase)
3. [Tool contract: What a tool function must look like](#3-tool-contract-what-a-tool-function-must-look-like)
4. [Elasticsearch integration: Config, client, and helpers](#4-elasticsearch-integration-config-client-and-helpers)
5. [Adding a new tool that uses an existing index](#5-adding-a-new-tool-that-uses-an-existing-index)
6. [Adding a new tool that needs a new Elasticsearch index](#6-adding-a-new-tool-that-needs-a-new-elasticsearch-index)
7. [Implementing an existing stub (e.g. deadlines)](#7-implementing-an-existing-stub-eg-deadlines)
8. [Checklist for any new or updated tool](#8-checklist-for-any-new-or-updated-tool)

---

## 1. Overview: How tools work end-to-end

- The **model** (e.g. gpt-4o-mini) receives a list of **tool specs** (name, description, parameters) with each chat request when "native" function calling is enabled.
- When the model decides to call a tool, it returns a **tool call** (function name + arguments).
- The **backend** looks up the tool by name, runs the corresponding **Python async function** with those arguments, and returns the **result string** (e.g. JSON) back to the model.
- The model then uses that result to produce the final answer to the user.

So to "add a tool" you must: (1) implement an async function that returns a string, (2) register it so it is included in the list of builtin tools sent to the model, and (3) if the tool needs data, wire it to a data source (e.g. Elasticsearch). Optionally you add a new index and ingestion for that data.

---

## 2. Exact code locations (map of the codebase)

Use this as a map. All paths are relative to the **project root** (the directory that contains `open-webui/` and `scripts/`).

| What | File path | What it does |
|------|-----------|--------------|
| **Tool implementations** | `open-webui/backend/open_webui/tools/builtin.py` | All builtin tools are async functions here. Grad-school tools: `list_faculty_by_area_and_school`, `list_top_programs_by_area`, `get_program_deadlines`, `filter_programs_by_deadline_and_degree`. Add new tools in the same file (same section or a new section). |
| **Tool registration** | `open-webui/backend/open_webui/utils/tools.py` | `get_builtin_tools()` builds the dict of tools sent to the model. It (1) imports tool functions from `open_webui.tools.builtin`, (2) adds them to a list (e.g. under `ENABLE_GRAD_SCHOOL_TOOLS`), (3) for each function builds a **spec** from the function’s signature and docstring and stores `{ "callable", "spec", "type": "builtin" }`. **You must add the new function to the imports and to the `builtin_functions.extend([...])` list for grad-school tools.** |
| **Spec generation** | `open-webui/backend/open_webui/utils/tools.py` | `convert_function_to_pydantic_model(func)` turns the function into a Pydantic model using **type hints** and **docstring** (`parse_description` for tool description, `parse_docstring` for `:param x: ...` and `:return: ...`). That model is then converted to an OpenAI function spec. So the **docstring and parameter names/types** are what the model sees. |
| **Where tools are attached to chat** | `open-webui/backend/open_webui/utils/middleware.py` | In `process_chat_payload()`, when `function_calling == "native"` and the model has `builtin_tools` capability, the code calls `get_builtin_tools(...)` and merges the result into `tools_dict`, then sets `form_data["tools"]` to the list of specs. So once a tool is in `get_builtin_tools()`, it is automatically available for native function calling. |
| **Where the tool is executed** | `open-webui/backend/open_webui/utils/middleware.py` | In `response_handler()`, when the model returns a tool call, the code resolves `tool = metadata["tools"][tool_function_name]`, then calls `tool_function(**tool_function_params)` (the `callable` from `get_builtin_tools`). Your function runs there and its return value is sent back to the model. |
| **ES config** | `open-webui/backend/open_webui/config.py` | `ELASTICSEARCH_URL`, `ELASTICSEARCH_API_KEY`, `ELASTICSEARCH_USERNAME`, `ELASTICSEARCH_PASSWORD`, `GRAD_SCHOOL_ES_INDEX`, `ENABLE_GRAD_SCHOOL_TOOLS`. Add new index names here (e.g. `GRAD_SCHOOL_DEADLINES_ES_INDEX`) if you introduce a new index. |
| **ES helpers (queries)** | `open-webui/backend/open_webui/utils/grad_school.py` | Contains `_get_es_client()`, `normalize_area()`, `search_faculty_by_school_and_areas()`, `rank_programs_by_area()`, and constants like `AREA_ALIASES`, `KNOWN_PARENT_AREAS`. Add new query helpers here (or in a new module) that use the ES client and the appropriate index. |
| **Ingestion (index creation + bulk index)** | `scripts/ingestion.py` | Downloads CSRankings data, aggregates it, and bulk-indexes into Elasticsearch. For a **new index** (e.g. deadlines), you either extend this script with a new mapping and ingest path or add a separate script that creates an index and indexes data. Index name and mapping must match what the backend helpers expect. |

---

## 3. Tool contract: What a tool function must look like

Every builtin tool used by the grad-school flow is an **async function** with this shape:

- **Signature:** Parameters the model should fill (e.g. `area: str`, `school: str`, `count: int = 20`) plus **reserved** parameters that the framework injects: `__request__: Request = None`, `__user__: dict = None`. Do not document `__request__` / `__user__` in the docstring (they are stripped from the spec).
- **Docstring:** The first paragraph (before any `:param`) becomes the **tool description** the model sees. Use **`:param name:`** for each user-facing parameter and **`:return:`** for the return description. The model uses these to choose and fill arguments.
- **Return type:** Return a **string**, usually `json.dumps(...)`. The backend sends this string to the model as the tool result. For errors, return a JSON object with an `"error"` key (e.g. `json.dumps({"error": "..."})`).
- **Logging:** Optional but recommended: `log.info("tool_name called: ...", ...)` at the start so you can see when the tool is invoked in server logs.

**Example (from `builtin.py`):**

```python
async def list_faculty_by_area_and_school(
    area: str,
    school: str,
    count: int = 20,
    __request__: Request = None,
    __user__: dict = None,
) -> str:
    """
    Find faculty at a specific school who work in a given research area.
    Use this to answer questions like "Which faculty at School Z do NLP/security/systems?"

    :param area: Research area (e.g. NLP, security, machine learning, systems, vision)
    :param school: School or department name (as in the database, e.g. "Carnegie Mellon University")
    :param count: Maximum number of faculty to return (default: 20)
    :return: JSON list of faculty with name, dept, homepage, scholar_url, top_areas, top_venues
    """
    log.info("grad_school tool called: list_faculty_by_area_and_school(area=%r, school=%r, count=%s)", area, school, count)
    if __request__ is None:
        return json.dumps({"error": "Request context not available"})
    # ... call grad_school helpers, return json.dumps(results, ensure_ascii=False)
```

Parameters whose names start with `__` are not included in the OpenAI function spec (see `parse_docstring` in `utils/tools.py`).

---

## 4. Elasticsearch integration: Config, client, and helpers

### 4.1 Config (`open-webui/backend/open_webui/config.py`)

- **Connection:** `ELASTICSEARCH_URL` (e.g. `http://localhost:9200`), `ELASTICSEARCH_API_KEY` or `ELASTICSEARCH_USERNAME`/`ELASTICSEARCH_PASSWORD`.
- **Grad-school index:** `GRAD_SCHOOL_ES_INDEX` (default `csrankings_authors`). For a second index (e.g. deadlines), add a new variable, e.g. `GRAD_SCHOOL_DEADLINES_ES_INDEX = os.environ.get("GRAD_SCHOOL_DEADLINES_ES_INDEX", "grad_program_deadlines")`.

### 4.2 Client and index in helpers (`open-webui/backend/open_webui/utils/grad_school.py`)

- **Client:** `_get_es_client()` builds an `Elasticsearch` instance from config (URL, API key or basic auth). Use this for all ES access so credentials stay in one place.
- **Index:** Helpers read the index name from config, e.g. `index = GRAD_SCHOOL_ES_INDEX`. For a new index, import the new config constant and use it in new helper functions.
- **Query pattern:** Existing helpers use `es.search(index=index, body=query)` with a `query` dict (e.g. `bool` with `filter`/`must`/`should`). Follow the same pattern: build a dict, call `es.search`, parse `resp["hits"]["hits"]` or aggregations.

### 4.3 Adding a new index

- **Config:** Add something like `GRAD_SCHOOL_DEADLINES_ES_INDEX` in `config.py` and, if needed, document it in setup docs.
- **Ingestion:** Either in `scripts/ingestion.py` or a new script: define a mapping (`make_index_mapping`-style), create the index (`es.indices.create`), and bulk-index documents. The mapping must match what your backend helpers query (field names, types, keyword vs text).
- **Backend:** In `grad_school.py` (or a new module), add functions that call `_get_es_client()`, use the new index name, and return structured data. The tool in `builtin.py` then calls these helpers and returns `json.dumps(...)`.

---

## 5. Adding a new tool that uses an existing index

Example: a new tool that queries the existing `csrankings_authors` index in a different way.

1. **Implement the helper** (if needed) in `open-webui/backend/open_webui/utils/grad_school.py`  
   - Add a function that takes the needed arguments, builds an ES query, calls `_get_es_client()` and `es.search(index=GRAD_SCHOOL_ES_INDEX, body=...)`, and returns a list of dicts or a structure you can JSON-serialize.

2. **Implement the tool** in `open-webui/backend/open_webui/tools/builtin.py`  
   - Add an `async def my_new_tool(...)` with the tool contract (docstring with `:param`/`:return`, `__request__`/`__user__`, return `json.dumps(...)`).  
   - Inside, call your new helper (or existing ones) and handle errors.

3. **Register the tool** in `open-webui/backend/open_webui/utils/tools.py`  
   - In the **imports** from `open_webui.tools.builtin`, add `my_new_tool`.  
   - In `get_builtin_tools()`, inside the `if getattr(..., "ENABLE_GRAD_SCHOOL_TOOLS", False):` block, add `my_new_tool` to the `builtin_functions.extend([...])` list.

4. **Restart the backend** and test in the UI (e.g. ask a question that should trigger the new tool).

No new config or ingestion is required if you only use the existing index.

---

## 6. Adding a new tool that needs a new Elasticsearch index

Example: a "program deadlines" tool that reads from an index `grad_program_deadlines`.

### Step 1: Define the index and ingestion

- **Schema:** Decide the document shape (e.g. `school`, `program_name`, `degree_level`, `deadline_date`, `source_url`). Design the mapping (keyword vs date vs text) to match how you will query (filters, sorts, aggregations).
- **Ingestion:**  
  - **Option A:** Add a new section (or script) that creates the index with a mapping and bulk-indexes from your data source (CSV, API, etc.).  
  - **Option B:** Add a new script under `scripts/` (e.g. `ingest_deadlines.py`) that uses the same `ES_URL`/`ES_API_KEY` (or `.env`) and creates an index with a name you will use in config.
- **Run ingestion** (see [SETUP_INGESTION.md](SETUP_INGESTION.md)) so the index exists and is populated.

### Step 2: Config for the new index

- In `open-webui/backend/open_webui/config.py`, add:
  - `GRAD_SCHOOL_DEADLINES_ES_INDEX = os.environ.get("GRAD_SCHOOL_DEADLINES_ES_INDEX", "grad_program_deadlines")`  
  (or whatever name you chose).

### Step 3: ES helpers for the new index

- In `open-webui/backend/open_webui/utils/grad_school.py` (or a new module that imports config and `_get_es_client`):
  - Import the new config constant.
  - Add one or more functions that:
    - Call `_get_es_client()`.
    - Use the **new index name**.
    - Build an ES `query` (and optional `aggs`) and call `es.search(index=..., body=...)`.
    - Parse `resp["hits"]["hits"]` (and aggregations if used) and return lists/dicts suitable for the tool.

### Step 4: Tool in builtin.py

- In `open-webui/backend/open_webui/tools/builtin.py`, add an `async def` that:
  - Matches the tool contract (docstring, `__request__`/`__user__`, return `str`).
  - Calls the new helpers and returns `json.dumps(...)` (or `json.dumps({"error": "..."})` on failure).

### Step 5: Register the tool in utils/tools.py

- Add the new function to the **imports** from `open_webui.tools.builtin`.
- Add it to the **grad-school** `builtin_functions.extend([...])` list in `get_builtin_tools()`.

### Step 6: Restart and test

- Restart the backend. In the UI, ask a question that should trigger the new tool and confirm it appears in the tool list and returns the expected data.

---

## 7. Implementing an existing stub (e.g. deadlines)

The codebase already has **stub** tools that return a "not implemented" message: `get_program_deadlines` and `filter_programs_by_deadline_and_degree` in `open-webui/backend/open_webui/tools/builtin.py`. To implement them:

1. **Data and index:** Obtain or define deadline data (source, schema). Create an Elasticsearch index (new ingestion script or extension of `scripts/ingestion.py`) with a mapping that matches your queries (e.g. `deadline_date` as `date`, `degree_level` as `keyword`, `school`/`program` as keyword or text).
2. **Config:** Add `GRAD_SCHOOL_DEADLINES_ES_INDEX` (or similar) in `config.py` as in [Section 6](#6-adding-a-new-tool-that-needs-a-new-elasticsearch-index).
3. **Helpers:** In `grad_school.py` (or a dedicated module), implement e.g.:
   - `search_deadlines_by_school(school, degree_level, start_date, end_date, limit)`  
   - `filter_programs_by_deadline_and_degree(degree_level, start_date, end_date, limit)`  
   that query the new index using `_get_es_client()` and the new index name.
4. **Replace stub bodies in builtin.py:** In `get_program_deadlines` and `filter_programs_by_deadline_and_degree`, remove the `return json.dumps({"error": "..."})` stub, call the new helpers, and return `json.dumps(results, ...)` (and handle errors with an `{"error": "..."}` object).
5. **Registration:** No change needed in `utils/tools.py`—these tools are already in the grad-school `builtin_functions.extend([...])` list.
6. **Restart and test:** Restart the backend and verify with deadline-related questions.

---

## 8. Checklist for any new or updated tool

Use this to confirm nothing is missed. An AI or human can tick each item.

- [ ] **Tool function** in `open-webui/backend/open_webui/tools/builtin.py`: async, docstring with first paragraph + `:param` / `:return`, parameters include `__request__` and `__user__`, returns a single string (usually JSON).
- [ ] **Import** in `open-webui/backend/open_webui/utils/tools.py`: new tool is imported from `open_webui.tools.builtin`.
- [ ] **Registration** in `open-webui/backend/open_webui/utils/tools.py`: new tool is added to the `builtin_functions.extend([...])` list inside the `ENABLE_GRAD_SCHOOL_TOOLS` block (so it is only loaded when grad-school tools are enabled).
- [ ] **Elasticsearch (if used):**  
  - [ ] Index exists and is populated (ingestion script run).  
  - [ ] Config in `config.py` for index name (if new index).  
  - [ ] Helper(s) in `grad_school.py` (or new module) that use `_get_es_client()` and the correct index, and return data the tool can serialize.
- [ ] **Tool implementation** calls those helpers and returns `json.dumps(...)`; on failure returns `json.dumps({"error": "..."})`.
- [ ] **Optional:** `log.info("tool_name called: ...", ...)` at the start of the tool for debugging.
- [ ] **Restart backend** and test in the UI with a question that should trigger the tool.

---

## Quick reference: File paths and symbols

| Action | File | Symbol / location |
|--------|------|--------------------|
| Add or edit tool implementation | `open-webui/backend/open_webui/tools/builtin.py` | New or existing `async def` in the GRAD-SCHOOL section (or new section). |
| Register tool | `open-webui/backend/open_webui/utils/tools.py` | Import at top from `open_webui.tools.builtin`; add to `builtin_functions.extend([...])` in the `ENABLE_GRAD_SCHOOL_TOOLS` block (lines 473–482). |
| Add ES config | `open-webui/backend/open_webui/config.py` | New `GRAD_SCHOOL_*_ES_INDEX` (or similar) near `GRAD_SCHOOL_ES_INDEX`. |
| Add ES query helpers | `open-webui/backend/open_webui/utils/grad_school.py` | New functions that use `_get_es_client()` and the index name from config. |
| New index + ingestion | `scripts/ingestion.py` or new script under `scripts/` | New mapping, index creation, and bulk indexing; document in setup/runbook. |

This runbook, together with [SETUP_INGESTION.md](SETUP_INGESTION.md) and [SETUP_OPEN_WEBUI.md](SETUP_OPEN_WEBUI.md), is intended to be sufficient for a developer or an AI to add a new tool or implement the deadlines tools end-to-end.
