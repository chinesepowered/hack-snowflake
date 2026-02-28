"""
Seed script — creates tables and inserts sample data.

Reads the database connection from .env:
  DATABASE_URL=mysql://user:pass@host:4000/chargebacks?sslaccept=strict

  OR individual vars:
  TIDB_HOST / TIDB_USER / TIDB_PASSWORD / TIDB_DATABASE / TIDB_PORT

Usage:
    uv run seed.py          # with uv
    python seed.py          # with plain python (after pip install -r requirements.txt)
"""
import os
import sys
from urllib.parse import parse_qs, urlparse

import certifi
import pymysql
import pymysql.cursors
from dotenv import load_dotenv

load_dotenv()


# ---------------------------------------------------------------------------
# Connection
# ---------------------------------------------------------------------------

def _get_conn_kwargs() -> tuple[dict, str]:
    """Return (pymysql connect kwargs, database name)."""
    url = os.environ.get("DATABASE_URL", "")
    if url:
        parsed = urlparse(url)
        qs = parse_qs(parsed.query)
        ssl_params = {"sslaccept", "ssl", "ssl_mode", "tls"}
        # Default to SSL on; only disable if URL explicitly says ssl=false/0/disable
        no_ssl_values = {"false", "0", "disable", "no", "none"}
        use_ssl = not any(
            str(v[0]).lower() in no_ssl_values
            for k, v in qs.items()
            if k.lower() in ssl_params
        )
        database = (parsed.path or "").lstrip("/") or "chargebacks"
        kwargs = {
            "host": parsed.hostname,
            "port": parsed.port or 4000,
            "user": parsed.username,
            "password": parsed.password,
        }
    else:
        missing = [k for k in ("TIDB_HOST", "TIDB_USER", "TIDB_PASSWORD") if not os.environ.get(k)]
        if missing:
            print(f"ERROR: Missing env vars: {', '.join(missing)}")
            print("Set DATABASE_URL or individual TIDB_* vars in .env")
            sys.exit(1)
        use_ssl = True
        database = os.environ.get("TIDB_DATABASE", "chargebacks")
        kwargs = {
            "host": os.environ["TIDB_HOST"],
            "port": int(os.environ.get("TIDB_PORT", 4000)),
            "user": os.environ["TIDB_USER"],
            "password": os.environ["TIDB_PASSWORD"],
        }

    if use_ssl:
        kwargs["ssl"] = {"ca": certifi.where()}

    return kwargs, database


def get_connection(database: str | None = None, kwargs: dict | None = None):
    base_kwargs, db_name = kwargs or _get_conn_kwargs()
    if isinstance(base_kwargs, tuple):
        base_kwargs, db_name = base_kwargs
    conn_kwargs = {**base_kwargs}
    if database is not None:
        conn_kwargs["database"] = database
    return pymysql.connect(
        **conn_kwargs,
        cursorclass=pymysql.cursors.DictCursor,
        autocommit=True,
    )


# ---------------------------------------------------------------------------
# DDL
# ---------------------------------------------------------------------------

CREATE_TABLES = """
CREATE TABLE IF NOT EXISTS transactions (
    id               BIGINT AUTO_INCREMENT PRIMARY KEY,
    transaction_id   VARCHAR(128) UNIQUE NOT NULL,
    customer_id      VARCHAR(128) NOT NULL,
    customer_email   VARCHAR(255) NOT NULL,
    customer_name    VARCHAR(255),
    amount_cents     INT NOT NULL,
    currency         CHAR(3) NOT NULL DEFAULT 'USD',
    status           VARCHAR(32) NOT NULL DEFAULT 'completed',
    payment_method   VARCHAR(64),
    card_last4       CHAR(4),
    card_brand       VARCHAR(32),
    ip_address       VARCHAR(45),
    user_agent       TEXT,
    billing_address  TEXT,
    shipping_address TEXT,
    created_at       DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    metadata         JSON
);

CREATE TABLE IF NOT EXISTS chargebacks (
    id                   BIGINT AUTO_INCREMENT PRIMARY KEY,
    chargeback_id        VARCHAR(128) UNIQUE NOT NULL,
    transaction_id       VARCHAR(128) NOT NULL,
    reason_code          VARCHAR(64),
    reason_description   TEXT,
    amount_cents         INT NOT NULL,
    currency             CHAR(3) NOT NULL DEFAULT 'USD',
    status               VARCHAR(32) NOT NULL DEFAULT 'open',
    evidence_due_by      DATETIME,
    pdf_path             VARCHAR(512),
    dispute_submitted_at DATETIME,
    created_at           DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (transaction_id) REFERENCES transactions(transaction_id)
);

CREATE TABLE IF NOT EXISTS customer_history (
    id             BIGINT AUTO_INCREMENT PRIMARY KEY,
    customer_id    VARCHAR(128) NOT NULL,
    transaction_id VARCHAR(128) NOT NULL,
    event_type     VARCHAR(64) NOT NULL,
    event_at       DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    details        JSON,
    ip_address     VARCHAR(45),
    INDEX idx_customer (customer_id),
    INDEX idx_transaction (transaction_id)
);
"""

