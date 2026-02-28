"""
Custom CrewAI tools that wrap database queries and external enrichment APIs.
Skyfire is used to autonomously pay for IP geolocation / identity enrichment calls.
"""
import json
import os
from typing import Optional, Type

import httpx
from crewai.tools import BaseTool
from pydantic import BaseModel, Field

from db import tidb


# ---------------------------------------------------------------------------
# Input schemas
# ---------------------------------------------------------------------------

class TransactionInput(BaseModel):
    transaction_id: str = Field(description="The payment processor transaction ID")


class ChargebackInput(BaseModel):
    chargeback_id: str = Field(description="The chargeback / dispute ID")


class CustomerInput(BaseModel):
    customer_id: str = Field(description="The internal customer ID")


class IpInput(BaseModel):
    ip_address: str = Field(description="IPv4 or IPv6 address to look up")


# ---------------------------------------------------------------------------
# DB tools
# ---------------------------------------------------------------------------

class FetchTransactionTool(BaseTool):
    name: str = "fetch_transaction"
    description: str = (
        "Fetches full transaction details from TiDB Serverless given a transaction_id. "
        "Returns customer info, amount, IP address, billing/shipping address, card details, and timestamps."
    )
    args_schema: Type[BaseModel] = TransactionInput

    def _run(self, transaction_id: str) -> str:
        row = tidb.get_transaction(transaction_id)
        if not row:
            return f"No transaction found for id={transaction_id}"
        return json.dumps(row, default=str)


class FetchCustomerHistoryTool(BaseTool):
    name: str = "fetch_customer_history"
    description: str = (
        "Fetches the full purchase history and event log (logins, address changes) "
        "for a customer from TiDB Serverless. Useful for showing a pattern of legitimate activity."
    )
    args_schema: Type[BaseModel] = CustomerInput

    def _run(self, customer_id: str) -> str:
        txns = tidb.get_customer_transaction_history(customer_id)
        events = tidb.get_customer_event_history(customer_id)
        return json.dumps({"transactions": txns, "events": events}, default=str)


class FetchIpTransactionsTool(BaseTool):
    name: str = "fetch_ip_transactions"
    description: str = (
        "Fetches all transactions originating from a given IP address. "
        "Useful for showing the IP was used legitimately across multiple sessions."
    )
    args_schema: Type[BaseModel] = IpInput

    def _run(self, ip_address: str) -> str:
        rows = tidb.get_ip_transactions(ip_address)
        return json.dumps(rows, default=str)


# ---------------------------------------------------------------------------
# Skyfire-powered IP enrichment tool
# ---------------------------------------------------------------------------

class IpEnrichmentTool(BaseTool):
    name: str = "enrich_ip_address"
    description: str = (
        "Looks up geolocation, ISP, and fraud-risk signals for an IP address. "
        "Uses Skyfire to autonomously pay for the enrichment API call."
    )
    args_schema: Type[BaseModel] = IpInput

    def _run(self, ip_address: str) -> str:
        skyfire_key = os.environ.get("SKYFIRE_API_KEY")
        ipinfo_token = os.environ.get("IPINFO_TOKEN")

        if skyfire_key:
            # Pay for the enrichment call via Skyfire before making it
            _skyfire_pay_for_call(skyfire_key, service="ipinfo", estimated_usd=0.001)

        if ipinfo_token:
            try:
                resp = httpx.get(
                    f"https://ipinfo.io/{ip_address}/json",
                    params={"token": ipinfo_token},
                    timeout=10,
                )
                resp.raise_for_status()
                return json.dumps(resp.json())
            except Exception as exc:
                return json.dumps({"error": str(exc), "ip": ip_address})

        # Fallback if no token configured
        return json.dumps({
            "ip": ip_address,
            "note": "Configure IPINFO_TOKEN for live geolocation data",
        })


def _skyfire_pay_for_call(api_key: str, service: str, estimated_usd: float) -> None:
    """
    Initiate a micro-payment through Skyfire so the agent autonomously covers
    the cost of the enrichment API call it is about to make.
    """
    skyfire_url = os.environ.get("SKYFIRE_API_URL", "https://api.skyfire.xyz")
    try:
        httpx.post(
            f"{skyfire_url}/v1/payments",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={
                "service": service,
                "amount_usd": estimated_usd,
                "memo": f"Chargeback dispute enrichment — {service}",
            },
            timeout=8,
        )
    except Exception:
        # Non-fatal: enrichment call proceeds regardless
        pass
