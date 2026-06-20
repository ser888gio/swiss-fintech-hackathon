-- Maersk fleet persistence upgrade (PostgreSQL).
-- New tables are also represented in SQLAlchemy metadata; these ALTERs preserve
-- existing service_payments rows during a Railway deployment.

ALTER TABLE service_payments ADD COLUMN IF NOT EXISTS agent_id VARCHAR;
ALTER TABLE service_payments ADD COLUMN IF NOT EXISTS status VARCHAR DEFAULT 'settled';
ALTER TABLE service_payments ADD COLUMN IF NOT EXISTS cover JSON;
CREATE INDEX IF NOT EXISTS ix_service_payments_agent_id ON service_payments (agent_id);
CREATE INDEX IF NOT EXISTS ix_service_payments_status ON service_payments (status);

CREATE TABLE IF NOT EXISTS agent_spend_reservations (
    id VARCHAR PRIMARY KEY,
    agent_id VARCHAR NOT NULL,
    idempotency_key VARCHAR NOT NULL,
    amount VARCHAR NOT NULL,
    currency VARCHAR NOT NULL,
    status VARCHAR NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_agent_spend_reservation UNIQUE (agent_id, idempotency_key)
);

CREATE TABLE IF NOT EXISTS treasury_goals (
    id VARCHAR PRIMARY KEY,
    agent_id VARCHAR,
    payload JSON NOT NULL,
    last_triggered_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS treasury_agent_runs (
    id VARCHAR PRIMARY KEY,
    agent_id VARCHAR,
    payload JSON NOT NULL,
    started_at TIMESTAMPTZ NOT NULL,
    completed_at TIMESTAMPTZ
);
