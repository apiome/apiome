-- DCW-2.3 (private-suite#2360): source-to-model change review apply audit.
--
-- Every successful source apply writes exactly one row here, inside the same
-- transaction as the canonical rows, the preservation envelope, and the
-- revision state — so the audit trail and the mutation commit or roll back
-- together (the DCW-0.2 failure-injection-no-partial-mutation rule).
--
-- The change_set_digest binds the applied candidate to the base revision it
-- was reviewed against; replaying an applied change set matches on it and
-- returns the recorded result instead of mutating again (idempotent replay).

CREATE TABLE IF NOT EXISTS apiome.source_change_audit (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id UUID NOT NULL REFERENCES apiome.tenants(id),
    version_id UUID NOT NULL REFERENCES apiome.versions(id),
    actor_id UUID REFERENCES apiome.users(id),
    action TEXT NOT NULL DEFAULT 'source.apply',
    outcome TEXT NOT NULL DEFAULT 'success',
    base_digest TEXT NOT NULL,
    result_digest TEXT NOT NULL,
    change_set_digest TEXT NOT NULL,
    counts JSONB,
    detail JSONB,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP
);

COMMENT ON TABLE apiome.source_change_audit IS
    'Append-only audit of source-to-model change applies (DCW-2.3, private-suite#2360). One row per successful apply, committed atomically with the canonical mutation.';
COMMENT ON COLUMN apiome.source_change_audit.base_digest IS
    'Semantic fingerprint of the merged document the candidate was reviewed against (the optimistic-concurrency token the apply verified).';
COMMENT ON COLUMN apiome.source_change_audit.result_digest IS
    'Semantic fingerprint of the merged document after the apply committed.';
COMMENT ON COLUMN apiome.source_change_audit.change_set_digest IS
    'Digest binding the reviewed candidate to its base revision; replays match on it for idempotency.';
COMMENT ON COLUMN apiome.source_change_audit.counts IS
    'Per-kind change totals (additions/updates/deletions/unsupportedPreserved) recorded at apply time.';
COMMENT ON COLUMN apiome.source_change_audit.detail IS
    'Structured context: dialect, source format, claim count, generator enrichment pointers.';

CREATE INDEX IF NOT EXISTS idx_source_change_audit_version
    ON apiome.source_change_audit (version_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_source_change_audit_tenant
    ON apiome.source_change_audit (tenant_id, created_at DESC);
