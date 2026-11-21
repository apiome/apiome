-- Document store, database backend (COA-5.1, #7077).
--
-- apiome-rest's document store (app.document_store) keeps immutable, content-addressed objects —
-- captured originals, rendered documents, large export artifacts — behind one interface with
-- three backends: an S3-compatible bucket, a directory, or this table. The table is the default
-- (APIOME_DOCUMENT_STORE=db), so an install without a bucket keeps working.
--
-- A row is one object: the bytes, keyed by the owning tenant and the SHA-256 of the bytes. Rows
-- are written once (INSERT … ON CONFLICT DO NOTHING) and never updated; equal bytes in two
-- tenants are two rows, so tenants never share a namespace.
--
-- Rollback notes (reverse carefully in shared environments — this drops every stored object):
--   DROP TABLE IF EXISTS apiome.document_store_blob;
SET search_path TO apiome, public;

CREATE TABLE IF NOT EXISTS apiome.document_store_blob (
    tenant_id     text NOT NULL
                      CHECK (tenant_id ~ '^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$'),
    sha256        text NOT NULL
                      CHECK (sha256 ~ '^[0-9a-f]{64}$'),
    size_bytes    bigint NOT NULL CHECK (size_bytes >= 0),
    media_type    text NOT NULL DEFAULT 'application/octet-stream',
    content       bytea NOT NULL,
    created_at    timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, sha256),
    CONSTRAINT document_store_blob_size_matches CHECK (octet_length(content) = size_bytes)
);

COMMENT ON TABLE apiome.document_store_blob IS
    'Document store objects for the db backend (COA-5.1, #7077): immutable bytes keyed by tenant and SHA-256.';
COMMENT ON COLUMN apiome.document_store_blob.tenant_id IS
    'Owning tenant: the tenants/<tenant_id> segment of the object key. Every read filters on it.';
COMMENT ON COLUMN apiome.document_store_blob.sha256 IS
    'Lower-case hex SHA-256 of content; the object''s identity.';
COMMENT ON COLUMN apiome.document_store_blob.size_bytes IS
    'Length of content in bytes; capped by APIOME_DOCUMENT_STORE_DB_MAX_BYTES at write time.';
COMMENT ON COLUMN apiome.document_store_blob.media_type IS
    'Media type recorded by the first write of these bytes.';
COMMENT ON COLUMN apiome.document_store_blob.content IS
    'The object''s bytes. Never updated.';
