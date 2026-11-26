-- Pact commit statuses — PFX-4.4 (#6941).
--
-- When a pact is published or a verification result arrives, Apiome puts the verdict of each
-- consumer ↔ provider pair back on the commit it is about: a GitHub commit status or a GitLab
-- commit status, written through the repository the tenant registered (its linked account's
-- stored credential). This table is the record of every such status:
--
--   pact_commit_status — the latest verdict for one context (`apiome-pact/<consumer>/<provider>`)
--                        on one pacticipant version, where it was sent, and what happened.
--
-- Rules kept by the database:
--
--   1. **One row per version and context.** A newer verdict for the same pair on the same commit
--      moves the row (GitHub and GitLab upsert a status by its context the same way).
--   2. **Nothing is dropped silently.** A verdict that could not be sent is still a row, with
--      `outcome = 'suppressed'` (never attempted: no repository, not a commit SHA, unsupported
--      provider, no credential, switched off) or `'failed'` (the provider refused), and a reason.
--   3. **States and outcomes are closed lists**, checked here and by apiome-rest
--      (`app.pact_commit_status`).
--   4. **Nothing crosses a tenant.** The pacticipant, consumer and provider are named by
--      `(id, tenant_id)`; a status goes with its pacticipant and its version.
--
-- No secret is stored: the token is resolved from the registered repository at send time and
-- never written anywhere.
--
-- Online: one new table; nothing existing is rewritten.
--
-- Rollback notes:
--   DROP TABLE IF EXISTS apiome.pact_commit_status;

SET search_path TO apiome, public;

CREATE TABLE IF NOT EXISTS pact_commit_status (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,

    -- The pacticipant whose repository the status goes to, and the version (commit) it is about.
    pacticipant_id UUID NOT NULL,
    pacticipant_version_id UUID NOT NULL,
    -- The pair the verdict is about. `side` says which of the two the status is posted for.
    consumer_id UUID NOT NULL,
    provider_id UUID NOT NULL,
    side TEXT NOT NULL
        CONSTRAINT pact_commit_status_side_check CHECK (side IN ('consumer', 'provider')),

    -- The status context, e.g. `apiome-pact/web-app/billing-api`.
    context TEXT NOT NULL
        CONSTRAINT pact_commit_status_context_check
            CHECK (length(btrim(context)) >= 1 AND length(context) <= 255),
    state TEXT NOT NULL
        CONSTRAINT pact_commit_status_state_check CHECK (state IN ('pending', 'pass', 'fail')),
    description TEXT NOT NULL DEFAULT ''
        CONSTRAINT pact_commit_status_description_check CHECK (length(description) <= 255),
    target_url TEXT
        CONSTRAINT pact_commit_status_target_url_check
            CHECK (target_url IS NULL
                   OR (target_url ~* '^https?://[^[:space:]]+$' AND length(target_url) <= 2048)),
    -- The pact content and the verification result that produced the verdict, when there is one.
    pact_version_sha TEXT,
    verification_number INTEGER,

    -- Where it was sent: the registered repository, its provider and full name, and the commit.
    commit_sha TEXT,
    repository_id UUID REFERENCES tenant_repositories(id) ON DELETE SET NULL,
    provider TEXT,
    repo_full_name TEXT,

    -- What happened to the send.
    outcome TEXT NOT NULL
        CONSTRAINT pact_commit_status_outcome_check
            CHECK (outcome IN ('queued', 'dispatched', 'suppressed', 'failed')),
    reason_code TEXT,
    message TEXT NOT NULL DEFAULT ''
        CONSTRAINT pact_commit_status_message_check CHECK (length(message) <= 2000),
    http_status INTEGER,
    attempts INTEGER NOT NULL DEFAULT 0
        CONSTRAINT pact_commit_status_attempts_check CHECK (attempts >= 0),

    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT pact_commit_status_context_key UNIQUE (tenant_id, pacticipant_version_id, context),
    CONSTRAINT pact_commit_status_pacticipant_fk
        FOREIGN KEY (pacticipant_id, tenant_id)
        REFERENCES pacticipant (id, tenant_id) ON DELETE CASCADE,
    CONSTRAINT pact_commit_status_version_fk
        FOREIGN KEY (pacticipant_version_id, pacticipant_id)
        REFERENCES pacticipant_version (id, pacticipant_id) ON DELETE CASCADE,
    CONSTRAINT pact_commit_status_consumer_fk
        FOREIGN KEY (consumer_id, tenant_id)
        REFERENCES pacticipant (id, tenant_id) ON DELETE CASCADE,
    CONSTRAINT pact_commit_status_provider_fk
        FOREIGN KEY (provider_id, tenant_id)
        REFERENCES pacticipant (id, tenant_id) ON DELETE CASCADE
);

-- Newest first per tenant (the list endpoint), and every reference that cascades (V418's rule).
CREATE INDEX IF NOT EXISTS idx_pact_commit_status_tenant_updated
    ON pact_commit_status (tenant_id, updated_at DESC, id DESC);
CREATE INDEX IF NOT EXISTS idx_pact_commit_status_pacticipant
    ON pact_commit_status (pacticipant_id, tenant_id);
CREATE INDEX IF NOT EXISTS idx_pact_commit_status_version
    ON pact_commit_status (pacticipant_version_id, pacticipant_id);
CREATE INDEX IF NOT EXISTS idx_pact_commit_status_consumer
    ON pact_commit_status (consumer_id, tenant_id);
CREATE INDEX IF NOT EXISTS idx_pact_commit_status_provider
    ON pact_commit_status (provider_id, tenant_id);
CREATE INDEX IF NOT EXISTS idx_pact_commit_status_repository
    ON pact_commit_status (repository_id) WHERE repository_id IS NOT NULL;

COMMENT ON TABLE pact_commit_status IS
    'Pact verdicts posted back to GitHub / GitLab commits, one row per version and context (PFX-4.4, #6941)';
COMMENT ON COLUMN pact_commit_status.context IS 'Status context: apiome-pact/<consumer>/<provider>';
COMMENT ON COLUMN pact_commit_status.outcome IS
    'queued (being sent), dispatched (accepted), suppressed (not attempted, see reason_code) or failed';
COMMENT ON COLUMN pact_commit_status.reason_code IS 'Stable reason for a suppressed or failed send';
