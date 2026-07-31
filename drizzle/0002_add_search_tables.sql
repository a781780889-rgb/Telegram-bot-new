-- ============================================================
-- Migration: Add search system tables
-- ============================================================
-- Run this against your PostgreSQL database manually, or use
-- Alembic: alembic revision --autogenerate -m "add_search_tables"
-- ============================================================

-- ── search_jobs ──────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS search_jobs (
    id              BIGSERIAL PRIMARY KEY,
    user_id         BIGINT        NOT NULL REFERENCES users(id),

    platform        VARCHAR(20)   NOT NULL,   -- telegram|whatsapp|both
    depth           VARCHAR(10)   NOT NULL DEFAULT 'normal',  -- fast|normal|deep
    period          VARCHAR(10)   NOT NULL DEFAULT 'week',    -- day|week|month|year|custom
    period_from     TIMESTAMPTZ,
    period_to       TIMESTAMPTZ,

    account_ids     JSONB,
    link_types_config JSONB,
    max_results     BIGINT        NOT NULL DEFAULT 1000,
    dedup_enabled   BOOLEAN       NOT NULL DEFAULT TRUE,
    compare_db      BOOLEAN       NOT NULL DEFAULT TRUE,
    save_new        BOOLEAN       NOT NULL DEFAULT TRUE,
    skip_invalid    BOOLEAN       NOT NULL DEFAULT TRUE,

    status          VARCHAR(20)   NOT NULL DEFAULT 'pending',

    found_total     BIGINT        NOT NULL DEFAULT 0,
    found_new       BIGINT        NOT NULL DEFAULT 0,
    found_duplicate BIGINT        NOT NULL DEFAULT 0,
    found_invalid   BIGINT        NOT NULL DEFAULT 0,
    found_telegram  BIGINT        NOT NULL DEFAULT 0,
    found_whatsapp  BIGINT        NOT NULL DEFAULT 0,

    started_at      TIMESTAMPTZ,
    finished_at     TIMESTAMPTZ,
    created_at      TIMESTAMPTZ   NOT NULL DEFAULT NOW(),

    error_log       TEXT,
    chat_id         BIGINT,
    message_id      BIGINT
);

CREATE INDEX IF NOT EXISTS ix_search_jobs_user_id ON search_jobs (user_id);
CREATE INDEX IF NOT EXISTS ix_search_jobs_status  ON search_jobs (status);

-- ── discovered_links ─────────────────────────────────────────

CREATE TABLE IF NOT EXISTS discovered_links (
    id              BIGSERIAL PRIMARY KEY,

    platform        VARCHAR(20)   NOT NULL,  -- telegram|whatsapp
    link_type       VARCHAR(20)   NOT NULL DEFAULT 'unknown',

    original_url    TEXT          NOT NULL,
    normalized_url  TEXT          NOT NULL,
    url_hash        VARCHAR(64)   NOT NULL,

    title           VARCHAR(512),
    username        VARCHAR(128),

    source              VARCHAR(128),
    source_account_id   BIGINT REFERENCES accounts(id),
    search_id           BIGINT REFERENCES search_jobs(id),

    status          VARCHAR(20)   NOT NULL DEFAULT 'valid',
    is_duplicate    BOOLEAN       NOT NULL DEFAULT FALSE,

    first_seen_at   TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
    last_seen_at    TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
    metadata_json   JSONB,

    created_at      TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ
);

-- The critical unique constraint — prevents any duplicate, even under concurrency
ALTER TABLE discovered_links
    ADD CONSTRAINT uq_link_platform_hash UNIQUE (platform, url_hash);

CREATE INDEX IF NOT EXISTS ix_link_platform_hash  ON discovered_links (platform, url_hash);
CREATE INDEX IF NOT EXISTS ix_link_search_id      ON discovered_links (search_id);
CREATE INDEX IF NOT EXISTS ix_link_platform       ON discovered_links (platform);
CREATE INDEX IF NOT EXISTS ix_link_created_at     ON discovered_links (created_at);
CREATE INDEX IF NOT EXISTS ix_link_status         ON discovered_links (status);

-- ── duplicate_records ────────────────────────────────────────

CREATE TABLE IF NOT EXISTS duplicate_records (
    id                  BIGSERIAL PRIMARY KEY,

    original_url        TEXT          NOT NULL,
    normalized_url      TEXT          NOT NULL,
    url_hash            VARCHAR(64)   NOT NULL,
    platform            VARCHAR(20)   NOT NULL,

    search_id           BIGINT REFERENCES search_jobs(id),
    existing_link_id    BIGINT REFERENCES discovered_links(id),
    source_account_id   BIGINT REFERENCES accounts(id),

    source              VARCHAR(128),
    detected_at         TIMESTAMPTZ   NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_dup_search_id      ON duplicate_records (search_id);
CREATE INDEX IF NOT EXISTS ix_dup_link_id        ON duplicate_records (existing_link_id);
CREATE INDEX IF NOT EXISTS ix_dup_detected_at    ON duplicate_records (detected_at);
