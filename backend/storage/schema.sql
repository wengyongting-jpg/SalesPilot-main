-- SalesPilot backend schema.
--
-- Messages, score history and state history have tables for incremental and indexed
-- reads. The opportunity payload remains the transcript source of truth; the
-- `messages` rows are maintained as a searchable projection for scoped recall.
--
-- Everything else that is genuinely a value object -- the scorecard, signal lists,
-- an agent run payload -- stays as JSON, because it is always read whole.

CREATE TABLE IF NOT EXISTS opportunities (
    id                          TEXT PRIMARY KEY,
    customer_name               TEXT NOT NULL,
    state                       TEXT NOT NULL,
    product                     TEXT NOT NULL,
    priority                    TEXT,
    signals                     TEXT NOT NULL DEFAULT '[]',
    signal_history              TEXT NOT NULL DEFAULT '[]',
    main_concern                TEXT,
    competitive_risk            INTEGER NOT NULL DEFAULT 0,
    churn_risk                  INTEGER NOT NULL DEFAULT 0,
    compliance_risk             INTEGER NOT NULL DEFAULT 0,
    expansion                   TEXT NOT NULL DEFAULT '[]',
    last_intent                 TEXT NOT NULL DEFAULT 'generic',
    best_intent                 TEXT NOT NULL DEFAULT 'generic',
    urgency_observed            INTEGER NOT NULL DEFAULT 0,
    -- Named for what it counts. `turns` is a read-only alias in the domain model and
    -- deliberately has no column, so no query can use the misleading name.
    customer_message_count      INTEGER NOT NULL DEFAULT 0,
    score                       TEXT,
    human_takeover              INTEGER NOT NULL DEFAULT 0,
    human_intervention_required INTEGER NOT NULL DEFAULT 0,
    pending_handoff_reason      TEXT,
    pending_question_field      TEXT,
    collected_answers           TEXT NOT NULL DEFAULT '{}',
    evidence_sources            TEXT NOT NULL DEFAULT '{}',
    qualification               TEXT NOT NULL DEFAULT 'qualified',
    qualification_reason        TEXT,
    solicitation_count          INTEGER NOT NULL DEFAULT 0,
    created_at                  TEXT NOT NULL,
    updated_at                  TEXT NOT NULL,
    payload                     TEXT NOT NULL DEFAULT '{}'
);

-- `seq` rather than a timestamp is the ordering key: two messages in the same
-- conversation can share a millisecond, and a transcript that reorders would
-- scramble the frontend's reconciliation.
CREATE TABLE IF NOT EXISTS messages (
    opportunity_id    TEXT NOT NULL,
    seq               INTEGER NOT NULL,
    id                TEXT NOT NULL,
    ts                TEXT NOT NULL,
    role              TEXT NOT NULL,
    author            TEXT,
    generation        TEXT,
    rep_name          TEXT,
    text              TEXT NOT NULL,
    client_message_id TEXT,
    PRIMARY KEY (opportunity_id, seq),
    FOREIGN KEY (opportunity_id) REFERENCES opportunities(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_messages_id ON messages(opportunity_id, id);
CREATE INDEX IF NOT EXISTS idx_messages_opportunity_seq ON messages(opportunity_id, seq DESC);

CREATE TABLE IF NOT EXISTS conversation_memory (
    opportunity_id TEXT PRIMARY KEY,
    version        INTEGER NOT NULL DEFAULT 1,
    payload        TEXT NOT NULL,
    updated_at     TEXT NOT NULL,
    FOREIGN KEY (opportunity_id) REFERENCES opportunities(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS score_history (
    opportunity_id TEXT NOT NULL,
    seq            INTEGER NOT NULL,
    ts             TEXT NOT NULL,
    score          INTEGER NOT NULL,
    state          TEXT NOT NULL,
    trigger        TEXT NOT NULL,
    evidence       TEXT NOT NULL DEFAULT '{}',
    PRIMARY KEY (opportunity_id, seq),
    FOREIGN KEY (opportunity_id) REFERENCES opportunities(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS state_history (
    opportunity_id TEXT NOT NULL,
    seq            INTEGER NOT NULL,
    ts             TEXT NOT NULL,
    from_state     TEXT NOT NULL,
    to_state       TEXT NOT NULL,
    reason         TEXT NOT NULL,
    PRIMARY KEY (opportunity_id, seq),
    FOREIGN KEY (opportunity_id) REFERENCES opportunities(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS cases (
    id                 TEXT PRIMARY KEY,
    opportunity_id     TEXT NOT NULL,
    customer_name      TEXT NOT NULL,
    state              TEXT NOT NULL,
    product            TEXT NOT NULL,
    reason             TEXT NOT NULL,
    summary            TEXT NOT NULL,
    recommended_action TEXT NOT NULL,
    status             TEXT NOT NULL,
    created_at         TEXT NOT NULL,
    payload            TEXT NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_cases_opportunity
    ON cases(opportunity_id, status);

-- Idempotency receipts. Persisted rather than held in process memory because a retry
-- usually happens when the client never saw the response, and a deploy or a crash
-- looks exactly like that from the client's side.
CREATE TABLE IF NOT EXISTS message_receipts (
    opportunity_id    TEXT NOT NULL,
    client_message_id TEXT NOT NULL,
    schema_version    INTEGER NOT NULL DEFAULT 1,
    response          TEXT NOT NULL,
    document          TEXT NOT NULL DEFAULT '{}',
    created_at        TEXT NOT NULL,
    PRIMARY KEY (opportunity_id, client_message_id)
);

-- One row per agent run, retained per message rather than overwritten, so the admin
-- Inbox can show history instead of only the latest exchange (interface-v1 5.3.5).
-- The queryable columns are duplicated out of the payload so a listing does not have
-- to parse every blob.
CREATE TABLE IF NOT EXISTS agent_runs (
    run_id            TEXT PRIMARY KEY,
    opportunity_id    TEXT NOT NULL,
    client_message_id TEXT,
    status            TEXT NOT NULL,
    started_at        TEXT,
    duration_ms       INTEGER NOT NULL DEFAULT 0,
    total_tokens      INTEGER NOT NULL DEFAULT 0,
    cost_amount       REAL NOT NULL DEFAULT 0,
    cost_currency     TEXT NOT NULL DEFAULT 'USD',
    pricing_known     INTEGER NOT NULL DEFAULT 1,
    payload           TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_runs_opportunity
    ON agent_runs(opportunity_id, started_at);
CREATE INDEX IF NOT EXISTS idx_runs_client_message
    ON agent_runs(opportunity_id, client_message_id);
