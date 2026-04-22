# Setup: Ingestion Script

This guide walks you through setting up and running the **CSRankings → Elasticsearch ingestion script** that fills the index used by the grad-school tools (e.g. faculty and program search).

## Prerequisites

- **Python 3** (3.10+ recommended)
- **A running Elasticsearch cluster** (local or Elastic Cloud). The Open WebUI grad-school tools expect this index to exist.

---

## 1. Run a local Elasticsearch cluster

You must have Elasticsearch running before ingesting data. For **local development**, the easiest way is Elastic’s one-command setup:

**[Local development installation (quickstart)](https://www.elastic.co/docs/deploy-manage/deploy/self-managed/local-development-installation-quickstart)**

1. Install [Docker Compose](https://docs.docker.com/compose/install/) (Docker Desktop or Docker Engine).
2. In a terminal, run:
   ```bash
   curl -fsSL https://elastic.co/start-local | sh
   ```
3. When the script finishes:
   - **Elasticsearch**: <http://localhost:9200>
   - **Kibana** (optional): <http://localhost:5601>

**Important:** Write down the api key. You will use the same API key in:
- This ingestion script (`.env` in `scripts/`)
- Open WebUI backend (`.env` in `open-webui/` or `open-webui/backend/`) for the grad-school tools

Keep the API key in a safe place; do not commit it to git.

---

## 2. Create a Python virtual environment

From the **project root** (the directory that contains `scripts/` and `open-webui/`):

```bash
cd scripts
python3 -m venv venv
```

Activate the venv:

- **Linux/macOS:** `source venv/bin/activate`
- **Windows:** `.\venv\Scripts\activate`

Your prompt should show `(venv)`.

---

## 3. Install dependencies

With the venv activated, still in `scripts/`:

```bash
pip install -r requirements.txt
```

This installs `elasticsearch`, `requests`, `python-dotenv`, and their dependencies.

---

## 4. Create a `.env` file (ingestion only)

In the **`scripts/`** directory, create a file named `.env` with your Elasticsearch URL and, if your cluster uses security, your API key.


**Local or remote Elasticsearch with API key:**

```env
ES_URL=http://localhost:9200
ES_API_KEY=your_elasticsearch_api_key_here
```

**Elastic Cloud:**

```env
ES_URL=https://your-cluster.es.region.aws.cloud.es.io:443
ES_API_KEY=your_elasticsearch_api_key_here
```

- Use the **same API key** you wrote down earlier so you can reuse it in Open WebUI’s `.env` later.
- **Do not commit `.env` or your API key to git.** Add `scripts/.env` to `.gitignore` if it is not already ignored.

---

## 5. Run the ingestion script

With the venv activated and Elasticsearch running, from the **`scripts/`** directory:

**First time (create index and ingest):**

```bash
python ingestion.py --create-index --index csrankings_authors
```

- `--create-index` deletes the index if it exists and recreates it with the correct mapping.
- `--index csrankings_authors` is the default index name expected by the Open WebUI grad-school tools; you can omit it if you’re happy with that name.

**Subsequent runs (re-ingest into existing index):**

If you only want to add/update documents without recreating the index:

```bash
python ingestion.py --index csrankings_authors
```

(Omitting `--create-index` keeps the existing index and mapping.)

**Optional: dry run (no Elasticsearch needed):**

To test the script without a running cluster:

```bash
python ingestion.py --dry-run --dry-run-count 5
```

This downloads the CSRankings data and prints a few sample aggregated documents; it does not connect to Elasticsearch.

## 5.1 Run the US News rankings ingestion

The repository includes a checked-in long-format CSV for the US News top 10 schools from 2020 to 2026 at `scripts/data/usnews_top10_2020_2026_long.csv`.

With the same `scripts/` venv activated and Elasticsearch running, ingest it with:

```bash
python ingest_usnews_rankings.py --input data/usnews_top10_2020_2026_long.csv --create-index
```

This creates and populates the `usnews_rankings` index used by the US News ranking tools in Open WebUI.

---

## 6. Verify

- **Local Elasticsearch:** Open <http://localhost:9200/csrankings_authors/_count> in a browser or use curl; you should see a count of indexed documents.
- **Kibana:** If you started Kibana, use Dev Tools or Index Management to inspect the `csrankings_authors` index.
- For US News rankings, also verify the `usnews_rankings` index exists and contains documents.

Once the index is populated, you can proceed to [Setup: Open WebUI](SETUP_OPEN_WEBUI.md) to run the UI and grad-school tools.
