-- SalesPilot backend schema, version 1.
--
-- One row per opportunity: the columns a queue or a filter needs, plus the
-- complete profile as JSON in `payload`. Agent runs are stored the same way
-- (interface-v1 §5.3 shape in `payload`), indexed by the two keys the admin
-- console queries on.

CREATE TABLE IF NOT EXISTS schema_version (
    version    INTEGER PRIMARY KEY,
    applied_at TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS opportunities (
    id             TEXT PRIMARY KEY,
    customer_name  TEXT    NOT NULL,
    state          TEXT    NOT NULL,
    product        TEXT    NOT NULL,
    priority       TEXT,
    qualification  TEXT    NOT NULL,
    human_takeover INTEGER NOT NULL DEFAULT 0,
    updated_at     TEXT    NOT NULL,
    payload        TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS cases (
    id             TEXT PRIMARY KEY,
    opportunity_id TEXT NOT NULL,
    status         TEXT NOT NULL,
    created_at     TEXT NOT NULL,
    payload        TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS cases_opportunity ON cases (opportunity_id);

CREATE TABLE IF NOT EXISTS message_receipts (
    opportunity_id    TEXT    NOT NULL,
    client_message_id TEXT    NOT NULL,
    schema_version    INTEGER NOT NULL DEFAULT 1,
    document          TEXT    NOT NULL,
    created_at        TEXT    NOT NULL,
    PRIMARY KEY (opportunity_id, client_message_id)
);

CREATE TABLE IF NOT EXISTS agent_runs (
    run_id            TEXT PRIMARY KEY,
    opportunity_id    TEXT NOT NULL,
    client_message_id TEXT,
    status            TEXT NOT NULL,
    started_at        TEXT NOT NULL,
    payload           TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS agent_runs_opportunity ON agent_runs (opportunity_id, started_at);
CREATE INDEX IF NOT EXISTS agent_runs_client_message ON agent_runs (client_message_id);
