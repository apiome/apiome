-- OpenAPI 3.2 constructs in Projects (#7048, COA-2.5).
--
-- A project revision's paths are stored as rows (version_path → path_operation → parameters,
-- request bodies, responses). Three OpenAPI 3.2 constructs had nowhere to go:
--
--   in: querystring
--       A 3.2 Parameter Object can describe the whole query string as one value
--       (`in: querystring`, with `content`). shared_path_parameter.in_location carried a CHECK that
--       allowed only path / query / header / cookie, so importing such a parameter failed the whole
--       path import. The CHECK now also allows 'querystring'.
--
--   itemSchema (sequential / streaming media types)
--       A 3.2 Media Type Object can describe each element of a stream (JSON Lines, JSON text
--       sequences, Server-Sent Events) with `itemSchema` instead of `schema`. The importer already
--       stores the element schema in the content row's class_id / inline_schema; `item_schema`
--       records that the stored schema is the element schema, so an export writes `itemSchema`
--       (OpenAPI 3.2) or the `x-apiome-item-schema` stash (3.1) instead of `schema`.
--
--   QUERY and custom methods
--       path_operation.operation is a free VARCHAR(50) already; nothing changes here.
--
-- The document's tag list (with the 3.2 `parent` / `summary` / `kind`) is already kept on
-- `projects.metadata` under `x-apiome-tag-taxonomy` (OA5, #3502), so it needs no DDL.
--
-- Additive and idempotent: every existing row keeps `item_schema = false`.
--
-- Rollback notes:
--   ALTER TABLE apiome.shared_path_request_body_content DROP COLUMN IF EXISTS item_schema;
--   ALTER TABLE apiome.shared_path_response_content DROP COLUMN IF EXISTS item_schema;
--   ALTER TABLE apiome.shared_path_parameter DROP CONSTRAINT IF EXISTS shared_path_parameter_in_location_check;
--   ALTER TABLE apiome.shared_path_parameter ADD CONSTRAINT shared_path_parameter_in_location_check
--     CHECK (in_location IN ('path', 'query', 'header', 'cookie'));
--   (fails while a 'querystring' row exists)

SET search_path TO apiome, public;

-- Drop whichever CHECK guards in_location (named by Postgres when V031 created it inline).
DO $$
DECLARE
    constraint_name TEXT;
BEGIN
    FOR constraint_name IN
        SELECT c.conname
        FROM pg_constraint c
        WHERE c.conrelid = 'apiome.shared_path_parameter'::regclass
          AND c.contype = 'c'
          AND pg_get_constraintdef(c.oid) ILIKE '%in_location%'
    LOOP
        EXECUTE format('ALTER TABLE apiome.shared_path_parameter DROP CONSTRAINT %I', constraint_name);
    END LOOP;
END $$;

ALTER TABLE apiome.shared_path_parameter
    ADD CONSTRAINT shared_path_parameter_in_location_check
    CHECK (in_location IN ('path', 'query', 'header', 'cookie', 'querystring'));

ALTER TABLE apiome.shared_path_request_body_content
    ADD COLUMN IF NOT EXISTS item_schema BOOLEAN NOT NULL DEFAULT FALSE;

ALTER TABLE apiome.shared_path_response_content
    ADD COLUMN IF NOT EXISTS item_schema BOOLEAN NOT NULL DEFAULT FALSE;

COMMENT ON COLUMN apiome.shared_path_request_body_content.item_schema IS
    'True when class_id / inline_schema is the OpenAPI 3.2 itemSchema (each element of a stream), not the body schema (#7048)';
COMMENT ON COLUMN apiome.shared_path_response_content.item_schema IS
    'True when class_id / inline_schema is the OpenAPI 3.2 itemSchema (each element of a stream), not the body schema (#7048)';
