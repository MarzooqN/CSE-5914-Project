# Local Setup — Quick Start

This is a quick-start guide to get the full stack running locally. Each step links to the detailed setup doc.

---

## Prerequisites

- **Docker Desktop** (with Docker Compose)
- **Python 3.11**
- **Node.js 22.10+** and **npm**
- An **OpenAI API key** (or **Ollama** installed locally)

---

## Steps

### 1. Get API Keys

#### OpenAI API Key

1. Go to [https://platform.openai.com/home](https://platform.openai.com/home). If you don't have an account, create one.
2. After logging in, on the Home page select **Create API Key** in the top right. Create the key with permissions set to **All** and name it anything you like. After creating, save the key for later.
3. On the Home page, if you would like to use `gpt-4o-mini`, add $1 to your credits (should be enough as it is a very cheap model). If you would like to use a free model, use `gpt-3.5-turbo`.

#### SerpAPI Key

1. Go to [https://serpapi.com](https://serpapi.com) and log in. Create an account if you do not have one (Select the Free plan)
2. After logging in, your private key will be present on the home page — save that for later.
3. To use SerpAPI, you will also need **Mozilla Firefox** installed. You will still be able to prompt the model without it, however if you would like the model to scrape for information live then Firefox is required. You can install it at [https://www.firefox.com/en-US/](https://www.firefox.com/en-US/).

---

### 2. Start Elasticsearch

You must have Elasticsearch running before ingesting data. For **local development**, the easiest way is Elastic’s one-command setup:

**[Local development installation (quickstart)](https://www.elastic.co/docs/deploy-manage/deploy/self-managed/local-development-installation-quickstart)**

1. Install [Docker Compose](https://docs.docker.com/compose/install/) (Docker Desktop or Docker Engine).
2. In a terminal, run (Run this command in the home (~) directory):
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

### 3. Ingest data into Elasticsearch

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

### 4. Start Open WebUI (frontend + backend)

**Frontend** (terminal 1):
```bash
cd open-webui
cp -RPp .env.example .env
# Edit .env — add OPENAI_API_KEY, OPENAI_API_BASE_URL, ELASTICSEARCH_API_KEY, SERPAPI_API_KEY
# Use OPENAI_API_BASE_URL='https://api.openai.com/v1'
npm install
# If you see compatibility warnings, try:
# npm install --force
npm run dev
```

**Backend** (terminal 2):
```bash
cd open-webui/backend
python3.11 -m venv venv && source venv/bin/activate
pip install -r requirements.txt -U
sh dev.sh
```

See [Setup: Open WebUI](SETUP_OPEN_WEBUI.md) for full details.

### 5. Use the app

1. Open <http://localhost:5173>
2. Create an admin account (first-time signup)
3. Select a model (e.g. `gpt-4o-mini`)
4. Ask questions about faculty, deadlines, or resume fit

---

## Using Ollama Model

### 1. Install Ollama

To use Ollama models they must be installed locally. From your **home directory** (`~`), install Ollama with:

```bash
curl -fsSL https://ollama.com/install.sh | sh
```

### 2. Pull a model

To pull a model, for example `llama3.2:1b`, run:

```bash
ollama pull llama3.2:1b
```

### 3. Configure native tool support

Ollama models must be configured to use native function calling in Open WebUI. To do this:

1. Click the **user icon** on the top right.
2. Select **Admin Panel**.
3. In the Admin Panel, select **Settings** from the navigation bar at the top.
4. In Settings, select **Models** and search for your model.
5. Once the model is found, select it and expand **Advanced Params**. Set **Function Calling** to **Native**.
6. Scroll to the bottom and **Save**.

> **Note:** Native tool configuration does not need to be performed for OpenAI models.

### 4. Select the local model in chat

Click the **model name** in the top-left of the chat, then select **Local** in the navigation bar of the dropdown menu, and select the model you just configured.

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
- See [Setup: Ingestion Script](SETUP_INGESTION.md) for full details on ingestion.
- See [Setup: Open WebUI](SETUP_OPEN_WEBUI.md) for full details on backend setup. 

For more details, see the individual setup docs linked above.
