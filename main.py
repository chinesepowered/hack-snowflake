"""
AI Chargeback Dispute Agent — FastAPI entry point.

Endpoints:
  POST /webhook/chargeback   — receives chargeback notifications (Stripe, etc.)
  POST /dispute/{id}         — manually trigger a dispute for a chargeback ID
  GET  /dispute/{id}/status  — check status of a dispute
  GET  /health               — liveness check

Flow:
  1. Receive chargeback webhook
  2. Kick off CrewAI pipeline to gather evidence
  3. Generate PDF with ReportLab
  4. Submit dispute via Composio (email + optional Stripe Disputes API)
  5. Update TiDB record with pdf path and submission timestamp
"""
import hashlib
import hmac
import json
import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path

# Suppress noisy LiteLLM internal loggers (apscheduler/proxy errors unrelated to our usage)
logging.getLogger("LiteLLM").setLevel(logging.CRITICAL)
logging.getLogger("LiteLLM Router").setLevel(logging.CRITICAL)
logging.getLogger("LiteLLM Proxy").setLevel(logging.CRITICAL)
logging.getLogger("litellm").setLevel(logging.CRITICAL)

import httpx
from dotenv import load_dotenv
from fastapi import BackgroundTasks, FastAPI, Header, HTTPException, Request, status
from fastapi.responses import FileResponse
from pydantic import BaseModel

from agents.crew import run_dispute_crew
from db import tidb
from pdf.generator import generate_dispute_pdf

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s — %(message)s")
log = logging.getLogger("dispute-agent")

PDF_OUTPUT_DIR = os.environ.get("PDF_OUTPUT_DIR", "./output")
WEBHOOK_SECRET = os.environ.get("WEBHOOK_SECRET", "")
COMPOSIO_API_KEY = os.environ.get("COMPOSIO_API_KEY", "")
MOCK_EMAIL = os.environ.get("MOCK_EMAIL", "").lower() in ("1", "true", "yes")


# ---------------------------------------------------------------------------
# App lifecycle
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    Path(PDF_OUTPUT_DIR).mkdir(parents=True, exist_ok=True)
    log.info("AI Chargeback Dispute Agent ready")
    yield


app = FastAPI(
    title="AI Chargeback Dispute Agent",
    description=(
        "Automated evidence gathering and PDF generation for chargeback disputes. "
        "Powered by CrewAI, TiDB Serverless, Composio, and Skyfire."
    ),
    version="1.0.0",
    lifespan=lifespan,
)


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

class ChargebackPayload(BaseModel):
    """Normalized chargeback event — maps from Stripe webhook or manual trigger."""
    chargeback_id: str
    transaction_id: str
    amount_cents: int
    currency: str = "USD"
    reason_code: str = "fraud"
    reason_description: str = "Customer claims transaction was unauthorized"
    evidence_due_by: str | None = None


class DisputeStatus(BaseModel):
    chargeback_id: str
    status: str
    pdf_path: str | None
    dispute_submitted_at: str | None


# ---------------------------------------------------------------------------
# Webhook signature verification (Stripe-style)
# ---------------------------------------------------------------------------

def _verify_stripe_signature(payload: bytes, sig_header: str, secret: str) -> bool:
    if not secret:
        return True  # Skip verification if not configured (dev mode)
    try:
        pairs = dict(item.split("=", 1) for item in sig_header.split(","))
        timestamp = pairs.get("t", "")
        v1 = pairs.get("v1", "")
        signed = f"{timestamp}.{payload.decode()}"
        expected = hmac.new(secret.encode(), signed.encode(), hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, v1)
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Core dispute pipeline
# ---------------------------------------------------------------------------

async def _run_dispute_pipeline(payload: ChargebackPayload) -> None:
    """Background task: run agents → generate PDF → submit via Composio → update DB."""
    cb_id = payload.chargeback_id
    txn_id = payload.transaction_id
    log.info("Starting dispute pipeline for chargeback=%s transaction=%s", cb_id, txn_id)

    try:
        # 1. CrewAI multi-agent evidence gathering
        evidence = run_dispute_crew(
            chargeback_id=cb_id,
            transaction_id=txn_id,
            chargeback_meta=payload.model_dump(),
        )

        # 2. Generate PDF
        pdf_path = generate_dispute_pdf(evidence, output_dir=PDF_OUTPUT_DIR)
        log.info("PDF generated: %s", pdf_path)

        # 3. Submit via Composio (email with PDF attachment)
        await _submit_via_composio(cb_id, txn_id, pdf_path, payload)

        # 4. Mark as submitted in TiDB
        tidb.update_chargeback_status(
            chargeback_id=cb_id,
            status="under_review",
            pdf_path=pdf_path,
            submitted_at=datetime.utcnow(),
        )
        log.info("Dispute pipeline complete for chargeback=%s", cb_id)

    except Exception as exc:
        log.exception("Dispute pipeline failed for chargeback=%s: %s", cb_id, exc)
        tidb.update_chargeback_status(chargeback_id=cb_id, status="open")


