# Sponsor Integrations

This document describes how each hackathon sponsor's technology is used in the project.

---

## CrewAI

**Role:** Multi-agent orchestration framework.

**Why CrewAI:** CrewAI provides a clean abstraction for defining agents with roles, goals, and backstories, and for wiring them into sequential or parallel pipelines with shared context. It handles tool invocation, context passing between tasks, and result extraction.

**How we use it:**

Four agents run in a `Process.sequential` pipeline. Each task receives prior tasks as `context`, so each agent builds on the previous agent's output:

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
