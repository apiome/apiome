-- Redacted MCP protocol transcripts — CLX-3.1 (#4855).
--
-- Problem: MCP lint (V2-MCP-21.x) and the CLX evidence substrate (V167) both describe the
-- capability *surface* a server advertises. Neither records how the server *behaved* while that
-- surface was enumerated — whether it negotiated a protocol version honestly, echoed the ids of
-- the requests it answered, or paged sanely. Those facts exist only on the wire, and the wire is
-- gone the moment discovery finishes. Without a durable record, the protocol-conformance rules
-- that depend on them (app.mcp_conformance_rules, requires_transcript=True) could only ever run
-- during discovery itself and could never be re-served, re-gated, or audited.
--
-- This migration creates apiome.mcp_protocol_transcripts: one immutable, REDACTED record of the
-- JSON-RPC exchanges performed during the discovery of one snapshot.
--
-- What is stored is deliberately NOT the wire traffic. app.mcp_protocol_transcript reduces every
-- exchange to its shape before it is ever persisted:
--   * request parameters       -> their key NAMES only (no values)
--   * results                  -> their top-level key names + an item count (no items)
--   * opaque pagination cursors-> a SHA-256 prefix (equality is preserved so a cycle is still
--                                 detectable; the cursor's contents are not recoverable)
--   * server error messages    -> scrubbed of credential-shaped substrings, length-bounded
-- No tool arguments, no tool results, and no credential material can reach this table. The
-- `redacted` column is stored as a stated property of the row, not an assumption about it.
--
-- Passivity: only the read-only discovery methods are ever recorded (initialize,
-- notifications/initialized, and the four */list endpoints). app.mcp_protocol_transcript enforces
-- this with an allow-list that structurally excludes tools/call, so a transcript can never be the
-- by-product of invoking a business tool.
--
-- One transcript per snapshot (mcp_protocol_transcripts_version_unique). mcp_endpoint_versions
-- rows are immutable, so the discovery that produced one is a fact about it and never changes:
-- rows are write-once, guarded by the shared V128 mutation guard. A re-discovery that finds a
-- changed surface creates a NEW version, which gets its own transcript; a re-discovery that finds
-- no change creates no version and therefore no transcript.
--
-- Absent by design: a snapshot discovered before this migration (or one restored from a store
-- rather than a live handshake) has NO row here. That is a visible gap, not a clean result — the
-- conformance engine reports every transcript-backed rule as *skipped* when no transcript exists,
-- and never lets an unobserved behaviour read as a pass. There is intentionally no backfill:
-- fabricating a transcript for a session nobody observed would be the exact failure this design
-- exists to prevent.
--
-- Rollback notes:
--   DROP TRIGGER IF EXISTS trigger_mcp_protocol_transcripts_immutable ON apiome.mcp_protocol_transcripts;
--   DROP TABLE IF EXISTS apiome.mcp_protocol_transcripts;
-- (The V128 guard function apiome.mcp_forbid_row_mutation() is shared — do not drop it here.)
--
-- Idempotent: CREATE ... IF NOT EXISTS throughout.

SET search_path TO apiome, public;

-- ---------------------------------------------------------------------------------------------------
-- mcp_protocol_transcripts — one immutable, redacted protocol record per discovery snapshot.
-- ---------------------------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS mcp_protocol_transcripts (
    id                     UUID PRIMARY KEY DEFAULT uuid_generate_v4(),

    -- The snapshot this transcript was captured while discovering. Cascades with its version
    -- (and thus its endpoint and tenant), so no tenant column is needed: version_id is opaque and
    -- every caller validates the owning endpoint/tenant before reaching a transcript.
    version_id             UUID NOT NULL
                             REFERENCES mcp_endpoint_versions (id) ON DELETE CASCADE,

    -- The redacted transcript, exactly as app.mcp_protocol_transcript.ProtocolTranscript.as_dict()
    -- emits it: {redacted, requested_version, negotiated_version, exchanges: [...]}.
    transcript             JSONB NOT NULL DEFAULT '{}'::jsonb,

    -- Protocol versions the handshake offered and settled on. Promoted out of the JSONB because
    -- the version-negotiation rules read them directly and a downgrade is worth indexing on.
    requested_version      TEXT,
    negotiated_version     TEXT,

    -- Stable hash over the redacted transcript, for staleness/identity checks.
    transcript_fingerprint TEXT,

    -- Stated, not assumed: this row holds reduced, redacted evidence and never verbatim wire data.
    redacted               BOOLEAN NOT NULL DEFAULT TRUE,

    captured_at            TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Exactly one transcript per snapshot: the discovery that produced an immutable version is a
-- single, immutable fact about it.
CREATE UNIQUE INDEX IF NOT EXISTS mcp_protocol_transcripts_version_unique
    ON mcp_protocol_transcripts (version_id);

-- Write-once, mirroring lint_evidence_runs (V167) and the version snapshots themselves: an audit
-- record that can be edited after the fact is not evidence. Reuses the shared V128 guard.
--
-- UPDATE only, deliberately — exactly as V167 does. A BEFORE DELETE guard here would also fire on
-- the cascade from mcp_endpoint_versions and make an endpoint (or tenant) impossible to delete.
-- Immutability means "a row's contents never change", not "the row outlives its subject".
DROP TRIGGER IF EXISTS trigger_mcp_protocol_transcripts_immutable ON mcp_protocol_transcripts;
CREATE TRIGGER trigger_mcp_protocol_transcripts_immutable
    BEFORE UPDATE ON mcp_protocol_transcripts
    FOR EACH ROW
    EXECUTE FUNCTION mcp_forbid_row_mutation();

COMMENT ON TABLE mcp_protocol_transcripts IS
    'CLX-3.1 (#4855): immutable, redacted record of the passive JSON-RPC exchanges performed while '
    'discovering one MCP snapshot. Stores shapes, counts and cursor digests only — never wire data, '
    'tool arguments, tool results, or credentials. Backs the transcript-derived protocol-conformance '
    'rules; a snapshot with no row has those rules reported as SKIPPED, never as passing.';
