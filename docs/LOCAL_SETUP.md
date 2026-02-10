# LOCAL_SETUP — ResearchMatch Environment Setup & How to Run

This document contains the **local environment setup**, **how to run the full stack**, and **runtime troubleshooting**.

> Main project overview: **[README.md](README.md)**

---

## 1) Prerequisites (Everyone)

Each teammate should be able to run:
1) **Elasticsearch + Kibana** (Docker)
2) **Ollama** (local LLM runtime)
3) **Streamlit app**

### Required installs
- **Docker Desktop + Docker Compose**
- **Python 3.9+**
- **Ollama**
- Git

---

## 2) Environment Variables (Recommended)

Create a `.env` file at repo root (optional but recommended):

```
ES_HOST=http://localhost:9200
OLLAMA_HOST=http://localhost:11434
OLLAMA_MODEL=llama3
SNAPSHOT_VERSION=v1
DATASET_DIR=data/golden
```

Your Python app can read these via `python-dotenv`.

---

## 3) Start the Database (Elasticsearch + Kibana)

### 3.1 Run Docker
```bash
docker compose up -d
```

Check:
- Elasticsearch: `http://localhost:9200`
- Kibana: `http://localhost:5601`

### 3.2 Pinned demo-friendly compose file
> Intended for local development + demos, not production.

```yaml
version: "3.8"
services:
  es01:
    image: docker.elastic.co/elasticsearch/elasticsearch:8.11.0
    container_name: es01
    environment:
      - discovery.type=single-node
      - xpack.security.enabled=false
      - xpack.security.enrollment.enabled=false
      - xpack.security.http.ssl.enabled=false
      - xpack.security.transport.ssl.enabled=false
      - "ES_JAVA_OPTS=-Xms512m -Xmx512m"
    ports:
      - "9200:9200"
    volumes:
      - esdata01:/usr/share/elasticsearch/data

  kibana:
    image: docker.elastic.co/kibana/kibana:8.11.0
    container_name: kibana
    environment:
      - ELASTICSEARCH_HOSTS=http://es01:9200
      - xpack.security.enabled=false
    ports:
      - "5601:5601"
    depends_on:
      - es01

volumes:
  esdata01:
```

---

## 4) Python Setup (Streamlit + Scripts)

### 4.1 Create a virtual environment + install deps
```bash
python -m venv .venv
source .venv/bin/activate   # macOS/Linux
# .venv\Scripts\activate    # Windows (PowerShell)

pip install -r requirements.txt
```

**Recommended `requirements.txt`:**
```
streamlit
pandas
requests
elasticsearch
python-dotenv
```

---

## 5) Ingest the Snapshot Dataset

We support a **reset + re-ingest** workflow for stability.

### 5.1 Reset DB and ingest Golden Dataset
```bash
python scripts/reset_db.py --dataset data/golden --snapshot_version v1
```

Expected behavior:
- Deletes the three indices (universities/programs/faculty)
- Recreates index mappings
- Bulk-ingests CSV data into Elasticsearch

> If you’re working on the dataset, point to `data/working` instead.

---

## 6) Ollama (Required)

### 6.1 Start Ollama and pull model
```bash
ollama run llama3
```

Ollama runs a local API at:
- `http://localhost:11434`

---

## 7) Run the Streamlit App

```bash
streamlit run app/streamlit_app.py
```

Open:
- Streamlit UI: `http://localhost:8501`

---

## 8) How the App Should Behave (Runtime Rules)

### 8.1 Grounding rules (must not hallucinate)
- The app retrieves records from Elasticsearch.
- It packages the retrieved JSON as context.
- It calls Ollama with a prompt that says **use ONLY this context**.
- If retrieval returns 0 results:
  - the assistant must respond: **“Not in our snapshot dataset.”**

### 8.2 Prompt template location
Store prompt template in:
- `app/prompts/answer_template.txt`

Recommended output format:
- 1–2 sentence summary
- bullet list of results
- deadlines **bolded**
- include `source_url` if present

---

## 9) Troubleshooting

### Elasticsearch won’t start / is slow
- Increase ES memory:
  - `ES_JAVA_OPTS=-Xms1g -Xmx1g` (if your laptop can handle it)
- Logs:
```bash
docker compose logs -f es01
```

### Kibana says “server not ready”
- Wait 30–60 seconds after ES starts.
- Logs:
```bash
docker compose logs -f kibana
```

### Ollama not responding
- Confirm model download:
```bash
ollama run llama3
```
- Verify host/port:
  - `http://localhost:11434`

### Port conflicts
- ES uses `9200`
- Kibana uses `5601`
- Streamlit uses `8501`
- Ollama uses `11434`

---

## 10) Quick “Fresh Laptop” Checklist (For QA)
- [ ] `docker compose up -d` works
- [ ] `pip install -r requirements.txt` works
- [ ] `python scripts/reset_db.py ...` ingests without errors
- [ ] `ollama run llama3` works
- [ ] `streamlit run ...` opens UI and answers a known query

---

## References (External)
- Streamlit Python support: https://docs.streamlit.io/knowledge-base/using-streamlit/sanity-checks  
- Ollama API: https://docs.ollama.com/api/introduction  
- Elastic (Docker): https://www.elastic.co/docs/deploy-manage/deploy/self-managed/install-elasticsearch-with-docker  
- CSRankings repo + CSV files: https://github.com/emeryberger/CSrankings
