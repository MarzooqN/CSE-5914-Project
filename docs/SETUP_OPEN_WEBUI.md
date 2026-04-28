# Setup: Open WebUI (Grad-School Assistant)

This guide walks you through setting up the **Open WebUI** frontend and backend so you can use the grad-school tools (e.g. faculty and program search) with a model like `gpt-4o-mini`. It follows the [Open WebUI Local Development Guide](https://docs.openwebui.com/getting-started/advanced-topics/development) but assumes you already have the project (e.g. from a clone of this repo)—so the **git clone** step is skipped—and uses a **Python venv** unless you prefer Conda.

**Before you start:** Complete [Setup: Ingestion Script](SETUP_INGESTION.md) so Elasticsearch has the `csrankings_authors` index. The grad-school tools need that index to answer faculty/program queries.

---

## Prerequisites

- **Python** 3.11
- **Node.js** 22.10 or higher (for frontend)
- **npm** (usually with Node.js)

---

## 1. Frontend setup

### 1.1 Environment file

From the **project root**, go into the Open WebUI directory (often `open-webui/`):

```bash
cd open-webui
```

Copy the example environment file to `.env`:

```bash
cp -RPp .env.example .env
```

Edit `.env` and set values for your environment (e.g. API base URL, backend URL). For local dev, defaults are often enough; add your **OpenAI API key** and **Elastic Search API Key** and other credentials as needed.

- **OpenAI:** `OPENAI_API_KEY` so the UI can call a model.
- **Elasticsearch (for grad-school tools):**  
  - `ELASTICSEARCH_URL` — e.g. `http://localhost:9200` for local ES.  
  - If your cluster uses an API key: `ELASTICSEARCH_API_KEY` — use the **same API key** you used for the ingestion script and stored safely.

**Do not push your `.env` file or any credentials to git.**


### 1.2 Install frontend dependencies

Still in `open-webui/`:

```bash
npm install
```

If you see compatibility warnings, you can try:

```bash
npm install --force
```

### 1.3 Start the frontend dev server

```bash
npm run dev
```

You should see the dev server running (e.g. at <http://localhost:5173>). The page may say it is waiting for the backend—that’s expected. **Leave this terminal running** and use a second terminal for the backend.

### 1.4 (Recommended) Build the frontend once

In the same frontend terminal, run:

```bash
npm run build
```

If the build succeeds, your frontend is in good shape for production-style runs. You can keep using `npm run dev` for development.

---

## 2. Backend setup

Use a **separate terminal** for the backend (e.g. **Terminal → New Terminal** in your IDE).

### 2.1 Go to the backend directory

From the **project root**:

```bash
cd open-webui/backend
```

### 2.2 Create and activate a Python venv

**Option A – Python venv (recommended):**

```bash
python3 -m venv venv
```

Activate it:

- **Linux/macOS:** `source venv/bin/activate`
- **Windows:** `.\venv\Scripts\activate`

Your prompt should show `(venv)`.

**Option B – Conda:** If you already use Conda and prefer it:

```bash
conda create --name open-webui python=3.11
conda activate open-webui
```

### 2.3 Install backend dependencies

With the venv (or Conda env) activated, in `open-webui/backend/`:

```bash
pip install -r requirements.txt -U
```

### 2.5 Start the backend

In the backend terminal (venv activated), from `open-webui/backend/`:

```bash
sh dev.sh
```

(On Windows you may need to run the equivalent command from the backend’s dev script.)

When the backend is up, you can open the API docs at <http://localhost:8080/docs>.

---

## 3. Use the app and create an admin account

1. In your browser, open the frontend (e.g. <http://localhost:5173>) and refresh if it was already open.
2. Create an **admin account** (sign up / first user) and log in.

---

## 4. Restrict the OpenAI connection to `gpt-4o-mini`

So the model list is not cluttered and the grad-school tool is used with a single model:

1. Click your **profile** (avatar/name) in the UI.
2. Open **Admin Panel**.
3. Go to **Settings → Connections**.
4. Find the **Open AI** connection and click the **gear/settings** button next to it.
5. In the connection settings, add a **model id**: `gpt-4o-mini`.
6. Click **+** to add it to the list.
7. **Save** the connection.

After saving, the OpenAI connection will only expose `gpt-4o-mini` in the model list.

---

## 5. Use the grad-school tool

1. Start a new chat and select the **gpt-4o-mini** model.
2. Ask questions that require faculty or program data, for example:
   - “Which faculty at CMU do security?”
   - “What are the top programs in NLP?”

If Elasticsearch is running, the index name matches (e.g. `csrankings_authors`), and `ELASTICSEARCH_URL` (and `ELASTICSEARCH_API_KEY` if required) are set in the backend `.env`, the assistant will call the grad-school tools and use the ingested data to answer.

---

## Troubleshooting

- **Port in use:** If port 5173 (frontend) or 8080 (backend) is already in use, stop the other process or change the port in the dev script or frontend config.
- **CORS / API errors:** Ensure the frontend URL (e.g. `http://localhost:5173`) is allowed in the backend’s CORS config (e.g. `CORS_ALLOW_ORIGIN` in `backend/dev.sh` or `.env`).
- **Grad-school tool errors:** Confirm Elasticsearch is running, the ingestion script has been run ([Setup: Ingestion Script](SETUP_INGESTION.md)), and `ELASTICSEARCH_URL` (and `ELASTICSEARCH_API_KEY` if needed) are set in the **backend** `.env`.

For more detail, see the [Open WebUI Local Development Guide](https://docs.openwebui.com/getting-started/advanced-topics/development).

**Related:** To add or change grad-school tools (e.g. implement deadlines, add new indices), see [Runbook: Adding Tools](RUNBOOK_ADDING_TOOLS.md).
