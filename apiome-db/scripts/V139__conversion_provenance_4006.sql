-- Convert-to-project/version provenance (#4006, MFI-22.5).
--
-- MFI-EPIC-22 turns a *catalog item* — an OpenAPI-worthy non-OpenAPI import (gRPC, GraphQL,
-- AsyncAPI, OData, …) that landed as a non-publishable catalog project (V138, MFI-23.1) — into a
-- real, editable **publishable OpenAPI Project**. The conversion job (MFI-22.5) emits an OpenAPI 3.1
-- document from the source's canonical model (MFI-22.1/22.2), mints a new Project + `v1` from it
-- (reusing the spec-import engine), runs the OpenAPI lint/score (MFI-EPIC-4) on the result, and must
-- record **where the converted spec came from** so:
--
--   * the converted Project links back to its origin (which catalog item + which source revision,
--     in which source format/protocol);
--   * a later **re-convert** of a changed source produces a *new version* of the same converted
--     Project instead of a duplicate Project (looked up by source artifact); and
--   * a later re-import diffs cleanly and the conversion is reproducible (the fidelity report and the
--     converter tool versions that produced it are captured alongside).
--
-- This migration adds the `apiome.conversion_provenance` audit table that holds exactly that lineage.
-- It is an **append-only** record: one row per conversion (initial convert or re-convert), never
-- updated — enforced write-once by a trigger, mirroring the immutable-audit pattern established for
-- the MCP catalog version rows (V128).
--
-- Rollback notes: purely additive. To roll back:
--   DROP TRIGGER IF EXISTS trigger_conversion_provenance_immutable ON apiome.conversion_provenance;
--   DROP FUNCTION IF EXISTS apiome.conversion_provenance_forbid_mutation();
--   DROP TABLE IF EXISTS apiome.conversion_provenance;

SET search_path TO apiome, public;

-- ---------------------------------------------------------------------------------------------------
-- The conversion-provenance ledger.
-- ---------------------------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS apiome.conversion_provenance (
    id                       UUID         NOT NULL DEFAULT gen_random_uuid() PRIMARY KEY,
    tenant_id                UUID         NOT NULL REFERENCES apiome.tenants(id) ON DELETE CASCADE,

    -- Source side: which catalog item (a project id, MFI-23.1) and which of its revisions was
    -- converted, in which format/protocol, with which import tool provenance. The source project may
    -- be deleted later; keep the provenance row (SET NULL) so the target Project's lineage survives.
    source_project_id        UUID         REFERENCES apiome.projects(id) ON DELETE SET NULL,
    source_version_id        UUID         REFERENCES apiome.versions(id) ON DELETE SET NULL,
    source_format            VARCHAR(128),
    source_protocol          VARCHAR(64),
    source_version_label     VARCHAR(255),
    source_tool_versions     JSONB        NOT NULL DEFAULT '{}'::jsonb,

    -- Target side: the publishable OpenAPI Project minted (or re-versioned) by the conversion, and
    -- the specific revision (`v1` on first convert, `vN` on re-convert) that carries the emitted spec.
    target_project_id        UUID         NOT NULL REFERENCES apiome.projects(id) ON DELETE CASCADE,
    target_version_id        UUID         REFERENCES apiome.versions(id) ON DELETE SET NULL,
    target_version_label     VARCHAR(255),

    -- Fidelity report (MFI-22.3) that the user reviewed before committing: the full JSON report plus
    -- its rolled-up score/grade/tier hoisted into columns for cheap listing/filtering.
    fidelity_report          JSONB        NOT NULL DEFAULT '{}'::jsonb,
    fidelity_score           SMALLINT,
    fidelity_grade           VARCHAR(2),
    fidelity_tier            VARCHAR(16),

    -- OpenAPI lint/score (MFI-EPIC-4) captured on the converted result.
    lint_score               SMALLINT,
    lint_grade               VARCHAR(2),

    -- Which conversion tooling produced this row (emitter/analyzer/rest versions), for reproducibility
    -- and so a later re-convert can be compared against the tools that made the prior one.
    converter_tool_versions  JSONB        NOT NULL DEFAULT '{}'::jsonb,

    -- True when this row superseded a prior conversion of the same source (a re-convert / new version)
    -- rather than minting a fresh Project. Redundant with a self-lookup but cheap and explicit.
    reconverted              BOOLEAN      NOT NULL DEFAULT false,

    created_by               UUID         REFERENCES apiome.users(id) ON DELETE SET NULL,
    created_at               TIMESTAMPTZ  NOT NULL DEFAULT CURRENT_TIMESTAMP
);

COMMENT ON TABLE apiome.conversion_provenance IS
  'Append-only ledger of catalog -> OpenAPI conversions (#4006, MFI-22.5): links each minted/re-'
  'versioned publishable Project back to the source catalog item + revision it was converted from, '
  'with the fidelity report, lint score, and converter tool versions that produced it.';

-- Re-convert lookup: "has this source artifact been converted before, and to which Project?" — the
-- latest row per source_project_id names the target Project a re-convert must add a new version to.
CREATE INDEX IF NOT EXISTS idx_conversion_provenance_source
  ON apiome.conversion_provenance(tenant_id, source_project_id, created_at DESC);

-- Reverse lookup: "where did this converted Project come from?" — one target Project may accumulate
-- several rows (one per re-convert), newest first.
CREATE INDEX IF NOT EXISTS idx_conversion_provenance_target
  ON apiome.conversion_provenance(tenant_id, target_project_id, created_at DESC);

-- ---------------------------------------------------------------------------------------------------
-- Write-once guarantee: a provenance row is an immutable audit record.
-- ---------------------------------------------------------------------------------------------------
-- Each conversion appends exactly one row; the lineage it captured (source, fidelity, tool versions)
-- is a fact about a point in time and must never be rewritten. A re-convert writes a *new* row rather
-- than mutating the old one, so both UPDATE and DELETE of an existing row are rejected here (the
-- CASCADE/SET NULL foreign-key actions above are system-driven and run as the table owner, so they
-- are unaffected by this row-level guard on user statements).
CREATE OR REPLACE FUNCTION conversion_provenance_forbid_mutation()
RETURNS TRIGGER AS $$
BEGIN
    RAISE EXCEPTION
        'apiome.conversion_provenance is append-only (row %): conversion provenance is an immutable '
        'audit record; a re-convert appends a new row rather than mutating an existing one',
        OLD.id
        USING ERRCODE = 'restrict_violation';
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trigger_conversion_provenance_immutable ON apiome.conversion_provenance;
CREATE TRIGGER trigger_conversion_provenance_immutable
    BEFORE UPDATE OR DELETE ON apiome.conversion_provenance
    FOR EACH ROW
    EXECUTE FUNCTION conversion_provenance_forbid_mutation();

COMMENT ON FUNCTION conversion_provenance_forbid_mutation() IS
  'Trigger guard enforcing the append-only / write-once nature of apiome.conversion_provenance so a '
  'conversion audit row can never be rewritten or deleted by a user statement (#4006, MFI-22.5).';
