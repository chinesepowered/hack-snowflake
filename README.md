# Chargeback Agent

Merchants lose billions to chargebacks every year — not because the transactions were fraudulent, but because building a winning dispute response is slow, manual, and easy to deprioritize. Most merchants never respond at all.

**Chargeback Agent** automates the entire dispute process. When a chargeback arrives, it immediately pulls transaction data, customer history, and IP intelligence from your database, writes a professional dispute narrative with AI, and delivers a complete evidence package to your payment processor — no human required.

---

## How it works

```
Chargeback webhook
       ↓
  CrewAI pipeline
  ┌─────────────────────────────────────────┐
  │  1. Data Agent        → TiDB Serverless │  purchase history, IP logs, billing details
  │  2. Enrichment Agent  → ipinfo.io       │  geolocation, ISP, IP transaction history
  │  3. Analyst Agent     → Claude          │  dispute narrative tailored to reason code
  │  4. Coordinator       → compiles all    │  structured evidence package
  └─────────────────────────────────────────┘
       ↓
  PDF evidence package (ReportLab)
       ↓
  Composio → Gmail / Stripe Disputes API
       ↓
  TiDB record updated (status, PDF path, timestamp)
```

The whole pipeline runs as a background task. Your webhook endpoint returns 202 immediately.

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
| **TiDB Serverless** | MySQL-compatible database — stores all transaction and chargeback data. Free tier: 5 GB, 250M request units/month. |
| **CrewAI** | Multi-agent orchestration — four specialized agents work in sequence to gather and analyze evidence. |
| **Composio** | Pre-built integrations — sends the dispute PDF via Gmail, Outlook, or directly through the Stripe Disputes API. |
| **Skyfire** | Agent-native payments — the enrichment agent autonomously pays for external API calls (IP geolocation) without human involvement. |

---

## Quick start

**Requirements:** [uv](https://docs.astral.sh/uv/), a [TiDB Serverless](https://tidbcloud.com) cluster, an [Anthropic API key](https://console.anthropic.com).

```bash
# Install dependencies
uv sync

# Configure
cp .env.example .env
# Set DATABASE_URL and ANTHROPIC_API_KEY in .env

# Bootstrap the database
uv run seed.py

# Start the server
uv run uvicorn main:app --reload
```

**Trigger a dispute manually:**
```bash
curl -X POST http://localhost:8000/dispute/cb_demo_001
curl http://localhost:8000/dispute/cb_demo_001/status
```

**Run the full demo without a server:**
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
| `POST` | `/webhook/chargeback` | Stripe webhook (auto-trigger) |
| `POST` | `/dispute/{id}` | Manually trigger pipeline for a chargeback |
| `GET` | `/dispute/{id}/status` | Check status and PDF path |
| `GET` | `/docs` | Interactive API docs |
| `GET` | `/health` | Liveness check |

---

## Stack

Python 3.11 · FastAPI · CrewAI · Claude · TiDB Serverless · ReportLab · Composio · Skyfire · uv
