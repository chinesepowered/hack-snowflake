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
import ssl
import sys
from urllib.parse import parse_qs, urlparse

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
        use_ssl = bool(ssl_params & {k.lower() for k in qs})
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
        kwargs["ssl"] = ssl.create_default_context()

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
]

CHARGEBACKS = [
    ("cb_demo_001", "txn_demo_001", "fraud",
     "Customer claims transaction was unauthorized", 9999, "USD",
     "open", "NOW() + INTERVAL 7 DAY"),
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

def main():
    conn_kwargs, database = _get_conn_kwargs()

    print(f"Connecting to {conn_kwargs.get('host')}:{conn_kwargs.get('port')} ...")

    # Step 1: ensure database exists (connect without selecting it)
    with pymysql.connect(**conn_kwargs, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(f"CREATE DATABASE IF NOT EXISTS `{database}`")
            print(f"Database `{database}` ready.")

    # Step 2: connect to the database and create tables
    with pymysql.connect(**conn_kwargs, database=database,
                         cursorclass=pymysql.cursors.DictCursor, autocommit=True) as conn:
        with conn.cursor() as cur:
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
    print("  Transactions : txn_demo_001, txn_demo_002, txn_demo_003")
    print("  Chargeback   : cb_demo_001  (status=open, 7 days to respond)")
    print("  Customer     : cus_abc123 / alice@example.com")
    print()
    print("To trigger the dispute pipeline:")
    print("  uv run uvicorn main:app --reload")
    print("  curl -X POST http://localhost:8000/dispute/cb_demo_001")


if __name__ == "__main__":
    main()
