# Deployment Guide

**Yes, this deploys for free.** The entire stack runs on free tiers:

| Service | Free tier |
|---|---|
| TiDB Serverless | 5 GB storage, 250M request units/month |
| Render | 750 hours/month (sleeps after 15 min idle) |
| Railway | $5 credit/month (no sleep) |
| Fly.io | 3 shared VMs, 256 MB RAM each (no sleep) |
| Groq | Free tier — fast inference, generous rate limits |
| Composio | Free tier for integrations |
| ipinfo.io | 50k lookups/month |

---

## Prerequisites

1. **uv** — Python package manager

   ```bash
   curl -LsSf https://astral.sh/uv/install.sh | sh
   ```

2. **TiDB Serverless** database (free)
   - Sign up at [tidbcloud.com](https://tidbcloud.com)
   - Create a Serverless cluster
   - Go to **Connect** → copy the connection string

3. **Groq API key** (free) — [console.groq.com](https://console.groq.com)

4. **Composio API key** (optional, for email submission) — [app.composio.dev](https://app.composio.dev)

5. **Skyfire API key** (optional, for agent micro-payments) — [app.skyfire.xyz](https://app.skyfire.xyz)

---

## Local development

```bash
# 1. Clone and install
git clone <repo>
cd hack-snowflake
uv sync

# 2. Configure environment
cp .env.example .env
# Edit .env — at minimum set DATABASE_URL and GROQ_API_KEY

# 3. Seed the database (creates tables + 5 demo chargebacks across 3 customers)
uv run seed.py

# 4. Start the server
uv run uvicorn main:app --reload
# → Dashboard at http://localhost:8000
# → API docs at http://localhost:8000/docs

# 5. Trigger a demo dispute (or use the dashboard)
curl -X POST http://localhost:8000/dispute/cb_demo_001

# 6. Check status
curl http://localhost:8000/dispute/cb_demo_001/status

# Reset all chargebacks back to open for another demo run (no reseed needed)
uv run seed.py --reset

# Or run the end-to-end pipeline locally without a server
uv run demo.py
```

The generated PDF lands in `./output/`.

---

## Deploy to Render (recommended — free, easiest)

Render is the simplest path: connect your GitHub repo and it deploys automatically.

### Steps

1. Push this repo to GitHub

2. Go to [render.com](https://render.com) → **New** → **Web Service**

3. Connect your GitHub repo

4. Configure:

   | Field | Value |
   |---|---|
   | **Runtime** | Python 3 |
   | **Build command** | `pip install uv && uv sync --no-dev` |
   | **Start command** | `uvicorn main:app --host 0.0.0.0 --port $PORT` |
   | **Instance type** | Free |

5. Add environment variables (under **Environment**):

   ```
   DATABASE_URL            = mysql://user:pass@host:4000/chargebacks
   GROQ_API_KEY            = gsk_...
   COMPOSIO_API_KEY        = ...
   DISPUTE_RECIPIENT_EMAIL = disputes@yourprocessor.com
   SKYFIRE_API_KEY         = ...
   IPINFO_TOKEN            = ...
   PDF_OUTPUT_DIR          = /tmp/output
   ```

   > **SSL note:** SSL is enabled by default — no `?sslaccept=strict` needed in the URL. To disable (not recommended), append `?ssl=false`.

   > **Filesystem note:** Render's free tier has an ephemeral filesystem. Set `PDF_OUTPUT_DIR=/tmp/output`. PDFs are emailed via Composio before the process may restart.

6. Click **Deploy**. Your service will be live at `https://<name>.onrender.com`.

7. Seed the database (run once from local with the same `DATABASE_URL`):

   ```bash
   uv run seed.py
   ```

### Stripe webhook (to auto-trigger on real chargebacks)

In Stripe Dashboard → Developers → Webhooks → Add endpoint:
- URL: `https://<name>.onrender.com/webhook/chargeback`
- Events: `charge.dispute.created`
- Copy the signing secret → add as `WEBHOOK_SECRET` in Render env vars

---

## Deploy to Railway (free $5 credit/month, no sleep)

Railway doesn't sleep and has better DX for persistent apps.

```bash
# Install Railway CLI
npm install -g @railway/cli

# Login and deploy
railway login
railway init
railway up
```

Add environment variables via `railway variables set KEY=VALUE` or the Railway dashboard.

Railway auto-detects the `Procfile`:
```
web: uvicorn main:app --host 0.0.0.0 --port $PORT
```

---

## Deploy to Fly.io (free allowance, no sleep)

```bash
# Install Fly CLI
curl -L https://fly.io/install.sh | sh

# Login
fly auth login

# Launch (creates fly.toml)
fly launch --name chargeback-agent --region ord --no-deploy

# Set secrets
fly secrets set \
  DATABASE_URL="mysql://..." \
  GROQ_API_KEY="gsk_..." \
  COMPOSIO_API_KEY="..." \
  SKYFIRE_API_KEY="..." \
  IPINFO_TOKEN="..." \
  PDF_OUTPUT_DIR="/tmp/output"

# Deploy
fly deploy
```

Fly requires a `Dockerfile`. Minimal example:

```dockerfile
FROM python:3.11-slim
WORKDIR /app
RUN pip install uv
COPY . .
RUN uv sync --no-dev
EXPOSE 8080
CMD ["uv", "run", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]
```

---

## Environment variables reference

| Variable | Required | Description |
|---|---|---|
| `DATABASE_URL` | Yes* | MySQL connection string — `mysql://user:pass@host:4000/db` |
| `TIDB_HOST` | Yes* | TiDB host (if not using DATABASE_URL) |
| `TIDB_USER` | Yes* | TiDB username |
| `TIDB_PASSWORD` | Yes* | TiDB password |
| `TIDB_DATABASE` | Yes* | Database name (default: `chargebacks`) |
| `GROQ_API_KEY` | Yes | Powers all CrewAI agents via Groq (`gpt-oss-120b`) |
| `COMPOSIO_API_KEY` | No | Email submission via Composio Gmail/Outlook |
| `DISPUTE_RECIPIENT_EMAIL` | No | Where to email the dispute PDF |
| `SKYFIRE_API_KEY` | No | Micro-payments for enrichment API calls |
| `IPINFO_TOKEN` | No | IP geolocation (50k/month free without token) |
| `WEBHOOK_SECRET` | No | Stripe webhook signing secret |
| `PDF_OUTPUT_DIR` | No | PDF output path (default: `./output`) |

*Either `DATABASE_URL` or the individual `TIDB_*` vars are required.

---

## API endpoints

| Method | Path | Description |
|---|---|---|
| `GET` | `/` | Dashboard UI |
| `GET` | `/chargebacks` | List all chargebacks as JSON |
| `GET` | `/health` | Liveness check |
| `POST` | `/webhook/chargeback` | Stripe webhook receiver |
| `POST` | `/dispute/{id}` | Manually trigger dispute pipeline |
| `GET` | `/dispute/{id}/status` | Check dispute status and PDF path |
| `GET` | `/docs` | Interactive API docs (Swagger UI) |
