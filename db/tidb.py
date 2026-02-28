"""
TiDB Serverless (MySQL-compatible) database layer.
Handles all queries for transaction history, chargeback records, and customer events.
"""
import os
from datetime import datetime
from typing import Optional

import pymysql
import pymysql.cursors
from dotenv import load_dotenv

load_dotenv()


def _get_connection():
    return pymysql.connect(
        host=os.environ["TIDB_HOST"],
        port=int(os.environ.get("TIDB_PORT", 4000)),
        user=os.environ["TIDB_USER"],
        password=os.environ["TIDB_PASSWORD"],
        database=os.environ["TIDB_DATABASE"],
        ssl={"ssl_mode": "VERIFY_IDENTITY"},
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
