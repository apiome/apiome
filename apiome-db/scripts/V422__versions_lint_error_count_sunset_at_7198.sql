-- Stored lint error count and sunset date on versions (DBP-1.15, #7198).
--
-- Home's "Needs attention" panel, the /ade launcher chip and the sunset timeline filter live
-- revisions on two values buried in JSONB:
--
--   * quality_report->'severity_counts'->>'error'  (apiome-ui lib/db/lint-attention-query.ts)
--   * metadata->>'sunsetAt' / 'sunsetDate' / 'sunset_date'
--       (apiome-ui lib/db/dashboard-home.ts loadSunsetRows; apiome-rest
--        Database.list_sunset_timeline_entries)
--
-- Each read detoasted both documents for every live revision of the reader's workspaces, and no
-- index could carry the predicate. Both values now live in stored generated columns, so they are
-- written wherever the report and the metadata are written — by apiome-rest and apiome-ui alike —
-- with no writer changes:
--
--   * versions.lint_error_count — the report's error count, truncated to a whole number and
--     clamped to 0 .. 2147483647. NULL when the report has no numeric count, so a malformed report
--     can never make an INSERT or UPDATE fail (the readers used to guard the same cast with
--     jsonb_typeof).
--   * versions.sunset_at — the first non-empty of sunsetAt, sunsetDate, sunset_date, trimmed, as
--     the text it was stored as (revision_deprecation.py mirrors sunsetAt and sunsetDate on every
--     write and reads them in this order). NULL when none is set.
--
-- Partial indexes serve the two filters: unpublished revisions with at least one lint error, and
-- revisions with a sunset date.
--
-- The content-stamp trigger (V403, apiome.bump_version_content_stamp) is re-created with both
-- columns in its list of non-content versions columns. Without that, every UPDATE of a revision
-- with a lint count or a sunset date — even one that only sets updated_at — bumped
-- versions.content_stamp and marked its rendered documents stale: in a BEFORE trigger NEW does not
-- yet carry the recomputed generated values, so they compared as changed. The body is otherwise
-- V403's, unchanged.
--
-- Large databases: adding a stored generated column rewrites apiome.versions under an ACCESS
-- EXCLUSIVE lock (reads and writes of versions wait; a few seconds per 200,000 rows). Schedule the
-- upgrade accordingly. The index builds that follow block writes to versions; to avoid that part,
-- run the CREATE INDEX statements below by hand with CONCURRENTLY (same names and definitions)
-- after the columns exist — the statements are IF NOT EXISTS.
--
-- Rollback notes:
--   DROP INDEX IF EXISTS apiome.idx_versions_lint_attention;
--   DROP INDEX IF EXISTS apiome.idx_versions_sunset_at;
--   ALTER TABLE apiome.versions DROP COLUMN IF EXISTS lint_error_count;
--   ALTER TABLE apiome.versions DROP COLUMN IF EXISTS sunset_at;
--   (and restore the JSONB predicates in the three readers named above; the trigger function may
--   keep the two extra names, which are harmless once the columns are gone).

ALTER TABLE apiome.versions
    ADD COLUMN IF NOT EXISTS lint_error_count integer GENERATED ALWAYS AS (
        CASE
            WHEN jsonb_typeof(quality_report->'severity_counts'->'error') = 'number'
            THEN LEAST(
                     GREATEST(trunc((quality_report->'severity_counts'->>'error')::numeric), 0),
                     2147483647
                 )::integer
        END
    ) STORED,
    ADD COLUMN IF NOT EXISTS sunset_at text GENERATED ALWAYS AS (
        NULLIF(TRIM(COALESCE(
            metadata->>'sunsetAt',
            metadata->>'sunsetDate',
            metadata->>'sunset_date',
            ''
        )), '')
    ) STORED;

COMMENT ON COLUMN apiome.versions.lint_error_count IS
    'Generated (DBP-1.15, #7198): quality_report severity_counts.error as a whole number, NULL when '
    'the report has no numeric count. Read by Home and the launcher for "needs attention".';

COMMENT ON COLUMN apiome.versions.sunset_at IS
    'Generated (DBP-1.15, #7198): the trimmed first non-empty of metadata sunsetAt / sunsetDate / '
    'sunset_date, as stored text. Read by Home and the REST sunset timeline.';

CREATE INDEX IF NOT EXISTS idx_versions_lint_attention
    ON apiome.versions (project_id)
    WHERE deleted_at IS NULL AND published = false AND lint_error_count > 0;

CREATE INDEX IF NOT EXISTS idx_versions_sunset_at
    ON apiome.versions (project_id, sunset_at)
    WHERE deleted_at IS NULL AND sunset_at IS NOT NULL;

CREATE OR REPLACE FUNCTION apiome.bump_version_content_stamp()
RETURNS trigger
LANGUAGE plpgsql
AS $fn$
DECLARE
    -- Columns whose change alone is not a content change, on any table.
    v_ignored         CONSTANT text[] := ARRAY['updated_at', 'canvas_metadata'];
    -- Versions columns that are bookkeeping or derived from the content, not content. The stored
    -- generated columns are listed too (V422): in a BEFORE trigger NEW does not carry their new
    -- values yet, so comparing them would count every bookkeeping UPDATE as a content change.
    v_version_ignored CONSTANT text[] := ARRAY[
        'content_stamp', 'updated_at', 'mcp_public_doc_tsv', 'mcp_public_embedding',
        'quality_score', 'quality_grade', 'quality_report', 'quality_report_fingerprint',
        'lint_error_count', 'sunset_at'];
    v_resolver text;
    v_old      jsonb;
    v_new      jsonb;
    v_row      jsonb;
    v_version  uuid;
BEGIN
    IF TG_TABLE_SCHEMA = 'apiome' AND TG_TABLE_NAME = 'versions' THEN
        IF TG_OP = 'UPDATE' AND TG_WHEN = 'BEFORE'
           AND (to_jsonb(NEW) - v_version_ignored) IS DISTINCT FROM (to_jsonb(OLD) - v_version_ignored)
           AND apiome.claim_version_content_stamp(NEW.id) THEN
            NEW.content_stamp := OLD.content_stamp + 1;
        END IF;
        RETURN NEW;
    END IF;

    IF TG_NARGS <> 1 THEN
        RAISE EXCEPTION 'bump_version_content_stamp on %.% needs one revision resolver argument',
            TG_TABLE_SCHEMA, TG_TABLE_NAME;
    END IF;
    v_resolver := TG_ARGV[0];

    IF TG_OP IN ('UPDATE', 'DELETE') THEN
        v_old := to_jsonb(OLD);
    END IF;
    IF TG_OP IN ('INSERT', 'UPDATE') THEN
        v_new := to_jsonb(NEW);
    END IF;
    IF TG_OP = 'UPDATE' AND (v_new - v_ignored) = (v_old - v_ignored) THEN
        RETURN NULL;
    END IF;

    FOREACH v_row IN ARRAY array_remove(ARRAY[v_old, v_new], NULL) LOOP
        IF v_resolver ~ '^[a-z_][a-z0-9_]*$' THEN
            v_version := (v_row ->> v_resolver)::uuid;
            IF apiome.claim_version_content_stamp(v_version) THEN
                UPDATE apiome.versions SET content_stamp = content_stamp + 1 WHERE id = v_version;
            END IF;
        ELSE
            FOR v_version IN EXECUTE v_resolver USING v_row LOOP
                IF apiome.claim_version_content_stamp(v_version) THEN
                    UPDATE apiome.versions SET content_stamp = content_stamp + 1 WHERE id = v_version;
                END IF;
            END LOOP;
        END IF;
    END LOOP;
    RETURN NULL;
END;
$fn$;

COMMENT ON FUNCTION apiome.bump_version_content_stamp() IS
    'The single trigger function that bumps versions.content_stamp once per transaction (COA-5.2, #7078; generated columns ignored since DBP-1.15, #7198).';