# ---------------------------------------------------------------------------
# Sample data
# ---------------------------------------------------------------------------

TRANSACTIONS = [
    # Alice — 3 purchases, same card, same IP, legitimate pattern
    ("txn_demo_001", "cus_abc123", "alice@example.com", "Alice Smith",
     9999, "USD", "completed", "card", "4242", "Visa",
     "203.0.113.42", "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
     "123 Main St, New York, NY 10001", "123 Main St, New York, NY 10001",
     "NOW() - INTERVAL 30 DAY"),
    ("txn_demo_002", "cus_abc123", "alice@example.com", "Alice Smith",
     4999, "USD", "completed", "card", "4242", "Visa",
     "203.0.113.42", "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
     "123 Main St, New York, NY 10001", "123 Main St, New York, NY 10001",
     "NOW() - INTERVAL 15 DAY"),
    ("txn_demo_003", "cus_abc123", "alice@example.com", "Alice Smith",
     1999, "USD", "completed", "card", "4242", "Visa",
     "203.0.113.42", "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
     "123 Main St, New York, NY 10001", "123 Main St, New York, NY 10001",
     "NOW() - INTERVAL 5 DAY"),
    # Bob — 2 purchases, Mastercard, consistent IP
    ("txn_demo_004", "cus_bob456", "bob@example.com", "Bob Johnson",
     24999, "USD", "completed", "card", "5678", "Mastercard",
     "198.51.100.77", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
     "456 Oak Ave, Chicago, IL 60601", "456 Oak Ave, Chicago, IL 60601",
     "NOW() - INTERVAL 45 DAY"),
    ("txn_demo_005", "cus_bob456", "bob@example.com", "Bob Johnson",
     2499, "USD", "completed", "card", "5678", "Mastercard",
     "198.51.100.77", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
     "456 Oak Ave, Chicago, IL 60601", "456 Oak Ave, Chicago, IL 60601",
     "NOW() - INTERVAL 20 DAY"),
    # Carol — 1 purchase, Amex
    ("txn_demo_006", "cus_carol789", "carol@example.com", "Carol Williams",
     5999, "USD", "completed", "card", "9876", "Amex",
     "203.0.113.15", "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15",
     "789 Pine St, Seattle, WA 98101", "789 Pine St, Seattle, WA 98101",
     "NOW() - INTERVAL 10 DAY"),
]

CHARGEBACKS = [
    ("cb_demo_001", "txn_demo_001", "fraud",
     "Customer claims transaction was unauthorized", 9999, "USD",
     "open", "NOW() + INTERVAL 7 DAY"),
    ("cb_demo_002", "txn_demo_004", "credit_not_processed",
     "Customer claims promised refund was never issued", 24999, "USD",
     "open", "NOW() + INTERVAL 14 DAY"),
    ("cb_demo_003", "txn_demo_006", "product_not_received",
     "Customer states item was never delivered", 5999, "USD",
     "open", "NOW() + INTERVAL 3 DAY"),
    ("cb_demo_004", "txn_demo_005", "duplicate",
     "Customer claims the same charge appears twice on their statement", 2499, "USD",
     "open", "NOW() + INTERVAL 10 DAY"),
    ("cb_demo_005", "txn_demo_003", "product_unacceptable",
     "Customer claims item received was significantly not as described", 1999, "USD",
     "open", "NOW() + INTERVAL 5 DAY"),
]

