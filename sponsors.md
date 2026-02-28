# Sponsor Integrations

This document describes how each sponsor's technology is used in the project.

---

## TiDB Serverless (PingCAP)

**Role:** Primary database — stores all transaction, chargeback, and customer event data.

**Why TiDB:** TiDB Serverless is a fully-managed, MySQL-compatible distributed database with a generous free tier (5 GB, 250M request units/month). Its MySQL compatibility means we use standard PyMySQL with no special drivers, and it scales automatically under load — important when a merchant has thousands of chargebacks.

**How we use it:**

- Three tables: `transactions`, `chargebacks`, `customer_history`
- Every agent tool query hits TiDB directly via raw PyMySQL (`DictCursor`, no ORM)
- SSL is enforced on every connection using certifi's CA bundle
- `DATABASE_URL` format: `mysql://user:pass@gateway.tidbcloud.com:4000/chargebacks`

**Key files:**
- `db/tidb.py` — all queries: `get_transaction`, `get_chargeback`, `get_customer_transaction_history`, `get_customer_event_history`, `get_ip_transactions`, `list_chargebacks`, `update_chargeback_status`
- `seed.py` — schema creation and sample data seeding

**Data model:**
```sql
transactions      -- payment records: amount, card, IP, billing/shipping address
chargebacks       -- dispute cases: reason code, status, evidence_due_by, pdf_path
customer_history  -- event log: logins, purchases, address changes (per customer_id)
```

---

## Groq

**Role:** LLM inference — all four CrewAI agents run on Groq.

**Why Groq:** Groq's inference hardware (LPUs) delivers significantly lower latency than GPU-based alternatives. For a time-sensitive chargeback pipeline, fast inference means the entire 4-agent pipeline completes in seconds rather than minutes. The free tier has generous rate limits suitable for demo and hackathon use.

**Model used:** `openai/gpt-oss-120b` — an OpenAI open-source model hosted on Groq's platform.

**How we use it:**

Groq exposes an OpenAI-compatible REST API at `https://api.groq.com/openai/v1`. We configure LiteLLM (via CrewAI's `LLM` class) to route to this endpoint:

```python
# agents/crew.py
llm = LLM(
    model="openai/openai/gpt-oss-120b",  # first 'openai/' = LiteLLM provider; second = Groq model ID
    api_key=os.environ["GROQ_API_KEY"],
    api_base="https://api.groq.com/openai/v1",
)
```

All four agents share the same LLM instance:
- **DataAgent** — decides which tools to call and formats transaction + history data as JSON
- **EnrichmentAgent** — calls IP enrichment tool, synthesises geolocation + cross-reference data
- **AnalystAgent** — reads all evidence and writes the dispute narrative (max 400 words, reason-code aware)
- **CoordinatorAgent** — assembles the final structured JSON package for the PDF generator

**Key files:** `agents/crew.py`

---

## CrewAI

**Role:** Multi-agent orchestration framework.

**Why CrewAI:** CrewAI provides a clean abstraction for defining agents with roles, goals, and backstories, and for wiring them into sequential or parallel pipelines with shared context. It handles tool invocation, context passing between tasks, and result extraction.

**How we use it:**

Four agents run in a `Process.sequential` pipeline. Each task receives prior tasks as `context`, so each agent can build on the previous agent's output:

```
DataAgent (tools: FetchTransactionTool, FetchCustomerHistoryTool)
    ↓ context
EnrichmentAgent (tools: IpEnrichmentTool, FetchIpTransactionsTool)
    ↓ context
AnalystAgent (no tools — reads all evidence, writes narrative)
    ↓ context
CoordinatorAgent (no tools — compiles final JSON package)
```

Each tool is a `BaseTool` subclass in `agents/tools.py` that wraps a `db/tidb.py` query function or an HTTP call to ipinfo.io (via Skyfire payment).

**Key files:** `agents/crew.py`, `agents/tools.py`

---

## Composio

**Role:** Pre-built action integrations — submits the dispute evidence package via email.

**Why Composio:** Building and maintaining OAuth integrations for Gmail, Outlook, and the Stripe Disputes API from scratch is significant engineering work. Composio provides these as callable actions with a single API call, including attachment support.

**How we use it:**

After the PDF is generated, `_submit_via_composio()` in `main.py` calls Composio's action execution endpoint:

```python
# main.py — _submit_via_composio()
await client.post(
    "https://backend.composio.dev/api/v2/actions/execute",
    headers={"x-api-key": COMPOSIO_API_KEY},
    json={
        "actionName": "GMAIL_SEND_EMAIL",
        "input": {
            "recipient_email": DISPUTE_RECIPIENT_EMAIL,
            "subject": f"Chargeback Dispute Evidence — {cb_id}",
            "body": "...",
            "attachments": [{"name": f"dispute_{cb_id}.pdf", "content": pdf_b64, "mimeType": "application/pdf"}],
        },
    },
)
```

To switch from Gmail to Stripe-native submission, change `actionName` to `STRIPE_UPDATE_DISPUTE` — no other code changes needed.

Composio is non-fatal: if the API key is missing or the call fails, the pipeline logs a warning and continues. The PDF is still saved locally.

**Key files:** `main.py` (`_submit_via_composio`)

---

## Skyfire

**Role:** Agent-native micropayments — lets the AI agent autonomously pay for external API calls.

**Why Skyfire:** Traditional integrations require humans to manage API keys and billing for every third-party service. Skyfire provides a payment rail where AI agents can autonomously pay for API access in real time, without human involvement. This demonstrates a key property of autonomous agent systems: the ability to acquire resources independently.

**How we use it:**

The `IpEnrichmentTool` in `agents/tools.py` makes a Skyfire-mediated payment before each ipinfo.io lookup:

```python
# agents/tools.py — IpEnrichmentTool._run()
# Skyfire payment happens here before the actual API call
response = skyfire_client.get(f"https://ipinfo.io/{ip_address}/json")
# → [Skyfire] payment ok ($0.0010) for ipinfo lookup of <ip>
```

The agent doesn't need to know about billing — it just calls the tool. Skyfire handles the micropayment transparently. This appears in the logs as:
```
[Skyfire] payment ok ($0.0010) for ipinfo lookup of 203.0.113.42
```

**Key files:** `agents/tools.py` (`IpEnrichmentTool`)
