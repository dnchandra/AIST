-- AIST LoanOrigination SQLite Schema
-- Deployed to RHEL 10: /opt/aist/ticketflow-api/loanorigination.db

CREATE TABLE IF NOT EXISTS applicants (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    username    TEXT UNIQUE NOT NULL,
    full_name   TEXT NOT NULL,
    email       TEXT NOT NULL,
    phone       TEXT,
    created_at  DATETIME DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS loan_applications (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    applicant_id    INTEGER NOT NULL REFERENCES applicants(id),
    loan_type       TEXT NOT NULL CHECK(loan_type IN ('personal','mortgage','auto','business')),
    amount          REAL NOT NULL CHECK(amount > 0),
    term_months     INTEGER NOT NULL CHECK(term_months > 0),
    purpose         TEXT,
    status          TEXT NOT NULL DEFAULT 'submitted'
                    CHECK(status IN ('submitted','under_review','ai_assessed','approved','rejected','disbursed')),
    interest_rate   REAL,
    monthly_payment REAL,
    ai_risk_score   REAL,
    ai_confidence   REAL,
    ai_reasoning    TEXT,
    officer_notes   TEXT,
    decided_by      TEXT,
    decided_at      DATETIME,
    created_at      DATETIME DEFAULT (datetime('now')),
    updated_at      DATETIME DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS documents (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    application_id  INTEGER NOT NULL REFERENCES loan_applications(id),
    doc_type        TEXT NOT NULL CHECK(doc_type IN ('id_proof','income_proof','address_proof','bank_statement','other')),
    filename        TEXT NOT NULL,
    uploaded_at     DATETIME DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS notifications_log (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    application_id  INTEGER,
    recipient       TEXT NOT NULL,
    channel         TEXT NOT NULL CHECK(channel IN ('webhook','email','sms')),
    message         TEXT NOT NULL,
    status          TEXT DEFAULT 'sent',
    created_at      DATETIME DEFAULT (datetime('now'))
);

-- Seed demo applicant profiles (matched to Auth Gateway users)
INSERT OR IGNORE INTO applicants (username, full_name, email, phone) VALUES
    ('applicant1', 'Alex Thompson', 'alex.thompson@aist.local', '+1-555-0101'),
    ('applicant2', 'Maria Rodriguez', 'maria.rodriguez@aist.local', '+1-555-0102'),
    ('admin', 'System Administrator', 'admin@aist.local', '+1-555-0100'),
    ('john.officer', 'John Rivera', 'john.rivera@aist.local', '+1-555-0103'),
    ('sarah.manager', 'Sarah Chen', 'sarah.chen@aist.local', '+1-555-0104');

