# Local Setup — Quick Start

This is a quick-start guide to get the full stack running locally. Each step links to the detailed setup doc.

---

## Prerequisites

- **Docker Desktop** (with Docker Compose)
- **Python 3.11+**
- **Node.js 22.10+** and **npm**
- An **OpenAI API key** (or **Ollama** installed locally)

---

## Steps

### 1. Start Elasticsearch

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

### 2. Ingest data into Elasticsearch

```bash
cd scripts
python3.11 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
```

Create `scripts/.env` with your ES credentials:
```env
ES_URL=http://localhost:9200
ES_API_KEY=your_api_key_here
```

Run both ingestion scripts:
```bash
python ingestion.py --create-index --index csrankings_authors
python ingest_deadlines.py --create-index
python ingest_usnews_rankings.py --input data/usnews_top10_2020_2026_long.csv --create-index
```

See [Setup: Ingestion Script](SETUP_INGESTION.md) for full details.

### 3. Start Open WebUI (frontend + backend)

**Frontend** (terminal 1):
```bash
cd open-webui
cp -RPp .env.example .env
# Edit .env — add OPENAI_API_KEY, ELASTICSEARCH_URL, ELASTICSEARCH_API_KEY, SERPAPI_API_KEY
npm install
npm run dev
```

**Backend** (terminal 2):
```bash
cd open-webui/backend
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt -U
sh dev.sh
```

See [Setup: Open WebUI](SETUP_OPEN_WEBUI.md) for full details.

### 4. Use the app

1. Open <http://localhost:5173>
2. Create an admin account (first-time signup)
3. Select a model (e.g. `gpt-4o-mini`)
4. Ask questions about faculty, deadlines, or resume fit

---

## Ports

| Service | Port |
|---------|------|
| Elasticsearch | 9200 |
| Kibana | 5601 |
| Open WebUI frontend | 5173 |
| Open WebUI backend | 8080 |
| Ollama (if used) | 11434 |

---

## Troubleshooting

- **ES won't start:** Check Docker is running, increase memory in Docker Desktop settings.
- **Grad-school tools not working:** Confirm ES is running, indices are populated, and `ELASTICSEARCH_URL` + `ELASTICSEARCH_API_KEY` are in the backend `.env`.
- **Frontend can't reach backend:** Make sure both are running; check CORS settings.

For more details, see the individual setup docs linked above.
