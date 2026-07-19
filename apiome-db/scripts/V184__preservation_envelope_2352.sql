-- Round-trip preservation envelope (DCW-2.1, private-suite#2352).
--
-- A visual editor cannot be a trustworthy source of truth if save/export drops valid
-- OpenAPI data it has not normalized. This migration adds the version-scoped preservation
-- payload: unknown-but-valid fields and x-* extensions, keyed by RFC 6901 JSON Pointer,
-- stored losslessly as JSONB next to the canonical rows so export can merge them back.
--
--   1. `apiome.version_preservation_claims` — one row per preserved JSON Pointer per
--      revision. `payload` holds the preserved subtree verbatim (JSON null / false /
--      empty containers are all representable and distinct from "no claim"). Optional
--      `source_file` / `source_digest` record which original source file the claim came
--      from and the digest of that file at import time, for provenance (DCW-2.4) and
--      stale-candidate detection (DCW-2.3). Tenant scoping is denormalized into
--      `tenant_id` so every query and the unique constraint stay tenant-scoped without a
--      three-way join.
--   2. Retention: claims are soft-deleted (`deleted_at`) when an envelope is replaced so
--      a mistaken apply can be audited and recovered; `apiome.purge_preservation_claims`
--      hard-deletes soft-deleted rows older than a retention window (default 30 days) and
--      is intended for a scheduled maintenance job.
--   3. `apiome.preservation_audit` — append-only audit of every envelope mutation
--      (replace / clear), with the acting user, claim counts, and structured detail.
--      Mirrors the `apiome.registry_audit` convention (#3481).
--
-- Transactional posture (DCW-0.2 gate `failure-injection-no-partial-mutation`): the REST
-- layer replaces an envelope and writes its audit row in ONE transaction — canonical
-- rows, preservation payload, and audit commit or roll back together. Nothing in this
-- schema permits partial envelope state: the partial unique index guarantees at most one
-- live claim per (version, pointer).
SET search_path TO apiome, public;

-- ─── 1. Preservation claims ──────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS apiome.version_preservation_claims (
    id            UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id     UUID NOT NULL REFERENCES apiome.tenants(id) ON DELETE CASCADE,
    version_id    UUID NOT NULL REFERENCES apiome.versions(id) ON DELETE CASCADE,
    -- RFC 6901 JSON Pointer into the exported OpenAPI document ('' addresses the root).
    pointer       TEXT NOT NULL,
    -- The preserved value, verbatim. 'null'::jsonb is a legal preserved value and is
    -- distinct from row absence, so the column itself is NOT NULL.
    payload       JSONB NOT NULL,
    -- Optional source provenance: original file path within a multi-file source layout,
    -- and the digest of that file's bytes at import time (algorithm-prefixed, e.g.
    -- 'sha256:<hex>').
    source_file   TEXT,
    source_digest TEXT,
    created_by    UUID REFERENCES apiome.users(id) ON DELETE SET NULL,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    -- Soft-delete for retention: replaced envelopes keep their claims until purge.
    deleted_at    TIMESTAMPTZ,
    CONSTRAINT version_preservation_pointer_shape CHECK (pointer = '' OR pointer LIKE '/%')
);

COMMENT ON TABLE apiome.version_preservation_claims IS
  'DCW-2.1 (private-suite#2352): version-scoped round-trip preservation envelope. One live row '
  'per preserved JSON Pointer per revision; payload is the preserved OpenAPI subtree verbatim.';
COMMENT ON COLUMN apiome.version_preservation_claims.pointer IS
  'RFC 6901 JSON Pointer of the preserved value within the exported document.';
COMMENT ON COLUMN apiome.version_preservation_claims.source_digest IS
  'Algorithm-prefixed digest (e.g. sha256:<hex>) of the originating source file at import time.';

-- At most one live claim per (version, pointer); soft-deleted history rows do not collide.
CREATE UNIQUE INDEX IF NOT EXISTS uq_version_preservation_live_pointer
    ON apiome.version_preservation_claims (version_id, pointer)
    WHERE deleted_at IS NULL;

CREATE INDEX IF NOT EXISTS idx_version_preservation_tenant_version
    ON apiome.version_preservation_claims (tenant_id, version_id)
    WHERE deleted_at IS NULL;

-- Purge visibility: retention sweeps scan by deletion age.
CREATE INDEX IF NOT EXISTS idx_version_preservation_deleted_at
    ON apiome.version_preservation_claims (deleted_at)
    WHERE deleted_at IS NOT NULL;

-- ─── 2. Retention purge function ─────────────────────────────────────────────

CREATE OR REPLACE FUNCTION apiome.purge_preservation_claims(p_retention_days INTEGER DEFAULT 30)
RETURNS INTEGER AS $$
DECLARE
    v_purged INTEGER;
BEGIN
    DELETE FROM apiome.version_preservation_claims
    WHERE deleted_at IS NOT NULL
      AND deleted_at < CURRENT_TIMESTAMP - (p_retention_days * INTERVAL '1 day');
    GET DIAGNOSTICS v_purged = ROW_COUNT;
    RETURN v_purged;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION apiome.purge_preservation_claims(INTEGER) IS
  'Hard-delete preservation claims soft-deleted more than p_retention_days ago (default 30). '
  'Returns the number of purged rows. DCW-2.1 retention behavior (private-suite#2352).';

-- ─── 3. Append-only envelope audit ───────────────────────────────────────────

CREATE TABLE IF NOT EXISTS apiome.preservation_audit (
    id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id   UUID NOT NULL REFERENCES apiome.tenants(id) ON DELETE CASCADE,
    version_id  UUID NOT NULL REFERENCES apiome.versions(id) ON DELETE CASCADE,
    actor_id    UUID REFERENCES apiome.users(id) ON DELETE SET NULL,
    -- 'envelope.replace' | 'envelope.clear'
    action      TEXT NOT NULL,
    outcome     TEXT NOT NULL DEFAULT 'success',
    -- Structured context: claim counts, source digest, envelope version, error info.
    detail      JSONB,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

COMMENT ON TABLE apiome.preservation_audit IS
  'Append-only audit of preservation-envelope mutations (DCW-2.1, private-suite#2352). '
  'Written in the same transaction as the envelope change.';

CREATE INDEX IF NOT EXISTS idx_preservation_audit_tenant_version
    ON apiome.preservation_audit (tenant_id, version_id, created_at DESC);
