# Chargeback Agent

Merchants lose billions to chargebacks every year — not because the transactions were fraudulent, but because building a winning dispute response is slow, manual, and easy to deprioritize. Most merchants never respond at all.

**Chargeback Agent** automates the entire dispute process. When a chargeback arrives, it immediately pulls transaction data, customer history, and IP intelligence from your database, writes a professional dispute narrative with AI, and delivers a complete evidence package to your payment processor — no human required.

---

## How it works

```
Chargeback webhook  ──or──  Dashboard "Run Dispute" button
       ↓
  CrewAI pipeline
  ┌─────────────────────────────────────────────────────┐
  │  1. Data Agent        → TiDB Serverless             │  purchase history, IP logs, billing details
  │  2. Enrichment Agent  → Skyfire → ipinfo.io         │  geolocation, ISP, IP transaction cross-ref
  │  3. Analyst Agent     → Groq (gpt-oss-120b)         │  dispute narrative tailored to reason code
  │  4. Coordinator       → compiles all                │  structured evidence package
  └─────────────────────────────────────────────────────┘
       ↓
  PDF evidence package (ReportLab)
       ↓
  Composio → Gmail / Stripe Disputes API
       ↓
  TiDB record updated (status, PDF path, timestamp)
```

The whole pipeline runs as a background task. Your webhook endpoint returns 202 immediately.

---

## Dashboard

Open `http://localhost:8000` after starting the server for a live ops dashboard:

- **Stats** — Total / Open / Under Review / Submitted counts at a glance
- **Chargebacks table** — all cases with customer info, amounts, reason codes, due dates, and status badges
- **Run Dispute button** — confirm and trigger the AI pipeline for any open chargeback
- **Live polling** — status updates every 4 seconds while a pipeline runs, no manual refresh needed
- **Health indicator** — shows whether the FastAPI server is reachable

---

## Evidence gathered

Every dispute PDF contains:

- **Transaction details** — amount, timestamp, card, billing/shipping address
- **IP intelligence** — geolocation, ISP, all other transactions from the same IP address
- **Customer history** — every prior purchase and account event (logins, address changes)
- **AI narrative** — a concise, professional response targeting the specific reason code

---

## Integrations

| | |
|---|---|
| **TiDB Serverless** | MySQL-compatible serverless database — stores all transaction, chargeback, and customer event data. SSL-enforced; works with a plain `DATABASE_URL` (no extra config). |
| **Groq** | LLM inference — all four CrewAI agents run on `gpt-oss-120b` via Groq's OpenAI-compatible endpoint. Fast, with generous free-tier rate limits. |
| **CrewAI** | Multi-agent orchestration — four specialized agents work sequentially to gather, enrich, analyse, and package evidence. |
| **Composio** | Pre-built integrations — sends the dispute PDF via Gmail, Outlook, or directly through the Stripe Disputes API. |
| **Skyfire** | Agent-native payments — the enrichment agent autonomously pays for external API calls (IP geolocation) without human involvement. |

---

## Quick start

**Requirements:** [uv](https://docs.astral.sh/uv/), a [TiDB Serverless](https://tidbcloud.com) cluster, a [Groq API key](https://console.groq.com) (free).

```bash
# Install dependencies
uv sync

# Configure
cp .env.example .env
# Edit .env — set DATABASE_URL and GROQ_API_KEY at minimum

# Bootstrap the database (5 chargebacks across 3 customers, 5 reason codes)
uv run seed.py

# Start the server
uv run uvicorn main:app --reload
# → open http://localhost:8000 for the dashboard
```

**Trigger a dispute from the dashboard** or via curl:
```bash
curl -X POST http://localhost:8000/dispute/cb_demo_001
curl http://localhost:8000/dispute/cb_demo_001/status
```

**Reset all demo chargebacks back to open (for re-demos, no reseed needed):**
```bash
uv run seed.py --reset
```

**Run the full pipeline without a server:**
```bash
uv run demo.py
# → generates a PDF in ./output/
```

**Connect to Stripe:**

In Stripe Dashboard → Developers → Webhooks → Add endpoint:
- URL: `https://your-deployment/webhook/chargeback`
- Event: `charge.dispute.created`

From that point on, every new chargeback triggers the pipeline automatically.

---

## Deployment

Deploys free to [Render](https://render.com), [Railway](https://railway.app), or [Fly.io](https://fly.io). See [deploy.md](deploy.md) for step-by-step instructions.

---

## API

| Method | Path | Description |
|---|---|---|
| `GET` | `/` | Dashboard UI |
| `GET` | `/chargebacks` | List all chargebacks (JSON) |
| `POST` | `/webhook/chargeback` | Stripe webhook (auto-trigger) |
| `POST` | `/dispute/{id}` | Manually trigger pipeline for a chargeback |
| `GET` | `/dispute/{id}/status` | Check status and PDF path |
| `GET` | `/health` | Liveness check |
| `GET` | `/docs` | Interactive API docs (Swagger UI) |

---

## Stack

Python 3.11 · FastAPI · CrewAI · Groq (`gpt-oss-120b`) · LiteLLM · TiDB Serverless · PyMySQL · ReportLab · Composio · Skyfire · uv
