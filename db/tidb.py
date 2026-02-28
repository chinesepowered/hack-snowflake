"""
TiDB Serverless (MySQL-compatible) database layer.
Handles all queries for transaction history, chargeback records, and customer events.

Connection priority:
  1. DATABASE_URL  e.g. mysql://user:pass@host:4000/db?sslaccept=strict
  2. Individual TIDB_HOST / TIDB_USER / TIDB_PASSWORD / TIDB_DATABASE vars
"""
import os
from datetime import datetime
from typing import Optional
from urllib.parse import parse_qs, urlparse

import pymysql
import pymysql.cursors
from dotenv import load_dotenv

load_dotenv()


def _parse_database_url(url: str) -> dict:
    """Parse a mysql:// or mysql+pymysql:// URL into pymysql connect kwargs."""
    parsed = urlparse(url)
    # Strip driver prefix (mysql+pymysql → mysql)
    qs = parse_qs(parsed.query)
    # Detect SSL from common query params
    ssl_params = {"sslaccept", "ssl", "ssl_mode", "tls"}
    use_ssl = bool(ssl_params & set(k.lower() for k in qs))
    return {
        "host": parsed.hostname,
        "port": parsed.port or 4000,
        "user": parsed.username,
        "password": parsed.password,
        "database": (parsed.path or "").lstrip("/") or None,
        "_use_ssl": use_ssl,
    }


def _get_connection():
    database_url = os.environ.get("DATABASE_URL", "")
    if database_url:
        kwargs = _parse_database_url(database_url)
        use_ssl = kwargs.pop("_use_ssl", True)
    else:
        kwargs = {
            "host": os.environ["TIDB_HOST"],
            "port": int(os.environ.get("TIDB_PORT", 4000)),
            "user": os.environ["TIDB_USER"],
            "password": os.environ["TIDB_PASSWORD"],
            "database": os.environ["TIDB_DATABASE"],
        }
        use_ssl = True  # TiDB Serverless always requires SSL

    if use_ssl:
        kwargs["ssl_verify_cert"] = True
        kwargs["ssl_verify_identity"] = True

    return pymysql.connect(
        **kwargs,
        cursorclass=pymysql.cursors.DictCursor,
        autocommit=True,
    )


def get_transaction(transaction_id: str) -> Optional[dict]:
    with _get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT * FROM transactions WHERE transaction_id = %s",
                (transaction_id,),
            )
            return cur.fetchone()


def get_chargeback(chargeback_id: str) -> Optional[dict]:
    with _get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT * FROM chargebacks WHERE chargeback_id = %s",
                (chargeback_id,),
            )
            return cur.fetchone()


def get_customer_transaction_history(customer_id: str, limit: int = 20) -> list[dict]:
    """All transactions for this customer, newest first."""
    with _get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT transaction_id, amount_cents, currency, status,
                       card_last4, card_brand, ip_address, created_at
                FROM transactions
                WHERE customer_id = %s
                ORDER BY created_at DESC
                LIMIT %s
                """,
                (customer_id, limit),
            )
            return cur.fetchall()


def get_customer_event_history(customer_id: str, limit: int = 30) -> list[dict]:
    """Login, purchase, and address-change events for this customer."""
    with _get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT event_type, event_at, ip_address, details
                FROM customer_history
                WHERE customer_id = %s
                ORDER BY event_at DESC
                LIMIT %s
                """,
                (customer_id, limit),
            )
            return cur.fetchall()


def get_ip_transactions(ip_address: str) -> list[dict]:
    """All transactions from the same IP — helps show pattern of legitimate use."""
    with _get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT transaction_id, customer_id, customer_email, amount_cents,
                       currency, status, created_at
                FROM transactions
                WHERE ip_address = %s
                ORDER BY created_at DESC
                LIMIT 50
                """,
                (ip_address,),
            )
            return cur.fetchall()


def update_chargeback_status(
    chargeback_id: str,
    status: str,
    pdf_path: Optional[str] = None,
    submitted_at: Optional[datetime] = None,
) -> None:
    with _get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE chargebacks
                SET status = %s,
                    pdf_path = COALESCE(%s, pdf_path),
                    dispute_submitted_at = COALESCE(%s, dispute_submitted_at)
                WHERE chargeback_id = %s
                """,
                (status, pdf_path, submitted_at, chargeback_id),
            )
