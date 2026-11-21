-- Document object tables and the revision content stamp (COA-5.2, #7078).
--
-- COA-5.1 (#7077, V402) gave apiome-rest a content-addressed document store. This migration adds
-- the metadata that says which stored object belongs to which revision, and a per-revision change
-- counter a rendered-document cache can key on:
--
--   * apiome.document_objects — one row per stored object: tenant, SHA-256, size, media type,
--     content coding, the backend that holds it and its key there. Unique on (tenant_id, sha256),
--     the same identity the store itself uses.
--   * apiome.version_documents — which object plays which role for a revision: the captured
--     original (or each part of a fileset plus its manifest), a rendered OpenAPI or canonical
--     document at a given content stamp and generator, or a frozen schema.
--   * versions.content_stamp — a BIGINT bumped once per transaction by any write to the
--     revision's normalized data (classes, properties, paths, operations, servers, security
--     schemes, component pins, the canonical API model) or to the revision row's own content
--     columns. Reads never bump it.
--
-- Online: ADD COLUMN … NOT NULL DEFAULT 0 with a constant default is a catalog-only change on
-- Postgres 11+, so `versions` is not rewritten. The new tables start empty.
--
-- Rollback notes (reverse carefully in shared environments — this drops the document metadata):
--   DO $$ DECLARE t text; BEGIN
--     FOR t IN SELECT tgrelid::regclass::text FROM pg_trigger
--              WHERE tgname = 'trg_content_stamp' LOOP
--       EXECUTE format('DROP TRIGGER IF EXISTS trg_content_stamp ON %s', t);
--     END LOOP; END $$;
--   DROP FUNCTION IF EXISTS apiome.bump_version_content_stamp();
--   DROP FUNCTION IF EXISTS apiome.claim_version_content_stamp(uuid);
--   DROP TABLE IF EXISTS apiome.version_documents;
--   DROP TABLE IF EXISTS apiome.document_objects;
--   ALTER TABLE apiome.versions DROP COLUMN IF EXISTS content_stamp;
SET search_path TO apiome, public;

-- ───────────────────────────── document objects ─────────────────────────────

CREATE TABLE IF NOT EXISTS apiome.document_objects (
    id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id     text NOT NULL
                      CHECK (tenant_id ~ '^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$'),
    sha256        text NOT NULL
                      CHECK (sha256 ~ '^[0-9a-f]{64}$'),
    size_bytes    bigint NOT NULL CHECK (size_bytes >= 0),
    media_type    text NOT NULL DEFAULT 'application/octet-stream',
    encoding      text NOT NULL DEFAULT 'identity'
                      CHECK (encoding ~ '^[a-z0-9][a-z0-9-]{0,31}$'),
    backend       text NOT NULL CHECK (backend IN ('db', 's3', 'filesystem')),
    storage_key   text NOT NULL CHECK (length(storage_key) BETWEEN 1 AND 1024),
    ref_count     integer NOT NULL DEFAULT 0 CHECK (ref_count >= 0),
    created_at    timestamptz NOT NULL DEFAULT now(),
    verified_at   timestamptz,
    CONSTRAINT document_objects_tenant_sha256_key UNIQUE (tenant_id, sha256)
);

COMMENT ON TABLE apiome.document_objects IS
    'Metadata of one document store object (COA-5.2, #7078): where the bytes live, never the bytes.';
COMMENT ON COLUMN apiome.document_objects.tenant_id IS
    'Owning tenant: the document store''s tenants/<tenant_id> key segment.';
COMMENT ON COLUMN apiome.document_objects.sha256 IS
    'Lower-case hex SHA-256 of the stored bytes; with tenant_id, the object''s identity.';
COMMENT ON COLUMN apiome.document_objects.size_bytes IS
    'Length of the stored bytes.';
COMMENT ON COLUMN apiome.document_objects.media_type IS
    'Media type of the document, e.g. application/yaml or application/json.';
COMMENT ON COLUMN apiome.document_objects.encoding IS
    'Content coding of the stored bytes (HTTP Content-Encoding token): identity, gzip, …';
COMMENT ON COLUMN apiome.document_objects.backend IS
    'Document store backend holding the bytes: db, s3 or filesystem.';
COMMENT ON COLUMN apiome.document_objects.storage_key IS
    'Object key inside that backend: <prefix>/tenants/<tenant_id>/objects/sha256/<aa>/<hex>.';
COMMENT ON COLUMN apiome.document_objects.ref_count IS
    'Number of version_documents rows that use the object; maintained by the lifecycle job (COA-5.10).';
COMMENT ON COLUMN apiome.document_objects.verified_at IS
    'Last time the stored bytes were re-hashed and matched sha256; NULL until first verified.';

-- ───────────────────────────── version documents ─────────────────────────────

CREATE TABLE IF NOT EXISTS apiome.version_documents (
    id                 uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    version_id         uuid NOT NULL REFERENCES apiome.versions(id) ON DELETE CASCADE,
    role               text NOT NULL
                           CHECK (role IN ('original', 'original_part', 'rendered_openapi',
                                           'rendered_canonical', 'frozen_schema')),
    object_id          uuid NOT NULL REFERENCES apiome.document_objects(id) ON DELETE RESTRICT,
    part_path          text CHECK (part_path IS NULL OR length(part_path) BETWEEN 1 AND 1024),
    content_stamp      bigint CHECK (content_stamp IS NULL OR content_stamp >= 0),
    generator          text,
    generator_version  text,
    created_at         timestamptz NOT NULL DEFAULT now(),
    -- A fileset part names its path inside the set; nothing else has one.
    CONSTRAINT version_documents_part_path_role
        CHECK ((role = 'original_part') = (part_path IS NOT NULL)),
    -- A rendered document records what it was rendered from and by.
    CONSTRAINT version_documents_rendered_provenance
        CHECK (role NOT IN ('rendered_openapi', 'rendered_canonical')
               OR (content_stamp IS NOT NULL AND generator IS NOT NULL
                   AND generator_version IS NOT NULL)),
    CONSTRAINT version_documents_slot_key
        UNIQUE NULLS NOT DISTINCT
            (version_id, role, part_path, content_stamp, generator, generator_version)
);

CREATE INDEX IF NOT EXISTS idx_version_documents_object_id
    ON apiome.version_documents (object_id);

COMMENT ON TABLE apiome.version_documents IS
    'Which document store object plays which role for a revision (COA-5.2, #7078). A fileset '
    '(Arazzo with its sources, multi-file protobuf) is one original row holding the manifest plus '
    'one original_part row per file.';
COMMENT ON COLUMN apiome.version_documents.role IS
    'original (the captured file, or a fileset''s manifest) | original_part (one file of a fileset) | '
    'rendered_openapi | rendered_canonical | frozen_schema.';
COMMENT ON COLUMN apiome.version_documents.part_path IS
    'Path of the part inside its fileset; set only for original_part.';
COMMENT ON COLUMN apiome.version_documents.content_stamp IS
    'versions.content_stamp the document was rendered at; a rendered row is stale once the stamp moves on.';
COMMENT ON COLUMN apiome.version_documents.generator IS
    'Generator that rendered the document (required for rendered roles).';
COMMENT ON COLUMN apiome.version_documents.generator_version IS
    'Version of that generator (required for rendered roles).';

-- ───────────────────────────── revision content stamp ─────────────────────────────

-- Constant default: catalog-only on Postgres 11+, no rewrite of versions.
ALTER TABLE apiome.versions
    ADD COLUMN IF NOT EXISTS content_stamp bigint NOT NULL DEFAULT 0;

COMMENT ON COLUMN apiome.versions.content_stamp IS
    'Change counter of the revision''s content (COA-5.2, #7078): +1 per transaction that writes its '
    'normalized data or its own content columns. Rendered-document caches key on it.';

-- Marks a revision as bumped in the current transaction. Returns true the first time per
-- transaction (the caller then bumps), false afterwards. The mark is a transaction-local setting,
-- so it vanishes at COMMIT/ROLLBACK and is undone with a rolled-back savepoint — together with the
-- bump it guarded.
CREATE OR REPLACE FUNCTION apiome.claim_version_content_stamp(p_version_id uuid)
RETURNS boolean
LANGUAGE plpgsql
AS $fn$
DECLARE
    v_marks text := coalesce(current_setting('apiome.content_stamp_bumped', true), '');
BEGIN
    IF p_version_id IS NULL OR position(p_version_id::text IN v_marks) > 0 THEN
        RETURN false;
    END IF;
    PERFORM set_config('apiome.content_stamp_bumped', v_marks || p_version_id::text || ',', true);
    RETURN true;
END;
$fn$;

COMMENT ON FUNCTION apiome.claim_version_content_stamp(uuid) IS
    'True the first time a revision is claimed in the current transaction (COA-5.2, #7078).';

-- The one trigger function behind every content stamp trigger.
--
--   * On apiome.versions (BEFORE UPDATE, no argument): bumps NEW.content_stamp when a column other
--     than the bookkeeping ones below changed.
--   * On a normalized table (AFTER INSERT/UPDATE/DELETE, one argument): the argument resolves the
--     affected revision(s). A bare column name (e.g. version_id) is read from the row; anything
--     else is a query run with the row as $1 (jsonb) that returns revision ids. Both the old and
--     the new row are resolved, so moving a row between revisions bumps both.
--
-- An UPDATE that changes nothing but updated_at / canvas_metadata (canvas layout, never rendered)
-- is not a content change.
CREATE OR REPLACE FUNCTION apiome.bump_version_content_stamp()
RETURNS trigger
LANGUAGE plpgsql
AS $fn$
DECLARE
    -- Columns whose change alone is not a content change, on any table.
    v_ignored         CONSTANT text[] := ARRAY['updated_at', 'canvas_metadata'];
    -- Versions columns that are bookkeeping or derived from the content, not content.
    v_version_ignored CONSTANT text[] := ARRAY[
        'content_stamp', 'updated_at', 'mcp_public_doc_tsv', 'mcp_public_embedding',
        'quality_score', 'quality_grade', 'quality_report', 'quality_report_fingerprint'];
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
    'The single trigger function that bumps versions.content_stamp once per transaction (COA-5.2, #7078).';

DROP TRIGGER IF EXISTS trg_content_stamp ON apiome.versions;
CREATE TRIGGER trg_content_stamp
    BEFORE UPDATE ON apiome.versions
    FOR EACH ROW EXECUTE FUNCTION apiome.bump_version_content_stamp();

-- Every normalized table of a revision and how a row finds its revision. A new normalized table
-- must be added here (apiome-rest tests/test_content_stamp_db.py fails until it is, or until it
-- is listed there as not rendered).
DO $do$
DECLARE
    v_path_op  CONSTANT text :=
        'SELECT vp.version_id FROM apiome.path_operation po '
        'JOIN apiome.version_path vp ON vp.id = po.version_path_id WHERE po.id = ';
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
              'SELECT version_id FROM apiome.classes WHERE id = ($1->>''class_id'')::uuid'],
        ARRAY['class_tags',
              'SELECT version_id FROM apiome.classes WHERE id = ($1->>''class_id'')::uuid'],
        -- project property library: every revision whose schema uses the property
        ARRAY['properties',
              'SELECT c.version_id FROM apiome.class_properties cp '
              'JOIN apiome.classes c ON c.id = cp.class_id WHERE cp.property_id = ($1->>''id'')::uuid '
              'UNION SELECT vp.version_id FROM apiome.path_operation_schema s '
              'JOIN apiome.path_operation po ON po.id = s.path_operation_id '
              'JOIN apiome.version_path vp ON vp.id = po.version_path_id '
              'WHERE s.property_id = ($1->>''id'')::uuid '
              'UNION SELECT vp.version_id FROM apiome.path_parameter_schema s '
              'JOIN apiome.path_response_content prc ON prc.id = s.path_response_content_id '
              'JOIN apiome.path_response pr ON pr.id = prc.path_response_id '
              'JOIN apiome.path_operation po ON po.id = pr.path_operation_id '
              'JOIN apiome.version_path vp ON vp.id = po.version_path_id '
              'WHERE s.property_id = ($1->>''id'')::uuid'],
        -- path children
        ARRAY['path_operation',
              'SELECT version_id FROM apiome.version_path WHERE id = ($1->>''version_path_id'')::uuid'],
        ARRAY['shared_path_parameter',
              'SELECT version_id FROM apiome.version_path WHERE id = ($1->>''version_path_id'')::uuid'],
        ARRAY['shared_path_request_body',
              'SELECT version_id FROM apiome.version_path WHERE id = ($1->>''version_path_id'')::uuid'],
        ARRAY['shared_path_response',
              'SELECT version_id FROM apiome.version_path WHERE id = ($1->>''version_path_id'')::uuid'],
        ARRAY['shared_path_request_body_content',
              'SELECT vp.version_id FROM apiome.shared_path_request_body b '
              'JOIN apiome.version_path vp ON vp.id = b.version_path_id '
              'WHERE b.id = ($1->>''shared_path_request_body_id'')::uuid'],
        ARRAY['shared_path_response_content',
              'SELECT vp.version_id FROM apiome.shared_path_response r '
              'JOIN apiome.version_path vp ON vp.id = r.version_path_id '
              'WHERE r.id = ($1->>''shared_path_response_id'')::uuid'],
        -- operation children
        ARRAY['path_operation_description',       ''],
        ARRAY['path_operation_parameter_link',    ''],
        ARRAY['path_operation_request_body_link', ''],
        ARRAY['path_operation_response_link',     ''],
        ARRAY['path_operation_schema',            ''],
        ARRAY['path_parameter',                   ''],
        ARRAY['path_response',                    ''],
        -- response children
        ARRAY['path_response_content',
              'SELECT vp.version_id FROM apiome.path_response pr '
              'JOIN apiome.path_operation po ON po.id = pr.path_operation_id '
              'JOIN apiome.version_path vp ON vp.id = po.version_path_id '
              'WHERE pr.id = ($1->>''path_response_id'')::uuid'],
        ARRAY['path_parameter_schema',
              'SELECT vp.version_id FROM apiome.path_response_content prc '
              'JOIN apiome.path_response pr ON pr.id = prc.path_response_id '
              'JOIN apiome.path_operation po ON po.id = pr.path_operation_id '
              'JOIN apiome.version_path vp ON vp.id = po.version_path_id '
              'WHERE prc.id = ($1->>''path_response_content_id'')::uuid']
    ];
    v_table    text;
    v_resolver text;
BEGIN
    FOR i IN 1 .. array_length(v_triggers, 1) LOOP
        v_table := v_triggers[i][1];
        -- '' = an operation child: resolve through its path_operation_id.
        v_resolver := CASE WHEN v_triggers[i][2] = ''
                           THEN v_path_op || '($1->>''path_operation_id'')::uuid'
                           ELSE v_triggers[i][2] END;
        EXECUTE format('DROP TRIGGER IF EXISTS trg_content_stamp ON apiome.%I', v_table);
        EXECUTE format(
            'CREATE TRIGGER trg_content_stamp AFTER INSERT OR UPDATE OR DELETE ON apiome.%I '
            'FOR EACH ROW EXECUTE FUNCTION apiome.bump_version_content_stamp(%L)',
            v_table, v_resolver);
    END LOOP;
END;
$do$;
