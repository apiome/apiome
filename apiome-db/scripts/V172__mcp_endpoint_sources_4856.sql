-- MCP source association and SBOM evidence — CLX-3.2 (#4856).
--
-- Problem: every existing assessment of a catalogued MCP endpoint is derived from what the server
-- *advertises*. The surface lint (V2-MCP-21.x) reads the capability list; the conformance engine
-- (CLX-3.1, V171) reads how the server behaved while that list was enumerated. Neither can say
-- anything about what the server is *made of* — the repository it was built from, the dependencies
-- it pulls in, the secrets sitting in its config, the shell commands its manifest runs. Those facts
-- exist in the server's source artifact, and nothing in the catalog points at one.
--
-- This migration creates the *source lane*: an explicit, operator-established link from an MCP
-- endpoint to the artifact it came from, plus the dependency inventory of that artifact.
--
--   mcp_endpoint_sources  — WHAT the server is built from, and how confidently we know that.
--   mcp_source_sboms      — WHAT is inside it, as coordinates only.
--
-- ---------------------------------------------------------------------------------------------------
-- Explicit, never inferred (AC: "a source association has explicit provenance and digest")
-- ---------------------------------------------------------------------------------------------------
-- A source association is never guessed from a URL that happens to look like a repository. Every row
-- records HOW the link came to be known, in `provenance`:
--
--   operator_declared     — a human linked it. The common case, and the weakest claim.
--   registry_published    — the MCP registry that published the server declared it.
--   discovery_advertised  — the server itself advertised it during discovery.
--   attested              — backed by a verifiable attestation (e.g. a signed provenance statement).
--
-- and HOW STRONGLY the artifact is pinned, in `verification_state`:
--
--   unverified    — a moving target: a branch name, a floating tag, `latest`. Findings derived from
--                   it describe whatever that reference pointed at when it was read, which is not
--                   necessarily what the endpoint is running now. Confidence-downgraded downstream.
--   digest_pinned — pinned to an immutable digest (a git commit sha, an OCI manifest digest, an
--                   exact package version). Findings are reproducible against it.
--   attested      — digest-pinned AND the digest is backed by an attestation.
--
-- These are two independent axes on purpose. An operator can hand-declare a fully digest-pinned
-- source (strong pin, weak provenance), and a registry can publish a floating `main` branch (weak
-- pin, stronger provenance). Collapsing them into one "trust level" would lose exactly the
-- distinction a reviewer needs.
--
-- ---------------------------------------------------------------------------------------------------
-- No source exfiltration (AC: "SBOM/vulnerability scans do not require source exfiltration")
-- ---------------------------------------------------------------------------------------------------
-- mcp_source_sboms stores a dependency inventory as COORDINATES ONLY — package name, purl, version,
-- declared license. No file contents, no source code, no manifest text is persisted here, and none is
-- transmitted anywhere. Vulnerability lookup (app.mcp_vulnerability) queries by purl alone: the
-- coordinates leave, the code never does. That is a property of the schema, not a habit of the
-- callers — there is no column here that could hold source.
--
-- ---------------------------------------------------------------------------------------------------
-- Absent by design
-- ---------------------------------------------------------------------------------------------------
-- There is intentionally NO backfill. An endpoint nobody has linked a source to has no row here, and
-- the trust-posture engine reports every source- and dependency-derived rule as SKIPPED for it, with
-- the evidence run recorded as coverage `partial`. An unlinked endpoint therefore reads as "not
-- scanned", never as "clean" — the same contract V171 established for unobserved protocol behaviour.
-- Fabricating a source link for an endpoint nobody vouched for would be the precise failure this
-- design exists to prevent.
--
-- Rollback notes:
--   DROP TRIGGER IF EXISTS trigger_mcp_source_sboms_immutable ON apiome.mcp_source_sboms;
--   DROP TABLE IF EXISTS apiome.mcp_source_sboms;
--   DROP TABLE IF EXISTS apiome.mcp_endpoint_sources;
-- (The V128 guard function apiome.mcp_forbid_row_mutation() is shared — do not drop it here.)
--
-- Idempotent: CREATE ... IF NOT EXISTS throughout.

SET search_path TO apiome, public;

-- ---------------------------------------------------------------------------------------------------
-- mcp_endpoint_sources — the explicit link from an endpoint to the artifact it is built from.
-- ---------------------------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS mcp_endpoint_sources (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),

    -- Denormalized from the endpoint so tenant-scoped listing and RLS-style filtering never need a
    -- join. Cascades with the tenant.
    tenant_id UUID NOT NULL REFERENCES tenants (id) ON DELETE CASCADE,

    -- The endpoint this artifact backs. A source is a fact about the ENDPOINT, not about any one of
    -- its version snapshots: the repository behind a server does not change because a re-discovery
    -- produced a new snapshot. Scans are run per snapshot but resolve their source through here.
    endpoint_id UUID NOT NULL REFERENCES mcp_endpoints (id) ON DELETE CASCADE,

    -- The lane this source belongs to. Four kinds, because an MCP server is distributed in four
    -- meaningfully different ways and each pins to a different kind of digest:
    --   git      — a repository at a commit (digest = 40-hex commit sha)
    --   package  — a registry package at a version (digest = registry integrity hash, when published)
    --   image    — a container image (digest = OCI manifest digest, sha256:...)
    --   registry — an MCP registry server identity (digest = the registry's own content digest)
    source_kind TEXT NOT NULL,

    -- The canonical, normalized reference, as produced by app.mcp_source_link. Normalized (not raw
    -- operator input) so that the same artifact reached by two spellings is one row, and so the
    -- unique index below actually means what it says.
    locator TEXT NOT NULL,

    -- Package URL (https://github.com/package-url/purl-spec) when the source has one. Promoted out of
    -- the locator because it is the join key for dependency and vulnerability evidence, and the ONLY
    -- thing ever transmitted to an external vulnerability database.
    purl TEXT,

    -- The human-facing reference the operator asked for: a branch, a tag, a semver, an image tag.
    -- May be a moving target — that is what `verification_state` is for.
    revision TEXT,

    -- The immutable content identity, when one is known. NULL means the source is not pinned, which
    -- forces verification_state = 'unverified' (see the check below).
    digest TEXT,
    digest_algorithm TEXT,

    -- How this association came to be known (see the header). Never inferred.
    provenance TEXT NOT NULL DEFAULT 'operator_declared',

    -- Supporting detail for the provenance claim — e.g. the attestation's issuer and subject, or the
    -- registry entry the link was published in. Free-form per provenance kind.
    provenance_detail JSONB NOT NULL DEFAULT '{}'::jsonb,

    -- How strongly the artifact is pinned (see the header).
    verification_state TEXT NOT NULL DEFAULT 'unverified',

    -- Who linked it. RESTRICT, not CASCADE: deleting a user must not silently erase the provenance of
    -- a source association that other evidence depends on.
    linked_by UUID REFERENCES users (id) ON DELETE RESTRICT,

    -- Soft retirement. A source that is retired stops backing new scans but stays readable, so
    -- historical evidence that cites it remains interpretable. Hard-deleting it would orphan the
    -- provenance of every finding already derived from it.
    retired_at TIMESTAMP WITH TIME ZONE,

    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT mcp_endpoint_sources_kind_check
        CHECK (source_kind IN ('git', 'package', 'image', 'registry')),

    CONSTRAINT mcp_endpoint_sources_provenance_check
        CHECK (provenance IN (
            'operator_declared', 'registry_published', 'discovery_advertised', 'attested'
        )),

    CONSTRAINT mcp_endpoint_sources_verification_check
        CHECK (verification_state IN ('unverified', 'digest_pinned', 'attested')),

    -- A source cannot claim to be pinned without a digest to pin it to. This is the schema-level
    -- guarantee behind the whole confidence model: `digest_pinned` on a row with no digest would let
    -- an unreproducible finding present itself as reproducible.
    CONSTRAINT mcp_endpoint_sources_pinned_needs_digest_check
        CHECK (
            verification_state = 'unverified'
            OR (digest IS NOT NULL AND digest_algorithm IS NOT NULL)
        ),

    CONSTRAINT mcp_endpoint_sources_locator_not_blank_check
        CHECK (length(trim(locator)) > 0)
);

-- One live association per (endpoint, kind, artifact). Retired rows are excluded so the same artifact
-- can be re-linked after a retirement without colliding with its own history.
CREATE UNIQUE INDEX IF NOT EXISTS mcp_endpoint_sources_live_unique
    ON mcp_endpoint_sources (endpoint_id, source_kind, locator)
    WHERE retired_at IS NULL;

CREATE INDEX IF NOT EXISTS mcp_endpoint_sources_endpoint_idx
    ON mcp_endpoint_sources (endpoint_id)
    WHERE retired_at IS NULL;

CREATE INDEX IF NOT EXISTS mcp_endpoint_sources_tenant_idx
    ON mcp_endpoint_sources (tenant_id);

-- The join key for dependency evidence; partial because most rows in some lanes have no purl.
CREATE INDEX IF NOT EXISTS mcp_endpoint_sources_purl_idx
    ON mcp_endpoint_sources (purl)
    WHERE purl IS NOT NULL;

COMMENT ON TABLE mcp_endpoint_sources IS
    'CLX-3.2 (#4856): explicit link from an MCP endpoint to the git repo / package / image / registry '
    'identity it is built from. Records how the link is known (provenance) and how strongly the '
    'artifact is pinned (verification_state) as two independent axes. Never inferred; an endpoint with '
    'no row here has its source- and dependency-derived posture rules reported as SKIPPED, never as '
    'passing.';

COMMENT ON COLUMN mcp_endpoint_sources.verification_state IS
    'unverified = a moving reference (branch/floating tag); digest_pinned = pinned to an immutable '
    'digest, so findings are reproducible; attested = digest-pinned and attestation-backed. Rows may '
    'only claim a pinned state when a digest is actually present (see the pinned_needs_digest check).';

COMMENT ON COLUMN mcp_endpoint_sources.purl IS
    'Package URL. The ONLY field ever transmitted to an external vulnerability database — lookups go '
    'out by coordinate, never by source content.';

-- ---------------------------------------------------------------------------------------------------
-- mcp_source_sboms — the dependency inventory of one pinned artifact. Coordinates only.
-- ---------------------------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS mcp_source_sboms (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),

    source_id UUID NOT NULL REFERENCES mcp_endpoint_sources (id) ON DELETE CASCADE,

    -- The artifact identity this inventory describes. An SBOM is a statement about a specific,
    -- immutable artifact — so it is keyed by digest, not by the source row alone. Re-scanning the same
    -- source at a new commit produces a NEW row; it never mutates the old one, because the old one is
    -- still the true inventory of the old commit.
    subject_digest TEXT NOT NULL,

    -- 'cyclonedx' | 'spdx' when ingested from a real SBOM document; 'apiome-manifest' when the
    -- components were derived from lockfiles rather than supplied as an SBOM.
    sbom_format TEXT NOT NULL,
    sbom_spec_version TEXT,

    -- How the inventory was obtained:
    --   operator_supplied — a CycloneDX/SPDX document was uploaded. Authoritative.
    --   manifest_derived  — Apiome derived it by reading lockfiles. Best-effort: a lockfile lists
    --                       what a build WOULD resolve, which is not always what the running server
    --                       actually contains. Recorded distinctly so a consumer never mistakes a
    --                       derived inventory for an authoritative one.
    origin TEXT NOT NULL,

    -- Component coordinates ONLY: [{"name","version","purl","license","scope"}]. There is deliberately
    -- no column here that can hold file contents, source, or manifest text.
    components JSONB NOT NULL DEFAULT '[]'::jsonb,
    component_count INTEGER NOT NULL DEFAULT 0,

    -- Stable hash over the canonicalized component set, for staleness and identity checks.
    sbom_fingerprint TEXT,

    -- Lockfiles/manifests the derivation actually read, by PATH ONLY (never content). Lets a reviewer
    -- see that an inventory covering one lockfile in a polyglot repo is incomplete.
    scanned_manifests JSONB NOT NULL DEFAULT '[]'::jsonb,

    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT mcp_source_sboms_format_check
        CHECK (sbom_format IN ('cyclonedx', 'spdx', 'apiome-manifest')),

    CONSTRAINT mcp_source_sboms_origin_check
        CHECK (origin IN ('operator_supplied', 'manifest_derived')),

    CONSTRAINT mcp_source_sboms_component_count_check
        CHECK (component_count >= 0)
);

-- One inventory per (source, artifact digest, origin). The origin is part of the key because an
-- operator-supplied SBOM and an Apiome-derived one are two different claims about the same artifact,
-- and a reviewer may legitimately want to compare them rather than have one silently overwrite the
-- other.
CREATE UNIQUE INDEX IF NOT EXISTS mcp_source_sboms_subject_unique
    ON mcp_source_sboms (source_id, subject_digest, origin);

CREATE INDEX IF NOT EXISTS mcp_source_sboms_source_idx
    ON mcp_source_sboms (source_id);

-- Write-once, mirroring lint_evidence_runs (V167) and the protocol transcripts (V171): an inventory
-- that can be edited after the fact is not evidence. Reuses the shared V128 guard.
--
-- UPDATE only, deliberately — exactly as V167/V171 do. A BEFORE DELETE guard would also fire on the
-- cascade from mcp_endpoint_sources and make a source (and thus an endpoint, and thus a tenant)
-- impossible to delete. Immutability means "a row's contents never change", not "the row outlives its
-- subject".
DROP TRIGGER IF EXISTS trigger_mcp_source_sboms_immutable ON mcp_source_sboms;
CREATE TRIGGER trigger_mcp_source_sboms_immutable
    BEFORE UPDATE ON mcp_source_sboms
    FOR EACH ROW
    EXECUTE FUNCTION mcp_forbid_row_mutation();

COMMENT ON TABLE mcp_source_sboms IS
    'CLX-3.2 (#4856): immutable dependency inventory of one pinned MCP source artifact. Stores '
    'component COORDINATES ONLY (name / purl / version / license) — never source, file contents, or '
    'manifest text. Vulnerability lookup queries by purl alone, so coordinates leave and code never '
    'does. origin distinguishes an authoritative operator-supplied SBOM from a best-effort '
    'lockfile-derived one.';

COMMENT ON COLUMN mcp_source_sboms.components IS
    'Component coordinates only: [{"name","version","purl","license","scope"}]. No source content may '
    'be stored here — there is no column for it, by design (no-exfiltration AC).';

COMMENT ON COLUMN mcp_source_sboms.scanned_manifests IS
    'Paths of the lockfiles/manifests the derivation read — paths only, never their content. Makes a '
    'partial inventory of a polyglot repository visible as partial.';
