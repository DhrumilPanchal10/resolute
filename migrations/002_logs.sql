-- ---------------------------------------------------------------------------
-- Migration 002 — application event logs
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS logs (
    id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id   UUID NOT NULL REFERENCES tenants(id)  ON DELETE CASCADE,
    account_id  UUID NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    level       TEXT NOT NULL DEFAULT 'INFO',   -- INFO | WARN | ERROR
    message     TEXT NOT NULL,
    occurred_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- GIN index for fast full-text search over log messages
CREATE INDEX IF NOT EXISTS logs_fts_idx
    ON logs USING GIN (to_tsvector('english', message));

-- Composite index for the common query pattern: account + time range
CREATE INDEX IF NOT EXISTS logs_account_time_idx
    ON logs (account_id, occurred_at DESC);

ALTER TABLE logs ENABLE ROW LEVEL SECURITY;

CREATE POLICY logs_tenant_isolation ON logs
    USING (tenant_id = current_setting('app.tenant_id', TRUE)::UUID);

GRANT SELECT, INSERT ON logs TO app_user;
