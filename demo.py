"""
Demo script — runs the full dispute pipeline locally without a webhook.
Uses the sample data from schema.sql.

Usage:
    python demo.py
"""
import asyncio
import os
import sys

from dotenv import load_dotenv

load_dotenv()

# Demo chargeback from schema.sql
DEMO_CHARGEBACK_ID = "cb_demo_001"
DEMO_TRANSACTION_ID = "txn_demo_001"


def run_crew_and_generate_pdf():
    from agents.crew import run_dispute_crew
    from pdf.generator import generate_dispute_pdf

    chargeback_meta = {
        "chargeback_id": DEMO_CHARGEBACK_ID,
        "transaction_id": DEMO_TRANSACTION_ID,
        "amount_cents": 9999,
        "currency": "USD",
        "reason_code": "fraud",
        "reason_description": "Customer claims transaction was unauthorized",
        "evidence_due_by": "2026-03-07 00:00:00",
    }

    print(f"\n{'='*60}")
    print("  AI Chargeback Dispute Agent — Demo Run")
    print(f"{'='*60}")
    print(f"  Chargeback : {DEMO_CHARGEBACK_ID}")
    print(f"  Transaction: {DEMO_TRANSACTION_ID}")
    print(f"{'='*60}\n")

    print("[1/2] Running CrewAI agent pipeline...")
    evidence = run_dispute_crew(
        chargeback_id=DEMO_CHARGEBACK_ID,
        transaction_id=DEMO_TRANSACTION_ID,
        chargeback_meta=chargeback_meta,
    )

    print("\n[2/2] Generating PDF evidence package...")
    pdf_path = generate_dispute_pdf(evidence, output_dir="./output")

    print(f"\n{'='*60}")
    print(f"  PDF generated: {pdf_path}")
    print(f"{'='*60}\n")
    return pdf_path


if __name__ == "__main__":
    # Quick env check
    missing = [k for k in ("TIDB_HOST", "TIDB_USER", "TIDB_PASSWORD", "ANTHROPIC_API_KEY") if not os.environ.get(k)]
    if missing:
        print(f"ERROR: Missing required env vars: {', '.join(missing)}")
        print("Copy .env.example to .env and fill in your credentials.")
        sys.exit(1)

    run_crew_and_generate_pdf()
