# Project Context — AI Chargeback Dispute Agent

This document is written for AI coding agents picking up this codebase. Read it fully before making changes.

---

## What this project does

Merchants lose ~40% of chargeback disputes by default — not because they're wrong, but because responding is slow and manual. This service automates the entire process: when a chargeback arrives via webhook, a multi-agent AI pipeline gathers evidence from the database, enriches it with external data, writes a professional dispute narrative, generates a PDF evidence package, and emails it to the payment processor — all without human involvement.

---

## Tech stack

| Layer | Technology | Purpose |
|---|---|---|
| API | FastAPI | Webhook receiver, REST endpoints |
| Agents | CrewAI | Multi-agent orchestration |
| LLM | Anthropic Claude (claude-sonnet-4-6) | Agent reasoning via LiteLLM |
| Database | TiDB Serverless (MySQL-compatible) | Transaction, chargeback, customer data |
| DB driver | PyMySQL | Direct MySQL driver, no ORM |
| PDF | ReportLab | Evidence package generation |
| Tool integrations | Composio | Email submission (Gmail/Outlook) |
| Agent payments | Skyfire | Micro-payments for enrichment API calls |
| IP enrichment | ipinfo.io | Geolocation / ISP lookup |
| Package manager | uv | Python dependency management |

---

## File map

```
.
├── main.py                  # FastAPI app — all HTTP endpoints and webhook handler
├── demo.py                  # Standalone demo: runs crew + generates PDF, no server needed
├── seed.py                  # DB bootstrap: creates tables and inserts sample data
├── schema.sql               # Raw SQL schema (reference; seed.py is the canonical seeder)
├── pyproject.toml           # uv project file with dependencies
├── .python-version          # Pins Python 3.11
├── Procfile                 # For Render/Railway: `uvicorn main:app --host 0.0.0.0 --port $PORT`
├── .env.example             # All env vars with descriptions
│
├── db/
│   └── tidb.py              # All database queries (no ORM — raw PyMySQL)
│                            # Supports DATABASE_URL or individual TIDB_* vars
│                            # SSL: ssl_verify_cert + ssl_verify_identity (TiDB Serverless requirement)
│
├── agents/
│   ├── tools.py             # CrewAI BaseTool subclasses wrapping DB queries + IP enrichment
│   │                        # IpEnrichmentTool calls Skyfire to pay before each API call
│   └── crew.py              # 4-agent sequential pipeline definition
│                            # Returns DisputeEvidence dataclass
│
├── pdf/
│   └── generator.py         # ReportLab PDF builder
│                            # Takes DisputeEvidence, returns file path
│
└── output/                  # Generated PDFs land here (gitignored)
```

---

## Agent pipeline (agents/crew.py)

Four agents run **sequentially** via `Process.sequential`. Each agent's output is passed as `context` to the next:

```
1. DataAgent (FetchTransactionTool, FetchCustomerHistoryTool)
   → fetches transaction record + full customer history from TiDB

2. EnrichmentAgent (IpEnrichmentTool, FetchIpTransactionsTool)
   → enriches IP with geolocation; finds all transactions from same IP
   → Skyfire micro-payment is made before the ipinfo.io call

3. AnalystAgent (no tools)
   → reads all evidence context, writes dispute narrative (max 400 words)
   → knows Visa/MC reason codes and what evidence wins disputes

4. CoordinatorAgent (no tools)
   → compiles all prior outputs into a single JSON blob with 5 keys:
     transaction, customer_history, ip_enrichment, ip_transactions, narrative
```

The final JSON is parsed into `DisputeEvidence` (a dataclass), then passed to the PDF generator.

If JSON parsing fails (LLM returns prose instead of JSON), the code gracefully degrades: the narrative goes in as-is, other fields default to empty dicts/lists.

---

## Database schema

Three tables:

- **transactions** — one row per payment. Has `ip_address`, `billing_address`, `shipping_address`, `card_last4`, `card_brand`, `customer_id`, `customer_email`.
- **chargebacks** — one row per dispute. FK to `transactions`. Has `status` (open → under_review → won/lost), `pdf_path`, `dispute_submitted_at`.
- **customer_history** — event log: logins, purchases, address changes. Keyed by `customer_id`. Used to show account legitimacy.

---

## Connection string handling (db/tidb.py)

Priority order:
1. `DATABASE_URL` env var — parsed with `urllib.parse.urlparse`; `?sslaccept=strict` in query string enables SSL
2. Individual `TIDB_HOST`, `TIDB_USER`, `TIDB_PASSWORD`, `TIDB_DATABASE` vars — SSL always enabled

SSL uses `ssl_verify_cert=True, ssl_verify_identity=True` (correct pymysql params for TiDB Serverless). Do **not** use `ssl={"ssl_mode": "VERIFY_IDENTITY"}` — that dict key is not recognised by pymysql.

---

## HTTP flow (main.py)

**Webhook path** (`POST /webhook/chargeback`):
1. Verify Stripe signature if `WEBHOOK_SECRET` is set
2. Normalise Stripe `charge.dispute.created` event → `ChargebackPayload`
3. Enqueue `_run_dispute_pipeline` as a FastAPI `BackgroundTask`
4. Return 202 immediately

**Manual trigger** (`POST /dispute/{chargeback_id}`):
- Looks up chargeback from DB, builds `ChargebackPayload`, same background task

**`_run_dispute_pipeline`**:
1. `run_dispute_crew()` → `DisputeEvidence`
2. `generate_dispute_pdf()` → PDF file path
3. `_submit_via_composio()` → POST to Composio `GMAIL_SEND_EMAIL` action
4. `tidb.update_chargeback_status()` → mark `under_review`, store PDF path

---

## Conventions

- **No ORM** — all DB access is raw PyMySQL with `DictCursor`. Keep it that way.
- **No background workers** — FastAPI `BackgroundTasks` handles async work. For production scale, swap for Celery/ARQ.
- **Graceful degradation** — missing optional credentials (Composio, Skyfire, ipinfo) are logged as warnings, not errors. The pipeline continues.
- **Model** — always use `anthropic/claude-sonnet-4-6` (LiteLLM provider-prefixed format). The plain `claude-sonnet-4-6` works too but the prefixed form is explicit.
- **Python version** — 3.11+. Type hints use `X | Y` union syntax (not `Optional[X]`).
- **uv** — use `uv run <script>` and `uv sync`. Do not use `pip install` directly.

---

## Adding a new data source to the evidence

1. Add a query function in `db/tidb.py`
2. Create a `BaseTool` subclass in `agents/tools.py`
3. Assign it to the appropriate agent in `agents/crew.py`
4. Add the data to `DisputeEvidence` dataclass
5. Render it in `pdf/generator.py`

---

## Known limitations / future work

- PDFs are stored on local disk — ephemeral on platforms like Render free tier. Wire up S3/R2 for persistence.
- No retry queue for failed pipelines — if the CrewAI run fails, the chargeback stays `open`. Add a retry mechanism.
- Composio's `GMAIL_SEND_EMAIL` requires the Gmail integration to be connected in the Composio dashboard. For Stripe-native submission, swap for the `STRIPE_UPDATE_DISPUTE` action.
- The CoordinatorAgent sometimes returns markdown-fenced JSON instead of raw JSON. The `json.JSONDecodeError` fallback handles this, but it loses structured data. Fix: add a post-processor that strips ` ```json ``` ` fences before parsing.
