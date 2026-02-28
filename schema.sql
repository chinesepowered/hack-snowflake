-- TiDB Serverless schema for chargeback dispute agent
-- Run this once to bootstrap your database

CREATE DATABASE IF NOT EXISTS chargebacks;
USE chargebacks;

CREATE TABLE IF NOT EXISTS transactions (
    id            BIGINT AUTO_INCREMENT PRIMARY KEY,
    transaction_id VARCHAR(128) UNIQUE NOT NULL,
    customer_id   VARCHAR(128) NOT NULL,
    customer_email VARCHAR(255) NOT NULL,
    customer_name  VARCHAR(255),
    amount_cents   INT NOT NULL,
    currency       CHAR(3) NOT NULL DEFAULT 'USD',
    status         VARCHAR(32) NOT NULL DEFAULT 'completed', -- completed, refunded, disputed
    payment_method VARCHAR(64),          -- card_last4, type
    card_last4     CHAR(4),
    card_brand     VARCHAR(32),
    ip_address     VARCHAR(45),          -- IPv4 or IPv6
    user_agent     TEXT,
    billing_address TEXT,
    shipping_address TEXT,
    created_at     DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    metadata       JSON
);

CREATE TABLE IF NOT EXISTS chargebacks (
    id            BIGINT AUTO_INCREMENT PRIMARY KEY,
    chargeback_id  VARCHAR(128) UNIQUE NOT NULL,
    transaction_id VARCHAR(128) NOT NULL,
    reason_code    VARCHAR(64),
    reason_description TEXT,
    amount_cents   INT NOT NULL,
    currency       CHAR(3) NOT NULL DEFAULT 'USD',
    status         VARCHAR(32) NOT NULL DEFAULT 'open', -- open, won, lost, under_review
    evidence_due_by DATETIME,
    pdf_path       VARCHAR(512),
    dispute_submitted_at DATETIME,
    created_at     DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (transaction_id) REFERENCES transactions(transaction_id)
);

CREATE TABLE IF NOT EXISTS customer_history (
    id            BIGINT AUTO_INCREMENT PRIMARY KEY,
    customer_id   VARCHAR(128) NOT NULL,
    transaction_id VARCHAR(128) NOT NULL,
    event_type    VARCHAR(64) NOT NULL, -- purchase, login, address_change, refund
    event_at      DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    details       JSON,
    ip_address    VARCHAR(45),
    INDEX idx_customer (customer_id),
    INDEX idx_transaction (transaction_id)
);

-- Sample data for testing
INSERT IGNORE INTO transactions (transaction_id, customer_id, customer_email, customer_name, amount_cents, currency, status, payment_method, card_last4, card_brand, ip_address, user_agent, billing_address, shipping_address, created_at) VALUES
('txn_demo_001', 'cus_abc123', 'alice@example.com', 'Alice Smith', 9999, 'USD', 'completed', 'card', '4242', 'Visa', '192.168.1.100', 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)', '123 Main St, New York, NY 10001', '123 Main St, New York, NY 10001', NOW() - INTERVAL 10 DAY),
('txn_demo_002', 'cus_abc123', 'alice@example.com', 'Alice Smith', 4999, 'USD', 'completed', 'card', '4242', 'Visa', '192.168.1.100', 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)', '123 Main St, New York, NY 10001', '123 Main St, New York, NY 10001', NOW() - INTERVAL 5 DAY);

INSERT IGNORE INTO chargebacks (chargeback_id, transaction_id, reason_code, reason_description, amount_cents, currency, status, evidence_due_by) VALUES
('cb_demo_001', 'txn_demo_001', 'fraud', 'Customer claims transaction was unauthorized', 9999, 'USD', 'open', NOW() + INTERVAL 7 DAY);

INSERT IGNORE INTO customer_history (customer_id, transaction_id, event_type, event_at, ip_address, details) VALUES
('cus_abc123', 'txn_demo_001', 'login', NOW() - INTERVAL 10 DAY - INTERVAL 1 HOUR, '192.168.1.100', '{"device": "MacBook Pro", "location": "New York, NY"}'),
('cus_abc123', 'txn_demo_001', 'purchase', NOW() - INTERVAL 10 DAY, '192.168.1.100', '{"item": "Premium Plan", "quantity": 1}'),
('cus_abc123', 'txn_demo_002', 'purchase', NOW() - INTERVAL 5 DAY, '192.168.1.100', '{"item": "Add-on Feature", "quantity": 2}');