async def _submit_via_composio(
    cb_id: str, txn_id: str, pdf_path: str, payload: ChargebackPayload
) -> None:
    """
    Use Composio to submit the dispute evidence.
    Composio provides pre-built integrations for Gmail, Outlook, and Stripe Disputes API.
    We call Composio's action execution endpoint directly here.
    """
    if MOCK_EMAIL:
        log.info("[MOCK] Email submission skipped (MOCK_EMAIL=true) — PDF saved at %s", pdf_path)
        return

    if not COMPOSIO_API_KEY:
        log.warning("COMPOSIO_API_KEY not set — skipping submission")
        return

    # Read PDF as base64 for email attachment
    import base64
    with open(pdf_path, "rb") as f:
        pdf_b64 = base64.b64encode(f.read()).decode()

    subject = f"Chargeback Dispute Evidence — {cb_id}"
    body = (
        f"Please find attached the dispute evidence package for chargeback {cb_id} "
        f"on transaction {txn_id}.\n\n"
        f"Disputed amount: {payload.currency} {payload.amount_cents / 100:,.2f}\n"
        f"Reason: {payload.reason_description}\n\n"
        "This dispute was automatically compiled by our AI Chargeback Dispute Agent."
    )

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                "https://backend.composio.dev/api/v2/actions/execute",
                headers={
                    "x-api-key": COMPOSIO_API_KEY,
                    "Content-Type": "application/json",
                },
                json={
                    "actionName": "GMAIL_SEND_EMAIL",
                    "input": {
                        "recipient_email": os.environ.get("DISPUTE_RECIPIENT_EMAIL", "disputes@example.com"),
                        "subject": subject,
                        "body": body,
                        "attachments": [
                            {
                                "name": f"dispute_{cb_id}.pdf",
                                "content": pdf_b64,
                                "mimeType": "application/pdf",
                            }
                        ],
                    },
                },
            )
            resp.raise_for_status()
            log.info("Composio submission successful for chargeback=%s", cb_id)
    except Exception as exc:
        log.error("Composio submission failed for chargeback=%s: %s", cb_id, exc)
        # Non-fatal — PDF is still saved locally


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/", include_in_schema=False)
async def frontend():
    return FileResponse("frontend/index.html")


@app.get("/chargebacks")
async def list_chargebacks():
    rows = tidb.list_chargebacks()
    return [
        {k: str(v) if isinstance(v, datetime) else v for k, v in row.items()}
        for row in rows
    ]


@app.get("/health")
async def health():
    return {"status": "ok", "timestamp": datetime.utcnow().isoformat()}


@app.post("/webhook/chargeback", status_code=status.HTTP_202_ACCEPTED)
async def webhook_chargeback(
    request: Request,
    background_tasks: BackgroundTasks,
    stripe_signature: str | None = Header(default=None, alias="stripe-signature"),
):
    """
    Stripe (or any payment processor) chargeback webhook.
    Accepts application/json and normalizes it into ChargebackPayload.
    """
    raw_body = await request.body()

    if stripe_signature and WEBHOOK_SECRET:
        if not _verify_stripe_signature(raw_body, stripe_signature, WEBHOOK_SECRET):
            raise HTTPException(status_code=400, detail="Invalid webhook signature")

    try:
        data = json.loads(raw_body)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    # Normalize from Stripe charge.dispute.created event format
    if "type" in data and data["type"] == "charge.dispute.created":
        dispute_obj = data.get("data", {}).get("object", {})
        payload = ChargebackPayload(
            chargeback_id=dispute_obj.get("id", ""),
            transaction_id=dispute_obj.get("charge", ""),
            amount_cents=dispute_obj.get("amount", 0),
            currency=dispute_obj.get("currency", "USD").upper(),
            reason_code=dispute_obj.get("reason", "fraud"),
            reason_description=dispute_obj.get("reason", "unauthorized transaction"),
            evidence_due_by=str(dispute_obj.get("evidence_details", {}).get("due_by", "")),
        )
    else:
        # Direct payload format (manual trigger or other processors)
        try:
            payload = ChargebackPayload(**data)
        except Exception as exc:
            raise HTTPException(status_code=422, detail=str(exc))

    background_tasks.add_task(_run_dispute_pipeline, payload)
    log.info("Chargeback queued for processing: %s", payload.chargeback_id)
    return {"accepted": True, "chargeback_id": payload.chargeback_id}


@app.post("/dispute/{chargeback_id}", status_code=status.HTTP_202_ACCEPTED)
async def trigger_dispute(
    chargeback_id: str,
    background_tasks: BackgroundTasks,
):
    """
    Manually trigger the dispute pipeline for an existing chargeback in the DB.
    Useful for retries or demo purposes.
    """
    cb = tidb.get_chargeback(chargeback_id)
    if not cb:
        raise HTTPException(status_code=404, detail=f"Chargeback {chargeback_id} not found")

    payload = ChargebackPayload(
        chargeback_id=cb["chargeback_id"],
        transaction_id=cb["transaction_id"],
        amount_cents=cb["amount_cents"],
        currency=cb.get("currency", "USD"),
        reason_code=cb.get("reason_code", "fraud"),
        reason_description=cb.get("reason_description", "unauthorized transaction"),
        evidence_due_by=str(cb.get("evidence_due_by", "")),
    )
    background_tasks.add_task(_run_dispute_pipeline, payload)
    return {"accepted": True, "chargeback_id": chargeback_id}


@app.get("/dispute/{chargeback_id}/status", response_model=DisputeStatus)
async def dispute_status(chargeback_id: str):
    cb = tidb.get_chargeback(chargeback_id)
    if not cb:
        raise HTTPException(status_code=404, detail=f"Chargeback {chargeback_id} not found")
    return DisputeStatus(
        chargeback_id=cb["chargeback_id"],
        status=cb["status"],
        pdf_path=cb.get("pdf_path"),
        dispute_submitted_at=str(cb["dispute_submitted_at"]) if cb.get("dispute_submitted_at") else None,
    )