EVENTS = [
    ("cus_abc123", "txn_demo_001", "login",
     "NOW() - INTERVAL 30 DAY - INTERVAL 2 HOUR", "203.0.113.42",
     '{"device": "MacBook Pro", "browser": "Chrome 120", "location": "New York, NY"}'),
    ("cus_abc123", "txn_demo_001", "purchase",
     "NOW() - INTERVAL 30 DAY", "203.0.113.42",
     '{"item": "Premium Plan Annual", "quantity": 1, "sku": "PLAN-PREM-ANN"}'),
    ("cus_abc123", "txn_demo_002", "login",
     "NOW() - INTERVAL 15 DAY - INTERVAL 1 HOUR", "203.0.113.42",
     '{"device": "MacBook Pro", "browser": "Chrome 120", "location": "New York, NY"}'),
    ("cus_abc123", "txn_demo_002", "purchase",
     "NOW() - INTERVAL 15 DAY", "203.0.113.42",
     '{"item": "Add-on: Advanced Analytics", "quantity": 1, "sku": "ADDON-ANALYTICS"}'),
    ("cus_abc123", "txn_demo_003", "login",
     "NOW() - INTERVAL 5 DAY - INTERVAL 30 MINUTE", "203.0.113.42",
     '{"device": "MacBook Pro", "browser": "Chrome 120", "location": "New York, NY"}'),
    ("cus_abc123", "txn_demo_003", "purchase",
     "NOW() - INTERVAL 5 DAY", "203.0.113.42",
     '{"item": "Extra Seats x2", "quantity": 2, "sku": "SEAT-EXTRA"}'),
]


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def reset_chargebacks(cur) -> None:
    """Reset all demo chargebacks to open status (for re-demo without reseeding)."""
    ids = [cb[0] for cb in CHARGEBACKS]
    placeholders = ", ".join(["%s"] * len(ids))
    cur.execute(
        f"""UPDATE chargebacks
            SET status = 'open', pdf_path = NULL, dispute_submitted_at = NULL
            WHERE chargeback_id IN ({placeholders})""",
        ids,
    )
    print(f"Reset {len(ids)} chargebacks → status=open")


def main():
    reset_only = "--reset" in sys.argv

    conn_kwargs, database = _get_conn_kwargs()

    print(f"Connecting to {conn_kwargs.get('host')}:{conn_kwargs.get('port')} ...")

    # Step 1: ensure database exists (connect without selecting it)
    with pymysql.connect(**conn_kwargs, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(f"CREATE DATABASE IF NOT EXISTS `{database}`")
            print(f"Database `{database}` ready.")

    # Step 2: connect to the database and create tables / reset
    with pymysql.connect(**conn_kwargs, database=database,
                         cursorclass=pymysql.cursors.DictCursor, autocommit=True) as conn:
        with conn.cursor() as cur:
            if reset_only:
                reset_chargebacks(cur)
                print("Done. Re-run the dispute pipeline from the dashboard.")
                return

            print("Creating tables...")
            for stmt in CREATE_TABLES.strip().split(";"):
                stmt = stmt.strip()
                if stmt:
                    cur.execute(stmt)

            print("Inserting sample transactions...")
            for t in TRANSACTIONS:
                cur.execute(f"""
                    INSERT IGNORE INTO transactions
                        (transaction_id, customer_id, customer_email, customer_name,
                         amount_cents, currency, status, payment_method, card_last4, card_brand,
                         ip_address, user_agent, billing_address, shipping_address, created_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, {t[14]})
                """, t[:14])

            print("Inserting sample chargebacks...")
            for cb in CHARGEBACKS:
                cur.execute(f"""
                    INSERT IGNORE INTO chargebacks
                        (chargeback_id, transaction_id, reason_code, reason_description,
                         amount_cents, currency, status, evidence_due_by)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, {cb[7]})
                """, cb[:7])

            print("Inserting customer event history...")
            for ev in EVENTS:
                cur.execute(f"""
                    INSERT INTO customer_history
                        (customer_id, transaction_id, event_type, event_at, ip_address, details)
                    VALUES (%s, %s, %s, {ev[3]}, %s, %s)
                    ON DUPLICATE KEY UPDATE event_at = event_at
                """, (ev[0], ev[1], ev[2], ev[4], ev[5]))

    print()
    print("Done. Sample data loaded:")
    print("  Transactions : txn_demo_001–006  (Alice ×3, Bob ×2, Carol ×1)")
    print("  Chargebacks  : cb_demo_001–005  (fraud, credit_not_processed,")
    print("                  product_not_received, duplicate, product_unacceptable)")
    print()
    print("To trigger disputes:  uv run uvicorn main:app --reload")
    print("To reset for re-demo: uv run seed.py --reset")


if __name__ == "__main__":
    main()
