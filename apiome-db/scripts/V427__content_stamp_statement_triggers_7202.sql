-- Content-stamp trigger: statement-level with transition tables (DBP-1.19, #7202).
--
-- V403 stamps a revision with one ROW-level trigger on each of 35 tables: per changed row it ran
-- to_jsonb(NEW) / to_jsonb(OLD), a dynamic EXECUTE for tables whose resolver is a query, and a
-- position() search in a growing text setting. Measured on 50,000 `classes` rows in one statement
-- the trigger added 16 % for one revision and 2.2x for rows spread over 500 revisions.
--
-- This migration moves the 35 tables to STATEMENT-level AFTER triggers with transition tables:
--
--   * trg_content_stamp_insert  AFTER INSERT  ... REFERENCING NEW TABLE AS new_rows
--   * trg_content_stamp_update  AFTER UPDATE  ... REFERENCING OLD TABLE AS old_rows NEW TABLE AS new_rows
--   * trg_content_stamp_delete  AFTER DELETE  ... REFERENCING OLD TABLE AS old_rows
--
-- (PostgreSQL allows one event per trigger that uses transition tables, hence three.) A statement
-- resolves the affected revisions with ONE query over its transition table and bumps them with ONE
-- UPDATE apiome.versions. The rules do not change:
--
--   * An UPDATE that changes nothing but updated_at / canvas_metadata is not a content change. It is
--     now decided set-wise: a new (old) row counts only when no old (new) row with the same primary
--     key equals it on every other column. Columns are read from the catalog when the statement runs
--     (apiome.content_stamp_row_filters), so a column added later is compared without a migration;
--     no row is serialized to jsonb.
--   * A moved row bumps both its old and its new revision (both sides of the UPDATE are resolved).
--   * Once per transaction: apiome.claim_versions(setting, ids) marks a whole array of revisions in
--     the same transaction-local setting V403 used (same `id,id,` format, exact element matching
--     instead of a substring search) and returns only the ones not yet marked. A rolled-back
--     savepoint still undoes its marks together with the bump they guarded.
--   * The publish counts (V424) are still cleared on a write to classes, version_path or
--     path_operation, once per revision per transaction.
--
-- The row trigger on apiome.versions itself (BEFORE UPDATE, no argument) is unchanged.
--
-- Resolver arguments changed shape: a bare column name as before, or a query over `{rows}` aliased
-- `r` (the transition table, or for an UPDATE the changed rows of it) that returns revision ids.
--
-- Online: only triggers and functions change; no table is rewritten. DROP/CREATE TRIGGER takes a
-- brief ACCESS EXCLUSIVE lock per table, as V403 did.
--
-- Rollback notes (restores the V403/V424 row-level behaviour; nothing is lost — the stamp column is
-- untouched). Run, in order:
--   1. DO $$ DECLARE t text; BEGIN
--        FOR t IN SELECT tgrelid::regclass::text FROM pg_trigger
--                 WHERE tgname IN ('trg_content_stamp_insert', 'trg_content_stamp_update',
--                                  'trg_content_stamp_delete') LOOP
--          EXECUTE format('DROP TRIGGER IF EXISTS trg_content_stamp_insert ON %s', t);
--          EXECUTE format('DROP TRIGGER IF EXISTS trg_content_stamp_update ON %s', t);
--          EXECUTE format('DROP TRIGGER IF EXISTS trg_content_stamp_delete ON %s', t);
--        END LOOP; END $$;
--   2. Re-run the `CREATE OR REPLACE FUNCTION apiome.bump_version_content_stamp()` statement of
--      V424 (it also covers the V403 versions branch), then the final `DO $do$ … $do$` block of
--      V403 (re-creates the 35 row-level `trg_content_stamp` triggers).
--   3. DROP FUNCTION IF EXISTS apiome.claim_versions(text, uuid[]);
--      DROP FUNCTION IF EXISTS apiome.content_stamp_row_filters(regclass);
SET search_path TO apiome, public;

-- ───────────────────────────── helpers ─────────────────────────────

-- Marks revisions in a transaction-local setting and returns those not marked before, sorted (a
-- stable order for the caller's UPDATE). p_setting is 'apiome.content_stamp_bumped' (V403) or
-- 'apiome.publish_counts_cleared' (V424); the value format is `<uuid>,<uuid>,`.
CREATE OR REPLACE FUNCTION apiome.claim_versions(p_setting text, p_ids uuid[])
RETURNS uuid[]
LANGUAGE plpgsql
AS $fn$
DECLARE
    v_marks text := coalesce(current_setting(p_setting, true), '');
    v_seen  text[];
    v_new   uuid[];
BEGIN
    v_seen := CASE WHEN v_marks = '' THEN ARRAY[]::text[] ELSE string_to_array(v_marks, ',') END;
    SELECT coalesce(array_agg(s.id ORDER BY s.id), ARRAY[]::uuid[]) INTO v_new
      FROM (SELECT DISTINCT i AS id FROM unnest(p_ids) AS i
             WHERE i IS NOT NULL AND NOT (i::text = ANY (v_seen))) AS s;
    IF cardinality(v_new) > 0 THEN
        PERFORM set_config(p_setting, v_marks || array_to_string(v_new, ',') || ',', true);
    END IF;
    RETURN v_new;
END;
$fn$;

COMMENT ON FUNCTION apiome.claim_versions(text, uuid[]) IS
    'Claims many revisions at once for a once-per-transaction action; returns the ones not claimed yet (DBP-1.19, #7202). Set-wise twin of claim_version_content_stamp.';

-- How an UPDATE statement pairs old and new rows of a table: the primary-key equality (n.k = o.k
-- AND …) and "some column that counts differs" (n.c IS DISTINCT FROM o.c OR …), with the aliases n
-- (new) and o (old). Columns that never count on their own (updated_at, canvas_metadata) are left
-- out. A json column is compared as text (json has no equality operator).
CREATE OR REPLACE FUNCTION apiome.content_stamp_row_filters(
    p_rel regclass, OUT key_match text, OUT any_diff text)
LANGUAGE plpgsql
STABLE
AS $fn$
DECLARE
    -- Same list as apiome.bump_version_content_stamp(): changed alone, not a content change.
    v_ignored CONSTANT text[] := ARRAY['updated_at', 'canvas_metadata'];
BEGIN
    SELECT string_agg(format('n.%1$I = o.%1$I', a.attname), ' AND ' ORDER BY a.attnum)
      INTO key_match
      FROM pg_index i
      JOIN pg_attribute a ON a.attrelid = i.indrelid AND a.attnum = ANY (i.indkey)
     WHERE i.indrelid = p_rel AND i.indisprimary;
    IF key_match IS NULL THEN
        RAISE EXCEPTION 'content stamp trigger on % needs a primary key to pair updated rows', p_rel;
    END IF;

    SELECT coalesce(string_agg(
               CASE WHEN t.typname = 'json'
                    THEN format('n.%1$I::text IS DISTINCT FROM o.%1$I::text', a.attname)
                    ELSE format('n.%1$I IS DISTINCT FROM o.%1$I', a.attname) END,
               ' OR ' ORDER BY a.attnum), 'false')
      INTO any_diff
      FROM pg_attribute a
      JOIN pg_type t ON t.oid = a.atttypid
     WHERE a.attrelid = p_rel AND a.attnum > 0 AND NOT a.attisdropped
       AND a.attname <> ALL (v_ignored);
END;
$fn$;

COMMENT ON FUNCTION apiome.content_stamp_row_filters(regclass) IS
    'Primary-key match and "a counting column differs" predicates for the content-stamp UPDATE trigger (DBP-1.19, #7202).';

-- ───────────────────────────── the trigger function ─────────────────────────────

-- One function behind every content stamp trigger.
--
--   * On apiome.versions (BEFORE UPDATE, FOR EACH ROW, no argument): bumps NEW.content_stamp when a
--     column other than the bookkeeping ones below changed. Unchanged since V424.
--   * On a normalized table (AFTER INSERT / UPDATE / DELETE, FOR EACH STATEMENT, one argument with
--     transition tables new_rows / old_rows): the argument resolves the affected revisions. A bare
--     column name is read from the rows; anything else is a query over `{rows}` (alias r) that
--     returns revision ids.
CREATE OR REPLACE FUNCTION apiome.bump_version_content_stamp()
RETURNS trigger
LANGUAGE plpgsql
AS $fn$
DECLARE
    -- Versions columns that are bookkeeping or derived from the content, not content. The stored
    -- generated columns are listed too (V422): in a BEFORE trigger NEW does not carry their new
    -- values yet, so comparing them would count every bookkeeping UPDATE as a content change. The
    -- publish counts (V424) are derived from the content.
    v_version_ignored CONSTANT text[] := ARRAY[
        'content_stamp', 'updated_at', 'mcp_public_doc_tsv', 'mcp_public_embedding',
        'quality_score', 'quality_grade', 'quality_report', 'quality_report_fingerprint',
        'lint_error_count', 'sunset_at', 'operation_count', 'schema_count'];
    -- Tables whose rows the publish counts count (V424).
    v_counted  CONSTANT boolean := TG_TABLE_NAME IN ('classes', 'version_path', 'path_operation');
    v_template text;
    v_sql      text;
    v_filters  record;
    v_ids      uuid[];
    v_claimed  uuid[];
BEGIN
    IF TG_LEVEL = 'ROW' THEN
        IF TG_TABLE_SCHEMA = 'apiome' AND TG_TABLE_NAME = 'versions'
           AND TG_OP = 'UPDATE' AND TG_WHEN = 'BEFORE'
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
    v_template := CASE WHEN TG_ARGV[0] ~ '^[a-z_][a-z0-9_]*$'
                       THEN format('SELECT r.%I FROM {rows} r', TG_ARGV[0])
                       ELSE TG_ARGV[0] END;

    IF TG_OP = 'INSERT' THEN
        IF NOT EXISTS (SELECT 1 FROM new_rows) THEN RETURN NULL; END IF;
        v_sql := replace(v_template, '{rows}', 'new_rows');
    ELSIF TG_OP = 'DELETE' THEN
        IF NOT EXISTS (SELECT 1 FROM old_rows) THEN RETURN NULL; END IF;
        v_sql := replace(v_template, '{rows}', 'old_rows');
    ELSE
        IF NOT EXISTS (SELECT 1 FROM new_rows) THEN RETURN NULL; END IF;
        -- Rows without an identical (on the counting columns) partner on the other side of the
        -- UPDATE; both sides are resolved so a row moved between revisions bumps both.
        SELECT * INTO v_filters FROM apiome.content_stamp_row_filters(TG_RELID);
        v_sql := '(' || replace(v_template, '{rows}', format(
                     '(SELECT n.* FROM new_rows n WHERE NOT EXISTS '
                     '(SELECT 1 FROM old_rows o WHERE %s AND NOT (%s)))',
                     v_filters.key_match, v_filters.any_diff))
              || ') UNION ('
              || replace(v_template, '{rows}', format(
                     '(SELECT o.* FROM old_rows o WHERE NOT EXISTS '
                     '(SELECT 1 FROM new_rows n WHERE %s AND NOT (%s)))',
                     v_filters.key_match, v_filters.any_diff))
              || ')';
    END IF;

    EXECUTE format('SELECT coalesce(array_agg(DISTINCT v), ARRAY[]::uuid[]) FROM (%s) AS q(v)', v_sql)
       INTO v_ids;
    IF cardinality(v_ids) = 0 THEN
        RETURN NULL;
    END IF;

    v_claimed := apiome.claim_versions('apiome.content_stamp_bumped', v_ids);
    IF cardinality(v_claimed) > 0 THEN
        UPDATE apiome.versions SET content_stamp = content_stamp + 1 WHERE id = ANY (v_claimed);
    END IF;
    IF v_counted THEN
        v_claimed := apiome.claim_versions('apiome.publish_counts_cleared', v_ids);
        IF cardinality(v_claimed) > 0 THEN
            UPDATE apiome.versions SET operation_count = NULL, schema_count = NULL
             WHERE id = ANY (v_claimed) AND (operation_count IS NOT NULL OR schema_count IS NOT NULL);
        END IF;
    END IF;
    RETURN NULL;
END;
$fn$;

COMMENT ON FUNCTION apiome.bump_version_content_stamp() IS
    'The single trigger function that bumps versions.content_stamp once per transaction (COA-5.2, #7078; generated columns ignored since DBP-1.15, #7198; clears the publish counts on a class, path or operation write since DBP-1.16, #7199; statement-level with transition tables since DBP-1.19, #7202).';

-- ───────────────────────────── the triggers ─────────────────────────────

-- Every normalized table of a revision and how its rows find their revision (a column name, or a
-- query over `{rows}` r). A new normalized table must be added here (apiome-rest
-- tests/test_content_stamp_db.py fails until it is, or until it is listed there as not rendered).
DO $do$
DECLARE
    v_path_op  CONSTANT text :=
        'SELECT vp.version_id FROM {rows} r '
        'JOIN apiome.path_operation po ON po.id = r.path_operation_id '
        'JOIN apiome.version_path vp ON vp.id = po.version_path_id';
    v_path_ref CONSTANT text :=
        'SELECT vp.version_id FROM {rows} r JOIN apiome.version_path vp ON vp.id = r.version_path_id';
    v_triggers CONSTANT text[][] := ARRAY[
        -- the revision's own rows
        ARRAY['classes',                 'version_id'],
        ARRAY['class_schema',            'version_id'],
        ARRAY['version_path',            'version_id'],
        ARRAY['version_server',          'version_id'],
        ARRAY['version_security_scheme', 'version_id'],
        ARRAY['version_component_pins',  'version_id'],
        -- the normalized canonical model (V135, V225, agent descriptors): every row carries version_id
        ARRAY['api_artifacts',           'version_id'],
        ARRAY['api_services',            'version_id'],
        ARRAY['api_operations',          'version_id'],
        ARRAY['api_messages',            'version_id'],
        ARRAY['api_channels',            'version_id'],
        ARRAY['api_types',               'version_id'],
        ARRAY['api_fields',              'version_id'],
        ARRAY['api_workflows',           'version_id'],
        ARRAY['api_workflow_steps',      'version_id'],
        ARRAY['api_agent_descriptors',   'version_id'],
        ARRAY['api_agent_skills',        'version_id'],
        -- class children
        ARRAY['class_properties',
              'SELECT c.version_id FROM {rows} r JOIN apiome.classes c ON c.id = r.class_id'],
        ARRAY['class_tags',
              'SELECT c.version_id FROM {rows} r JOIN apiome.classes c ON c.id = r.class_id'],
        -- project property library: every revision whose schema uses the property
        ARRAY['properties',
              'SELECT c.version_id FROM {rows} r '
              'JOIN apiome.class_properties cp ON cp.property_id = r.id '
              'JOIN apiome.classes c ON c.id = cp.class_id '
              'UNION SELECT vp.version_id FROM {rows} r '
              'JOIN apiome.path_operation_schema s ON s.property_id = r.id '
              'JOIN apiome.path_operation po ON po.id = s.path_operation_id '
              'JOIN apiome.version_path vp ON vp.id = po.version_path_id '
              'UNION SELECT vp.version_id FROM {rows} r '
              'JOIN apiome.path_parameter_schema s ON s.property_id = r.id '
              'JOIN apiome.path_response_content prc ON prc.id = s.path_response_content_id '
              'JOIN apiome.path_response pr ON pr.id = prc.path_response_id '
              'JOIN apiome.path_operation po ON po.id = pr.path_operation_id '
              'JOIN apiome.version_path vp ON vp.id = po.version_path_id'],
        -- path children
        ARRAY['path_operation',                   v_path_ref],
        ARRAY['shared_path_parameter',            v_path_ref],
        ARRAY['shared_path_request_body',         v_path_ref],
        ARRAY['shared_path_response',             v_path_ref],
        ARRAY['shared_path_request_body_content',
              'SELECT vp.version_id FROM {rows} r '
              'JOIN apiome.shared_path_request_body b ON b.id = r.shared_path_request_body_id '
              'JOIN apiome.version_path vp ON vp.id = b.version_path_id'],
        ARRAY['shared_path_response_content',
              'SELECT vp.version_id FROM {rows} r '
              'JOIN apiome.shared_path_response b ON b.id = r.shared_path_response_id '
              'JOIN apiome.version_path vp ON vp.id = b.version_path_id'],
        -- operation children
        ARRAY['path_operation_description',       v_path_op],
        ARRAY['path_operation_parameter_link',    v_path_op],
        ARRAY['path_operation_request_body_link', v_path_op],
        ARRAY['path_operation_response_link',     v_path_op],
        ARRAY['path_operation_schema',            v_path_op],
        ARRAY['path_parameter',                   v_path_op],
        ARRAY['path_response',                    v_path_op],
        -- response children
        ARRAY['path_response_content',
              'SELECT vp.version_id FROM {rows} r '
              'JOIN apiome.path_response pr ON pr.id = r.path_response_id '
              'JOIN apiome.path_operation po ON po.id = pr.path_operation_id '
              'JOIN apiome.version_path vp ON vp.id = po.version_path_id'],
        ARRAY['path_parameter_schema',
              'SELECT vp.version_id FROM {rows} r '
              'JOIN apiome.path_response_content prc ON prc.id = r.path_response_content_id '
              'JOIN apiome.path_response pr ON pr.id = prc.path_response_id '
              'JOIN apiome.path_operation po ON po.id = pr.path_operation_id '
              'JOIN apiome.version_path vp ON vp.id = po.version_path_id']
    ];
    v_table text;
    v_arg   text;
BEGIN
    FOR i IN 1 .. array_length(v_triggers, 1) LOOP
        v_table := v_triggers[i][1];
        v_arg   := v_triggers[i][2];
        -- The row-level trigger of V403 …
        EXECUTE format('DROP TRIGGER IF EXISTS trg_content_stamp ON apiome.%I', v_table);
        -- … becomes three statement-level ones (one event per transition-table trigger).
        EXECUTE format('DROP TRIGGER IF EXISTS trg_content_stamp_insert ON apiome.%I', v_table);
        EXECUTE format('DROP TRIGGER IF EXISTS trg_content_stamp_update ON apiome.%I', v_table);
        EXECUTE format('DROP TRIGGER IF EXISTS trg_content_stamp_delete ON apiome.%I', v_table);
        EXECUTE format(
            'CREATE TRIGGER trg_content_stamp_insert AFTER INSERT ON apiome.%I '
            'REFERENCING NEW TABLE AS new_rows '
            'FOR EACH STATEMENT EXECUTE FUNCTION apiome.bump_version_content_stamp(%L)',
            v_table, v_arg);
        EXECUTE format(
            'CREATE TRIGGER trg_content_stamp_update AFTER UPDATE ON apiome.%I '
            'REFERENCING OLD TABLE AS old_rows NEW TABLE AS new_rows '
            'FOR EACH STATEMENT EXECUTE FUNCTION apiome.bump_version_content_stamp(%L)',
            v_table, v_arg);
        EXECUTE format(
            'CREATE TRIGGER trg_content_stamp_delete AFTER DELETE ON apiome.%I '
            'REFERENCING OLD TABLE AS old_rows '
            'FOR EACH STATEMENT EXECUTE FUNCTION apiome.bump_version_content_stamp(%L)',
            v_table, v_arg);
    END LOOP;
END;
$do$;
